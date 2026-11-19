"""Orquestrador: controla o fluxo de cada caso, os estados e as permissões.

Fluxo
  formulário ──► conferência do documento ──► conferência com o ponto ──► alertas
       └──► chat (o agente pergunta só o que falta) ──► finalização ──► e-mails
                                                                  └──► RH confirma ou descarta alertas

Estados do atestado
  em_atendimento ──► aguardando_rh (há alertas abertos) ──► resolvido
                └──► sem_pendencias (nenhum alerta)    ──► resolvido

Permissões
  - O agente (LLM) só chama: registrar_resposta, registrar_preferencias,
    registrar_complemento, atualizar_documento e finalizar_chat.
  - Decidir alertas, atualizar o cadastro e concluir o caso exigem uma
    pessoa do RH (decidir_alerta, concluir_caso). O agente nunca altera o
    ponto nem decide sobre o atestado.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta

import config
import db
import notificacoes
from conferencia import CODIGOS_AUTOMATICOS, conferir, janela_ponto, nomes_compativeis
from documento import ResultadoDocumento, analisar_documento

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def gerar_protocolo(momento: datetime) -> str:
    return f"SNG-{momento:%Y%m%d}-{secrets.token_hex(3).upper()}"


# ---------------------------------------------------------------------------
# 1. Formulário
# ---------------------------------------------------------------------------
def validar_formulario(dados: dict) -> tuple[dict, dict | None]:
    """Valida os campos e confere se o funcionário existe. Devolve (erros, funcionario)."""
    erros: dict[str, str] = {}
    hoje = db.hoje()
    funcionario = None

    fid = (dados.get("funcionario_id") or "").strip().upper()
    if not fid:
        erros["funcionario_id"] = "Informe o seu ID (ex.: FUNC001)."
    else:
        funcionario = db.buscar_funcionario(fid)
        if funcionario is None:
            erros["funcionario_id"] = f"O ID {fid} não foi encontrado no cadastro."
    nome = " ".join((dados.get("nome") or "").split())
    if len(nome.split()) < 2:
        erros["nome"] = "Informe nome e sobrenome."
    elif funcionario and not nomes_compativeis(funcionario["nome"], nome):
        erros["nome"] = "O nome não confere com o cadastro deste ID."

    if dados.get("tipo") not in config.TIPOS_DOCUMENTO:
        erros["tipo"] = "Escolha o tipo de documento."
    inicio, fim = dados.get("data_inicio"), dados.get("data_fim")
    if not isinstance(inicio, date) or not isinstance(fim, date):
        erros["datas"] = "Informe a data de início e a de término."
    else:
        if fim < inicio:
            erros["datas"] = "A data de término é anterior à de início."
        elif inicio < hoje - timedelta(days=config.MAX_DIAS_RETROATIVOS):
            erros["datas"] = f"A data de início está mais de {config.MAX_DIAS_RETROATIVOS} dias no passado."
        elif inicio > hoje + timedelta(days=config.MAX_DIAS_FUTUROS):
            erros["datas"] = f"A data de início está mais de {config.MAX_DIAS_FUTUROS} dias no futuro."
        elif (fim - inicio).days + 1 > config.MAX_DIAS_ATESTADO:
            erros["datas"] = f"O período passa de {config.MAX_DIAS_ATESTADO} dias."
        elif dados.get("tipo") == "declaracao_comparecimento" and fim != inicio:
            erros["datas"] = "A declaração de comparecimento vale para um único dia (início = término)."
    if dados.get("motivo") not in (None, *config.MOTIVOS):
        erros["motivo"] = "Motivo inválido."
    if len(db.so_digitos(dados.get("telefone", ""))) not in (10, 11):
        erros["telefone"] = "Informe o telefone com DDD (10 ou 11 dígitos)."
    if not RE_EMAIL.match((dados.get("email") or "").strip()):
        erros["email"] = "Informe um e-mail válido."
    if not dados.get("arquivo_bytes"):
        erros["arquivo"] = "Anexe o atestado (PDF, JPG ou PNG)."
    return erros, funcionario


def registrar_formulario(cliente, dados: dict, funcionario: dict) -> dict:
    """Grava o atestado, confere o documento e o ponto e gera os alertas."""
    doc = analisar_documento(cliente, dados["arquivo_bytes"], dados["arquivo_nome"])
    inicio, fim = dados["data_inicio"], dados["data_fim"]
    campos = {
        "tipo": dados["tipo"], "data_inicio": inicio, "data_fim": fim, "dias": (fim - inicio).days + 1,
        "motivo": dados.get("motivo"), "telefone_informado": dados["telefone"].strip(),
        "email_informado": dados["email"].strip().lower(), "tentativas_envio": 1,
        **doc.campos_atestado(),
    }
    momento = db.agora()
    for _ in range(3):
        protocolo = gerar_protocolo(momento)
        try:
            atestado_id = db.criar_atestado(protocolo, funcionario["id"], campos, momento)
            break
        except db.ProtocoloDuplicado:
            continue
    else:
        raise db.ErroBanco("não foi possível gerar um protocolo único")

    db.auditar(atestado_id, "colaborador", "formulario_enviado", detalhe={
        "tipo": dados["tipo"], "inicio": inicio, "fim": fim, "motivo_informado": bool(dados.get("motivo")),
    })
    db.auditar(atestado_id, "agente", "documento_aceito" if doc.aceito else "documento_recusado",
               doc.regra, doc.para_auditoria())
    resultado = reavaliar_alertas(atestado_id)
    return {"atestado_id": atestado_id, "protocolo": protocolo, "documento": doc, "conferencia": resultado}


# ---------------------------------------------------------------------------
# 2. Conferência (documento + ponto) → alertas
# ---------------------------------------------------------------------------
def contexto_caso(atestado_id: int) -> tuple[dict, dict, list[dict]]:
    at = db.buscar_atestado(atestado_id)
    func = db.buscar_funcionario(at["funcionario_id"])
    return at, func, db.listar_alertas(atestado_id)


def reavaliar_alertas(atestado_id: int):
    at, func, existentes_lista = contexto_caso(atestado_id)
    inicio_janela, fim_janela = janela_ponto(at["data_inicio"], at["data_fim"])
    ponto = db.ponto_periodo(func["id"], inicio_janela, fim_janela)
    outros = db.atestados_do_funcionario(func["id"], exceto_id=atestado_id)
    mesmo_arquivo = db.atestados_por_hash(at.get("arquivo_sha256"), exceto_id=atestado_id)
    resultado = conferir(at, func, ponto, outros, mesmo_arquivo, db.hoje())
    db.auditar(atestado_id, "agente", "ponto_consultado", detalhe={
        "periodo_lido": [inicio_janela, fim_janela], "registros": len(ponto), "alertas": sorted(resultado.codigos),
    })

    existentes = {a["codigo"]: a for a in existentes_lista}
    for alerta in resultado.alertas:
        atual = existentes.get(alerta.codigo)
        if atual is None:
            db.inserir_alerta(atestado_id, alerta.para_dict())
            db.auditar(atestado_id, "agente", "alerta_gerado", alerta.codigo,
                       {"titulo": alerta.titulo, "gravidade": alerta.gravidade})
        elif atual["status"] == "aberto":
            db.atualizar_alerta(atual["id"], {k: v for k, v in alerta.para_dict().items() if k != "codigo"})
    for codigo, atual in existentes.items():
        if codigo in CODIGOS_AUTOMATICOS and codigo not in resultado.codigos and atual["status"] == "aberto":
            db.atualizar_alerta(atual["id"], {
                "status": "descartado", "decidido_por": "agente", "decidido_em": db.agora(),
                "decisao_obs": "Não se aplica mais após nova conferência (ex.: novo documento).",
            })
            db.auditar(atestado_id, "agente", "alerta_encerrado_pelo_agente", codigo)
    db.atualizar_atestado(atestado_id, {"observacoes": " ".join(resultado.observacoes)[:1000] or None})
    return resultado


def atualizar_documento(cliente, atestado_id: int, dados: bytes, nome_arquivo: str) -> ResultadoDocumento:
    """Novo arquivo enviado pelo chat."""
    at = db.buscar_atestado(atestado_id)
    doc = analisar_documento(cliente, dados, nome_arquivo)
    campos = {"tentativas_envio": int(at["tentativas_envio"]) + 1}
    if doc.aceito or not at["documento_aceito"]:
        campos.update(doc.campos_atestado())   # um arquivo recusado não substitui um já aceito
    db.atualizar_atestado(atestado_id, campos)
    db.auditar(atestado_id, "agente", "documento_aceito" if doc.aceito else "documento_recusado",
               doc.regra, doc.para_auditoria())
    reavaliar_alertas(atestado_id)
    return doc


# ---------------------------------------------------------------------------
# 3. Chat: respostas do colaborador e pendências
# ---------------------------------------------------------------------------
def contato_difere(at: dict, func: dict) -> dict:
    return {
        "telefone": db.so_digitos(at["telefone_informado"]) != db.so_digitos(func["telefone"]),
        "email": at["email_informado"].strip().lower() != func["email"].strip().lower(),
    }


def pendencias_chat(at: dict, func: dict, alertas: list[dict]) -> list[dict]:
    """O que o agente ainda precisa obter do colaborador (o 'objetivo' do agente)."""
    pend = []
    if not at["documento_aceito"] and int(at["tentativas_envio"]) < config.MAX_TENTATIVAS_ENVIO:
        pend.append({"chave": "documento", "descricao": "pedir um novo envio do documento, legível"})
    for a in alertas:
        if a["status"] == "aberto" and a.get("pergunta") and not a.get("resposta_colaborador"):
            pend.append({"chave": f"alerta:{a['codigo']}", "codigo": a["codigo"], "descricao": f"esclarecer: {a['titulo']}"})
    difere = contato_difere(at, func)
    if (difere["telefone"] or difere["email"]) and at.get("atualizar_cadastro") is None:
        campos = " e ".join(c for c in ("telefone", "e-mail") if difere["telefone" if c == "telefone" else "email"])
        pend.append({"chave": "cadastro", "descricao": f"perguntar se quer atualizar o {campos} do cadastro"})
    if at.get("receber_email") is None:
        pend.append({"chave": "email", "descricao": "perguntar se quer receber a confirmação e o andamento por e-mail"})
    if at.get("complemento") is None:
        pend.append({"chave": "complemento", "descricao": "perguntar se há algo a complementar"})
    return pend


def registrar_resposta(atestado_id: int, codigo: str, resposta: str) -> dict:
    codigo = (codigo or "").strip().upper()
    resposta = " ".join((resposta or "").split())[:1000]
    alerta = next((a for a in db.listar_alertas(atestado_id) if a["codigo"] == codigo), None)
    if alerta is None or alerta["status"] != "aberto" or not alerta.get("pergunta"):
        return {"ok": False, "erro": f"não há pergunta aberta com o código {codigo}"}
    if not resposta:
        return {"ok": False, "erro": "resposta vazia"}
    db.atualizar_alerta(alerta["id"], {"resposta_colaborador": resposta})
    db.auditar(atestado_id, "colaborador", "resposta_registrada", codigo)
    return {"ok": True, "codigo": codigo}


def registrar_preferencias(atestado_id: int, receber_email: bool | None = None,
                           atualizar_cadastro: bool | None = None) -> dict:
    at, func, alertas = contexto_caso(atestado_id)
    campos = {}
    if receber_email is not None:
        campos["receber_email"] = int(bool(receber_email))
    if atualizar_cadastro is not None:
        campos["atualizar_cadastro"] = int(bool(atualizar_cadastro))
    db.atualizar_atestado(atestado_id, campos)

    difere = contato_difere(at, func)
    if atualizar_cadastro and (difere["telefone"] or difere["email"]) and not any(a["codigo"] == "C1" for a in alertas):
        novos = {}
        if difere["telefone"]:
            novos["telefone_novo"] = at["telefone_informado"]
        if difere["email"]:
            novos["email_novo"] = at["email_informado"]
        db.inserir_alerta(atestado_id, {
            "codigo": "C1", "gravidade": "baixa", "titulo": "Atualização de cadastro pedida pelo funcionário",
            "descricao": "O funcionário pediu para atualizar: " + ", ".join(f"{k.split('_')[0]} → {v}" for k, v in novos.items())
                         + ". Confirme para gravar no cadastro.",
            "evidencia": novos, "pergunta": None,
        })
        db.auditar(atestado_id, "agente", "alerta_gerado", "C1", {"campos": list(novos)})
    db.auditar(atestado_id, "colaborador", "preferencias_registradas", detalhe=campos)
    return {"ok": True, **campos}


def registrar_complemento(atestado_id: int, texto: str) -> dict:
    texto = " ".join((texto or "").split())[:1000] or "(nada a complementar)"
    db.atualizar_atestado(atestado_id, {"complemento": texto})
    db.auditar(atestado_id, "colaborador", "complemento_registrado", detalhe={"tem_texto": texto != "(nada a complementar)"})
    return {"ok": True}


# ---------------------------------------------------------------------------
# 4. Finalização do chat e e-mails
# ---------------------------------------------------------------------------
def finalizar_chat(atestado_id: int, motivo: str = "concluido") -> dict:
    at, func, alertas = contexto_caso(atestado_id)
    if at["chat_finalizado_em"]:
        return {"ok": True, "protocolo": at["protocolo"], "status": at["status"], "ja_finalizado": True}
    pend = pendencias_chat(at, func, alertas)
    if motivo == "concluido" and pend:
        return {"ok": False, "erro": "Ainda há pendências.", "faltando": [p["descricao"] for p in pend]}

    abertos = [a for a in alertas if a["status"] == "aberto"]
    if abertos:
        status = "aguardando_rh"
    elif any((a.get("decidido_por") or "").startswith("rh:") for a in alertas):
        status = "resolvido"
    else:
        status = "sem_pendencias"
    momento = db.agora()
    db.atualizar_atestado(atestado_id, {
        "status": status, "chat_finalizado_em": momento, "resolvido_em": momento if status == "resolvido" else None,
    })
    at.update(status=status)

    emails = []
    if at.get("receber_email"):
        emails.append(notificacoes.confirmacao_funcionario(at, func, abertos))
    emails.append(notificacoes.aviso_rh(at, func, abertos))
    db.auditar(atestado_id, "agente", "chat_finalizado", detalhe={
        "motivo": motivo, "status": status, "pendencias_nao_respondidas": [p["descricao"] for p in pend],
        "emails": [f"{e['para']}:{e['status']}" for e in emails],
    })
    return {"ok": True, "protocolo": at["protocolo"], "status": status, "alertas_abertos": len(abertos),
            "emails": emails}


# ---------------------------------------------------------------------------
# 5. Decisões humanas (só pelo painel do RH)
# ---------------------------------------------------------------------------
def decidir_alerta(alerta_id: int, decisao: str, responsavel: str, observacao: str = "") -> dict:
    if decisao not in ("confirmado", "descartado"):
        raise ValueError("decisão inválida")
    if not responsavel.strip():
        raise PermissionError("decisão exige o nome do responsável do RH")
    alerta = db.buscar_alerta(alerta_id)
    if alerta is None or alerta["status"] != "aberto":
        return {"ok": False, "erro": "alerta não está aberto"}
    ator = f"rh:{responsavel.strip()}"
    db.atualizar_alerta(alerta_id, {"status": decisao, "decidido_por": ator[:60],
                                    "decisao_obs": observacao.strip()[:500] or None, "decidido_em": db.agora()})
    atestado_id = alerta["atestado_id"]
    db.auditar(atestado_id, ator, "alerta_decidido", alerta["codigo"], {"decisao": decisao, "observacao": observacao})

    at, func, alertas = contexto_caso(atestado_id)
    if alerta["codigo"] == "C1" and decisao == "confirmado":
        ev = alerta["evidencia"]
        db.atualizar_contato_funcionario(func["id"], ev.get("telefone_novo"), ev.get("email_novo"))
        db.auditar(atestado_id, ator, "cadastro_atualizado", "C1", {"campos": list(ev)})

    if not any(a["status"] == "aberto" for a in alertas) and at["chat_finalizado_em"]:
        _resolver(at, func, ator)
    return {"ok": True}


def concluir_caso(atestado_id: int, responsavel: str, observacao: str = "") -> dict:
    """RH marca como conferido um caso sem alertas abertos."""
    at, func, alertas = contexto_caso(atestado_id)
    if any(a["status"] == "aberto" for a in alertas):
        return {"ok": False, "erro": "ainda há alertas abertos"}
    ator = f"rh:{responsavel.strip()}"
    db.auditar(atestado_id, ator, "caso_conferido", detalhe={"observacao": observacao})
    _resolver(at, func, ator)
    return {"ok": True}


def _resolver(at: dict, func: dict, ator: str) -> None:
    if at["status"] == "resolvido":
        return
    db.atualizar_atestado(at["id"], {"status": "resolvido", "resolvido_em": db.agora()})
    at["status"] = "resolvido"
    if at.get("receber_email"):
        notificacoes.andamento_funcionario(at, func)
    db.auditar(at["id"], ator, "caso_resolvido")

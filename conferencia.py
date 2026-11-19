"""Conferência determinística: atestado × documento × ponto × histórico.

Regra de ouro do projeto: datas e horários são conferidos por funções
Python fixas. O LLM só explica os resultados e conversa com o
funcionário. Nenhuma função aqui altera o ponto ou decide sobre o
atestado: elas só geram ALERTAS para uma pessoa do RH confirmar ou
descartar. O texto usa sempre "divergência a verificar", nunca "fraude".

Alertas
  A1  Ponto registrado durante o afastamento            (alta)
  A2  Faltas sem justificativa perto do afastamento     (média)
  A3  Formulário diferente do documento                 (média)
  A4  Atestado duplicado ou período já coberto          (alta)
  A5  Afastamento acima de 15 dias (INSS)               (média)
  A6  Nome no documento diferente do funcionário        (média)
  A7  Documento não conferido automaticamente           (baixa)
  A8  Sem documento válido                              (alta)
  C1  Atualização de cadastro pedida pelo funcionário   (baixa; criado no chat)
"""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

import config
from datas import dias, dias_uteis_vizinhos, eh_dia_util, formatar

CODIGOS_AUTOMATICOS = {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"}
ORDEM_GRAVIDADE = {"alta": 0, "media": 1, "baixa": 2}


@dataclass
class Alerta:
    codigo: str
    gravidade: str
    titulo: str
    descricao: str
    evidencia: dict = field(default_factory=dict)
    pergunta: str | None = None   # o que o agente pergunta ao funcionário (None = só para o RH)

    def para_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResultadoConferencia:
    alertas: list[Alerta]
    observacoes: list[str]        # notas que não são alerta (ex.: 1º dia parcial)

    @property
    def codigos(self) -> set[str]:
        return {a.codigo for a in self.alertas}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _minutos(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def _normalizar_nome(nome: str) -> list[str]:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", nome or "") if unicodedata.category(c) != "Mn")
    particulas = {"da", "de", "do", "das", "dos", "e"}
    return [t for t in sem_acento.lower().replace(".", " ").split() if t not in particulas]


def nomes_compativeis(cadastro: str, documento: str) -> bool:
    """'Ana Oliveira' é compatível com 'Ana Paula Oliveira'; não com 'Pedro Souza'."""
    a, b = _normalizar_nome(cadastro), _normalizar_nome(documento)
    if not a or not b:
        return True  # sem nome legível não dá para afirmar divergência

    def parecidos(x: str, y: str) -> bool:  # tolera erro de grafia ou leitura (Isabela/Izabela)
        return SequenceMatcher(None, x, y).ratio() >= 0.8

    return parecidos(a[0], b[0]) and any(parecidos(a[-1], t) for t in b[1:] or b)


def _lista_datas(datas_: list[date]) -> str:
    return ", ".join(d.strftime("%d/%m") for d in datas_)


# ---------------------------------------------------------------------------
# Verificações (cada uma independente e testável)
# ---------------------------------------------------------------------------
def verificar_documento(at: dict) -> list[Alerta]:
    if not at.get("documento_aceito"):
        return [Alerta(
            "A8", "alta", "Sem documento válido",
            "Nenhum arquivo legível e do tipo aceito foi recebido até agora"
            + (f" (último motivo: {at['documento_motivo']})." if at.get("documento_motivo") else "."),
            {"tentativas": at.get("tentativas_envio", 0)},
        )]
    sem_extracao = all(at.get(k) in (None, "") for k in ("doc_nome", "doc_data_inicio", "doc_dias"))
    if at.get("tipo_detectado") in (None, "nao_verificado") or sem_extracao:
        return [Alerta(
            "A7", "baixa", "Documento não conferido automaticamente",
            "O arquivo está legível, mas a IA não conseguiu ler o tipo ou os dados. Confira o documento manualmente.",
            {"tipo_detectado": at.get("tipo_detectado")},
        )]
    return []


def verificar_trabalho_no_afastamento(at: dict, func: dict, ponto: dict[date, dict], ontem: date,
                                      observacoes: list[str]) -> list[Alerta]:
    inicio, fim = at["data_inicio"], at["data_fim"]
    if at["tipo"] == "declaracao_comparecimento":
        if any(p["situacao"] == "trabalhado" for d, p in ponto.items() if inicio <= d <= fim):
            observacoes.append("Declaração de comparecimento cobre só algumas horas: presença no ponto no mesmo dia é esperada.")
        return []

    jornada_ini, jornada_fim = _minutos(func["jornada_inicio"]), _minutos(func["jornada_fim"])
    limite_parcial = jornada_ini + config.FRACAO_PRIMEIRO_DIA_PARCIAL * (jornada_fim - jornada_ini)
    dias_com_registro = []
    for d in dias(inicio, min(fim, ontem)):
        p = ponto.get(d)
        if not p or p["situacao"] != "trabalhado":
            continue
        saida = _minutos(p.get("saida"))
        if d == inicio and saida is not None and saida <= limite_parcial:
            observacoes.append(
                f"No 1º dia ({formatar(d)}) houve entrada às {p['entrada']} e saída às {p['saida']}: "
                "entendido como saída para o atendimento (não é alerta)."
            )
            continue
        dias_com_registro.append({"data": d.isoformat(), "entrada": p.get("entrada"), "saida": p.get("saida")})

    if fim >= ontem + timedelta(days=1):
        observacoes.append("O afastamento ainda está em curso: os dias a partir de hoje não têm ponto para conferir.")
    if not dias_com_registro:
        return []
    datas_txt = ", ".join(
        f"{date.fromisoformat(r['data']):%d/%m} ({r['entrada']}–{r['saida']})" for r in dias_com_registro
    )
    primeiro = dias_com_registro[0]
    return [Alerta(
        "A1", "alta", "Ponto registrado durante o afastamento",
        f"Há registro de trabalho em {len(dias_com_registro)} dia(s) dentro do período do atestado: {datas_txt}.",
        {"dias": dias_com_registro},
        f"No ponto aparece entrada às {primeiro['entrada']} e saída às {primeiro['saida']} no dia "
        f"{date.fromisoformat(primeiro['data']):%d/%m}, que está dentro do período do atestado. "
        "Pode me ajudar a entender o que aconteceu nesse dia?",
    )]


def verificar_faltas_vizinhas(at: dict, ponto: dict[date, dict], ontem: date) -> list[Alerta]:
    vizinhos = dias_uteis_vizinhos(at["data_inicio"], at["data_fim"], config.JANELA_FALTAS_DIAS_UTEIS, ontem)
    faltas = [d for d in vizinhos
              if (p := ponto.get(d)) and p["situacao"] == "falta" and not p.get("justificativa")]
    if not faltas:
        return []
    return [Alerta(
        "A2", "media", "Faltas sem justificativa perto do afastamento",
        f"{len(faltas)} falta(s) sem justificativa em dias úteis próximos ao atestado: {_lista_datas(faltas)}.",
        {"datas": [d.isoformat() for d in faltas]},
        f"No ponto aparecem faltas sem justificativa em {_lista_datas(faltas)}. "
        "Você tem atestado ou outra justificativa para esses dias?",
    )]


def verificar_formulario_x_documento(at: dict) -> list[Alerta]:
    if not at.get("documento_aceito"):
        return []
    diferencas, partes_pergunta = [], []
    doc_inicio, doc_dias = at.get("doc_data_inicio"), at.get("doc_dias")
    if doc_inicio and doc_inicio != at["data_inicio"]:
        diferencas.append({"campo": "data de início", "formulario": at["data_inicio"].isoformat(), "documento": doc_inicio.isoformat()})
        partes_pergunta.append(f"início em {formatar(doc_inicio)} (no formulário: {formatar(at['data_inicio'])})")
    if doc_dias and int(doc_dias) != int(at["dias"]):
        diferencas.append({"campo": "dias", "formulario": int(at["dias"]), "documento": int(doc_dias)})
        partes_pergunta.append(f"{doc_dias} dia(s) (no formulário: {at['dias']})")
    tipo_doc = at.get("tipo_detectado")
    if tipo_doc in config.TIPOS_DOCUMENTO and tipo_doc != at["tipo"]:
        diferencas.append({"campo": "tipo", "formulario": at["tipo"], "documento": tipo_doc})
        partes_pergunta.append(f"tipo {config.TIPOS_DOCUMENTO[tipo_doc].lower()} "
                               f"(no formulário: {config.TIPOS_DOCUMENTO[at['tipo']].lower()})")
    if not diferencas:
        return []
    return [Alerta(
        "A3", "media", "Formulário diferente do documento",
        "O documento indica " + "; ".join(partes_pergunta) + ".",
        {"diferencas": diferencas},
        "O documento indica " + " e ".join(partes_pergunta) + ". Qual informação está correta?",
    )]


def verificar_duplicidade(at: dict, outros: list[dict], mesmo_arquivo: list[dict]) -> list[Alerta]:
    inicio, fim = at["data_inicio"], at["data_fim"]
    sobrepostos = [o for o in outros if o["data_inicio"] <= fim and inicio <= o["data_fim"]]
    if not (mesmo_arquivo or sobrepostos):
        return []
    protocolos = sorted({o["protocolo"] for o in [*mesmo_arquivo, *sobrepostos]})
    motivos = []
    if mesmo_arquivo:
        motivos.append("o mesmo arquivo já foi enviado")
    if sobrepostos:
        motivos.append("o período coincide com outro atestado")
    return [Alerta(
        "A4", "alta", "Atestado duplicado ou período já coberto",
        f"{' e '.join(motivos).capitalize()} (protocolo {', '.join(protocolos)}).",
        {"protocolos": protocolos, "mesmo_arquivo": bool(mesmo_arquivo), "sobreposicao": bool(sobrepostos)},
        f"Já existe um atestado registrado para esse período (protocolo {protocolos[0]}). "
        "Você está reenviando o mesmo documento ou é um novo afastamento?",
    )]


def verificar_duracao(at: dict) -> list[Alerta]:
    if at["tipo"] != "atestado_medico" or int(at["dias"]) <= config.LIMITE_INSS_DIAS:
        return []
    return [Alerta(
        "A5", "media", f"Afastamento acima de {config.LIMITE_INSS_DIAS} dias (INSS)",
        f"Afastamento de {at['dias']} dias: os primeiros {config.LIMITE_INSS_DIAS} são de responsabilidade da empresa; "
        f"a partir do {config.LIMITE_INSS_DIAS + 1}º dia o caso deve ser encaminhado ao INSS.",
        {"dias": int(at["dias"])},
    )]


def verificar_nome(at: dict, func: dict) -> list[Alerta]:
    nome_doc = at.get("doc_nome")
    if not at.get("documento_aceito") or not nome_doc or nomes_compativeis(func["nome"], nome_doc):
        return []
    return [Alerta(
        "A6", "media", "Nome no documento diferente do funcionário",
        f"O documento está em nome de \"{nome_doc}\"; o cadastro é de \"{func['nome']}\".",
        {"nome_documento": nome_doc, "nome_cadastro": func["nome"]},
        f"O documento parece estar em nome de {nome_doc}. Foi anexado o arquivo certo, "
        "ou é um atestado de acompanhante?",
    )]


# ---------------------------------------------------------------------------
# Conferência completa
# ---------------------------------------------------------------------------
def conferir(atestado: dict, funcionario: dict, ponto: list[dict], outros_atestados: list[dict],
             mesmo_arquivo: list[dict], hoje: date) -> ResultadoConferencia:
    """Roda todas as verificações e devolve os alertas e as observações."""
    ontem = hoje - timedelta(days=1)
    por_dia = {p["data"]: p for p in ponto}
    observacoes: list[str] = []
    alertas = [
        *verificar_documento(atestado),
        *verificar_trabalho_no_afastamento(atestado, funcionario, por_dia, ontem, observacoes),
        *verificar_faltas_vizinhas(atestado, por_dia, ontem),
        *verificar_formulario_x_documento(atestado),
        *verificar_duplicidade(atestado, outros_atestados, mesmo_arquivo),
        *verificar_duracao(atestado),
        *verificar_nome(atestado, funcionario),
    ]
    alertas.sort(key=lambda a: (ORDEM_GRAVIDADE[a.gravidade], a.codigo))
    return ResultadoConferencia(alertas, observacoes)


def janela_ponto(inicio: date, fim: date) -> tuple[date, date]:
    """Intervalo de ponto que a conferência precisa ler (período + vizinhos)."""
    folga = config.JANELA_FALTAS_DIAS_UTEIS * 3 + 4
    return inicio - timedelta(days=folga), fim + timedelta(days=folga)


__all__ = ["Alerta", "ResultadoConferencia", "conferir", "janela_ponto", "nomes_compativeis",
           "CODIGOS_AUTOMATICOS", "eh_dia_util"]

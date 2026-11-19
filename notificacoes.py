"""Ferramenta de e-mail do agente: modo simulação ou SMTP.

Segurança:
  - O destinatário é SEMPRE escolhido pelo sistema: o e-mail do cadastro
    do funcionário ou o EMAIL_RH do .env. O LLM nunca escolhe endereço.
  - Um e-mail digitado no formulário só passa a valer depois que o RH
    aprovar a atualização do cadastro (alerta C1).
  - Cada destinatário recebe só o necessário: o RH não recebe motivo nem
    documento; o funcionário não recebe observações internas do RH.

Modo simulação (padrão): nada sai do computador; os e-mails ficam na
tabela notificacoes e aparecem na aba "Caixa de saída" do painel.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import config
import db
from datas import formatar

ROTULO_STATUS = {
    "em_atendimento": "em atendimento",
    "aguardando_rh": "em conferência pelo RH",
    "sem_pendencias": "recebido, sem pendências",
    "resolvido": "conferido pelo RH",
}


def _enviar_smtp(destinatario: str, assunto: str, corpo: str) -> None:
    mensagem = EmailMessage()
    mensagem["From"] = config.EMAIL_REMETENTE
    mensagem["To"] = destinatario
    mensagem["Subject"] = assunto
    mensagem.set_content(corpo)
    contexto = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=contexto, timeout=20) as smtp:
            smtp.login(config.SMTP_USUARIO, config.SMTP_SENHA)
            smtp.send_message(mensagem)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls(context=contexto)
            smtp.login(config.SMTP_USUARIO, config.SMTP_SENHA)
            smtp.send_message(mensagem)


def enviar(tipo: str, destinatario_tipo: str, destinatario: str, assunto: str, corpo: str,
           atestado_id: int | None = None) -> dict:
    """Registra e (no modo smtp) envia. Nunca levanta exceção: falha vira status 'falhou'."""
    modo = "smtp" if config.EMAIL_MODO == "smtp" else "simulacao"
    destino_real = destinatario
    if modo == "smtp" and config.EMAIL_REDIRECIONAR_PARA:
        destino_real = config.EMAIL_REDIRECIONAR_PARA
        assunto = f"[teste → {destinatario}] {assunto}"

    status, erro = "simulado", None
    if modo == "smtp":
        try:
            _enviar_smtp(destino_real, assunto, corpo)
            status = "enviado"
        except Exception as e:  # credencial, rede, porta bloqueada...
            status, erro = "falhou", str(e)

    registro = {
        "atestado_id": atestado_id, "tipo": tipo, "destinatario_tipo": destinatario_tipo,
        "destinatario": destino_real, "assunto": assunto, "corpo": corpo,
        "modo": modo, "status": status, "erro": erro,
    }
    try:
        db.registrar_notificacao(registro)
    except db.ErroBanco as e:
        erro = f"{erro or ''} (não registrado no banco: {e})".strip()
    return {"tipo": tipo, "para": destinatario_tipo, "status": status, "erro": erro}


# ---------------------------------------------------------------------------
# Modelos de mensagem
# ---------------------------------------------------------------------------
def _periodo(at: dict) -> str:
    if at["data_inicio"] == at["data_fim"]:
        return formatar(at["data_inicio"])
    return f"{formatar(at['data_inicio'])} a {formatar(at['data_fim'])} ({at['dias']} dias)"


def confirmacao_funcionario(at: dict, func: dict, alertas_abertos: list[dict]) -> dict:
    primeiro_nome = func["nome"].split()[0]
    linhas = [
        f"Olá, {primeiro_nome}.",
        "",
        f"Recebemos o seu {config.TIPOS_DOCUMENTO[at['tipo']].lower()}.",
        f"Protocolo: {at['protocolo']}",
        f"Período: {_periodo(at)}",
        f"Situação: {ROTULO_STATUS.get(at['status'], at['status'])}",
    ]
    itens = [a["titulo"] for a in alertas_abertos if a["codigo"] != "C1"]
    if itens:
        linhas += ["", "O RH vai conferir os seguintes pontos com você, se necessário:"]
        linhas += [f"  - {t}" for t in itens]
    linhas += ["", "Você receberá um novo e-mail quando a conferência terminar.", "",
               "Mensagem automática do assistente de RH (Sinergia). Não responda este e-mail."]
    return enviar("confirmacao", "funcionario", func["email"],
                  f"Atestado recebido · protocolo {at['protocolo']}", "\n".join(linhas), at["id"])


def aviso_rh(at: dict, func: dict, alertas_abertos: list[dict]) -> dict:
    graves = sum(1 for a in alertas_abertos if a["gravidade"] == "alta")
    linhas = [
        f"Novo atestado recebido pelo agente: {func['nome']} ({func['id']}, {func['setor']}).",
        "",
        f"Protocolo: {at['protocolo']}",
        f"Tipo: {config.TIPOS_DOCUMENTO[at['tipo']]}",
        f"Período: {_periodo(at)}",
        f"Situação: {ROTULO_STATUS.get(at['status'], at['status'])}",
        "",
    ]
    if alertas_abertos:
        linhas.append(f"Alertas para conferir ({len(alertas_abertos)}):")
        for a in alertas_abertos:
            resposta = " · funcionário respondeu" if a.get("resposta_colaborador") else ""
            linhas.append(f"  - [{a['gravidade']}] {a['titulo']}{resposta}")
    else:
        linhas.append("Nenhuma divergência encontrada na conferência com o ponto.")
    linhas += ["", f"Abrir no painel: {config.URL_PAINEL}", "",
               "O documento e os detalhes ficam só no painel (não são enviados por e-mail)."]
    assunto = (f"[{'URGENTE' if graves else 'Atestado'}] {func['nome']} · "
               f"{len(alertas_abertos)} alerta(s) · {at['protocolo']}")
    return enviar("aviso_rh", "rh", config.EMAIL_RH, assunto, "\n".join(linhas), at["id"])


def andamento_funcionario(at: dict, func: dict) -> dict:
    primeiro_nome = func["nome"].split()[0]
    corpo = "\n".join([
        f"Olá, {primeiro_nome}.",
        "",
        f"O RH concluiu a conferência do seu atestado (protocolo {at['protocolo']}, período {_periodo(at)}).",
        "Se for preciso alguma ação da sua parte, o RH entrará em contato.",
        "",
        "Mensagem automática do assistente de RH (Sinergia). Não responda este e-mail.",
    ])
    return enviar("andamento", "funcionario", func["email"],
                  f"Atestado conferido · protocolo {at['protocolo']}", corpo, at["id"])


def testar_smtp() -> str:
    """Usado pelo verificar_ambiente.py: conecta e faz login, sem enviar nada."""
    contexto = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=contexto, timeout=15) as smtp:
            smtp.login(config.SMTP_USUARIO, config.SMTP_SENHA)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls(context=contexto)
            smtp.login(config.SMTP_USUARIO, config.SMTP_SENHA)
    return f"login SMTP ok em {config.SMTP_HOST}:{config.SMTP_PORT}"

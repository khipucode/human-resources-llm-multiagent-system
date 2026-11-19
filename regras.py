"""Cores do painel do RH: cada cor diz QUEM precisa agir."""

from __future__ import annotations

from datetime import datetime

import config

# Fundo com transparência para funcionar nos temas claro e escuro.
CORES = {
    "vermelho": {"emoji": "🔴", "rotulo": "RH precisa agir já", "fundo": "rgba(220, 53, 69, 0.24)"},
    "azul": {"emoji": "🔵", "rotulo": "Aguardando o RH", "fundo": "rgba(13, 110, 253, 0.20)"},
    "amarelo": {"emoji": "🟡", "rotulo": "Com o funcionário", "fundo": "rgba(255, 193, 7, 0.26)"},
    "verde": {"emoji": "🟢", "rotulo": "Sem pendências", "fundo": "rgba(25, 135, 84, 0.22)"},
    "cinza": {"emoji": "⚪", "rotulo": "Resolvido", "fundo": "rgba(108, 117, 125, 0.14)"},
}

STATUS_ROTULOS = {
    "em_atendimento": "Em atendimento",
    "aguardando_rh": "Aguardando o RH",
    "sem_pendencias": "Sem pendências",
    "resolvido": "Resolvido",
}

GRAVIDADE_ROTULOS = {"alta": "🔴 alta", "media": "🟠 média", "baixa": "🔵 baixa"}


def classificar_linha(reg: dict, agora: datetime) -> tuple[str, str]:
    """Escolhe a cor e o motivo, por ordem de prioridade."""
    abertos, graves = int(reg.get("alertas_abertos") or 0), int(reg.get("alertas_graves") or 0)
    horas = max(0.0, (agora - reg["criado_em"]).total_seconds() / 3600)

    if reg["status"] == "resolvido":
        return "cinza", "Conferido pelo RH"
    if graves:
        return "vermelho", f"{graves} alerta(s) grave(s)"
    if reg["status"] == "em_atendimento":
        if horas < config.LIMITE_EM_ATENDIMENTO_HORAS:
            return "amarelo", "Funcionário no chat agora"
        if abertos:
            return "azul", f"Chat não concluído · {abertos} alerta(s)"
        return "amarelo", "Chat não concluído"
    if abertos:
        return "azul", f"{abertos} alerta(s) para conferir"
    return "verde", "Ponto de acordo com o atestado"

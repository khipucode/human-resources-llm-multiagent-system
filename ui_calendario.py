"""Calendário do ponto em HTML (semanas de segunda a domingo).

Cores com transparência, para funcionar nos temas claro e escuro.
O período do atestado aparece com borda tracejada roxa e os dias com
alerta, com borda vermelha.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

from datas import dias

FUNDO = {
    "trabalhado": "rgba(25, 135, 84, 0.20)",
    "falta": "rgba(255, 140, 0, 0.34)",
    "afastado": "rgba(13, 110, 253, 0.22)",
    "folga": "rgba(128, 128, 128, 0.13)",
    "feriado": "rgba(128, 128, 128, 0.13)",
}
ROTULO = {"falta": "Falta", "afastado": "Afastado", "folga": "Folga", "feriado": "Feriado"}

ESTILO = """
<style>
.sng-cal {width:100%; border-collapse:separate; border-spacing:4px; table-layout:fixed; font-size:0.78rem;}
.sng-cal tr, .sng-cal th {border:none !important; background:transparent !important;}
.sng-cal th {font-weight:600; opacity:0.7; text-align:center; padding:2px 0;}
.sng-cal td {border-radius:6px; padding:4px 5px; height:46px; vertical-align:top; border:2px solid transparent;}
.sng-cal td .d {font-weight:600;}
.sng-cal td .s {opacity:0.85; font-size:0.72rem; line-height:1.15;}
.sng-cal td.fora {opacity:0.35;}
.sng-cal td.periodo {border:2px dashed #8b5cf6;}
.sng-cal td.alerta {border:3px solid #dc3545;}
.sng-leg {display:flex; flex-wrap:wrap; gap:10px; font-size:0.75rem; margin:4px 0 2px;}
.sng-leg span {display:inline-flex; align-items:center; gap:4px;}
.sng-leg i {display:inline-block; width:14px; height:14px; border-radius:3px;}
</style>
"""


def calendario_html(ponto: list[dict], inicio: date, fim: date,
                    periodos: list[tuple[date, date]] = (), dias_alerta: set[date] = frozenset()) -> str:
    por_dia = {p["data"]: p for p in ponto}
    primeiro = inicio - timedelta(days=inicio.weekday())
    ultimo = fim + timedelta(days=6 - fim.weekday())
    linhas = []
    semana = []
    for d in dias(primeiro, ultimo):
        p = por_dia.get(d)
        classes = []
        if not (inicio <= d <= fim):
            classes.append("fora")
        if d in dias_alerta:
            classes.append("alerta")
        elif any(a <= d <= b for a, b in periodos):
            classes.append("periodo")
        if p:
            fundo = FUNDO.get(p["situacao"], "transparent")
            if p["situacao"] == "trabalhado":
                texto = f"{p.get('entrada') or '?'}–{p.get('saida') or '?'}"
            else:
                texto = ROTULO.get(p["situacao"], p["situacao"])
            titulo = p.get("justificativa") or ""
        else:
            fundo, texto, titulo = "transparent", "", ""
        semana.append(
            f'<td class="{" ".join(classes)}" style="background:{fundo}" title="{html.escape(titulo)}">'
            f'<div class="d">{d:%d/%m}</div><div class="s">{html.escape(texto)}</div></td>'
        )
        if d.weekday() == 6:
            linhas.append("<tr>" + "".join(semana) + "</tr>")
            semana = []
    cabecalho = "".join(f"<th>{n}</th>" for n in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"])
    legenda = (
        '<div class="sng-leg">'
        f'<span><i style="background:{FUNDO["trabalhado"]}"></i>Trabalhado</span>'
        f'<span><i style="background:{FUNDO["falta"]}"></i>Falta</span>'
        f'<span><i style="background:{FUNDO["afastado"]}"></i>Afastado (já justificado)</span>'
        f'<span><i style="background:{FUNDO["folga"]}"></i>Folga / feriado</span>'
        '<span><i style="border:2px dashed #8b5cf6"></i>Período do atestado</span>'
        '<span><i style="border:3px solid #dc3545"></i>Dia com alerta</span>'
        "</div>"
    )
    return f'{ESTILO}<table class="sng-cal"><tr>{cabecalho}</tr>{"".join(linhas)}</table>{legenda}'


def dias_com_alerta(alertas: list[dict]) -> set[date]:
    """Dias citados na evidência dos alertas A1 (trabalho) e A2 (faltas)."""
    resultado = set()
    for a in alertas:
        if a["status"] == "descartado":
            continue
        ev = a.get("evidencia") or {}
        for item in ev.get("dias", []):
            resultado.add(date.fromisoformat(item["data"]))
        for texto in ev.get("datas", []):
            resultado.add(date.fromisoformat(texto))
    return resultado

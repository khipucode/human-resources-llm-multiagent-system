"""Funções de calendário usadas pela conferência e pelo simulador de ponto."""

from __future__ import annotations

from datetime import date, timedelta

import config

DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def eh_feriado(d: date) -> bool:
    return (d.day, d.month) in config.FERIADOS_FIXOS


def eh_dia_util(d: date) -> bool:
    """Jornada de segunda a sexta, sem feriados nacionais fixos."""
    return d.weekday() < 5 and not eh_feriado(d)


def dias(inicio: date, fim: date):
    """Todos os dias de inicio a fim, inclusive."""
    d = inicio
    while d <= fim:
        yield d
        d += timedelta(days=1)


def dia_util_antes(referencia: date, n: int) -> date:
    """n-ésimo dia útil antes da referência (n=1 é o último dia útil antes dela)."""
    d, contados = referencia, 0
    while contados < n:
        d -= timedelta(days=1)
        if eh_dia_util(d):
            contados += 1
    return d


def dias_uteis_vizinhos(inicio: date, fim: date, n: int, limite: date) -> list[date]:
    """Até n dias úteis antes de inicio e até n depois de fim (sem passar de limite)."""
    antes, d = [], inicio
    while len(antes) < n:
        d -= timedelta(days=1)
        if eh_dia_util(d):
            antes.append(d)
    depois, d = [], fim
    while len(depois) < n:
        d += timedelta(days=1)
        if d > limite:
            break
        if eh_dia_util(d):
            depois.append(d)
    return sorted(antes) + depois


def formatar(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"

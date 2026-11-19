"""Testes da conferência determinística (não precisam de banco nem de Groq).

Rode com:  python -m pytest -q
Cada cenário de cenarios.py diz quais alertas o agente deve gerar; aqui
conferimos isso em várias datas diferentes (feriados, viradas de mês, ...).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cenarios import FUNCIONARIOS_POR_ID, atestado_previo_daniel, gerar_ponto, montar_cenarios  # noqa: E402
from conferencia import conferir, nomes_compativeis  # noqa: E402

HASH_DANIEL = "d" * 64
DATAS = [date(2026, 10, 29), date(2026, 11, 2), date(2026, 11, 16), date(2026, 12, 26), date(2027, 1, 4)]
DATAS += [date(2026, 9, 1) + timedelta(days=i) for i in range(0, 120, 7)]


def _hhmm(valor):
    return valor[:5] if valor else None


def montar_mundo(hoje: date):
    ponto = {}
    for p in gerar_ponto(hoje):
        ponto.setdefault(p["funcionario_id"], []).append(
            {**p, "entrada": _hhmm(p["entrada"]), "saida": _hhmm(p["saida"])}
        )
    previo = atestado_previo_daniel(hoje, HASH_DANIEL)
    previo_resumo = {"protocolo": previo["protocolo"], **{k: previo["campos"][k] for k in ("data_inicio", "data_fim")}}
    return ponto, previo_resumo


def atestado_do_cenario(c, **mudancas) -> dict:
    at = {
        "tipo": c.tipo, "data_inicio": c.inicio, "data_fim": c.fim, "dias": c.dias,
        "documento_aceito": 1, "tipo_detectado": c.tipo, "confianca_tipo": 0.95,
        "doc_nome": c.doc_nome, "doc_data_inicio": c.doc_inicio, "doc_dias": c.doc_dias,
        "arquivo_sha256": HASH_DANIEL if c.funcionario_id == "FUNC004" else "x" * 64,
    }
    at.update(mudancas)
    return at


def conferir_cenario(c, hoje, ponto, previo, **mudancas):
    at = atestado_do_cenario(c, **mudancas)
    daniel = c.funcionario_id == "FUNC004"
    return conferir(
        at, FUNCIONARIOS_POR_ID[c.funcionario_id], ponto[c.funcionario_id],
        outros_atestados=[previo] if daniel else [],
        mesmo_arquivo=[previo] if daniel else [],
        hoje=hoje,
    )


@pytest.mark.parametrize("hoje", DATAS, ids=lambda d: d.isoformat())
def test_cenarios_geram_os_alertas_esperados(hoje):
    ponto, previo = montar_mundo(hoje)
    for c in montar_cenarios(hoje):
        resultado = conferir_cenario(c, hoje, ponto, previo)
        assert resultado.codigos == set(c.esperado), (c.funcionario_id, c.titulo, resultado.alertas)


def test_cenarios_ficam_dentro_do_historico_de_ponto():
    hoje = date(2026, 10, 29)
    for c in montar_cenarios(hoje):
        assert hoje - timedelta(days=30) <= c.inicio and c.fim < hoje, c


def test_primeiro_dia_parcial_vira_observacao_e_nao_alerta():
    hoje = date(2026, 10, 29)
    ponto, previo = montar_mundo(hoje)
    gabriela = next(c for c in montar_cenarios(hoje) if c.funcionario_id == "FUNC007")
    resultado = conferir_cenario(gabriela, hoje, ponto, previo)
    assert not resultado.alertas
    assert any("1º dia" in o for o in resultado.observacoes)


def test_declaracao_tratada_como_atestado_gera_alerta():
    """Se o mesmo dia fosse um atestado de dia inteiro, a presença à tarde seria alerta."""
    hoje = date(2026, 10, 29)
    ponto, previo = montar_mundo(hoje)
    henrique = next(c for c in montar_cenarios(hoje) if c.funcionario_id == "FUNC008")
    # 13:30 passa da metade da jornada: não é "1º dia parcial"
    resultado = conferir_cenario(henrique, hoje, ponto, previo, tipo="atestado_medico", tipo_detectado="atestado_medico")
    assert "A1" in resultado.codigos


def test_documento_nao_aceito_gera_a8_e_nao_compara_dados():
    hoje = date(2026, 10, 29)
    ponto, previo = montar_mundo(hoje)
    ana = montar_cenarios(hoje)[0]
    resultado = conferir_cenario(ana, hoje, ponto, previo, documento_aceito=0, doc_nome="Outra Pessoa", doc_dias=9)
    assert resultado.codigos == {"A8"}


def test_sem_extracao_gera_a7():
    hoje = date(2026, 10, 29)
    ponto, previo = montar_mundo(hoje)
    ana = montar_cenarios(hoje)[0]
    resultado = conferir_cenario(ana, hoje, ponto, previo, tipo_detectado="nao_verificado",
                                 doc_nome=None, doc_data_inicio=None, doc_dias=None)
    assert resultado.codigos == {"A7"}


def test_tipo_diferente_entra_no_a3():
    hoje = date(2026, 10, 29)
    ponto, previo = montar_mundo(hoje)
    ana = montar_cenarios(hoje)[0]
    resultado = conferir_cenario(ana, hoje, ponto, previo, tipo_detectado="atestado_acompanhante")
    assert resultado.codigos == {"A3"}
    assert resultado.alertas[0].pergunta


@pytest.mark.parametrize("cadastro, documento, esperado", [
    ("Ana Oliveira", "Ana Paula Oliveira", True),
    ("Ana Oliveira", "ANA OLIVEIRA", True),
    ("João Pereira", "Joao Pereira", True),
    ("Isabela Ribeiro", "Izabela Ribeiro", True),
    ("João Pereira", "Pedro Henrique Souza", False),
    ("Carla Ferreira", "Carlos Ferreira", False),
])
def test_nomes_compativeis(cadastro, documento, esperado):
    assert nomes_compativeis(cadastro, documento) is esperado

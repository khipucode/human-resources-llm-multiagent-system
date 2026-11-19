"""Cria as tabelas da v2 e carrega o mundo simulado.

Uso:
  python preparar_banco.py            # cria tabelas e carrega os dados (se ainda não houver)
  python preparar_banco.py --recriar  # apaga as tabelas da v2 e recria tudo com datas de hoje

Também gera os atestados sintéticos de cada cenário em exemplos/cenarios/
e um roteiro de demonstração (exemplos/cenarios/ROTEIRO.md).
As tabelas da v1 (colaboradores, atendimentos, eventos, mensagens) não são tocadas.
"""

from __future__ import annotations

import argparse
import hashlib
import sys

import config
import db
from cenarios import FUNCIONARIOS, atestado_previo_daniel, gerar_ponto, montar_cenarios
from datas import formatar
from gerar_atestados_sinteticos import gerar_documento_cenario, gerar_exemplos_qualidade


def gerar_documentos(hoje) -> dict[str, str]:
    """Gera o PDF de cada cenário e devolve o SHA-256 por funcionário."""
    hashes = {}
    pasta = config.PASTA_EXEMPLOS / "cenarios"
    pasta.mkdir(parents=True, exist_ok=True)
    for c in montar_cenarios(hoje):
        gerar_documento_cenario(c, c.caminho_arquivo)
        hashes[c.funcionario_id] = hashlib.sha256(c.caminho_arquivo.read_bytes()).hexdigest()
    return hashes


def escrever_roteiro(hoje) -> None:
    linhas = [
        "# Roteiro de demonstração",
        "",
        f"Gerado em {formatar(hoje)}. As datas mudam se você rodar `python preparar_banco.py --recriar` outro dia.",
        "",
        "No formulário, com MODO_DEMO=1, escolha o cenário e os campos são preenchidos sozinhos.",
        "",
        "| ID | Funcionário | Tipo | Início | Término | Arquivo | O agente deve |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in montar_cenarios(hoje):
        esperado = ", ".join(sorted(c.esperado)) or "não alertar"
        linhas.append(
            f"| {c.funcionario_id} | {c.nome} | {config.TIPOS_DOCUMENTO[c.tipo]} | {formatar(c.inicio)} | "
            f"{formatar(c.fim)} | `{c.arquivo}` | {esperado}: {c.explicacao} |"
        )
    (config.PASTA_EXEMPLOS / "cenarios" / "ROTEIRO.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recriar", action="store_true", help="apaga as tabelas da v2 e recria tudo")
    args = parser.parse_args()
    hoje = db.hoje()

    try:
        if args.recriar:
            db.apagar_tabelas_v2()
            print("Tabelas da v2 apagadas.")
        db.executar_script((config.RAIZ / "schema.sql").read_text(encoding="utf-8"))
        print("Tabelas prontas:", ", ".join(t for t in db.tabelas_existentes() if t in db.TABELAS_V2))

        hashes = gerar_documentos(hoje)
        escrever_roteiro(hoje)
        gerar_exemplos_qualidade()
        print(f"Atestados sintéticos em {config.PASTA_EXEMPLOS} (cenarios/ e qualidade/)")

        if db.contar("funcionarios") > 0:
            print("Já existem dados. Para gerar de novo com as datas de hoje: python preparar_banco.py --recriar")
            return

        momento = db.agora()
        db.inserir_varios("funcionarios", [{**f, "atualizado_em": momento} for f in FUNCIONARIOS])
        ponto = gerar_ponto(hoje)
        db.inserir_varios("ponto", ponto)
        previo = atestado_previo_daniel(hoje, hashes["FUNC004"])
        atestado_id = db.criar_atestado(previo["protocolo"], previo["funcionario_id"], previo["campos"], previo["criado_em"])
        db.auditar(atestado_id, "simulador", "registro_simulado", detalhe={"obs": "atestado anterior para o cenário de duplicado"})
    except db.ErroBanco as erro:
        print(f"[X] {erro}")
        print("    Rode `python verificar_ambiente.py` para conferir o .env e o MariaDB.")
        sys.exit(1)

    faltas = sum(1 for p in ponto if p["situacao"] == "falta")
    print(f"Carregados: {len(FUNCIONARIOS)} funcionários, {len(ponto)} registros de ponto "
          f"({faltas} faltas) e 1 atestado anterior (cenário de duplicado).")
    print("Roteiro da demonstração: exemplos/cenarios/ROTEIRO.md")


if __name__ == "__main__":
    main()

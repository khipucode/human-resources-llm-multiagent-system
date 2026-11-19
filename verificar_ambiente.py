"""Confere a configuração antes de rodar: .env, banco, dados simulados, Groq e e-mail.

Uso: python verificar_ambiente.py
"""

import sys

import config


def linha(ok: bool, texto: str) -> bool:
    print(("  [OK] " if ok else "  [X]  ") + texto)
    return ok


def main() -> None:
    tudo_ok = True

    print("1. Arquivo .env")
    for nome, valor in {
        "GROQ_API_KEY": config.GROQ_API_KEY, "MYSQL_USER": config.MYSQL["user"],
        "MYSQL_PASSWORD": config.MYSQL["password"], "MYSQL_DATABASE": config.MYSQL["database"],
        "SENHA_RH": config.SENHA_RH,
    }.items():
        tudo_ok &= linha(bool(valor), f"{nome} {'definido' if valor else 'FALTANDO'}")

    print("\n2. Banco de dados")
    try:
        import db

        info = db.testar_conexao()
        linha(True, f"conectado em {config.MYSQL['host']}:{config.MYSQL['port']} · {info['versao']}")
        faltam = set(db.TABELAS_V2) - set(info["tabelas"])
        if faltam:
            tudo_ok = linha(False, "faltam as tabelas da v2: rode  python preparar_banco.py") and False
        else:
            n = db.contar("funcionarios")
            tudo_ok &= linha(n > 0, f"{n} funcionários e {db.contar('ponto')} registros de ponto"
                             + ("" if n else ": rode  python preparar_banco.py"))
    except Exception as erro:
        tudo_ok = linha(False, str(erro)) and False
        print("       Dicas: confira se a MariaDB está rodando (sudo systemctl status mariadb)")
        print("       e se usuário, senha e banco do .env são os mesmos criados no console da MariaDB.")

    print("\n3. Groq")
    from agente import criar_cliente

    cliente = criar_cliente()
    if cliente is None:
        tudo_ok = linha(False, "sem GROQ_API_KEY") and False
    else:
        try:
            disponiveis = {m.id for m in cliente.models.list().data}
            for papel, modelo in (("chat", config.MODELO_CHAT), ("visão", config.MODELO_VISAO)):
                tudo_ok &= linha(modelo in disponiveis, f"modelo de {papel} '{modelo}' "
                                 + ("disponível" if modelo in disponiveis else
                                    "não encontrado: troque no .env (veja console.groq.com/docs/models)"))
        except Exception as erro:
            tudo_ok = linha(False, f"não foi possível consultar o Groq: {erro}") and False

    print("\n4. E-mail")
    if config.EMAIL_MODO != "smtp":
        linha(True, "modo simulação: os e-mails aparecem na aba 'Caixa de saída' do painel")
    else:
        import notificacoes

        try:
            linha(True, notificacoes.testar_smtp())
            if not config.EMAIL_REDIRECIONAR_PARA:
                print("       Atenção: sem EMAIL_REDIRECIONAR_PARA, os e-mails vão para os endereços @example.com "
                      "dos funcionários fictícios (que não existem).")
        except Exception as erro:
            tudo_ok = linha(False, f"SMTP falhou: {erro}") and False
            print("       No Gmail, use uma 'senha de app' (não a senha normal) e a porta 587.")

    print("\n" + ("Tudo pronto. Rode: streamlit run app.py" if tudo_ok else "Corrija os itens marcados com [X]."))
    sys.exit(0 if tudo_ok else 1)


if __name__ == "__main__":
    main()

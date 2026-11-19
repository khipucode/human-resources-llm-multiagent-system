"""Acesso ao banco (PyMySQL). Uma conexão curta por operação.

Aqui só há leitura e escrita. As decisões ficam em conferencia.py
(regras) e orquestrador.py (fluxo do caso).
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import date, datetime, timedelta

import pymysql
import pymysql.cursors

import config


class ErroBanco(Exception):
    """Falha de conexão ou de consulta."""


class ProtocoloDuplicado(ErroBanco):
    """O protocolo gerado já existe (colisão rara): gerar outro."""


def agora() -> datetime:
    """Data e hora de São Paulo, sem fuso, prontas para o DATETIME."""
    return datetime.now(config.FUSO).replace(tzinfo=None, microsecond=0)


def hoje() -> date:
    return agora().date()


def _json(valor) -> str:
    return json.dumps(valor or {}, ensure_ascii=False, default=str)


@contextlib.contextmanager
def conexao():
    faltando = [k for k in ("host", "user", "database") if not config.MYSQL[k]]
    if faltando:
        raise ErroBanco(f"Configure no .env: {', '.join('MYSQL_' + k.upper() for k in faltando)}")
    try:
        con = pymysql.connect(
            **config.MYSQL,
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except pymysql.MySQLError as erro:
        raise ErroBanco(f"Não foi possível conectar ao banco: {erro}") from erro
    try:
        yield con
    except pymysql.err.IntegrityError as erro:
        if erro.args and erro.args[0] == 1062 and "protocolo" in str(erro):
            raise ProtocoloDuplicado(str(erro)) from erro
        raise ErroBanco(f"Erro de integridade: {erro}") from erro
    except pymysql.MySQLError as erro:
        raise ErroBanco(f"Erro no banco: {erro}") from erro
    finally:
        con.close()


def _consultar(sql: str, parametros=()) -> list[dict]:
    with conexao() as con, con.cursor() as cur:
        cur.execute(sql, parametros)
        return list(cur.fetchall())


def _executar(sql: str, parametros=()) -> int:
    with conexao() as con, con.cursor() as cur:
        cur.execute(sql, parametros)
        return int(cur.lastrowid or 0)


# ---------------------------------------------------------------------------
# Instalação (preparar_banco.py)
# ---------------------------------------------------------------------------
TABELAS_V2 = ["auditoria", "conversas", "notificacoes", "alertas", "atestados", "ponto", "funcionarios"]


def executar_script(sql: str) -> None:
    """Executa um arquivo .sql simples (sem procedures), comando por comando."""
    sem_comentarios = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    comandos = [c.strip() for c in sem_comentarios.split(";") if c.strip()]
    with conexao() as con, con.cursor() as cur:
        for comando in comandos:
            cur.execute(comando)


def apagar_tabelas_v2() -> None:
    with conexao() as con, con.cursor() as cur:
        for tabela in TABELAS_V2:  # ordem respeita as chaves estrangeiras
            cur.execute(f"DROP TABLE IF EXISTS {tabela}")


def inserir_varios(tabela: str, linhas: list[dict]) -> None:
    if not linhas:
        return
    colunas = list(linhas[0])
    sql = f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join(['%s'] * len(colunas))})"
    with conexao() as con, con.cursor() as cur:
        cur.executemany(sql, [tuple(l[c] for c in colunas) for l in linhas])


def contar(tabela: str) -> int:
    if tabela not in TABELAS_V2:
        raise ValueError(tabela)
    return int(_consultar(f"SELECT COUNT(*) AS n FROM {tabela}")[0]["n"])


def tabelas_existentes() -> list[str]:
    linhas = _consultar("SHOW TABLES")
    return sorted(next(iter(l.values())) for l in linhas)


def testar_conexao() -> dict:
    versao = _consultar("SELECT VERSION() AS v")[0]["v"]
    return {"versao": versao, "tabelas": tabelas_existentes()}


# ---------------------------------------------------------------------------
# Funcionários e ponto
# ---------------------------------------------------------------------------
def _hora(valor):
    """PyMySQL devolve TIME como timedelta; converte para 'HH:MM'."""
    if valor is None:
        return None
    if isinstance(valor, timedelta):
        total = int(valor.total_seconds())
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}"
    return str(valor)[:5]


def _normalizar_funcionario(f: dict | None) -> dict | None:
    if f:
        f["jornada_inicio"] = _hora(f["jornada_inicio"])
        f["jornada_fim"] = _hora(f["jornada_fim"])
    return f


def buscar_funcionario(funcionario_id: str) -> dict | None:
    linhas = _consultar("SELECT * FROM funcionarios WHERE id = %s AND ativo = 1", (funcionario_id,))
    return _normalizar_funcionario(linhas[0]) if linhas else None


def listar_funcionarios() -> list[dict]:
    return [_normalizar_funcionario(f) for f in _consultar("SELECT * FROM funcionarios ORDER BY id")]


def atualizar_contato_funcionario(funcionario_id: str, telefone: str | None, email: str | None) -> None:
    campos, valores = [], []
    if telefone:
        campos.append("telefone = %s")
        valores.append(telefone)
    if email:
        campos.append("email = %s")
        valores.append(email)
    if not campos:
        return
    campos.append("atualizado_em = %s")
    valores += [agora(), funcionario_id]
    _executar(f"UPDATE funcionarios SET {', '.join(campos)} WHERE id = %s", valores)


def ponto_periodo(funcionario_id: str, inicio: date, fim: date) -> list[dict]:
    linhas = _consultar(
        "SELECT data, entrada, saida, situacao, justificativa FROM ponto "
        "WHERE funcionario_id = %s AND data BETWEEN %s AND %s ORDER BY data",
        (funcionario_id, inicio, fim),
    )
    for l in linhas:
        l["entrada"], l["saida"] = _hora(l["entrada"]), _hora(l["saida"])
    return linhas


# ---------------------------------------------------------------------------
# Atestados
# ---------------------------------------------------------------------------
COLUNAS_ATESTADO = {
    "tipo", "data_inicio", "data_fim", "dias", "motivo", "telefone_informado", "email_informado",
    "receber_email", "atualizar_cadastro", "complemento",
    "documento_aceito", "documento_motivo", "tentativas_envio", "arquivo_nome", "arquivo_caminho",
    "arquivo_sha256", "arquivo_mime", "nitidez", "tipo_detectado", "confianca_tipo",
    "doc_nome", "doc_data_inicio", "doc_dias", "doc_assinado",
    "status", "observacoes", "chat_finalizado_em", "resolvido_em", "atualizado_em",
}


def criar_atestado(protocolo: str, funcionario_id: str, campos: dict, criado_em: datetime | None = None) -> int:
    campos = {k: v for k, v in campos.items() if k in COLUNAS_ATESTADO}
    momento = criado_em or agora()
    campos.setdefault("atualizado_em", momento)
    colunas = ["protocolo", "funcionario_id", "criado_em", *campos]
    valores = [protocolo, funcionario_id, momento, *campos.values()]
    return _executar(
        f"INSERT INTO atestados ({', '.join(colunas)}) VALUES ({', '.join(['%s'] * len(colunas))})",
        valores,
    )


def atualizar_atestado(atestado_id: int, campos: dict) -> None:
    campos = {k: v for k, v in campos.items() if k in COLUNAS_ATESTADO}
    if not campos:
        return
    campos.setdefault("atualizado_em", agora())
    _executar(
        f"UPDATE atestados SET {', '.join(f'{c} = %s' for c in campos)} WHERE id = %s",
        [*campos.values(), atestado_id],
    )


def buscar_atestado(atestado_id: int) -> dict | None:
    linhas = _consultar("SELECT * FROM atestados WHERE id = %s", (atestado_id,))
    return linhas[0] if linhas else None


def atestados_do_funcionario(funcionario_id: str, exceto_id: int | None = None) -> list[dict]:
    return _consultar(
        "SELECT id, protocolo, data_inicio, data_fim, status, arquivo_sha256 FROM atestados "
        "WHERE funcionario_id = %s AND id <> %s ORDER BY data_inicio",
        (funcionario_id, exceto_id or 0),
    )


def atestados_por_hash(sha256: str, exceto_id: int | None = None) -> list[dict]:
    if not sha256:
        return []
    return _consultar(
        "SELECT a.id, a.protocolo, a.funcionario_id, a.data_inicio, a.data_fim, a.status "
        "FROM atestados a WHERE a.arquivo_sha256 = %s AND a.id <> %s",
        (sha256, exceto_id or 0),
    )


def listar_atestados(periodo_dias: int = 30) -> list[dict]:
    desde = agora() - timedelta(days=periodo_dias)
    return _consultar(
        """
        SELECT a.*, f.nome, f.setor, f.cargo,
               (SELECT COUNT(*) FROM alertas l WHERE l.atestado_id = a.id AND l.status = 'aberto') AS alertas_abertos,
               (SELECT COUNT(*) FROM alertas l WHERE l.atestado_id = a.id AND l.status = 'aberto'
                  AND l.gravidade = 'alta') AS alertas_graves,
               (SELECT COUNT(*) FROM alertas l WHERE l.atestado_id = a.id) AS alertas_total
        FROM atestados a JOIN funcionarios f ON f.id = a.funcionario_id
        WHERE a.criado_em >= %s
        ORDER BY a.criado_em DESC
        LIMIT 1000
        """,
        (desde,),
    )


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
def listar_alertas(atestado_id: int) -> list[dict]:
    linhas = _consultar(
        "SELECT * FROM alertas WHERE atestado_id = %s "
        "ORDER BY FIELD(gravidade, 'alta', 'media', 'baixa'), codigo",
        (atestado_id,),
    )
    for l in linhas:
        l["evidencia"] = json.loads(l["evidencia"] or "{}")
    return linhas


def listar_alertas_periodo(periodo_dias: int = 30) -> list[dict]:
    desde = agora() - timedelta(days=periodo_dias)
    return _consultar(
        "SELECT l.codigo, l.gravidade, l.status, l.criado_em, l.decidido_em, l.decidido_por "
        "FROM alertas l JOIN atestados a ON a.id = l.atestado_id WHERE a.criado_em >= %s",
        (desde,),
    )


def inserir_alerta(atestado_id: int, alerta: dict) -> None:
    _executar(
        "INSERT INTO alertas (atestado_id, codigo, gravidade, titulo, descricao, evidencia, pergunta, criado_em) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (atestado_id, alerta["codigo"], alerta["gravidade"], alerta["titulo"], alerta["descricao"],
         _json(alerta.get("evidencia")), alerta.get("pergunta"), agora()),
    )


def atualizar_alerta(alerta_id: int, campos: dict) -> None:
    permitidas = {"gravidade", "titulo", "descricao", "evidencia", "pergunta", "resposta_colaborador",
                  "status", "decidido_por", "decisao_obs", "decidido_em"}
    campos = {k: (_json(v) if k == "evidencia" else v) for k, v in campos.items() if k in permitidas}
    if campos:
        _executar(
            f"UPDATE alertas SET {', '.join(f'{c} = %s' for c in campos)} WHERE id = %s",
            [*campos.values(), alerta_id],
        )


def buscar_alerta(alerta_id: int) -> dict | None:
    linhas = _consultar("SELECT * FROM alertas WHERE id = %s", (alerta_id,))
    if not linhas:
        return None
    linhas[0]["evidencia"] = json.loads(linhas[0]["evidencia"] or "{}")
    return linhas[0]


# ---------------------------------------------------------------------------
# Auditoria, conversa e notificações
# ---------------------------------------------------------------------------
def auditar(atestado_id: int | None, ator: str, evento: str, codigo: str | None = None, detalhe: dict | None = None) -> None:
    _executar(
        "INSERT INTO auditoria (atestado_id, ocorrido_em, ator, evento, codigo, detalhe) VALUES (%s, %s, %s, %s, %s, %s)",
        (atestado_id, agora(), ator[:60], evento[:50], codigo, _json(detalhe)),
    )


def listar_auditoria(atestado_id: int) -> list[dict]:
    return _consultar(
        "SELECT ocorrido_em, ator, evento, codigo, detalhe FROM auditoria WHERE atestado_id = %s ORDER BY id",
        (atestado_id,),
    )


def registrar_conversa(atestado_id: int, mensagens: list[dict]) -> None:
    if not mensagens:
        return
    with conexao() as con, con.cursor() as cur:
        cur.executemany(
            "INSERT INTO conversas (atestado_id, papel, conteudo, enviado_em) VALUES (%s, %s, %s, %s)",
            [(atestado_id, m["papel"], m["conteudo"], m["enviado_em"]) for m in mensagens],
        )


def listar_conversa(atestado_id: int) -> list[dict]:
    return _consultar(
        "SELECT papel, conteudo, enviado_em FROM conversas WHERE atestado_id = %s ORDER BY id", (atestado_id,)
    )


def registrar_notificacao(dados: dict) -> int:
    return _executar(
        "INSERT INTO notificacoes (atestado_id, tipo, destinatario_tipo, destinatario, assunto, corpo, modo, status, erro, criado_em) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (dados.get("atestado_id"), dados["tipo"], dados["destinatario_tipo"], dados["destinatario"],
         dados["assunto"][:200], dados["corpo"], dados["modo"], dados["status"],
         (dados.get("erro") or None) and dados["erro"][:500], agora()),
    )


def listar_notificacoes(limite: int = 200) -> list[dict]:
    return _consultar(
        "SELECT n.*, a.protocolo FROM notificacoes n LEFT JOIN atestados a ON a.id = n.atestado_id "
        "ORDER BY n.id DESC LIMIT %s",
        (limite,),
    )


def mascarar_email(email: str) -> str:
    """ana.oliveira@example.com -> an***@example.com (para mostrar ao LLM e na tela)."""
    usuario, _, dominio = (email or "").partition("@")
    return f"{usuario[:2]}***@{dominio}" if dominio else "***"


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")

"""Painel do RH: atestados com alertas, ponto em calendário, caixa de saída e indicadores."""

import hmac
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pymupdf
import streamlit as st

import config
import db
import orquestrador
from conferencia import nomes_compativeis
from datas import formatar
from regras import CORES, GRAVIDADE_ROTULOS, STATUS_ROTULOS, classificar_linha
from ui_calendario import calendario_html, dias_com_alerta

st.title("Painel do RH")


# ---------------------------------------------------------------------------
# Acesso
# ---------------------------------------------------------------------------
def autenticado() -> bool:
    if st.session_state.get("rh_nome"):
        return True
    if not config.SENHA_RH:
        st.error("Defina SENHA_RH no arquivo .env para liberar o painel.")
        return False
    with st.form("login_rh"):
        nome = st.text_input("Seu nome (vai para a trilha de auditoria)")
        senha = st.text_input("Senha do RH", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if nome.strip() and hmac.compare_digest(senha.encode(), config.SENHA_RH.encode()):
                st.session_state.rh_nome = nome.strip()
                st.rerun()
            st.error("Senha incorreta ou nome em branco.")
    return False


if not autenticado():
    st.stop()


@st.cache_data(ttl=15, show_spinner="Consultando o banco...")
def carregar_atestados(periodo: int) -> list[dict]:
    return db.listar_atestados(periodo)


def recarregar():
    carregar_atestados.clear()
    st.rerun()


def ha_quanto(momento, agora) -> str:
    minutos = int((agora - momento).total_seconds() // 60)
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 48 * 60:
        return f"{minutos // 60} h"
    return f"{minutos // 1440} dias"


with st.sidebar:
    st.caption(f"Conectado como **{st.session_state.rh_nome}**")
    periodo = st.selectbox("Período", [7, 30, 90, 365], index=1, format_func=lambda d: f"Últimos {d} dias")
    if st.button("Atualizar agora", width="stretch"):
        recarregar()
    if st.button("Sair", width="stretch"):
        del st.session_state["rh_nome"]
        st.rerun()

try:
    registros = carregar_atestados(periodo)
except db.ErroBanco as erro:
    st.error(f"Não foi possível ler o banco: {erro}")
    st.stop()

agora = db.agora()
for r in registros:
    r["cor"], r["situacao"] = classificar_linha(r, agora)

aba_atestados, aba_ponto, aba_caixa, aba_indicadores = st.tabs(
    ["📋 Atestados", "🗓️ Funcionários e ponto", "📧 Caixa de saída", "📊 Indicadores"]
)


# ---------------------------------------------------------------------------
# Detalhe de um atestado
# ---------------------------------------------------------------------------
def tabela_form_x_documento(at: dict, func: dict) -> pd.DataFrame:
    def marca(igual):
        return "" if igual else " ⚠️"

    linhas = [("Nome", func["nome"], at.get("doc_nome"))]
    linhas.append(("Tipo", config.TIPOS_DOCUMENTO[at["tipo"]],
                   config.TIPOS_DOCUMENTO.get(at.get("tipo_detectado") or "", at.get("tipo_detectado"))))
    linhas.append(("Início", formatar(at["data_inicio"]), formatar(at.get("doc_data_inicio")) if at.get("doc_data_inicio") else None))
    linhas.append(("Dias", str(at["dias"]), str(at["doc_dias"]) if at.get("doc_dias") else None))
    dados = []
    for campo, form, doc in linhas:
        if doc in (None, "nao_verificado"):
            dados.append({"Campo": campo, "Formulário": form, "Documento (lido pela IA)": "não lido"})
        else:
            iguais = (nomes_compativeis(form, doc) if campo == "Nome" else form == doc)
            dados.append({"Campo": campo, "Formulário": form, "Documento (lido pela IA)": doc + marca(iguais)})
    return pd.DataFrame(dados)


def mostrar_alerta(a: dict):
    with st.container(border=True):
        st.markdown(f"**{GRAVIDADE_ROTULOS[a['gravidade']]} · {a['titulo']}** `{a['codigo']}`")
        st.markdown(a["descricao"])
        if a.get("pergunta"):
            st.markdown(f"🤖 _Pergunta do agente:_ {a['pergunta']}")
            st.markdown(f"💬 _Resposta do funcionário:_ {a.get('resposta_colaborador') or 'ainda sem resposta'}")
        if a["status"] == "aberto":
            obs = st.text_input("Observação (vai para a auditoria)", key=f"obs_{a['id']}")
            col1, col2 = st.columns(2)
            rotulo_confirmar = "Confirmar e atualizar cadastro" if a["codigo"] == "C1" else "Confirmar divergência"
            if col1.button(rotulo_confirmar, key=f"conf_{a['id']}", type="primary", width="stretch"):
                orquestrador.decidir_alerta(a["id"], "confirmado", st.session_state.rh_nome, obs)
                recarregar()
            if col2.button("Descartar", key=f"desc_{a['id']}", width="stretch"):
                orquestrador.decidir_alerta(a["id"], "descartado", st.session_state.rh_nome, obs)
                recarregar()
        else:
            quem = a.get("decidido_por") or ""
            st.caption(f"{'✔️ Confirmado' if a['status'] == 'confirmado' else '✖️ Descartado'} por {quem} "
                       f"em {a['decidido_em']:%d/%m %H:%M}" + (f" · {a['decisao_obs']}" if a.get("decisao_obs") else ""))


def mostrar_documento(at: dict):
    caminho = Path(at["arquivo_caminho"]) if at.get("arquivo_caminho") else None
    if caminho is None:
        st.caption("Nenhum arquivo.")
    elif not caminho.is_file():
        st.caption("O arquivo fica no computador onde o agente rodou e não foi encontrado aqui.")
    elif caminho.suffix.lower() == ".pdf":
        with pymupdf.open(caminho) as doc:
            st.image(doc[0].get_pixmap(dpi=80).tobytes("png"), caption=at["arquivo_nome"], width="stretch")
        st.download_button("Baixar PDF", caminho.read_bytes(), file_name=at["arquivo_nome"] or caminho.name)
    else:
        st.image(str(caminho), caption=at["arquivo_nome"], width="stretch")
        st.download_button("Baixar imagem", caminho.read_bytes(), file_name=at["arquivo_nome"] or caminho.name)


def mostrar_detalhe(reg: dict):
    at, func, alertas = orquestrador.contexto_caso(reg["id"])
    vistos = st.session_state.setdefault("detalhes_vistos", set())
    if at["id"] not in vistos:  # registra quem abriu o quê (uma vez por sessão)
        db.auditar(at["id"], f"rh:{st.session_state.rh_nome}", "detalhe_visualizado")
        vistos.add(at["id"])
    st.divider()
    st.subheader(f"{CORES[reg['cor']]['emoji']} {func['nome']} · {at['protocolo']}")
    st.caption(f"{func['id']} · {func['setor']} · {func['cargo']} · status: {STATUS_ROTULOS[at['status']]} · "
               f"enviado em {at['criado_em']:%d/%m %H:%M}")

    esquerda, direita = st.columns([3, 2], gap="large")
    with esquerda:
        st.markdown("**Formulário × documento**")
        st.dataframe(tabela_form_x_documento(at, func), hide_index=True, width="stretch")
        difere = orquestrador.contato_difere(at, func)
        st.markdown(
            f"**Contato informado:** {at['telefone_informado']}{' (difere do cadastro)' if difere['telefone'] else ''} · "
            f"{at['email_informado']}{' (difere do cadastro)' if difere['email'] else ''}  \n"
            f"**Quer e-mails:** {'sim' if at.get('receber_email') else 'não' if at.get('receber_email') == 0 else '—'} · "
            f"**Complemento:** {at.get('complemento') or '—'}"
        )
        if at.get("observacoes"):
            st.info(f"Observação do agente: {at['observacoes']}")

        st.markdown(f"**Alertas ({sum(a['status'] == 'aberto' for a in alertas)} abertos)**")
        if not alertas:
            st.success("Nenhum alerta: o ponto está de acordo com o atestado.")
        for a in alertas:
            mostrar_alerta(a)
        if at["status"] != "resolvido" and not any(a["status"] == "aberto" for a in alertas):
            if st.button("Marcar caso como conferido", type="primary"):
                orquestrador.concluir_caso(at["id"], st.session_state.rh_nome)
                recarregar()

    with direita:
        st.markdown("**Documento**")
        mostrar_documento(at)
        st.markdown("**Ponto no período**")
        inicio_cal = at["data_inicio"] - timedelta(days=7)
        fim_cal = min(at["data_fim"] + timedelta(days=7), db.hoje())
        ponto = db.ponto_periodo(func["id"], inicio_cal, fim_cal)
        st.markdown(calendario_html(ponto, inicio_cal, max(fim_cal, inicio_cal), [(at["data_inicio"], at["data_fim"])],
                                    dias_com_alerta(alertas)), unsafe_allow_html=True)

    with st.expander("Trilha de auditoria"):
        st.dataframe(pd.DataFrame([
            {"Quando": e["ocorrido_em"].strftime("%d/%m %H:%M:%S"), "Quem": e["ator"], "Evento": e["evento"],
             "Alerta": e["codigo"] or "", "Detalhe": e["detalhe"]}
            for e in db.listar_auditoria(at["id"])
        ]), hide_index=True, width="stretch")
    conversa = db.listar_conversa(at["id"]) if config.SALVAR_CONVERSA else []
    if conversa:
        with st.expander("Conversa com o agente"):
            for m in conversa:
                with st.chat_message("assistant" if m["papel"] == "agente" else "user"):
                    st.markdown(m["conteudo"])


# ---------------------------------------------------------------------------
# Aba: atestados
# ---------------------------------------------------------------------------
with aba_atestados:
    if not registros:
        st.info("Nenhum atestado no período. Envie um pela página de atendimento.")
    else:
        colunas = st.columns(len(CORES))
        for coluna, (cor, info) in zip(colunas, CORES.items()):
            coluna.metric(f"{info['emoji']} {info['rotulo']}", sum(r["cor"] == cor for r in registros))
        st.caption("🔴 alerta grave aberto (ponto no afastamento, duplicado ou sem documento) · 🔵 alertas para o RH "
                   "conferir · 🟡 funcionário ainda no chat · 🟢 ponto de acordo com o atestado · ⚪ resolvido")

        tabela = pd.DataFrame([
            {
                "": CORES[r["cor"]]["emoji"],
                "Situação": r["situacao"],
                "Funcionário": r["nome"],
                "ID": r["funcionario_id"],
                "Setor": r["setor"],
                "Documento": config.TIPOS_DOCUMENTO[r["tipo"]],
                "Período": f"{r['data_inicio']:%d/%m} a {r['data_fim']:%d/%m}",
                "Dias": str(r["dias"]),
                "📎": "✓" if r["documento_aceito"] else "⚠️",
                "Alertas": f"{r['alertas_abertos']} aberto(s)" if r["alertas_abertos"] else "—",
                "Enviado": f"{r['criado_em']:%d/%m %H:%M} · há {ha_quanto(r['criado_em'], agora)}",
                "Protocolo": r["protocolo"],
            }
            for r in registros
        ])
        fundos = [CORES[r["cor"]]["fundo"] for r in registros]
        estilo = tabela.style.apply(lambda linha: [f"background-color: {fundos[linha.name]}"] * len(linha), axis=1)
        selecao = st.dataframe(estilo, hide_index=True, width="stretch", on_select="rerun",
                               selection_mode="single-row", key="tabela_atestados")
        linhas = selecao.selection.rows if selecao else []
        if not linhas:
            st.info("👆 Marque a caixinha à esquerda de uma linha para ver o documento, os alertas e o ponto.")
        else:
            mostrar_detalhe(registros[linhas[0]])


# ---------------------------------------------------------------------------
# Aba: funcionários e ponto
# ---------------------------------------------------------------------------
with aba_ponto:
    funcionarios = {f["id"]: f for f in db.listar_funcionarios()}
    escolhido_id = st.selectbox("Funcionário", list(funcionarios),
                                format_func=lambda i: f"{i} · {funcionarios[i]['nome']} · {funcionarios[i]['setor']}")
    escolhido = funcionarios.get(escolhido_id)
    if escolhido:
        st.caption(f"{escolhido['cargo']} · jornada {escolhido['jornada_inicio']}–{escolhido['jornada_fim']} (seg. a sex.) · "
                   f"{escolhido['email']} · {escolhido['telefone']}")
        fim_cal = db.hoje() - timedelta(days=1)
        inicio_cal = fim_cal - timedelta(days=config.DIAS_HISTORICO_PONTO - 1)
        ponto = db.ponto_periodo(escolhido["id"], inicio_cal, fim_cal)
        atestados_func = db.atestados_do_funcionario(escolhido["id"])
        alertas_func = [a for at in atestados_func for a in db.listar_alertas(at["id"])]
        st.markdown(calendario_html(ponto, inicio_cal, fim_cal, [(a["data_inicio"], a["data_fim"]) for a in atestados_func],
                                    dias_com_alerta(alertas_func)), unsafe_allow_html=True)
        resumo = pd.Series([p["situacao"] for p in ponto]).value_counts()
        st.caption(" · ".join(f"{k}: {v}" for k, v in resumo.items()))
        if atestados_func:
            st.markdown("**Atestados deste funcionário**")
            st.dataframe(pd.DataFrame([
                {"Protocolo": a["protocolo"], "Início": formatar(a["data_inicio"]), "Término": formatar(a["data_fim"]),
                 "Status": STATUS_ROTULOS[a["status"]]}
                for a in atestados_func
            ]), hide_index=True, width="stretch")
        with st.expander("Registros de ponto (tabela)"):
            st.dataframe(pd.DataFrame([
                {"Data": f"{p['data']:%d/%m/%Y}", "Entrada": p["entrada"] or "", "Saída": p["saida"] or "",
                 "Situação": p["situacao"], "Justificativa": p["justificativa"] or ""}
                for p in ponto
            ]), hide_index=True, width="stretch")
        st.caption("O agente só lê o ponto: nenhuma marcação é alterada pelo sistema.")


# ---------------------------------------------------------------------------
# Aba: caixa de saída
# ---------------------------------------------------------------------------
with aba_caixa:
    modo = "simulação (nada sai do computador)" if config.EMAIL_MODO != "smtp" else f"SMTP ({config.SMTP_HOST})"
    st.caption(f"Modo de e-mail: **{modo}**. O destinatário é sempre o e-mail do cadastro ou o do RH.")
    notificacoes = db.listar_notificacoes()
    if not notificacoes:
        st.info("Nenhum e-mail ainda. Eles são gerados quando o funcionário termina o chat.")
    icones = {"simulado": "🧪", "enviado": "✅", "falhou": "❌"}
    for n in notificacoes:
        with st.expander(f"{icones[n['status']]} {n['assunto']}"):
            st.caption(f"Para: {n['destinatario']} ({n['destinatario_tipo']}) · {n['criado_em']:%d/%m %H:%M} · {n['status']}"
                       + (f" · erro: {n['erro']}" if n.get("erro") else ""))
            st.text(n["corpo"])


# ---------------------------------------------------------------------------
# Aba: indicadores
# ---------------------------------------------------------------------------
NOMES_ALERTAS = {
    "A1": "A1 Ponto no afastamento", "A2": "A2 Faltas próximas", "A3": "A3 Form. × doc.",
    "A4": "A4 Duplicado", "A5": "A5 Mais de 15 dias", "A6": "A6 Nome diferente", "A7": "A7 Não lido",
    "A8": "A8 Sem documento", "C1": "C1 Cadastro",
}

with aba_indicadores:
    alertas_periodo = db.listar_alertas_periodo(periodo)
    total = len(registros)
    sem_alerta = sum(1 for r in registros if not r["alertas_total"])
    finalizados = [r for r in registros if r["chat_finalizado_em"]]
    resolvidos = [r for r in registros if r["resolvido_em"]]
    decididos_rh = [a for a in alertas_periodo if (a["decidido_por"] or "").startswith("rh:")]
    descartados_rh = sum(1 for a in decididos_rh if a["status"] == "descartado")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Atestados no período", total)
    c2.metric("Sem nenhum alerta", f"{sem_alerta / total:.0%}" if total else "—")
    c3.metric("Alertas gerados", len(alertas_periodo))
    c4.metric("Abertos agora", sum(1 for a in alertas_periodo if a["status"] == "aberto"))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Confirmados pelo RH", sum(1 for a in decididos_rh if a["status"] == "confirmado"))
    c2.metric("Descartados pelo RH", descartados_rh,
              help="Alertas que o RH considerou improcedentes: aproxima a taxa de falsos alertas.")
    c3.metric("Tempo médio do chat",
              f"{sum((r['chat_finalizado_em'] - r['criado_em']).total_seconds() for r in finalizados) / len(finalizados) / 60:.1f} min"
              if finalizados else "—", help="Do envio do formulário ao fim do chat.")
    c4.metric("Tempo médio até resolver",
              f"{sum((r['resolvido_em'] - r['criado_em']).total_seconds() for r in resolvidos) / len(resolvidos) / 3600:.1f} h"
              if resolvidos else "—", help="Do envio do formulário até o RH concluir.")

    if alertas_periodo:
        contagem = pd.DataFrame(alertas_periodo)["codigo"].map(NOMES_ALERTAS).value_counts().rename_axis("Alerta").reset_index(name="Quantidade")
        st.markdown("**Alertas por tipo**")
        st.bar_chart(contagem, x="Alerta", y="Quantidade", horizontal=True, sort="-Quantidade")

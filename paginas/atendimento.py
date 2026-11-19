"""Página do funcionário: formulário → conferência automática → chat com o agente."""

from datetime import timedelta

import streamlit as st

import config
import db
import orquestrador
from agente import AgenteRH, criar_cliente
from cenarios import FUNCIONARIOS_POR_ID, montar_cenarios
from regras import GRAVIDADE_ROTULOS

CAMPOS = ["f_id", "f_nome", "f_tipo", "f_inicio", "f_fim", "f_motivo", "f_tel", "f_email"]


@st.cache_resource
def cliente_groq():
    return criar_cliente()


def carregar_cenario():
    """Modo demonstração: preenche o formulário com o cenário escolhido."""
    escolha = st.session_state.get("demo_cenario")
    if not escolha:
        st.session_state["f_arquivo_exemplo"] = None
        return
    c = next(c for c in montar_cenarios(db.hoje()) if c.funcionario_id == escolha)
    f = FUNCIONARIOS_POR_ID[c.funcionario_id]
    st.session_state.update({
        "f_id": c.funcionario_id, "f_nome": f["nome"], "f_tipo": c.tipo, "f_inicio": c.inicio, "f_fim": c.fim,
        "f_motivo": c.motivo, "f_tel": f["telefone"], "f_email": f["email"],
        "f_arquivo_exemplo": str(c.caminho_arquivo),
    })


def novo_atendimento():
    for chave in ["agente", "demo_cenario", "f_arquivo_exemplo", *CAMPOS]:
        st.session_state.pop(chave, None)


# ---------------------------------------------------------------------------
# Formulário
# ---------------------------------------------------------------------------
def mostrar_formulario():
    st.title("Envio de atestado")
    st.caption("Preencha os dados e anexe o documento. Depois, o assistente confere tudo e conversa com você se "
               "precisar de algum esclarecimento. Não é preciso informar diagnóstico nem sintomas.")
    if cliente_groq() is None:
        st.warning("Sem GROQ_API_KEY no .env: o formulário funciona, mas o chat e a leitura do documento ficam desligados.")

    if config.MODO_DEMO:
        with st.expander("🧪 Modo demonstração: carregar um cenário de teste", expanded=False):
            cens = montar_cenarios(db.hoje())
            st.selectbox(
                "Cenário", [None, *[c.funcionario_id for c in cens]], key="demo_cenario", on_change=carregar_cenario,
                format_func=lambda fid: "— escolha —" if fid is None else
                next(f"{c.funcionario_id} · {c.nome} · {c.titulo}" for c in cens if c.funcionario_id == fid),
            )
            if st.session_state.get("f_arquivo_exemplo"):
                st.caption("O atestado sintético do cenário será usado se você não anexar outro arquivo.")

    hoje = db.hoje()
    with st.form("formulario_atestado"):
        col1, col2 = st.columns(2)
        col1.text_input("ID do funcionário", key="f_id", placeholder="FUNC001")
        col2.text_input("Nome completo", key="f_nome")
        st.selectbox("Tipo de documento", list(config.TIPOS_DOCUMENTO), key="f_tipo",
                     format_func=config.TIPOS_DOCUMENTO.get)
        col1, col2 = st.columns(2)
        limites = {"min_value": hoje - timedelta(days=config.MAX_DIAS_RETROATIVOS),
                   "max_value": hoje + timedelta(days=config.MAX_DIAS_FUTUROS), "format": "DD/MM/YYYY"}
        col1.date_input("Data de início", key="f_inicio", **limites)
        col2.date_input("Data de término", key="f_fim", **limites)
        st.selectbox("Motivo geral (opcional)", [None, *config.MOTIVOS], key="f_motivo",
                     format_func=lambda m: "— prefiro não preencher —" if m is None else config.MOTIVOS[m],
                     help="Não escreva diagnóstico. Esta informação não é enviada à IA nem por e-mail.")
        col1, col2 = st.columns(2)
        col1.text_input("Telefone com DDD", key="f_tel", placeholder="(19) 99999-9999")
        col2.text_input("E-mail", key="f_email")
        arquivo = st.file_uploader("Atestado (PDF, JPG ou PNG)", type=config.EXTENSOES_ACEITAS,
                                   max_upload_size=config.TAMANHO_MAX_MB)
        enviado = st.form_submit_button("Enviar", type="primary")

    if not enviado:
        return
    dados = {
        "funcionario_id": st.session_state.f_id, "nome": st.session_state.f_nome, "tipo": st.session_state.f_tipo,
        "data_inicio": st.session_state.f_inicio, "data_fim": st.session_state.f_fim,
        "motivo": st.session_state.f_motivo, "telefone": st.session_state.f_tel, "email": st.session_state.f_email,
        "arquivo_bytes": None, "arquivo_nome": None,
    }
    if arquivo is not None:
        dados["arquivo_bytes"], dados["arquivo_nome"] = arquivo.getvalue(), arquivo.name
    elif st.session_state.get("f_arquivo_exemplo"):
        caminho = config.PASTA_EXEMPLOS / "cenarios" / st.session_state.f_arquivo_exemplo.split("/")[-1]
        if caminho.is_file():
            dados["arquivo_bytes"], dados["arquivo_nome"] = caminho.read_bytes(), caminho.name

    try:
        erros, funcionario = orquestrador.validar_formulario(dados)
    except db.ErroBanco as erro:
        st.error(f"Banco de dados indisponível: {erro}")
        return
    if erros:
        st.error("Corrija os campos abaixo:\n\n" + "\n".join(f"- {m}" for m in erros.values()))
        return
    with st.spinner("Conferindo o documento e o seu ponto..."):
        try:
            caso = orquestrador.registrar_formulario(cliente_groq(), dados, funcionario)
            agente = AgenteRH(cliente_groq(), caso["atestado_id"])
            agente.iniciar()
        except db.ErroBanco as erro:
            st.error(f"Não foi possível registrar: {erro}")
            return
    st.session_state.agente = agente
    st.rerun()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
def mostrar_chat(agente: AgenteRH):
    estado = agente.estado()
    st.title("Atendimento")
    st.caption(f"Protocolo {estado['protocolo']} · {estado['afastamento']['tipo']} de "
               f"{estado['afastamento']['inicio'][8:10]}/{estado['afastamento']['inicio'][5:7]} a "
               f"{estado['afastamento']['fim'][8:10]}/{estado['afastamento']['fim'][5:7]}")

    for papel, texto in agente.mensagens_ui:
        with st.chat_message("assistant" if papel == "agente" else "user"):
            st.markdown(texto)

    if agente.encerrado or estado["atendimento_encerrado"]:
        st.success(f"Atendimento encerrado · protocolo **{estado['protocolo']}**")
        st.button("Enviar outro atestado", type="primary", on_click=novo_atendimento)
    else:
        entrada = st.chat_input("Escreva aqui · toque em + para anexar outro arquivo", accept_file=True,
                                file_type=config.EXTENSOES_ACEITAS, max_upload_size=config.TAMANHO_MAX_MB)
        if entrada:
            texto = (entrada.text or "").strip()
            arquivos = list(entrada.files or [])
            with st.chat_message("user"):
                st.markdown((f"📎 {arquivos[0].name}\n\n" if arquivos else "") + texto)
            with st.chat_message("assistant"):
                with st.spinner("Conferindo..." if arquivos else "Digitando..."):
                    if arquivos:
                        agente.receber_arquivo(arquivos[0].getvalue(), arquivos[0].name, texto)
                    elif texto:
                        agente.responder(texto)
            st.rerun()
    if agente.erro:
        st.warning(f"Aviso técnico: {agente.erro}")

    if config.MODO_DEMO:
        mostrar_bastidores(agente)


def mostrar_bastidores(agente: AgenteRH):
    """Barra lateral da demonstração: o que o agente conferiu e o que ainda falta."""
    at, func, alertas = orquestrador.contexto_caso(agente.atestado_id)
    pend = orquestrador.pendencias_chat(at, func, alertas)
    with st.sidebar:
        st.subheader("Bastidores do agente")
        st.caption("Visível só no modo demonstração")
        doc_ok = bool(at["documento_aceito"])
        st.markdown(f"**Documento:** {'✅' if doc_ok else '⚠️'} {at['documento_motivo']}")
        if at.get("doc_nome") or at.get("doc_data_inicio") or at.get("doc_dias"):
            inicio_txt = f"{at['doc_data_inicio']:%d/%m}" if at.get("doc_data_inicio") else "?"
            st.markdown(f"**Lido do documento:** {at.get('doc_nome') or '—'} · início {inicio_txt} · "
                        f"{at.get('doc_dias') or '?'} dia(s)")
        st.markdown("**Alertas da conferência**")
        if not alertas:
            st.markdown("✅ Nenhum: o ponto está de acordo com o atestado")
        for a in alertas:
            situacao = {"aberto": "respondido" if a.get("resposta_colaborador") else "aberto",
                        "descartado": "encerrado", "confirmado": "confirmado pelo RH"}[a["status"]]
            st.markdown(f"{GRAVIDADE_ROTULOS[a['gravidade']].split()[0]} {a['titulo']} · _{situacao}_")
        st.markdown("**Pendências do chat**")
        if not pend:
            st.markdown("✅ Nenhuma")
        for p in pend:
            st.markdown(f"⬜ {p['descricao'].capitalize()}")
        if at.get("observacoes"):
            st.caption(f"Observações: {at['observacoes']}")


if "agente" in st.session_state:
    mostrar_chat(st.session_state.agente)
else:
    mostrar_formulario()

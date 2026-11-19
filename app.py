"""Sinergia — agente de RH (versão 2). Ponto de entrada da aplicação web local.

Execute:  streamlit run app.py
Abre em:  http://localhost:8501
"""

import streamlit as st

st.set_page_config(page_title="Sinergia · Atestados", page_icon="📄", layout="wide")

pagina = st.navigation([
    st.Page("paginas/atendimento.py", title="Envio de atestado", icon="📝", default=True),
    st.Page("paginas/painel_rh.py", title="Painel do RH", icon="📋"),
])
pagina.run()

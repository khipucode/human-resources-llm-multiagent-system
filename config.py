"""Configuração do agente de RH (versão 2) do projeto Sinergia.

Credenciais vêm do arquivo .env (nunca do código).
Parâmetros de negócio ficam aqui, separados da lógica, para o RH ajustar
limiares sem mexer no agente. Valores marcados como "parâmetro" são pontos
de partida a calibrar.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")


def _env(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------
GROQ_API_KEY = _env("GROQ_API_KEY")
MODELO_CHAT = _env("MODELO_CHAT", "openai/gpt-oss-20b")
# Modelo com visão: confere o documento e lê nome, datas e dias.
# Os modelos mudam com frequência: confira em console.groq.com/docs/vision
MODELO_VISAO = _env("MODELO_VISAO", "qwen/qwen3.8-27b")

# ---------------------------------------------------------------------------
# Banco (MariaDB/MySQL local)
# ---------------------------------------------------------------------------
MYSQL = {
    "host": _env("MYSQL_HOST", "127.0.0.1"),
    "port": int(_env("MYSQL_PORT", "3306") or 3306),
    "user": _env("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": _env("MYSQL_DATABASE"),
}

# ---------------------------------------------------------------------------
# Execução local
# ---------------------------------------------------------------------------
FUSO = ZoneInfo("America/Sao_Paulo")
PASTA_UPLOADS = RAIZ / "uploads"          # atestados ficam SÓ no computador local
PASTA_EXEMPLOS = RAIZ / "exemplos"
SENHA_RH = _env("SENHA_RH")
MODO_DEMO = _env("MODO_DEMO", "1") == "1"            # mostra os cenários de teste no formulário
SALVAR_CONVERSA = _env("SALVAR_CONVERSA", "0") == "1"  # grava o texto do chat (LGPD: desligado)
URL_PAINEL = _env("URL_PAINEL", "http://localhost:8501/painel_rh")

# ---------------------------------------------------------------------------
# E-mail
# ---------------------------------------------------------------------------
EMAIL_MODO = _env("EMAIL_MODO", "simulacao").lower()   # "simulacao" ou "smtp"
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587") or 587)
SMTP_USUARIO = _env("SMTP_USUARIO")
SMTP_SENHA = os.getenv("SMTP_SENHA", "")
EMAIL_REMETENTE = _env("EMAIL_REMETENTE") or SMTP_USUARIO or "agente-rh@example.com"
EMAIL_RH = _env("EMAIL_RH", "rh@example.com")
# Em testes com SMTP real: manda TODOS os e-mails para este endereço
# (os funcionários fictícios têm e-mails @example.com, que não existem).
EMAIL_REDIRECIONAR_PARA = _env("EMAIL_REDIRECIONAR_PARA")

# ---------------------------------------------------------------------------
# Formulário e documento
# ---------------------------------------------------------------------------
TIPOS_DOCUMENTO = {
    "atestado_medico": "Atestado médico",
    "declaracao_comparecimento": "Declaração de comparecimento",
    "atestado_acompanhante": "Atestado de acompanhante",
}
# Motivo geral: lista fechada e opcional (sem texto livre, para ninguém
# escrever diagnóstico). Não é enviado ao LLM nem aparece nos e-mails.
MOTIVOS = {
    "doenca": "Doença ou mal-estar",
    "consulta_exame": "Consulta ou exame",
    "acompanhante": "Acompanhamento de familiar",
    "acidente": "Acidente",
    "prefiro_nao_informar": "Prefiro não informar",
}

EXTENSOES_ACEITAS = ["pdf", "jpg", "jpeg", "png"]
TAMANHO_MAX_MB = 10

# Qualidade mínima do arquivo (R02). Nitidez = variância do Laplaciano numa
# imagem de 1000 px de largura. Nos sintéticos: nítido ≈ 700–1000;
# desfoque σ=2 ≈ 25–30 (ainda legível); σ=3 ≈ 5.
NITIDEZ_MINIMA = 20.0
RESOLUCAO_MINIMA_PX = 600
BRILHO_MINIMO = 50
CONTRASTE_MINIMO = 6.0
TINTA_MINIMA = 0.004
LIMIAR_CONFIANCA_TIPO = 0.60
MAX_TENTATIVAS_ENVIO = 3

MAX_DIAS_RETROATIVOS = 60     # início do afastamento aceito até N dias atrás
MAX_DIAS_FUTUROS = 30
MAX_DIAS_ATESTADO = 180

# ---------------------------------------------------------------------------
# Conferência com o ponto (alertas)
# ---------------------------------------------------------------------------
DIAS_HISTORICO_PONTO = 30        # o simulador gera este tanto de dias
LIMITE_INSS_DIAS = 15            # Lei 8.213/1991, art. 60: a partir do 16º dia, INSS
JANELA_FALTAS_DIAS_UTEIS = 3     # faltas sem justificativa até N dias úteis antes/depois
# 1º dia parcial: marcação só no 1º dia, com saída antes desta fração da jornada
FRACAO_PRIMEIRO_DIA_PARCIAL = 0.5
# Feriados nacionais fixos (dia, mês). Feriados móveis ficam fora do protótipo.
FERIADOS_FIXOS = {(1, 1), (21, 4), (1, 5), (7, 9), (12, 10), (2, 11), (15, 11), (20, 11), (25, 12)}

# Painel do RH
LIMITE_EM_ATENDIMENTO_HORAS = 2  # depois disso, o chat é considerado não concluído

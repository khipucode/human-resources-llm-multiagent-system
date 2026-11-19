"""Percepção do documento: conferência do arquivo e leitura dos dados.

Duas etapas:
  1. Checagens locais, sem API (R01 formato/tamanho, R02 qualidade):
     abre PDF ou imagem e mede nitidez, resolução, brilho e contraste.
  2. Modelo de visão do Groq: tipo do documento, se está legível e
     completo, e os dados do afastamento (nome, data de início, dias).
     NUNCA diagnóstico, CID ou número de CRM.

A etapa 2 está isolada em ler_documento(). Uma CNN ou um OCR próprio
pode substituí-la devolvendo o mesmo dicionário.

O atestado é salvo SÓ na pasta local uploads/. Ao modelo vai uma imagem
reduzida da 1ª página: use apenas documentos sintéticos no protótipo (LGPD).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import cv2
import numpy as np
import pymupdf

import config

MIME_POR_EXTENSAO = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}

PROBLEMAS = {  # mensagens prontas: o texto livre do modelo nunca chega ao funcionário
    "borrado": "o documento está borrado ou fora de foco",
    "cortado": "parte do documento ficou de fora da imagem",
    "escuro": "a imagem está escura demais",
    "reflexo": "há reflexo ou sombra cobrindo o texto",
    "incompleto": "falta uma parte do documento (por exemplo, o verso ou uma página)",
    "nao_e_documento": "o arquivo não parece ser um atestado ou uma declaração",
    "outro": "o documento não está legível",
}


def _agora() -> datetime:
    return datetime.now(config.FUSO).replace(tzinfo=None, microsecond=0)


@dataclass
class ResultadoDocumento:
    nome_original: str
    aceito: bool
    motivo: str
    regra: str | None = None              # regra que recusou: R01 ou R02
    tipo_detectado: str = "nao_verificado"
    confianca_tipo: float | None = None
    legivel: bool | None = None
    nitidez: float | None = None
    paginas: int | None = None
    mime: str | None = None
    tamanho_bytes: int = 0
    sha256: str | None = None
    caminho: Path | None = None
    verificado_por_visao: bool = False
    # Dados lidos do documento
    doc_nome: str | None = None
    doc_data_inicio: date | None = None
    doc_dias: int | None = None
    doc_assinado: bool | None = None
    analisado_em: datetime = field(default_factory=_agora)

    def campos_atestado(self) -> dict:
        """Colunas da tabela atestados preenchidas por esta conferência."""
        return {
            "documento_aceito": int(self.aceito),
            "documento_motivo": self.motivo[:255],
            "arquivo_nome": self.nome_original[:255],
            "arquivo_caminho": str(self.caminho) if self.caminho else None,
            "arquivo_sha256": self.sha256,
            "arquivo_mime": self.mime,
            "nitidez": self.nitidez,
            "tipo_detectado": self.tipo_detectado,
            "confianca_tipo": self.confianca_tipo,
            "doc_nome": self.doc_nome,
            "doc_data_inicio": self.doc_data_inicio,
            "doc_dias": self.doc_dias,
            "doc_assinado": None if self.doc_assinado is None else int(self.doc_assinado),
        }

    def para_auditoria(self) -> dict:
        """Vai para a auditoria: o resultado, sem o conteúdo do documento."""
        return {
            "arquivo": self.nome_original, "sha256": self.sha256, "aceito": self.aceito,
            "regra": self.regra, "motivo": self.motivo, "tipo_detectado": self.tipo_detectado,
            "confianca_tipo": self.confianca_tipo, "nitidez": self.nitidez,
            "verificado_por_visao": self.verificado_por_visao,
            "dados_lidos": {"data_inicio": self.doc_data_inicio, "dias": self.doc_dias,
                            "nome_lido": bool(self.doc_nome), "assinado": self.doc_assinado},
        }


# ---------------------------------------------------------------------------
# Etapa 1: checagens locais
# ---------------------------------------------------------------------------
def _salvar_local(dados: bytes, sha256: str, extensao: str) -> Path:
    momento = datetime.now(config.FUSO)
    pasta = config.PASTA_UPLOADS / momento.strftime("%Y") / momento.strftime("%m")
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{momento:%Y%m%d_%H%M%S}_{sha256[:12]}.{extensao}"
    caminho.write_bytes(dados)
    return caminho


def carregar_imagem(dados: bytes, extensao: str) -> tuple[np.ndarray, int]:
    """Devolve a 1ª página como imagem BGR e o número de páginas."""
    if extensao == "pdf":
        with pymupdf.open(stream=dados, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ValueError("PDF protegido por senha")
            if doc.page_count == 0:
                raise ValueError("PDF sem páginas")
            pix = doc[0].get_pixmap(dpi=150, colorspace=pymupdf.csRGB, alpha=False)
            rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), doc.page_count
    imagem = cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError("imagem corrompida ou em formato não suportado")
    return imagem, 1


def avaliar_qualidade(imagem: np.ndarray) -> dict:
    """R02 local: nitidez, resolução, brilho e presença de texto."""
    altura, largura = imagem.shape[:2]
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    escala = 1000 / largura
    normalizada = cv2.resize(cinza, (1000, max(1, int(altura * escala))), interpolation=cv2.INTER_AREA)
    nitidez = float(cv2.Laplacian(normalizada, cv2.CV_64F).var())
    brilho = float(normalizada.mean())
    contraste = float(normalizada.std())
    tinta = float((normalizada < 128).mean())

    problema = None
    if min(altura, largura) < config.RESOLUCAO_MINIMA_PX:
        problema = "a resolução da imagem é baixa demais"
    elif brilho < config.BRILHO_MINIMO:
        problema = PROBLEMAS["escuro"]
    elif contraste < config.CONTRASTE_MINIMO:
        problema = "a página parece estar em branco"
    elif nitidez < config.NITIDEZ_MINIMA:
        problema = PROBLEMAS["borrado"]
    elif tinta < config.TINTA_MINIMA:
        problema = "quase não há texto visível no documento"
    return {"ok": problema is None, "problema": problema, "nitidez": round(nitidez, 2)}


# ---------------------------------------------------------------------------
# Etapa 2: leitura pelo modelo de visão
# ---------------------------------------------------------------------------
PROMPT_VISAO = """Você confere documentos enviados ao RH de uma empresa brasileira.
Olhe a imagem e responda SOMENTE com um objeto JSON, sem texto fora dele:
{
  "tipo": "atestado_medico" | "declaracao_comparecimento" | "atestado_acompanhante" | "outro",
  "legivel": true | false,
  "completo": true | false,
  "problema": "nenhum" | "borrado" | "cortado" | "escuro" | "reflexo" | "incompleto" | "nao_e_documento" | "outro",
  "confianca": número entre 0 e 1 para o campo "tipo",
  "nome": "nome da pessoa a quem o documento se refere" ou null,
  "data_inicio": "AAAA-MM-DD" ou null,
  "dias": número inteiro de dias de afastamento ou null,
  "assinado": true | false
}
Definições:
- atestado_medico: documento de médico ou dentista que recomenda afastamento por um período.
- declaracao_comparecimento: declara que a pessoa esteve em consulta ou exame num horário, sem afastamento por dias.
- atestado_acompanhante: atesta que a pessoa acompanhou um familiar em atendimento.
- outro: qualquer outro documento ou imagem.
- completo = false se o documento estiver cortado nas bordas ou faltar parte do texto.
- nome: no atestado de acompanhante, o nome de quem acompanhou.
- data_inicio: início do afastamento; se não houver, a data do atendimento. Converta dd/mm/aaaa para AAAA-MM-DD.
- dias: quantidade de dias de afastamento escrita no documento; na declaração de comparecimento use 1.
- assinado: há assinatura, carimbo ou identificação do profissional.
Privacidade: NÃO transcreva diagnóstico, sintomas, CID, número do CRM, endereço ou qualquer outro dado.
Devolva apenas os campos acima."""


def _imagem_para_base64(imagem: np.ndarray, lado_max: int = 1600) -> str:
    altura, largura = imagem.shape[:2]
    escala = min(1.0, lado_max / max(altura, largura))
    if escala < 1.0:
        imagem = cv2.resize(imagem, (int(largura * escala), int(altura * escala)), interpolation=cv2.INTER_AREA)
    for qualidade in (85, 70, 55):
        ok, buffer = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
        if ok and len(buffer) < 3_000_000:
            return base64.b64encode(buffer.tobytes()).decode("ascii")
    raise ValueError("imagem grande demais para enviar ao modelo de visão")


def _extrair_json(texto: str) -> dict:
    texto = (texto or "").strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        achado = re.search(r"\{.*\}", texto, flags=re.DOTALL)
        if not achado:
            raise
        return json.loads(achado.group(0))


def _data_ou_none(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor).strip()[:10]) if valor else None
    except ValueError:
        return None


def _dias_ou_none(valor) -> int | None:
    try:
        dias = int(float(valor))
    except (TypeError, ValueError):
        return None
    return dias if 1 <= dias <= 365 else None


def ler_documento(cliente, imagem: np.ndarray) -> dict | None:
    """Ponto de troca: devolve o dicionário abaixo, ou None se a visão falhar."""
    if cliente is None:
        return None
    try:
        resposta = cliente.chat.completions.create(
            model=config.MODELO_VISAO,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_VISAO},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_imagem_para_base64(imagem)}"}},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_completion_tokens=2048,  # folga para modelos que raciocinam antes de responder
        )
        dados = _extrair_json(resposta.choices[0].message.content)
    except Exception as erro:  # rede, limite de uso, modelo indisponível, JSON inválido
        print(f"[documento] modelo de visão indisponível: {erro}", file=sys.stderr)
        return None

    tipo = str(dados.get("tipo", "outro")).strip().lower()
    problema = str(dados.get("problema", "nenhum")).strip().lower()
    try:
        confianca = float(dados.get("confianca", 0))
    except (TypeError, ValueError):
        confianca = 0.0
    nome = " ".join(str(dados.get("nome") or "").split())[:120] or None
    return {
        "tipo": tipo if tipo in set(config.TIPOS_DOCUMENTO) | {"outro"} else "outro",
        "legivel": bool(dados.get("legivel", False)),
        "completo": bool(dados.get("completo", False)),
        "problema": problema if problema in PROBLEMAS or problema == "nenhum" else "outro",
        "confianca": round(min(1.0, max(0.0, confianca)), 3),
        "nome": nome,
        "data_inicio": _data_ou_none(dados.get("data_inicio")),
        "dias": _dias_ou_none(dados.get("dias")),
        "assinado": None if dados.get("assinado") is None else bool(dados.get("assinado")),
    }


# ---------------------------------------------------------------------------
# Função principal: percepção + regras R01/R02
# ---------------------------------------------------------------------------
def analisar_documento(cliente, dados: bytes, nome_original: str) -> ResultadoDocumento:
    extensao = Path(nome_original).suffix.lower().lstrip(".")
    base = {"nome_original": nome_original, "tamanho_bytes": len(dados)}

    if extensao not in config.EXTENSOES_ACEITAS:
        return ResultadoDocumento(**base, aceito=False, regra="R01",
                                  motivo=f"o formato .{extensao or '?'} não é aceito (envie PDF, JPG ou PNG)")
    if len(dados) > config.TAMANHO_MAX_MB * 1024 * 1024:
        return ResultadoDocumento(**base, aceito=False, regra="R01", motivo=f"o arquivo passa de {config.TAMANHO_MAX_MB} MB")

    sha256 = hashlib.sha256(dados).hexdigest()
    base.update(sha256=sha256, mime=MIME_POR_EXTENSAO[extensao])
    try:
        imagem, paginas = carregar_imagem(dados, extensao)
    except Exception as erro:
        return ResultadoDocumento(**base, aceito=False, regra="R02", motivo=f"não consegui abrir o arquivo ({erro})")

    base.update(caminho=_salvar_local(dados, sha256, extensao), paginas=paginas)
    qualidade = avaliar_qualidade(imagem)
    base["nitidez"] = qualidade["nitidez"]
    if not qualidade["ok"]:
        return ResultadoDocumento(**base, aceito=False, regra="R02", legivel=False, motivo=qualidade["problema"])

    visao = ler_documento(cliente, imagem)
    if visao is None:
        return ResultadoDocumento(**base, aceito=True, legivel=True,
                                  motivo="arquivo legível na checagem local (tipo e dados não verificados)")

    base.update(
        tipo_detectado=visao["tipo"], confianca_tipo=visao["confianca"], verificado_por_visao=True,
        doc_nome=visao["nome"], doc_data_inicio=visao["data_inicio"], doc_dias=visao["dias"],
        doc_assinado=visao["assinado"],
    )
    if not visao["legivel"] or not visao["completo"]:
        problema = visao["problema"] if visao["problema"] != "nenhum" else "outro"
        return ResultadoDocumento(**base, aceito=False, regra="R02", legivel=False, motivo=PROBLEMAS[problema])
    if visao["tipo"] == "outro":
        return ResultadoDocumento(**base, aceito=False, regra="R01", legivel=True, motivo=PROBLEMAS["nao_e_documento"])
    if visao["confianca"] < config.LIMIAR_CONFIANCA_TIPO:
        base["tipo_detectado"] = "nao_verificado"  # vira alerta A7 para conferência manual
        return ResultadoDocumento(**base, aceito=True, legivel=True,
                                  motivo=f"documento legível (baixa confiança no tipo: {visao['confianca']:.2f})")
    return ResultadoDocumento(**base, aceito=True, legivel=True, motivo="documento legível e do tipo aceito")

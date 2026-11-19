"""Gera atestados e declarações SINTÉTICOS para testar o agente.

Todos levam a marca d'água "DOCUMENTO SINTÉTICO — SEM VALIDADE", com
médicos e CRM inventados. Servem para testar sem usar atestados reais
(LGPD), calibrar os limiares de qualidade e, se quiserem, treinar uma CNN.

Uso:
  python gerar_atestados_sinteticos.py            # exemplos de qualidade em exemplos/qualidade/
  python gerar_atestados_sinteticos.py --n 500    # conjunto rotulado em exemplos/dataset/
Os documentos dos 10 cenários são gerados por preparar_banco.py.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent
LARGURA, ALTURA = 1240, 1754  # A4 a 150 dpi

NOMES = ["Ana Paula Ferreira", "Carlos Eduardo Lima", "Juliana Souza Martins", "Rafael Oliveira Costa",
         "Mariana Alves Rocha", "Pedro Henrique Santos", "Fernanda Ribeiro Gomes", "Lucas Pereira Dias"]
MEDICOS = ["Dra. Helena Prado", "Dr. Marcos Vieira", "Dra. Beatriz Campos", "Dr. Ricardo Nunes"]
CLINICAS = ["Clínica Vida Plena", "Centro Médico Esperança", "Policlínica São Lucas (fictícia)", "UBS Modelo (fictícia)"]


def _fonte(tamanho: int, negrito: bool = False):
    candidatos = (["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"] if negrito
                  else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"])
    for nome in candidatos:
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(size=tamanho)


def _texto(tipo: str, paciente: str, inicio: date, dias: int, medico: str, crm: str,
           rnd: random.Random) -> tuple[str, list[str]]:
    if tipo == "atestado_medico":
        return "ATESTADO MÉDICO", [
            f"Atesto, para os devidos fins, que {paciente}",
            "esteve sob meus cuidados profissionais nesta data",
            "e deverá permanecer afastado(a) de suas atividades",
            f"por {dias} ({'dia' if dias == 1 else 'dias'}), a partir de {inicio:%d/%m/%Y}.",
            "",
            f"Local e data: São Paulo, {inicio:%d/%m/%Y}",
            "", "", "______________________________",
            medico, crm,
        ]
    if tipo == "declaracao_comparecimento":
        return "DECLARAÇÃO DE COMPARECIMENTO", [
            f"Declaro que {paciente} compareceu a esta unidade",
            f"no dia {inicio:%d/%m/%Y}, das 14h00 às 16h00,",
            "para consulta/exame.",
            "",
            f"São Paulo, {inicio:%d/%m/%Y}",
            "", "", "______________________________",
            medico, crm,
        ]
    if tipo == "atestado_acompanhante":
        return "ATESTADO DE ACOMPANHANTE", [
            f"Atesto que {paciente} acompanhou seu/sua",
            f"filho(a) em atendimento médico no dia {inicio:%d/%m/%Y},",
            "permanecendo nesta unidade durante o período do atendimento.",
            "",
            f"São Paulo, {inicio:%d/%m/%Y}",
            "", "", "______________________________",
            medico, crm,
        ]
    return "RECIBO DE PAGAMENTO", [   # "outro": o agente deve recusar
        f"Recebemos de {paciente} a importância de",
        f"R$ {rnd.randint(50, 900)},00 referente a serviços prestados.",
        "",
        f"São Paulo, {inicio:%d/%m/%Y}",
        "", "______________________________",
        "Loja Exemplo Ltda. (fictícia)",
    ]


def documento_limpo(tipo: str, rnd: random.Random, paciente: str | None = None,
                    inicio: date | None = None, dias: int | None = None) -> np.ndarray:
    paciente = paciente or rnd.choice(NOMES)
    inicio = inicio or date.today() - timedelta(days=rnd.randint(0, 5))
    dias = dias or rnd.choice([1, 2, 3, 5, 7, 10, 15, 20])
    medico = rnd.choice(MEDICOS)
    crm = f"CRM-SP {rnd.randint(10000, 99999)} (fictício)"

    img = Image.new("RGB", (LARGURA, ALTURA), "white")
    d = ImageDraw.Draw(img)
    d.text((100, 90), rnd.choice(CLINICAS), font=_fonte(34, True), fill=(20, 60, 120))
    d.text((100, 140), "Rua das Flores, 123 — São Paulo/SP — (11) 0000-0000", font=_fonte(22), fill=(80, 80, 80))
    d.line((100, 190, LARGURA - 100, 190), fill=(20, 60, 120), width=3)
    titulo, linhas = _texto(tipo, paciente, inicio, dias, medico, crm, rnd)
    d.text((LARGURA // 2, 300), titulo, font=_fonte(46, True), fill="black", anchor="mm")
    y = 430
    for linha in linhas:
        d.text((120, y), linha, font=_fonte(32), fill="black")
        y += 58
    marca = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(marca).text((LARGURA // 2, ALTURA // 2 + 300), "DOCUMENTO SINTÉTICO — SEM VALIDADE",
                               font=_fonte(52, True), fill=(220, 0, 0, 90), anchor="mm")
    img = Image.alpha_composite(img.convert("RGBA"), marca.rotate(30, center=(LARGURA // 2, ALTURA // 2 + 300)))
    ImageDraw.Draw(img).text((100, ALTURA - 80), "Documento gerado para testes do projeto Sinergia. Sem validade legal.",
                             font=_fonte(20), fill=(200, 0, 0))
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def degradar(img: np.ndarray, defeito: str, rnd: random.Random) -> np.ndarray:
    if defeito == "borrado":
        return cv2.GaussianBlur(img, (0, 0), rnd.uniform(4.0, 7.0))
    if defeito == "escuro":
        return cv2.convertScaleAbs(img, alpha=0.18, beta=0)
    if defeito == "cortado":
        h, w = img.shape[:2]
        return img[: int(h * 0.45), int(w * 0.25):]
    if defeito == "baixa_resolucao":
        return cv2.resize(img, (420, 594), interpolation=cv2.INTER_AREA)
    if defeito == "foto":  # foto de celular aceitável: leve rotação, sombra e ruído
        h, w = img.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rnd.uniform(-4, 4), 1.0)
        img = cv2.warpAffine(img, m, (w, h), borderValue=(180, 170, 160))
        sombra = np.tile(np.linspace(1.0, 0.8, w, dtype=np.float32), (h, 1))[..., None]
        ruido = np.random.default_rng(rnd.randint(0, 9999)).normal(0, 6, img.shape)
        return np.clip(img.astype(np.float32) * sombra + ruido, 0, 255).astype(np.uint8)
    return img


def salvar(img: np.ndarray, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.suffix == ".pdf":
        _, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        with pymupdf.open() as pdf:
            pagina = pdf.new_page(width=595, height=842)
            pagina.insert_image(pagina.rect, stream=jpg.tobytes())
            # Metadados fixos: o mesmo documento gera sempre o mesmo arquivo (e o mesmo hash)
            pdf.set_metadata({"producer": "Sinergia (sintético)", "creationDate": "", "modDate": ""})
            pdf.save(caminho, garbage=4, deflate=True, no_new_id=True)
    else:
        cv2.imwrite(str(caminho), img)


def gerar_documento_cenario(cenario, caminho: Path) -> None:
    rnd = random.Random(cenario.funcionario_id)  # semente fixa: o mesmo cenário gera o mesmo arquivo
    img = documento_limpo(cenario.tipo, rnd, cenario.doc_nome, cenario.doc_inicio, cenario.doc_dias)
    salvar(img, caminho)


EXEMPLOS_QUALIDADE = [  # (tipo, defeito, extensão)
    ("atestado_medico", "foto", ".jpg"),             # aceitar
    ("atestado_medico", "borrado", ".jpg"),          # recusar (R02)
    ("atestado_medico", "escuro", ".jpg"),           # recusar (R02)
    ("atestado_medico", "baixa_resolucao", ".jpg"),  # recusar (R02)
    ("outro", "nenhum", ".png"),                     # recusar (R01, pelo modelo de visão)
]


def gerar_exemplos_qualidade() -> list[Path]:
    """Arquivos para testar a recusa por qualidade (borrado, escuro...) no chat."""
    rnd = random.Random(42)
    saida = RAIZ / "exemplos" / "qualidade"
    caminhos = []
    for i, (tipo, defeito, ext) in enumerate(EXEMPLOS_QUALIDADE, 1):
        caminho = saida / f"{i:02d}_{tipo}_{defeito}{ext}"
        salvar(degradar(documento_limpo(tipo, rnd), defeito, rnd), caminho)
        caminhos.append(caminho)
    return caminhos


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=0, help="gera N documentos aleatórios com rótulos")
    parser.add_argument("--semente", type=int, default=42)
    args = parser.parse_args()
    rnd = random.Random(args.semente)

    if args.n <= 0:
        for caminho in gerar_exemplos_qualidade():
            print("gerado:", caminho.relative_to(RAIZ))
        return

    saida = RAIZ / "exemplos" / "dataset"
    tipos = ["atestado_medico", "declaracao_comparecimento", "atestado_acompanhante", "outro"]
    defeitos = ["nenhum", "nenhum", "foto", "foto", "borrado", "escuro", "cortado", "baixa_resolucao"]
    saida.mkdir(parents=True, exist_ok=True)
    with open(saida / "rotulos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arquivo", "tipo", "defeito", "legivel"])
        for i in range(args.n):
            tipo, defeito = rnd.choice(tipos), rnd.choice(defeitos)
            nome = f"{i:05d}_{tipo}_{defeito}.jpg"
            salvar(degradar(documento_limpo(tipo, rnd), defeito, rnd), saida / nome)
            w.writerow([nome, tipo, defeito, int(defeito in ("nenhum", "foto"))])
    print(f"{args.n} documentos e rotulos.csv em {saida}")


if __name__ == "__main__":
    main()

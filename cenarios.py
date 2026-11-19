"""Mundo simulado: 10 funcionários fictícios, 30 dias de ponto e cenários de teste.

Todas as datas são relativas a "hoje", então os cenários continuam
válidos em qualquer dia em que você rodar `python preparar_banco.py`.
Cada cenário diz o que o agente DEVE detectar: isso serve para a
demonstração, para os testes automáticos e para medir acertos e falsos
alertas.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import config
from datas import dia_util_antes, dias, eh_dia_util, eh_feriado


def slug(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return "_".join(sem_acento.lower().split())


_BASE = [
    ("FUNC001", "Ana Oliveira", "Produção", "Operadora de produção"),
    ("FUNC002", "Bruno Santos", "Logística", "Auxiliar de logística"),
    ("FUNC003", "Carla Ferreira", "Administrativo", "Assistente administrativa"),
    ("FUNC004", "Daniel Costa", "Manutenção", "Técnico de manutenção"),
    ("FUNC005", "Elisa Martins", "Comercial", "Vendedora interna"),
    ("FUNC006", "Felipe Almeida", "TI", "Analista de suporte"),
    ("FUNC007", "Gabriela Rocha", "Produção", "Supervisora de turno"),
    ("FUNC008", "Henrique Lima", "Logística", "Conferente"),
    ("FUNC009", "Isabela Ribeiro", "Administrativo", "Analista financeira"),
    ("FUNC010", "João Pereira", "Manutenção", "Eletricista"),
]

FUNCIONARIOS = [
    {
        "id": fid,
        "nome": nome,
        "setor": setor,
        "cargo": cargo,
        # example.com é reservado para testes: nenhum e-mail chega a uma pessoa real
        "email": f"{slug(nome).replace('_', '.')}@example.com",
        "telefone": f"(19) 99101-{int(fid[4:]):04d}",
        "jornada_inicio": "08:00:00",
        "jornada_fim": "17:00:00",
    }
    for fid, nome, setor, cargo in _BASE
]
FUNCIONARIOS_POR_ID = {f["id"]: f for f in FUNCIONARIOS}


@dataclass(frozen=True)
class Cenario:
    funcionario_id: str
    titulo: str
    tipo: str
    inicio: date
    dias: int                 # dias informados no formulário
    doc_nome: str             # o que está escrito no documento sintético
    doc_inicio: date
    doc_dias: int
    esperado: frozenset       # códigos de alerta que o agente deve gerar
    explicacao: str
    motivo: str | None = None

    @property
    def fim(self) -> date:
        return self.inicio + timedelta(days=self.dias - 1)

    @property
    def nome(self) -> str:
        return FUNCIONARIOS_POR_ID[self.funcionario_id]["nome"]

    @property
    def arquivo(self) -> str:
        return f"{self.funcionario_id}_{slug(self.nome)}.pdf"

    @property
    def caminho_arquivo(self):
        return config.PASTA_EXEMPLOS / "cenarios" / self.arquivo


def _sexta_recente(hoje: date) -> date:
    d = hoje - timedelta(days=5)        # a segunda seguinte fica pelo menos 2 dias antes de hoje
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


def _segunda_recente(hoje: date) -> date:
    d = hoje - timedelta(days=6)        # a sexta da mesma semana fica pelo menos 2 dias antes de hoje
    while d.weekday() != 0:
        d -= timedelta(days=1)
    return d


def montar_cenarios(hoje: date) -> list[Cenario]:
    ontem = hoje - timedelta(days=1)
    ana = dia_util_antes(hoje, 6)
    bruno = dia_util_antes(hoje, 10)
    carla = dia_util_antes(hoje, 4)
    daniel = dia_util_antes(hoje, 12)
    elisa = _segunda_recente(hoje)
    felipe = _sexta_recente(hoje)
    gabriela = dia_util_antes(hoje, 7)
    henrique = dia_util_antes(hoje, 3)
    isabela = hoje - timedelta(days=22)
    joao = dia_util_antes(hoje, 5)

    # Elisa: o documento diz 5 dias e o formulário 3. Os dias 4 e 5 aparecem
    # como faltas sem justificativa (A2) se forem dias úteis já passados.
    extras_elisa = [d for d in dias(elisa + timedelta(days=3), elisa + timedelta(days=4)) if eh_dia_util(d) and d <= ontem]
    esperado_elisa = frozenset({"A3", "A2"} if extras_elisa else {"A3"})

    return [
        Cenario("FUNC001", "Tudo certo (controle)", "atestado_medico", ana, 3, "Ana Oliveira", ana, 3,
                frozenset(), "Faltas no ponto batem com o atestado. Não deve haver alerta.", "doenca"),
        Cenario("FUNC002", "Ponto batido durante o afastamento", "atestado_medico", bruno, 5, "Bruno Santos", bruno, 5,
                frozenset({"A1"}), "No 2º dia útil do afastamento há entrada e saída no ponto.", "doenca"),
        Cenario("FUNC003", "Faltas sem justificativa antes do atestado", "atestado_medico", carla, 2, "Carla Ferreira", carla, 2,
                frozenset({"A2"}), "Os 2 dias úteis antes do início estão como falta, sem justificativa.", "consulta_exame"),
        Cenario("FUNC004", "Atestado já enviado antes (duplicado)", "atestado_medico", daniel, 2, "Daniel Costa", daniel, 2,
                frozenset({"A4"}), "O mesmo arquivo e o mesmo período já estão registrados.", "doenca"),
        Cenario("FUNC005", "Formulário diz 3 dias, documento diz 5", "atestado_medico", elisa, 3, "Elisa Martins", elisa, 5,
                esperado_elisa, "O documento tem 5 dias; os 2 dias a mais aparecem como faltas no ponto.", "doenca"),
        Cenario("FUNC006", "Afastamento cobre fim de semana (controle)", "atestado_medico", felipe, 4, "Felipe Almeida", felipe, 4,
                frozenset(), "Sexta a segunda: sábado e domingo são folga. Não deve haver alerta.", "doenca"),
        Cenario("FUNC007", "Saiu cedo no 1º dia (controle)", "atestado_medico", gabriela, 3, "Gabriela Rocha", gabriela, 3,
                frozenset(), "Entrada 08:00 e saída 10:20 no 1º dia (foi ao médico). Não é alerta.", "doenca"),
        Cenario("FUNC008", "Declaração de comparecimento (controle)", "declaracao_comparecimento", henrique, 1, "Henrique Lima", henrique, 1,
                frozenset(), "Trabalhou de manhã e foi à consulta à tarde. Declaração cobre só horas.", "consulta_exame"),
        Cenario("FUNC009", "Afastamento de 20 dias (INSS)", "atestado_medico", isabela, 20, "Isabela Ribeiro", isabela, 20,
                frozenset({"A5"}), "Mais de 15 dias: a partir do 16º o caso vai para o INSS.", "doenca"),
        Cenario("FUNC010", "Documento em nome de outra pessoa", "atestado_medico", joao, 2, "Pedro Henrique Souza", joao, 2,
                frozenset({"A6"}), "O nome no documento não é o do funcionário.", "doenca"),
    ]


def _batida(rnd: random.Random, base: str, variacao_min: int) -> str:
    h, m = map(int, base.split(":"))
    total = h * 60 + m + rnd.randint(-variacao_min, variacao_min)
    return f"{total // 60:02d}:{total % 60:02d}:00"


def gerar_ponto(hoje: date) -> list[dict]:
    """30 dias de ponto para os 10 funcionários, com os ajustes de cada cenário."""
    inicio = hoje - timedelta(days=config.DIAS_HISTORICO_PONTO)
    ontem = hoje - timedelta(days=1)
    registros: dict[tuple[str, date], dict] = {}

    for f in FUNCIONARIOS:
        for d in dias(inicio, ontem):
            rnd = random.Random(f"{f['id']}-{d.isoformat()}")
            if eh_feriado(d):
                linha = {"situacao": "feriado", "entrada": None, "saida": None, "justificativa": "Feriado nacional"}
            elif d.weekday() >= 5:
                linha = {"situacao": "folga", "entrada": None, "saida": None, "justificativa": None}
            else:
                linha = {"situacao": "trabalhado", "entrada": _batida(rnd, "08:00", 12),
                         "saida": _batida(rnd, "17:05", 15), "justificativa": None}
            registros[(f["id"], d)] = {"funcionario_id": f["id"], "data": d, **linha}

    def marcar(fid: str, d: date, situacao: str, entrada=None, saida=None, justificativa=None):
        if (fid, d) in registros and eh_dia_util(d):
            registros[(fid, d)].update(situacao=situacao, entrada=entrada, saida=saida, justificativa=justificativa)

    for c in montar_cenarios(hoje):
        fid = c.funcionario_id
        uteis = [d for d in dias(c.inicio, c.fim) if eh_dia_util(d)]
        if fid == "FUNC004":      # período já coberto por um atestado anterior
            for d in uteis:
                marcar(fid, d, "afastado", justificativa=f"Atestado {protocolo_previo(hoje)}")
        elif fid == "FUNC005":    # faltas nos 5 dias do documento
            for d in dias(c.doc_inicio, c.doc_inicio + timedelta(days=c.doc_dias - 1)):
                marcar(fid, d, "falta")
        elif fid == "FUNC008":    # trabalhou de manhã, consulta à tarde
            marcar(fid, c.inicio, "trabalhado", "08:02:00", "13:30:00")
        else:
            for d in uteis:
                marcar(fid, d, "falta")
        if fid == "FUNC002" and len(uteis) >= 2:
            marcar(fid, uteis[1], "trabalhado", "08:03:00", "17:01:00")
        if fid == "FUNC003":
            for n in (1, 2):
                marcar(fid, dia_util_antes(c.inicio, n), "falta")
        if fid == "FUNC007":
            marcar(fid, c.inicio, "trabalhado", "08:00:00", "10:20:00")

    return [registros[k] for k in sorted(registros, key=lambda k: (k[0], k[1]))]


def protocolo_previo(hoje: date) -> str:
    c = next(c for c in montar_cenarios(hoje) if c.funcionario_id == "FUNC004")
    return f"SNG-{c.inicio:%Y%m%d}-PREV04"


def atestado_previo_daniel(hoje: date, sha256: str) -> dict:
    """Atestado que o Daniel já tinha enviado (para o cenário de duplicado)."""
    c = next(c for c in montar_cenarios(hoje) if c.funcionario_id == "FUNC004")
    f = FUNCIONARIOS_POR_ID["FUNC004"]
    criado = datetime.combine(c.inicio, time(10, 15))
    return {
        "protocolo": protocolo_previo(hoje),
        "funcionario_id": "FUNC004",
        "criado_em": criado,
        "campos": {
            "tipo": c.tipo, "data_inicio": c.inicio, "data_fim": c.fim, "dias": c.dias, "motivo": "doenca",
            "telefone_informado": f["telefone"], "email_informado": f["email"], "receber_email": 1,
            "atualizar_cadastro": 0, "complemento": "(nada a complementar)",
            "documento_aceito": 1, "documento_motivo": "documento legível e do tipo aceito", "tentativas_envio": 1,
            "arquivo_nome": c.arquivo, "arquivo_caminho": str(c.caminho_arquivo), "arquivo_sha256": sha256,
            "arquivo_mime": "application/pdf", "tipo_detectado": c.tipo, "confianca_tipo": 0.95,
            "doc_nome": c.doc_nome, "doc_data_inicio": c.doc_inicio, "doc_dias": c.doc_dias, "doc_assinado": 1,
            "status": "resolvido", "chat_finalizado_em": criado + timedelta(minutes=4),
            "resolvido_em": criado + timedelta(hours=3), "atualizado_em": criado + timedelta(hours=3),
            "observacoes": "Registro anterior (dados simulados).",
        },
    }

"""Agente de RH (versão 2) do projeto Sinergia — conversa depois do formulário.

É o mesmo laço do agente_groq.py ("o modelo escolhe a ferramenta, o
Python executa e devolve o resultado"), agora com um objetivo explícito:
resolver as PENDÊNCIAS do caso. Quem calcula as pendências é o Python
(orquestrador.pendencias_chat), a partir do formulário, do documento e
da conferência com o ponto. O LLM conduz a conversa, registra as
respostas pelas ferramentas e explica os alertas em linguagem simples.

  Percepção: formulário + documento + ponto (já conferidos) e as mensagens
  Decisão:   lista de pendências calculada por regras
  Ação:      perguntar, registrar respostas, finalizar e disparar e-mails

Teste no terminal (sem a página web), com um atestado já enviado:
  python agente.py <id_do_atestado>
"""

from __future__ import annotations

import json
import sys

import config
import db
import orquestrador
from datas import DIAS_SEMANA

MAX_RODADAS = 8          # chamadas de ferramenta por turno (evita loops)
MAX_HISTORICO = 30


def criar_cliente():
    """Cliente do Groq, ou None se não houver chave."""
    if not config.GROQ_API_KEY:
        return None
    from groq import Groq

    return Groq(api_key=config.GROQ_API_KEY, max_retries=2, timeout=60)


FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "registrar_resposta",
            "description": "Registra a explicação do colaborador para um alerta (use o código do alerta do estado).",
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string", "description": "Código do alerta, ex.: A1"},
                    "resposta": {"type": "string", "description": "Resumo fiel do que o colaborador explicou"},
                },
                "required": ["codigo", "resposta"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_preferencias",
            "description": "Registra se o colaborador quer receber e-mails e/ou se quer atualizar o cadastro com o contato informado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "receber_email": {"type": "boolean"},
                    "atualizar_cadastro": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_complemento",
            "description": "Registra o que o colaborador quis complementar (texto vazio se não houver nada).",
            "parameters": {
                "type": "object",
                "properties": {"texto": {"type": "string"}},
                "required": ["texto"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_situacao",
            "description": "Mostra o estado atual do atendimento e as pendências.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalizar_atendimento",
            "description": (
                "Encerra o atendimento e dispara os e-mails. Use 'concluido' quando não houver pendências, "
                "ou 'colaborador_desistiu' se ele quiser parar antes. Se faltar algo, a ferramenta recusa e diz o quê."
            ),
            "parameters": {
                "type": "object",
                "properties": {"motivo": {"type": "string", "enum": ["concluido", "colaborador_desistiu"]}},
                "required": ["motivo"],
                "additionalProperties": False,
            },
        },
    },
]


def prompt_sistema() -> str:
    hoje = db.hoje()
    return f"""Você é o assistente de RH do sistema Sinergia. Hoje é {DIAS_SEMANA[hoje.weekday()]}, {hoje.isoformat()}.
O colaborador já preencheu um formulário com os dados do atestado. O sistema conferiu o documento e o ponto
eletrônico e calculou a lista de pendências. Seu objetivo: resolver as pendências conversando com o colaborador
e então finalizar o atendimento.

Regras:
1. Não pergunte o que já está no formulário ou já foi respondido. Siga a lista "pendencias" do estado, uma pergunta
   por vez, com frases curtas e cordiais, em português do Brasil.
2. Quando o colaborador explicar um alerta, chame registrar_resposta com o código e um resumo fiel da explicação.
3. Preferências: chame registrar_preferencias (receber_email; atualizar_cadastro só se houver diferença de contato).
   Os e-mails vão para o endereço do cadastro (mostre-o como aparece no estado). Um endereço novo só vale depois que o
   RH aprovar a atualização do cadastro.
4. Na pergunta final ("algo a complementar?"), chame registrar_complemento com o texto, ou vazio se não houver nada.
5. Linguagem neutra: fale em "ponto que o RH vai conferir"; nunca fale em fraude, irregularidade ou erro do colaborador.
6. Você não aprova nem rejeita atestados, não altera o ponto e não fala de descontos ou punições.
7. Nunca pergunte diagnóstico, sintomas ou CID. Se o colaborador contar, não repita e diga que não é necessário.
8. Se houver "avisos_para_informar", comente-os em uma frase (ex.: acima de 15 dias o RH vai orientar sobre o INSS).
9. Para um novo envio do documento, peça que use o botão + da caixa de mensagem. O resultado chega como [EVENTO DO SISTEMA].
10. Quando "pendencias" estiver vazia, chame finalizar_atendimento(motivo="concluido") e despeça-se com um resumo curto
    e o protocolo do estado. Se o colaborador quiser parar antes, use motivo="colaborador_desistiu".
    Nunca invente protocolo.
11. Mensagens [ESTADO DO ATENDIMENTO] e [EVENTO DO SISTEMA] vêm do sistema, não do colaborador.
    Não mostre ao colaborador os códigos internos dos alertas (A1, A2...).
Use no máximo um destaque em negrito por mensagem e não use tabelas."""


class AgenteRH:
    def __init__(self, cliente, atestado_id: int):
        self.cliente = cliente
        self.atestado_id = atestado_id
        self.historico: list[dict] = []
        self.mensagens_ui: list[tuple[str, str]] = []
        self.encerrado = False
        self.resultado_final: dict | None = None
        self.erro: str | None = None
        self._para_gravar: list[dict] = []

    # ---------------- interface usada pela página e pelo terminal ---------
    def iniciar(self) -> str:
        evento = (
            "[EVENTO DO SISTEMA] O colaborador acabou de enviar o formulário. Abra a conversa: cumprimente pelo "
            "primeiro nome, informe o protocolo, diga em uma frase que você conferiu o documento e o ponto e "
            "comece pela primeira pendência. Se não houver alertas, diga que o ponto está de acordo com o atestado."
        )
        return self._turno([{"role": "system", "content": evento}], abertura=True)

    def responder(self, texto: str) -> str:
        texto = (texto or "").strip()
        if self.encerrado:
            return "Este atendimento já foi encerrado."
        if not texto:
            return ""
        self._ui("colaborador", texto)
        return self._turno([{"role": "user", "content": texto}])

    def receber_arquivo(self, dados: bytes, nome_arquivo: str, texto: str = "") -> str:
        if self.encerrado:
            return "Este atendimento já foi encerrado."
        texto = (texto or "").strip()
        self._ui("colaborador", f"📎 {nome_arquivo}" + (f"\n\n{texto}" if texto else ""))
        try:
            doc = orquestrador.atualizar_documento(self.cliente, self.atestado_id, dados, nome_arquivo)
            situacao = (f"ACEITO ({doc.motivo})" if doc.aceito else f"RECUSADO: {doc.motivo}")
            evento = (f"[EVENTO DO SISTEMA] Novo arquivo '{nome_arquivo}' conferido: {situacao}. "
                      "A conferência com o ponto foi refeita; siga as pendências atualizadas do estado. "
                      "Se foi recusado, explique o motivo com gentileza e dê uma dica prática "
                      "(boa luz, documento inteiro e reto, ou o PDF original).")
        except db.ErroBanco as erro:
            self.erro = str(erro)
            evento = "[EVENTO DO SISTEMA] Falha técnica ao conferir o arquivo. Peça para tentar de novo em instantes."
        return self._turno([
            {"role": "system", "content": evento},
            {"role": "user", "content": f"[Anexo enviado: {nome_arquivo}] {texto}".strip()},
        ])

    def estado(self) -> dict:
        at, func, alertas = orquestrador.contexto_caso(self.atestado_id)
        pend = orquestrador.pendencias_chat(at, func, alertas)
        difere = orquestrador.contato_difere(at, func)
        abertos = [a for a in alertas if a["status"] == "aberto"]
        return {
            "colaborador": {"primeiro_nome": func["nome"].split()[0], "id": func["id"]},
            "protocolo": at["protocolo"],
            "afastamento": {
                "tipo": config.TIPOS_DOCUMENTO[at["tipo"]], "inicio": at["data_inicio"].isoformat(),
                "fim": at["data_fim"].isoformat(), "dias": int(at["dias"]),
            },
            "documento": {
                "aceito": bool(at["documento_aceito"]), "situacao": at["documento_motivo"],
                "tentativas": f"{at['tentativas_envio']} de {config.MAX_TENTATIVAS_ENVIO}",
            },
            "contato": {
                "telefone_difere_do_cadastro": difere["telefone"],
                "email_difere_do_cadastro": difere["email"],
                "email_do_cadastro": db.mascarar_email(func["email"]),
            },
            "perguntas_sobre_alertas": [
                {"codigo": a["codigo"], "pergunta": a["pergunta"], "respondido": bool(a.get("resposta_colaborador"))}
                for a in abertos if a.get("pergunta")
            ],
            "avisos_para_informar": [a["descricao"] for a in abertos if a["codigo"] == "A5"],
            "ja_registrado": {
                "receber_email": at.get("receber_email"), "atualizar_cadastro": at.get("atualizar_cadastro"),
                "complemento": at.get("complemento") is not None,
            },
            "pendencias": [p["descricao"] for p in pend],
            "atendimento_encerrado": bool(at["chat_finalizado_em"]),
        }

    # ---------------- laço do LLM com ferramentas -------------------------
    def _turno(self, novas: list[dict], abertura: bool = False) -> str:
        texto = None
        if self.cliente is None:
            texto = (self._abertura_padrao() if abertura
                     else "O assistente está sem conexão com o Groq (falta GROQ_API_KEY no .env). "
                          "Seu atestado já foi registrado e o RH vai conferir.")
        else:
            try:
                texto = self._conversar(novas)
            except db.ErroBanco as erro:
                self.erro = str(erro)
                texto = "Tive um problema ao acessar o banco de dados. Pode tentar de novo em instantes?"
            except Exception as erro:  # rede, limite de uso do Groq...
                print(f"[agente] erro ao consultar o Groq: {erro}", file=sys.stderr)
                texto = (self._abertura_padrao() if abertura
                         else "Tive um problema técnico agora. Pode repetir a sua última mensagem em instantes?")

        self.historico.extend(m for m in novas if m["role"] in ("user", "system"))
        self.historico.append({"role": "assistant", "content": texto})
        self._ui("agente", texto)
        self._gravar_conversa()
        return texto

    def _conversar(self, novas: list[dict]) -> str:
        estado = {"role": "system",
                  "content": "[ESTADO DO ATENDIMENTO — gerado pelo sistema]\n" + json.dumps(self.estado(), ensure_ascii=False)}
        mensagens = [{"role": "system", "content": prompt_sistema()}, *self.historico[-MAX_HISTORICO:], estado, *novas]
        for _ in range(MAX_RODADAS):
            resposta = self.cliente.chat.completions.create(
                model=config.MODELO_CHAT,
                messages=mensagens,
                tools=FERRAMENTAS,
                tool_choice="auto",
                reasoning_format="hidden",
                temperature=0.3,
            )
            mensagem = resposta.choices[0].message
            if not mensagem.tool_calls:
                texto = (mensagem.content or "").strip()
                if texto:
                    return texto
                break
            mensagens.append({
                "role": "assistant",
                "content": mensagem.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in mensagem.tool_calls
                ],
            })
            for chamada in mensagem.tool_calls:
                resultado = self._executar_ferramenta(chamada.function.name, chamada.function.arguments)
                mensagens.append({
                    "role": "tool", "tool_call_id": chamada.id, "name": chamada.function.name,
                    "content": json.dumps(resultado, ensure_ascii=False, default=str),
                })
        if self.encerrado and self.resultado_final:
            return f"Atendimento encerrado. Seu protocolo é **{self.resultado_final['protocolo']}**."
        return "Desculpe, não consegui concluir. Pode repetir, por favor?"

    def _executar_ferramenta(self, nome: str, argumentos_json: str | None) -> dict:
        try:
            args = json.loads(argumentos_json or "{}")
            if not isinstance(args, dict):
                raise ValueError("argumentos devem ser um objeto JSON")
        except ValueError as erro:
            return {"ok": False, "erro": f"argumentos inválidos: {erro}"}

        if nome == "registrar_resposta":
            resultado = orquestrador.registrar_resposta(self.atestado_id, args.get("codigo", ""), args.get("resposta", ""))
        elif nome == "registrar_preferencias":
            resultado = orquestrador.registrar_preferencias(
                self.atestado_id, args.get("receber_email"), args.get("atualizar_cadastro"))
        elif nome == "registrar_complemento":
            resultado = orquestrador.registrar_complemento(self.atestado_id, args.get("texto", ""))
        elif nome == "consultar_situacao":
            return {"ok": True, **self.estado()}
        elif nome == "finalizar_atendimento":
            resultado = orquestrador.finalizar_chat(self.atestado_id, args.get("motivo", "concluido"))
            if resultado.get("ok"):
                self.encerrado, self.resultado_final = True, resultado
            return resultado
        else:
            return {"ok": False, "erro": "ferramenta não autorizada"}
        resultado["pendencias"] = [p["descricao"] for p in orquestrador.pendencias_chat(*orquestrador.contexto_caso(self.atestado_id))]
        return resultado

    # ---------------- utilidades ------------------------------------------
    def _abertura_padrao(self) -> str:
        """Mensagem inicial sem LLM (se o Groq estiver fora do ar)."""
        e = self.estado()
        texto = (f"Olá, {e['colaborador']['primeiro_nome']}! Recebi o seu atestado (protocolo **{e['protocolo']}**). "
                 "Conferi o documento e o seu ponto.")
        perguntas = [p["pergunta"] for p in e["perguntas_sobre_alertas"] if not p["respondido"]]
        if not e["documento"]["aceito"]:
            texto += f" O arquivo não pôde ser aceito: {e['documento']['situacao']}. Pode enviar de novo pelo botão +?"
        elif perguntas:
            texto += f" Preciso entender um ponto: {perguntas[0]}"
        else:
            texto += " O ponto está de acordo com o atestado."
        return texto

    def _ui(self, papel: str, texto: str) -> None:
        self.mensagens_ui.append((papel, texto))
        self._para_gravar.append({"papel": papel, "conteudo": texto, "enviado_em": db.agora()})

    def _gravar_conversa(self) -> None:
        if config.SALVAR_CONVERSA:
            try:
                db.registrar_conversa(self.atestado_id, self._para_gravar)
            except db.ErroBanco as erro:
                self.erro = str(erro)
                return
        self._para_gravar = []


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Uso: python agente.py <id_do_atestado>  (o atestado é criado pelo formulário da página web)")
        return
    cliente = criar_cliente()
    agente = AgenteRH(cliente, int(sys.argv[1]))
    print("Agente:", agente.iniciar())
    while not agente.encerrado:
        try:
            entrada = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if entrada.lower() in {"sair", "exit", "quit"}:
            break
        if entrada:
            print("Agente:", agente.responder(entrada))
    if agente.resultado_final:
        print(f"\nProtocolo {agente.resultado_final['protocolo']} · status {agente.resultado_final['status']}")


if __name__ == "__main__":
    main()

-- =====================================================================
-- Sinergia — Agente de RH (versão 2) · banco de dados
-- Compatível com MariaDB 10.3+ e MySQL 5.7+
--
-- Não precisa importar à mão: `python preparar_banco.py` executa este
-- arquivo e carrega os dados simulados.
--
-- Os nomes das tabelas são diferentes dos da v1 (colaboradores,
-- atendimentos, eventos, mensagens), então as duas versões podem usar o
-- mesmo banco sem conflito.
--
-- O arquivo do atestado NÃO fica no banco: fica na pasta uploads/ do
-- computador local; aqui ficam só o caminho e o hash SHA-256.
-- Horários gravados pelo Python no fuso de São Paulo.
-- =====================================================================

SET NAMES utf8mb4;

-- Cadastro de funcionários (os 10 fictícios vêm do preparar_banco.py)
CREATE TABLE IF NOT EXISTS funcionarios (
  id              VARCHAR(10)   NOT NULL,          -- ex.: FUNC001
  nome            VARCHAR(120)  NOT NULL,
  setor           VARCHAR(60)   NOT NULL,
  cargo           VARCHAR(80)   NOT NULL,
  email           VARCHAR(160)  NOT NULL,
  telefone        VARCHAR(20)   NOT NULL,
  jornada_inicio  TIME          NOT NULL DEFAULT '08:00:00',
  jornada_fim     TIME          NOT NULL DEFAULT '17:00:00',
  ativo           TINYINT(1)    NOT NULL DEFAULT 1,
  atualizado_em   DATETIME      NOT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ponto eletrônico: um registro por funcionário e dia
CREATE TABLE IF NOT EXISTS ponto (
  id              INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  funcionario_id  VARCHAR(10)   NOT NULL,
  data            DATE          NOT NULL,
  entrada         TIME          NULL,
  saida           TIME          NULL,
  situacao        ENUM('trabalhado','falta','folga','feriado','afastado') NOT NULL,
  justificativa   VARCHAR(255)  NULL,             -- NULL numa falta = falta sem justificativa
  PRIMARY KEY (id),
  UNIQUE KEY uq_ponto_dia (funcionario_id, data),
  CONSTRAINT fk_ponto_funcionario FOREIGN KEY (funcionario_id)
    REFERENCES funcionarios (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Atestados: um por envio de formulário
CREATE TABLE IF NOT EXISTS atestados (
  id                  INT UNSIGNED       NOT NULL AUTO_INCREMENT,
  protocolo           VARCHAR(24)        NOT NULL,
  funcionario_id      VARCHAR(10)        NOT NULL,

  -- Formulário
  tipo                ENUM('atestado_medico','declaracao_comparecimento','atestado_acompanhante') NOT NULL,
  data_inicio         DATE               NOT NULL,
  data_fim            DATE               NOT NULL,
  dias                SMALLINT UNSIGNED  NOT NULL,
  motivo              ENUM('doenca','consulta_exame','acompanhante','acidente','prefiro_nao_informar') NULL,
  telefone_informado  VARCHAR(20)        NOT NULL,
  email_informado     VARCHAR(160)       NOT NULL,

  -- Respostas do chat
  receber_email       TINYINT(1)         NULL,
  atualizar_cadastro  TINYINT(1)         NULL,
  complemento         VARCHAR(1000)      NULL,

  -- Documento (conferência local + modelo de visão)
  documento_aceito    TINYINT(1)         NOT NULL DEFAULT 0,
  documento_motivo    VARCHAR(255)       NULL,
  tentativas_envio    TINYINT UNSIGNED   NOT NULL DEFAULT 0,
  arquivo_nome        VARCHAR(255)       NULL,
  arquivo_caminho     VARCHAR(500)       NULL,   -- caminho NO COMPUTADOR LOCAL
  arquivo_sha256      CHAR(64)           NULL,
  arquivo_mime        VARCHAR(100)       NULL,
  nitidez             DECIMAL(10,2)      NULL,
  tipo_detectado      ENUM('atestado_medico','declaracao_comparecimento','atestado_acompanhante','outro','nao_verificado') NULL,
  confianca_tipo      DECIMAL(4,3)       NULL,

  -- Dados lidos do documento pela IA (nunca diagnóstico ou CID)
  doc_nome            VARCHAR(120)       NULL,
  doc_data_inicio     DATE               NULL,
  doc_dias            SMALLINT UNSIGNED  NULL,
  doc_assinado        TINYINT(1)         NULL,

  -- Situação
  status              ENUM('em_atendimento','aguardando_rh','sem_pendencias','resolvido')
                      NOT NULL DEFAULT 'em_atendimento',
  observacoes         VARCHAR(1000)      NULL,
  criado_em           DATETIME           NOT NULL,
  chat_finalizado_em  DATETIME           NULL,
  resolvido_em        DATETIME           NULL,
  atualizado_em       DATETIME           NOT NULL,

  PRIMARY KEY (id),
  UNIQUE KEY uq_atestados_protocolo (protocolo),
  KEY ix_atestados_funcionario (funcionario_id, data_inicio),
  KEY ix_atestados_status (status),
  KEY ix_atestados_criado (criado_em),
  KEY ix_atestados_sha (arquivo_sha256),
  CONSTRAINT fk_atestados_funcionario FOREIGN KEY (funcionario_id)
    REFERENCES funcionarios (id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Alertas gerados pela conferência (um por código e atestado)
CREATE TABLE IF NOT EXISTS alertas (
  id                    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  atestado_id           INT UNSIGNED  NOT NULL,
  codigo                VARCHAR(4)    NOT NULL,   -- A1..A8, C1
  gravidade             ENUM('alta','media','baixa') NOT NULL,
  titulo                VARCHAR(160)  NOT NULL,
  descricao             VARCHAR(1000) NOT NULL,
  evidencia             TEXT          NULL,       -- JSON
  pergunta              VARCHAR(500)  NULL,       -- o que o agente pergunta ao colaborador
  resposta_colaborador  VARCHAR(1000) NULL,
  status                ENUM('aberto','confirmado','descartado') NOT NULL DEFAULT 'aberto',
  decidido_por          VARCHAR(60)   NULL,       -- 'rh:<nome>' ou 'agente'
  decisao_obs           VARCHAR(500)  NULL,
  criado_em             DATETIME      NOT NULL,
  decidido_em           DATETIME      NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_alertas_codigo (atestado_id, codigo),
  KEY ix_alertas_status (status),
  CONSTRAINT fk_alertas_atestado FOREIGN KEY (atestado_id)
    REFERENCES atestados (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- E-mails (simulados ou enviados)
CREATE TABLE IF NOT EXISTS notificacoes (
  id                 INT UNSIGNED  NOT NULL AUTO_INCREMENT,
  atestado_id        INT UNSIGNED  NULL,
  tipo               VARCHAR(40)   NOT NULL,      -- confirmacao, aviso_rh, andamento
  destinatario_tipo  ENUM('funcionario','rh') NOT NULL,
  destinatario       VARCHAR(160)  NOT NULL,
  assunto            VARCHAR(200)  NOT NULL,
  corpo              TEXT          NOT NULL,
  modo               ENUM('simulacao','smtp') NOT NULL,
  status             ENUM('simulado','enviado','falhou') NOT NULL,
  erro               VARCHAR(500)  NULL,
  criado_em          DATETIME      NOT NULL,
  PRIMARY KEY (id),
  KEY ix_notificacoes_criado (criado_em),
  CONSTRAINT fk_notificacoes_atestado FOREIGN KEY (atestado_id)
    REFERENCES atestados (id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Texto do chat (só com SALVAR_CONVERSA=1 no .env)
CREATE TABLE IF NOT EXISTS conversas (
  id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  atestado_id  INT UNSIGNED     NOT NULL,
  papel        ENUM('colaborador','agente') NOT NULL,
  conteudo     TEXT             NOT NULL,
  enviado_em   DATETIME         NOT NULL,
  PRIMARY KEY (id),
  KEY ix_conversas_atestado (atestado_id, enviado_em),
  CONSTRAINT fk_conversas_atestado FOREIGN KEY (atestado_id)
    REFERENCES atestados (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Trilha de auditoria: cada ação do agente e do RH
CREATE TABLE IF NOT EXISTS auditoria (
  id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT,
  atestado_id  INT UNSIGNED     NULL,
  ocorrido_em  DATETIME         NOT NULL,
  ator         VARCHAR(60)      NOT NULL,         -- 'agente', 'colaborador' ou 'rh:<nome>'
  evento       VARCHAR(50)      NOT NULL,
  codigo       VARCHAR(4)       NULL,             -- alerta relacionado, se houver
  detalhe      TEXT             NULL,             -- JSON
  PRIMARY KEY (id),
  KEY ix_auditoria_atestado (atestado_id, ocorrido_em),
  CONSTRAINT fk_auditoria_atestado FOREIGN KEY (atestado_id)
    REFERENCES atestados (id) ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

# Roteiro de demonstração

Gerado em 30/10/2026. As datas mudam se você rodar `python preparar_banco.py --recriar` outro dia.

No formulário, com MODO_DEMO=1, escolha o cenário e os campos são preenchidos sozinhos.

| ID | Funcionário | Tipo | Início | Término | Arquivo | O agente deve |
|---|---|---|---|---|---|---|
| FUNC001 | Ana Oliveira | Atestado médico | 22/10/2026 | 24/10/2026 | `FUNC001_ana_oliveira.pdf` | não alertar: Faltas no ponto batem com o atestado. Não deve haver alerta. |
| FUNC002 | Bruno Santos | Atestado médico | 16/10/2026 | 20/10/2026 | `FUNC002_bruno_santos.pdf` | A1: No 2º dia útil do afastamento há entrada e saída no ponto. |
| FUNC003 | Carla Ferreira | Atestado médico | 26/10/2026 | 27/10/2026 | `FUNC003_carla_ferreira.pdf` | A2: Os 2 dias úteis antes do início estão como falta, sem justificativa. |
| FUNC004 | Daniel Costa | Atestado médico | 14/10/2026 | 15/10/2026 | `FUNC004_daniel_costa.pdf` | A4: O mesmo arquivo e o mesmo período já estão registrados. |
| FUNC005 | Elisa Martins | Atestado médico | 19/10/2026 | 21/10/2026 | `FUNC005_elisa_martins.pdf` | A2, A3: O documento tem 5 dias; os 2 dias a mais aparecem como faltas no ponto. |
| FUNC006 | Felipe Almeida | Atestado médico | 23/10/2026 | 26/10/2026 | `FUNC006_felipe_almeida.pdf` | não alertar: Sexta a segunda: sábado e domingo são folga. Não deve haver alerta. |
| FUNC007 | Gabriela Rocha | Atestado médico | 21/10/2026 | 23/10/2026 | `FUNC007_gabriela_rocha.pdf` | não alertar: Entrada 08:00 e saída 10:20 no 1º dia (foi ao médico). Não é alerta. |
| FUNC008 | Henrique Lima | Declaração de comparecimento | 27/10/2026 | 27/10/2026 | `FUNC008_henrique_lima.pdf` | não alertar: Trabalhou de manhã e foi à consulta à tarde. Declaração cobre só horas. |
| FUNC009 | Isabela Ribeiro | Atestado médico | 08/10/2026 | 27/10/2026 | `FUNC009_isabela_ribeiro.pdf` | A5: Mais de 15 dias: a partir do 16º o caso vai para o INSS. |
| FUNC010 | João Pereira | Atestado médico | 23/10/2026 | 24/10/2026 | `FUNC010_joao_pereira.pdf` | A6: O nome no documento não é o do funcionário. |

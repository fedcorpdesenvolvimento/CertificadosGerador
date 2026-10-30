# Diário da equipe de agentes

Histórico compartilhado entre os agentes especializados (`.claude/agents/`): dev-backend, dev-frontend,
dba-firebird, analista-requisitos, analista-infra, analista-qa. Cada agente lê as últimas entradas antes de começar e
acrescenta a sua ao terminar. Entradas em ordem cronológica, nunca apagadas. Decisões de negócio continuam
indo para `docs/ESPECIFICACAO.md` (Anexo B); aqui fica o "quem fez o quê, como e o que ficou pendente".

Formato:

```
## AAAA-MM-DD — <papel> — <tarefa em uma linha>
- Contexto recebido: ...
- Feito: ...
- Verificado: pytest/ruff/navegador/banco ...
- Arquivos: ...
- Pendente / para quem: ...
```

---

## 2026-10-29 — orquestrador — criação da equipe
- Contexto recebido: o usuário pediu agentes independentes por especialidade, com histórico preservado entre eles.
- Feito: definições em `.claude/agents/` (5 papéis) e este diário como memória compartilhada.
- Estado do projeto nesta data: ADR-09 em homologação com o W2BIT (chave de transição `CERTGEN_API_KEY` em uso
  no Render até existir disco persistente ou a Digital Ocean); RN-03 revista (15008 = RESIDENCIAL 0001); GAP-27
  (emissão assíncrona) e GAP-28 (Check-up Lar e texto da 14008; PLANO da 14008 = COM) abertos; homologação da tela
  (RF-05b/05c/06a) entregue em a87755e.
- Pendente / para quem: disco `/data` no Render ou semente de chave por ambiente (analista-infra + dev-backend)
  quando o usuário decidir; GAP-28 aguarda dados do usuário (analista-requisitos registra).

## 2026-10-29 — orquestrador — analista-qa acrescentado
- Contexto recebido: o usuário apontou que faltava um analista de QA para realizar os testes.
- Feito: `.claude/agents/analista-qa.md`. Regra: QA prova e encontra defeitos; não corrige código de produção,
  devolve ao dono da área com passos de reprodução. Toda entrega passa pelo QA antes de ser dada como pronta.
- Pendente / para quem: nada.

## 2026-10-30 — dba-firebird — base de testes da API /v1 para o integrador do portal (W2BIT)
- Contexto recebido: escolher um segurado real por apólice (4008, 5008, 9008, 10008, 13008, 14008, 15008, 6008, 7008),
  mais um segundo caso 15008/0000000019, um CNPJ e a confirmação do caso conhecido 33016330725/0000001192/13008/380819,
  para `POST /v1/segurados/verificar` e `POST /v1/certificados/emitir`. Chave de transição no Render aceita qualquer administradora.
- Feito: script somente leitura no scratchpad (`base_testes_portal.py`, via `conexao.conectar()`, bind parameters, filtros
  RD-02/RD-19). Critério: inicio_vig em 2026 (mais recente primeiro), final_vig <> 30/12/1899, nome/endereço/cidade preenchidos,
  `pessoas.possui_portal = 'S'` preferido (QRY-01). Todas as 9 apólices têm caso com portal; 14008 e 9008 têm também
  administradoras sem portal. Relatório em texto entregue ao orquestrador para montar o arquivo do cliente.
- Verificado: banco (FATURA.GDB, leitura). Achados de dados sujos: 4008 tem 197 e 5008 tem 62 linhas não canceladas com
  inicio_vig no ano 2201 (digitação; descartadas com BETWEEN 2026-01-01 e 2026-12-31); 15008 tem 4.084 e 5008 tem 248 linhas de
  2026 com final_vig nulo ou 30/12/1899 (DEF-06 continua presente no legado). Caso conhecido confirmado: status_seg = 'R'
  (não cancelado), 42 linhas não canceladas = 21 faturas x 2 certificados (AP.602 e CASA17L) — o /verificar devolve as 3 mais
  recentes, portanto 2 unidades da fatura 382196 (10/2026) + 1 da 381675 (09/2026).
- Arquivos: `docs/equipe/DIARIO.md` (esta entrada). Nada no repositório além disso; sem commit.
- Pendente / para quem: orquestrador monta o documento para o W2BIT; QA pode usar os mesmos casos para o roteiro de
  `docs/TESTE-API-POSTMAN.md`. Linhas com inicio_vig em 2201 merecem registro em dados sujos (analista-requisitos, seção 13).

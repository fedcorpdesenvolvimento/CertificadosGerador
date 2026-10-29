# Diário da equipe de agentes

Histórico compartilhado entre os agentes especializados (`.claude/agents/`): dev-backend, dev-frontend,
dba-firebird, analista-requisitos, analista-infra. Cada agente lê as últimas entradas antes de começar e
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

# Especificação — Gerador de Certificados (SDD)

**Projeto:** Gerador de Certificados de Seguro Incêndio / Conteúdo
**Local do sistema novo:** `U:\--2021\05-Gerador Certificados`
**Stack alvo:** Python 3.12 · FastAPI · Jinja2 · Playwright · Firebird
**Documento:** v0.2 — 2026-09-03
**Status:** `DRAFT` — legado analisado, banco inspecionado em 03/09/2026; 13 lacunas fechadas; abertos: `GAP-10`, `GAP-11`, `GAP-12`, `GAP-14`, `GAP-19` (erros de digitação), `GAP-21`/`GAP-22` (módulos Prestamista e Vida); `RN-28` aguarda os arquivos `hdi.png` e `porto.png`

### Fontes analisados

| Arquivo | Tamanho | Data |
|---|---|---|
| `UfrmImprimeCertInc.pas` | 72.911 bytes, 1.678 linhas | 18/07/2025 |
| `UfrmImprimeCertInc.dfm` | 70.529.970 bytes | 17/07/2025 |
| `0_33016330725_0004_13008_380819.pdf` | 162.826 bytes | 03/09/2026 |
| `0_05554363733__15008_381066.pdf` | 93.543 bytes | 03/09/2026 |
| `0_14529138704__15008_381066.pdf` | 93.516 bytes | 03/09/2026 |

Todas as referências de linha neste documento apontam para `UfrmImprimeCertInc.pas`. Referências a `.dfm` indicam propriedades de design-time.

---

## 0. Como ler este documento

Documento de **Specification-Driven Design**: a especificação é o artefato primário, o código é derivado dela. Todo item normativo tem identificador estável e rastreabilidade até o legado.

| Prefixo | Significado | Verificação |
|---|---|---|
| `RF-nn` | Requisito Funcional | Teste de aceitação |
| `RN-nn` | Regra de Negócio | Teste unitário |
| `RD-nn` | Requisito de Dados | Teste de contrato / schema |
| `RNF-nn` | Requisito Não-Funcional | Medição ou inspeção |
| `QRY-nn` | Consulta especificada | Teste de integração |
| `ADR-nn` | Decisão arquitetural | Revisão |
| `GAP-nn` | Lacuna que bloqueia implementação | Fechamento explícito |
| `DEF-nn` | Defeito identificado no legado | Decisão: corrigir ou preservar |
| `SEC-nn` | Achado de segurança | Ação imediata |

Convenção normativa: DEVE / NÃO DEVE / PODE conforme RFC 2119.

**Regra de ouro:** nenhum `GAP-nn` aberto pode ser implementado por suposição.

**Sobre os `DEF-nn`:** o legado está em produção. Cada defeito exige decisão consciente entre *corrigir* (o novo sistema produz saída diferente do atual, o que precisa de aval do negócio) e *preservar* (o novo sistema replica o comportamento, inclusive o errado, para compatibilidade). A seção 13 registra a decisão de cada um. **NÃO DEVE** haver defeito sem decisão.

---

## 1. Contexto

### 1.1 O que o legado faz

`Tfrm_imprimecertinc` é uma tela Delphi VCL que emite certificados de seguro incêndio a partir de um banco Firebird, via FastReport, e faz muito mais que imprimir:

```
                    ┌──────────────────────────────────┐
                    │   Firebird  (DataModule1.         │
                    │             SQLCON_FAT)           │
                    └────────────┬─────────────────────┘
                                 │  7 variantes da mesma SELECT
                    ┌────────────▼─────────────────────┐
                    │  Tfrm_imprimecertinc              │
                    │                                   │
                    │  [Imprime]        [Imprime/Geral] │
                    │   fluxo manual     fluxo em massa │
                    └────┬───────────────────┬──────────┘
                         │                   │
         ┌───────────────┼───────────────────┼────────────────┐
         ▼               ▼                   ▼                ▼
   ┌──────────┐   ┌─────────────┐    ┌──────────────┐  ┌────────────┐
   │ 5 .fr3   │   │ UPDATE      │    │ upload S3    │  │ XML + SMTP │
   │ → PDF    │   │ SEGURADOS_  │    │ via java     │  │ (Porto)    │
   │          │   │ INC         │    │ fedcorp.jar  │  │            │
   └──────────┘   └─────────────┘    └──────────────┘  └────────────┘
```

Isso é relevante porque **o gerador não é um leitor passivo do banco**: ele grava. Ver `RD-20` e `RNF-05`.

### 1.2 Objetivo do sistema novo

Reescrever o gerador em Python preservando o fluxo operacional, e adicionar o requisito novo: **para cada certificado emitido, produzir também um JSON com exatamente as informações impressas no PDF.**

O JSON é o entregável estratégico — transforma o certificado de documento opaco em dado estruturado, auditável e integrável.

### 1.3 Escopo

| Dentro | Fora desta versão | Justificativa |
|---|---|---|
| Tela web local de emissão | Autenticação / perfis | O legado não tem |
| Conexão local ao Firebird | — | Fase 1 |
| Geração de PDF | Reimplementar os 5 `.fr3` como 5 templates | `ADR-05`: um template condicional |
| Geração de JSON espelhado | — | Requisito novo |
| Emissão manual por fatura | Emissão em massa (`Imprime/Geral`) | Fase 6, ver 14 |
| Gravação de `link_certificado_aws` | Upload S3 e XML/SMTP para a Porto | Fase 7, ver 14 |
| Porta para futura API | Servidor da API | Fase 5 |

### 1.4 Princípio de faseamento (local → API)

A origem dos dados é decisão de infraestrutura, não de domínio. Fase 1 lê Firebird; fase 5 lê API. Domínio, template e serializador **NÃO DEVEM** mudar. Garantido pela arquitetura de portas da seção 10 (`ADR-01`).

---

## 2. Glossário do domínio

| Termo | Campo no banco | Definição |
|---|---|---|
| **Administradora** | `pessoas.pessoa` / `.nome` / `.abrev` | Imobiliária ou administradora de condomínios. Primeiro filtro de toda emissão. Código é `CHAR(10)` zero-padded (`'0000004691'`). |
| **Apólice** | `segurados_inc.apolice` | Contrato-mestre, código string (`'13008'`). Determina o produto (`RN-03`). |
| **Sequência** | `segurados_inc.seq` | Inteiro que versiona a apólice. A chave é o par `(apolice, seq)`. |
| **Fatura** | `segurados_inc.fatura` (INTEGER) | Lote de cobrança. **Também é o `sequencial` do endosso** (`RN-16`). |
| **Segurado** | `segurados_inc.nome` | Coberto. No certificado aparece como *BENEFICIÁRIO*. |
| **Certificado** | `segurados_inc.certificado` | String de adesão individual. **Contém `/`, `.` e espaços** (`'CF1DI/AP.602'`, `'3082/01/AP 1302'`) — ver `RN-17`. |
| **Código do pedido no portal** | `segurados_inc.codigo_pedido_port` | Inteiro, frequentemente nulo. Identificador na Porto Seguro. Ver `GAP-11`. |
| **Produto** | derivado da apólice (`RN-03`) | Modalidade. Catálogo de 7 em `RN-03.3`. |
| **Vigência** | `inicio_vig`, `final_vig` | Período de cobertura, tipicamente mensal. |
| **Endosso** | `segurados_inc.endosso` → `endossos.endosso` | Alteração contratual. |
| **Categoria do endosso** | `endossos.cod_cat` | `'3'` ou `'4'` ⇒ apólice de locação (`RN-04`). |
| **Assistência Mondial** | `endossos.codigo_assist_mondial` | `'1003'` ⇒ produto inclui *Faz Tudo Lar* (`RN-18`). |
| **Faturamento** | tabela `faturas` | Cabeçalho do lote: `dt_ini_vig`, `data_fat`, `status`, `seguradora`. |
| **Competência** | derivada de `inicio_vig` | `MMYYYY` — usada no caminho do S3 (`RN-19`). |
| **Controle de envio** | `segurados_inc.id_controle_envio_portal` | Agrupador do lote enviado à Porto, de um generator. |
| **Importância segurada (IS)** | ver 4.4 | Valor máximo indenizável por cobertura. |
| **Prêmio** | `segurados_inc.premio` | Valor pago. Impresso só se *Imprime Premio* marcado (`RF-10`). |
| **Processo SUSEP** | `apolice_seguradora.proc_susep` | Número do processo regulatório. Obrigatório no documento. |
| **COD_0800** | `certificado \|\| ' ' \|\| pessoas.abrev` | Código informado na central de atendimento. Confirmado empiricamente (`RN-20`). |

---

## 3. Atores e casos de uso

### 3.1 Ator: Operador de emissão

Backoffice, emite por fatura. Conhece a tela atual. **A tela nova DEVE ser reconhecível** — mesma ordem, mesmos rótulos, mesma cascata.

### 3.2 Os dois fluxos do legado

O legado tem **dois botões de emissão com regras diferentes**, e essa é a descoberta estrutural mais importante da análise. Não é uma tela, são duas rotinas que compartilham controles.

| | `[Imprime]` — Button1 (linha 156) | `[Imprime/Geral]` — Button4 (linha 624) |
|---|---|---|
| Escopo | Uma fatura escolhida na tela | Todas as faturas com `status='A'` que casem com as datas |
| Driver | `CheckListBox1` (seleção do operador) | Tabela `faturas` (`QRY-07`) |
| Consulta de listagem | `QRY-05a` (SQLQuery1) | `QRY-05b` (SQLQuery7) |
| Consulta de emissão | `QRY-06` (SQLQuery3) — exige `cpf` **e** `portal` | `QRY-09` (SQLQuery5) — só `cert` |

> **`QRY-05a`** e **`QRY-05b`** são os dois nomes das variantes divergentes da consulta de listagem no legado, unificadas em `QRY-05` (seção 6.5). A numeração salta de `QRY-07` para `QRY-09` por isso.
| Mapa de produto | 5 apólices (linha 1221) | 9 apólices + exceção por administradora (linha 776) |
| Nome do arquivo | 5 campos (`RN-11a`) | 6 campos (`RN-11b`) |
| Pasta | `DirectoryEdit1` | `{raiz}\{administradora}\{competência}` |
| Grava `id_controle_envio_portal` | Não | Sim |
| Data de emissão (`DateEdit2`) | Ignorada | Filtra `faturas.data_fat` |
| XML | `GeraXML` (uma fatura) | `GeraXMLGeral` (o lote) |

**`RF-11`** — O sistema novo **DEVE** implementar os dois fluxos como **um único caso de uso parametrizado**, não como duas rotinas. A divergência de comportamento entre eles é a origem de `DEF-03`, `DEF-04` e `DEF-09`.

### 3.3 Casos de uso

| ID | Caso de uso | Fluxo legado | Prioridade |
|---|---|---|---|
| `UC-01` | Emitir todos os certificados de uma fatura | Imprime | Must |
| `UC-02` | Emitir seleção parcial de segurados | Imprime | Must |
| `UC-03` | Emitir em arquivos individuais | Imprime + *Individuais* | Must |
| `UC-04` | Pré-visualizar lote consolidado | Imprime sem *Individuais* | Should |
| `UC-05` | Obter o JSON de cada certificado | **novo** | Must |
| `UC-06` | Conferir os dados antes de imprimir | Busca Segurados | Should |
| `UC-07` | Reemitir certificado já emitido | Imprime | Should |
| `UC-08` | Emitir em massa por competência | Imprime/Geral | Fase 6 |
| `UC-09` | Publicar certificado no S3 e gravar o link | ambos | Fase 7 |
| `UC-10` | Gerar XML de envio à Porto | ambos | Fase 7 |
| `UC-11` | Emitir consumindo API em vez de Firebird | — | Fase 5 |

---

## 4. Modelo de domínio e dicionário de dados

### 4.1 Tabelas

Modelo **observado** nas 9 consultas do legado. Sem acesso ao DDL — tipos vêm dos `TField` do `.dfm` e das inferências marcadas. Ver `GAP-03`.

```
┌────────────────────────────┐        ┌──────────────────────────────┐
│         pessoas            │        │          faturas             │
│ pessoa          CHAR(10) PK│        │ administradora               │
│ nome            VARCHAR    │◄───────┤ apolice                      │
│ abrev           VARCHAR    │        │ seq                          │
│ status          CHAR       │        │ fatura            (= endosso.│
│ possui_portal   CHAR('S')  │        │                    sequencial)│
└────────────┬───────────────┘        │ seguradora                   │
             │ pessoa =               │ dt_ini_vig        DATE       │
             │ administradora         │ data_fat          DATE       │
             │                        │ status            CHAR('A')  │
             │                        └──────────┬───────────────────┘
             │                                   │ fatura = sequencial
             │            ┌──────────────────────▼───────────────────┐
             │            │              endossos                    │
             │            │ endosso                    PK            │
             │            │ sequencial        (= fatura)             │
             │            │ cod_cat           '3','4' ⇒ locação      │
             │            │ codigo_assist_mondial '1003' ⇒ Faz Tudo  │
             │            │ cob_especiais                            │
             │            └──────────────┬───────────────────────────┘
             │                           │ endosso
┌────────────▼───────────────────────────▼───────────────────────────┐
│                        segurados_inc                               │
│ administradora        apolice          seq          fatura   INT   │
│ certificado  VARCHAR (contém / . espaço)                           │
│ cpf_cnpj     VARCHAR (com e sem máscara — DEF-08)                  │
│ codigo_pedido_port    INTEGER, nullable                            │
│ nome  nome_cond  endereco  unidade  cep  uf  cidade  bairro        │
│ inicio_vig  final_vig   DATE (final_vig pode ser 0 — DEF-06)       │
│ inc_conteudo  inc_predio  aluguel  premio   NUMERIC                │
│ endosso   cod_seguradora   status_seg ('C' = cancelado)            │
│ link_certificado_aws  dt_cria_link  id_controle_envio_portal       │
└──────┬──────────────────────────────────────────┬──────────────────┘
       │ apolice + cod_seguradora                 │ fatura + certificado
┌──────▼─────────────────────┐   ┌────────────────▼──────────────────┐
│   apolice_seguradora       │   │     segurados_inc_cob_aux         │
│ apolice                    │   │ fatura        certificado         │
│ cod_seguradora             │   │ quebra_vidro  rc  danos_eletricos │
│ apolice_seguradora VARCHAR │   │ linha_branca (STRING! — DEF-11)   │
│ proc_susep         VARCHAR │   │ resp_civil  rup_encanamento       │
└────────────────────────────┘   │ rup_enc_ter  acidente_pessoal     │
                                 └───────────────────────────────────┘
```

**`RD-01`** — A chave de identidade de um certificado é `(administradora, apolice, seq, fatura, certificado)`. **`codigo_pedido_port` NÃO DEVE** fazer parte da identidade — ver `GAP-11` e `DEF-04`.

**`RD-02`** — Todo acesso a `segurados_inc` **DEVE** filtrar `status_seg <> 'C'`.

**`RD-03`** — Todo acesso a `pessoas` para listar administradoras **DEVE** filtrar `status <> 'C'` (linha 1279).

**`RD-19`** — `segurados_inc.cpf_cnpj <> ''` é filtro presente em `QRY-05b`, `QRY-09` e `QRY-10`, mas **ausente** em `QRY-05a` e `QRY-06`. O sistema novo **DEVE** aplicá-lo em todas: um segurado sem documento não pode gerar certificado. Ver `DEF-03`.

**`RD-20`** — O sistema **escreve** em `segurados_inc`: `link_certificado_aws`, `dt_cria_link` e `id_controle_envio_portal` (linhas 351-362, 1074-1085). Isso invalida qualquer premissa de acesso read-only. Ver `RNF-05`.

### 4.2 Tipos confirmados pelos `TField` do `.dfm`

Os `TField` persistidos no `ClientDataSet1` são a melhor fonte de tipo disponível sem o DDL:

| Campo | `TField` | Consequência |
|---|---|---|
| `FATURA` | `TIntegerField` | Fatura é **inteiro**, não string — concatenada sem quotes no SQL |
| `SEQ` | `TIntegerField` | Inteiro |
| `CODIGO_PEDIDO_PORT` | `TIntegerField` | Inteiro nullable |
| `CERTIFICADO` | `TStringField` | String com caracteres especiais |
| `ENDOSSO` | `TStringField` | **String**, apesar do nome sugerir número |
| `INICIO_VIG` / `FINAL_VIG` | `TDateField` | Data |
| `INC_CONTEUDO`, `INC_PREDIO`, `ALUGUEL`, `PREMIO`, `COB_INCENDIO` | `TFMTBCDField` | Decimal exato — reforça `RD-05` |
| `QUEBRA_VIDRO`, `RC`, `DANOS_ELETRICOS`, `RESP_CIVIL`, `RUP_ENCANAMENTO`, `RUP_ENC_TER`, `ACIDENTE_PESSOAL` | `TFMTBCDField` | Decimal |
| `LINHA_BRANCA` | **`TStringField`** | Anomalia — ver `DEF-11` |

**`RD-05`** — Valores monetários **DEVEM** ser `decimal.Decimal` em Python e serializados em JSON como **string decimal** (`"150000.00"`), nunca `float`. O legado já usa BCD; regredir para binário seria piorar.

**`RD-06`** — Datas **DEVEM** ser `datetime.date`, ISO 8601 no JSON e `DD/MM/YYYY` no PDF. Nenhuma data trafega como string em formato local dentro do sistema (`DEF-01`).

### 4.3 Dicionário de dados do certificado

Projeção comum às consultas `QRY-05a`, `QRY-05b`, `QRY-06`, `QRY-09` e `QRY-10` — **idêntica em todas as cinco**. Coluna *PDF* traz o rótulo real observado nos PDFs de referência.

| # | Expressão SQL | Alias | Rótulo no PDF | JSON |
|---|---|---|---|---|
| 1 | `pes.nome` | `NOME_ADM` | CO-ESTIPULANTE | `administradora.nome` |
| 2 | `ss.endosso` | `ENDOSSO` | — | `contrato.endosso` |
| 3 | `ss.apolice` | `APOLICE` | **CONTRATO** | `contrato.apolice.codigo` |
| 4 | `ss.seq` | `SEQ` | — | `contrato.apolice.seq` |
| 5 | `ss.fatura` | `FATURA` | — | `contrato.fatura` |
| 6 | `ss.nome` | `BENEFICIARIO` | BENEFICIÁRIO | `segurado.nome` |
| 7 | `ss.codigo_pedido_port` | `CODIGO_PEDIDO_PORT` | — (só no nome do arquivo) | `contrato.codigo_pedido_porto` |
| 8 | `ss.cpf_cnpj` | `DOCUMENTO_SEG` | CPF | `segurado.documento.numero` |
| 9 | `ss.inicio_vig` | `INICIO_VIG` | VIGÊNCIA (1ª data) | `vigencia.inicio` |
| 10 | `ss.final_vig` | `FINAL_VIG` | VIGÊNCIA (2ª data) | `vigencia.fim` |
| 11 | `ss.endereco` | `ENDERECO` | ENDEREÇO | `local_risco.endereco` |
| 12 | `ss.unidade` | `UNIDADE` | UNIDADE SEGURADA | `local_risco.unidade` |
| 13 | `ss.cep` | `CEP` | CEP | `local_risco.cep` |
| 14 | `ss.uf` | `UF` | UF | `local_risco.uf` |
| 15 | `ss.cidade` | `CIDADE` | CIDADE | `local_risco.cidade` |
| 16 | `ss.bairro` | `BAIRRO` | BAIRRO | `local_risco.bairro` |
| 17 | `aps.apolice_seguradora` | `APOLICE_SEGURADORA` | **APÓLICE** | `contrato.apolice.numero_seguradora` |
| 18 | `aps.proc_susep` | `PROC_SUSEP` | PROCESSO SUSEP Nº | `contrato.processo_susep` |
| 19 | `ss.certificado` | `CERTIFICADO` | CERTIFICADO | `certificado.numero` |
| 20 | `ss.inc_conteudo` | `INC_CONTEUDO` | — | `coberturas[]` |
| 21 | `ss.inc_predio` | `INC_PREDIO` | — | `coberturas[]` |
| 22 | `ss.aluguel` | `ALUGUEL` | COBERTURA PERDA DE ALUGUEL | `coberturas[]` |
| 23 | `(inc_conteudo + inc_predio)` | `COB_INCENDIO` | COBERTURA INCÊNDIO | `coberturas[]` |
| 24 | `ss.premio` | `PREMIO` | PREMIO | `premio.valor_total` |
| 25 | `en.codigo_assist_mondial` | `CODIGO_ASSIST_MONDIAL` | — (decide o template) | `assistencia.codigo_mondial` |
| 26 | `ss.nome_cond` | `NOME_COND` | CONDOMÍNIO | `local_risco.condominio` |
| 27 | `certificado \|\| ' ' \|\| pes.abrev` | `COD_0800` | *"favor informar o código"* | `certificado.cod_0800` |
| 28 | `sicb.quebra_vidro` | `QUEBRA_VIDRO` | — | `coberturas[]` |
| 29 | `sicb.rc` | `RC` | COBERTURA RC | `coberturas[]` |
| 30 | `sicb.danos_eletricos` | `DANOS_ELETRICOS` | — | `coberturas[]` |
| 31 | ~~`sicb.linha_branca`~~ | ~~`LINHA_BRANCA`~~ | — | *removido — `GAP-16`* |
| 32 | `sicb.resp_civil` | `RESP_CIVIL` | — | `coberturas[]` |
| 33 | `sicb.rup_encanamento` | `RUP_ENCANAMENTO` | COBERTURA RUPTURA DE ENCANAMENTO | `coberturas[]` |
| 34 | `sicb.rup_enc_ter` | `RUP_ENC_TER` | — | `coberturas[]` |
| 35 | `sicb.acidente_pessoal` | `ACIDENTE_PESSOAL` | — | `coberturas[]` |

**`RN-20` — `COD_0800` confirmado empiricamente.** No PDF `..._15008_381066` o campo traz `3082/01/AP 1302 19PAEL`: certificado `3082/01/AP 1302` + espaço + `abrev` `19PAEL`. No PDF `..._13008_380819` traz apenas `CF1DI/AP.602`, sem sufixo — a administradora IMODATA tem `abrev` nula ou vazia. O sistema novo **DEVE** recompor o código na aplicação e **DEVE** registrar aviso quando `abrev` estiver ausente, porque o código impresso fica incompleto e o segurado não consegue se identificar na central.

**`RD-04`** — `ss.cod_seguradora` participa do `JOIN` com `apolice_seguradora` mas **não é projetado** em nenhuma das consultas do legado. O sistema novo **DEVE** projetá-lo: identifica a seguradora emissora e é dado obrigatório do certificado.

**`RD-08`** — `pes.abrev` **DEVE** ser projetada, para validar o `COD_0800` recomposto contra o valor do banco.

### 4.4 Catálogo de coberturas

**`RN-01`** — Catálogo fechado e ordenado de **11** coberturas. *(Eram 12 na v0.2; `LINHA_BRANCA` saiu em 03/09/2026 — é flag `S`/`N`, não valor, e o negócio decidiu que não é necessária nesta fase. Ver `GAP-16`.)* O PDF **DEVE** omitir as de IS nula ou zero; o JSON **DEVE** declará-las com `contratada: false`.

| # | Código | Nome no certificado | Origem | Visto nos PDFs |
|---|---|---|---|---|
| 1 | `INC_PREDIO` | Incêndio — Prédio | `segurados_inc.inc_predio` | — |
| 2 | `INC_CONTEUDO` | Incêndio — Conteúdo | `segurados_inc.inc_conteudo` | — |
| 3 | `COB_INCENDIO` | Cobertura Incêndio | derivada (`RN-02`) | ✓ ambos |
| 4 | `ALUGUEL` | Cobertura Perda de Aluguel | `segurados_inc.aluguel` | ✓ ambos |
| 5 | `RUP_ENCANAMENTO` | Cobertura Ruptura de Encanamento | `sicb.rup_encanamento` | ✓ 13008 |
| 6 | `RC` | Cobertura RC | `sicb.rc` | ✓ 13008 |
| 7 | `RUP_ENC_TER` | Ruptura de Encanamento — Terceiros | `sicb.rup_enc_ter` | — |
| 8 | `RESP_CIVIL` | Responsabilidade Civil | `sicb.resp_civil` | — |
| 9 | `DANOS_ELETRICOS` | Danos Elétricos | `sicb.danos_eletricos` | — |
| 10 | `QUEBRA_VIDRO` | Quebra de Vidros | `sicb.quebra_vidro` | — |
| 11 | `ACIDENTE_PESSOAL` | Acidentes Pessoais | `sicb.acidente_pessoal` | — |

**`RN-02`** — `COB_INCENDIO = COALESCE(inc_conteudo,0) + COALESCE(inc_predio,0)`, em `Decimal`. **DEVE** ser recalculada na aplicação e comparada com o valor do banco; divergência gera aviso. Ver `DEF-05`, que é o defeito mais grave do levantamento.

> **`GAP-10`** — `rc` e `resp_civil` são colunas distintas, e o PDF de referência imprime "COBERTURA RC" ao lado do texto legal *"RESPONSABILIDADE CIVIL TERCEIROS"*, o que sugere que `rc` = RC a terceiros e `resp_civil` = outra modalidade (familiar? do condomínio?). Igualmente, `rup_encanamento` vs `rup_enc_ter`. **DEVE** ser confirmado nos rótulos dos `.fr3`.

---
## 5. Especificação da tela

### 5.1 Controles do legado — inventário completo

Extraído do `.dfm`. A coluna *Legenda* traz a legenda literal, que o sistema novo **DEVE** preservar (`RF-12`).

| Controle | Legenda | Tipo | Papel | Default |
|---|---|---|---|---|
| `ComboBox1` | Administradora | combo | `QRY-01`, exibe `pessoas.nome` | vazio |
| `Edit1` | *(sem legenda)* | edit | código da administradora, resolvido por `QRY-02` | vazio |
| `DateEdit1` | Vigência | date | início de vigência | vazio |
| `DateEdit2` | **Emissão:** | date | data de faturamento — **só no fluxo em massa** | vazio |
| `ComboBox2` | Apólice | combo | `QRY-03`, formato `apolice.seq` | vazio |
| `ComboBox3` | Fatura | combo | `QRY-04` | vazio |
| `ComboBox4` | Produto | combo | 5 itens fixos, `ItemIndex` derivado | `-1` |
| `CheckBox1` | **Imprime Premio** | check | mostra o bloco de prêmio | `false` |
| `CheckBox2` | **Individuais** | check | um PDF por segurado vs. pré-visualização | **`true`** |
| `CheckBox3` | **Upload AWS** | check | **nunca lido** — `DEF-07` | `true` |
| `CheckBox4` | **Faz Tudo Lar** | check | derivado de `codigo_assist_mondial` | `false` |
| `CheckBox5` | **Locação** | check | derivado de `endossos.cod_cat` | `false` |
| `CheckBox6` | **Só XML de Cert.** | check | pula a geração de PDF | `false` |
| `CheckListBox1` | — | lista | segurados, todos marcados ao carregar | — |
| `RxSwitch1` | — | switch | marcar / desmarcar todos | — |
| `Edit2` | — | edit | contador `Seg.:N` | — |
| `DirectoryEdit1` | — | path | pasta de destino; na tela nova o botão **Procurar…** abre a janela nativa do Windows (o servidor roda na máquina do operador, `RNF-10`) | `D:\Temporario\CERTINC` |
| `SpeedButton1` | **Busca Segurados** | botão | carrega o `CheckListBox` | — |
| `Button1` | **&Imprime** | botão | fluxo manual | — |
| `Button4` | **Imprime/&Geral** | botão | fluxo em massa | — |
| `Button2` | *(limpar)* | botão | reseta a tela | — |
| `Button3` | *(fechar)* | botão | fecha | — |
| `ProgressBar1` | — | progresso | contagem de emitidos | — |

**`RF-12`** — As legendas acima **DEVEM** ser preservadas literalmente na tela nova, incluindo *Imprime Premio* e *Só XML de Cert.*. Renomear controles que o operador usa diariamente é custo sem benefício.

**`RF-13`** — `ComboBox4` (Produto) e `CheckBox5` (Locação) são **derivados**, nunca entrada. *(`CheckBox4` Faz Tudo Lar passou a ser entrada pré-preenchida em 03/09/2026 — ver `RF-13a` em `ADR-06`.)* Na tela nova **DEVEM** ser exibidos como somente-leitura, deixando visível a derivação. No legado são editáveis, o que permite ao operador contradizer a regra sem aviso.

### 5.2 Máquina de estados da cascata

```
  ┌──────────────────────────────────────────────────────────────┐
  │ S0  VAZIO                              habilita: Administra- │
  │                                        dora, Vigência,       │
  │                                        Emissão               │
  └───────────────────────┬──────────────────────────────────────┘
                          │ escolhe administradora → QRY-02 resolve o código
                          ▼                          QRY-03 carrega apólices
  ┌──────────────────────────────────────────────────────────────┐
  │ S1  ADM_OK                             habilita: Apólice     │
  └───────────────────────┬──────────────────────────────────────┘
                          │ escolhe apólice → RN-03 deriva Produto
                          ▼                  QRY-04 carrega faturas
  ┌──────────────────────────────────────────────────────────────┐
  │ S2  APOLICE_OK                         habilita: Fatura      │
  └───────────────────────┬──────────────────────────────────────┘
                          │ escolhe fatura
                          ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ S3  FATURA_OK                          habilita: Busca       │
  │                                        Segurados             │
  └───────────────────────┬──────────────────────────────────────┘
                          │ Busca Segurados → QRY-05 lista
                          │                   QRY-11 deriva Faz Tudo / Locação
                          ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ S4  SEGURADOS_OK   todos marcados      habilita: destino,    │
  │                                        opções, Imprime       │
  └───────────────────────┬──────────────────────────────────────┘
                          │ Imprime → QRY-06 por certificado
                          ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ S5  EMITINDO  →  S6  CONCLUIDO  (relatório emitidos/falhas)  │
  └──────────────────────────────────────────────────────────────┘
```

**`RF-01`** — Alterar um campo da cascata **DEVE** limpar e desabilitar os posteriores e descartar as seleções. No legado a cascata é montada em eventos `OnExit` independentes, sem invalidação: mudar a apólice depois de buscar os segurados deixa a lista obsoleta na tela e a emissão usa a apólice nova com certificados da antiga. Ver `DEF-02`.

**`RF-02`** — **Imprime** **DEVE** permanecer desabilitado fora de `S4`.

**`RN-05`** — Relação entre as duas datas, agora confirmada no código:

- `DateEdit1` (Vigência) filtra `segurados_inc.inicio_vig` em `QRY-03` e `QRY-04`, e `faturas.dt_ini_vig` em `QRY-07`. Também define a **competência** (`RN-19`).
- `DateEdit2` (Emissão) filtra **apenas** `faturas.data_fat`, e **apenas** no fluxo em massa (linha 707).
- O fluxo em massa exige ao menos uma das duas preenchida (linha 670); o manual não exige nenhuma.

O sistema novo **DEVE** rotular os campos conforme o efeito real: *Vigência* filtra os segurados; *Emissão* filtra o faturamento. **`GAP-04` fechado.**

**`RN-05a`** *(decisão do usuário, 04/09/2026)* — No fluxo manual, o campo **Emissão:** passa a ser um filtro **adicional e opcional** nas listas de apólices (`QRY-03`) e de faturas (`QRY-04`): quando preenchido, só entram as faturas cuja **data de emissão** (`faturas.data_fat`) é igual à informada, via `EXISTS` em `faturas` pela chave `(fatura, administradora, apolice, seq)`. *Vigência* continua filtrando `segurados_inc.inicio_vig`; os dois podem ser combinados. Nenhum dos dois é obrigatório. Isto revisa a parte de `RN-05` que restringia *Emissão* ao fluxo em massa.

> A **DATA DE EMISSÃO impressa no PDF** é outra coisa: os três PDFs de referência trazem `03/09/2026`, a data em que foram gerados, não o conteúdo de `DateEdit2`. É a data corrente no momento da emissão. Ver `RN-21`.

**`RN-21`** — O campo *DATA DE EMISSÃO* do PDF **DEVE** ser a data de geração do documento (`date.today()`), não um campo do banco nem `DateEdit2`. Consequência: reemitir um certificado produz PDF diferente do original. **DEVE** constar no JSON como `_meta.gerado_em` e como `certificado.data_emissao`, para que a diferença seja rastreável (relacionado a `RNF-08`).

### 5.3 Ações auxiliares

**`RF-04`** — A lista **DEVE** oferecer marcar/desmarcar todos (`RxSwitch1`) e exibir o contador (`Edit2`, formato `Seg.:N`).

**`RF-14`** — Ao carregar, **todos** os segurados **DEVEM** vir marcados (linhas 1332 e 940). O caso comum é emitir a fatura inteira.

**`RF-05`** — Cada item **DEVE** exibir certificado, código do portal, documento, nome, endereço e unidade. O legado codifica isso numa string com delimitadores e depois a reparseia:

```pascal
linha := CERTIFICADO + ' [' + IntToStr(codigo_pedido_port) + '] '
       + DOCUMENTO_SEG + ' | ' + BENEFICIARIO + '  ' + ENDERECO + '  ' + UNIDADE ;
```
```pascal
pos    := BuscaDireita('[', item);   cert   := copy(item, 1, pos-1) ;
pos2   := BuscaDireita(']', item);   portal := copy(item, pos+1, pos2-pos-1) ;
pos    := BuscaDireita('|', item);   cpf    := copy(item, pos2+1, pos-pos2-1) ;
```

**`RN-17`** — O sistema novo **NÃO DEVE** reconstruir a chave por parsing de rótulo. Cada item da lista **DEVE** carregar a chave estruturada (`RD-01`) como dado, e o texto é apenas apresentação.

> **`DEF-10`** — O parsing acima quebra se o **certificado contiver `[`, `]` ou `|`** — e certificados reais contêm `/`, `.` e espaços (`'3082/01/AP 1302'`), o que mostra que o campo é texto livre. Um único certificado com colchete emite o documento errado, silenciosamente. `RN-17` elimina a classe de problema.

**`RF-06`** — A pasta de destino **DEVE** ser validada como existente e gravável **antes** de iniciar a emissão.

---

## 6. Especificação das consultas

### 6.0 A consulta canônica

Descoberta central: **`QRY-05a`, `QRY-05b`, `QRY-06`, `QRY-09` e `QRY-10` são a mesma `SELECT`** — projeção e joins byte a byte idênticos — variando apenas o `WHERE`. São cinco cópias mantidas à mão em cinco `TSQLQuery` do `.dfm`.

**`RD-17`** — O sistema novo **DEVE** ter **uma** consulta canônica em `queries.sql`, com filtros compostos programaticamente. Cinco cópias é o mecanismo por trás de `DEF-03` e `DEF-05`: uma correção aplicada a uma cópia não chega às outras — e é exatamente o que já aconteceu, já que `QRY-04` tem `COALESCE` no `codigo_pedido_port` e as demais não.

```sql
-- name: certificado_base
SELECT pes.nome                                             AS nome_adm,
       pes.abrev                                            AS abrev_adm,
       ss.administradora, ss.apolice, ss.seq, ss.fatura,
       ss.endosso, ss.cod_seguradora,
       ss.nome                                              AS beneficiario,
       ss.codigo_pedido_port,
       ss.cpf_cnpj                                          AS documento_seg,
       ss.inicio_vig, ss.final_vig,
       ss.endereco, ss.unidade, ss.cep, ss.uf, ss.cidade, ss.bairro,
       ss.nome_cond,
       aps.apolice_seguradora, aps.proc_susep,
       ss.certificado,
       ss.inc_conteudo, ss.inc_predio, ss.aluguel,
       (COALESCE(ss.inc_conteudo,0) + COALESCE(ss.inc_predio,0)) AS cob_incendio,
       ss.premio,
       en.codigo_assist_mondial, en.cod_cat,
       ss.certificado || ' ' || COALESCE(pes.abrev,'')       AS cod_0800,
       sicb.quebra_vidro, sicb.rc, sicb.danos_eletricos,
       sicb.resp_civil, sicb.rup_encanamento,
       sicb.rup_enc_ter, sicb.acidente_pessoal
FROM segurados_inc ss
LEFT JOIN pessoas             pes  ON pes.pessoa = ss.administradora
LEFT JOIN apolice_seguradora  aps  ON aps.apolice = ss.apolice
                                  AND aps.cod_seguradora = ss.cod_seguradora
LEFT JOIN endossos            en   ON en.endosso = ss.endosso
LEFT JOIN segurados_inc_cob_aux sicb ON sicb.endosso = ss.endosso          -- GAP-17: PK (ENDOSSO, CERTIFICADO)
                                    AND sicb.certificado = ss.certificado
WHERE ss.status_seg <> 'C'
  AND ss.cpf_cnpj <> ''
  /*FILTROS*/
ORDER BY ss.administradora, ss.apolice, ss.seq, ss.fatura,
         ss.endereco, ss.unidade, ss.cpf_cnpj
```

Diferenças declaradas em relação ao legado:

1. **`RD-04`/`RD-08`** — projeta `cod_seguradora`, `abrev` e `cod_cat`.
2. **`RN-02`** — `COALESCE` em `cob_incendio` (`DEF-05`).
3. **`RN-20`** — `COALESCE(pes.abrev,'')` no `cod_0800`: sem isso, `abrev` nula torna o **código inteiro nulo** em Firebird, e o campo sai vazio no certificado — não só sem o sufixo.
4. **`RD-19`** — `cpf_cnpj <> ''` aplicado sempre (`DEF-03`).
5. **`GAP-17`** — `JOIN` com `segurados_inc_cob_aux` por `(endosso, certificado)`, a PK das duas tabelas, em vez de `(fatura, certificado)`, que se mostrou não único no banco (03/09/2026).
6. **`GAP-16`** — `linha_branca` não é projetada.

**`RN-06`** — Todas as consultas **DEVEM** usar bind parameters. Concatenação de valores em SQL é proibida.

**`RN-07`** — Filtros opcionais **DEVEM** ser compostos por lista de predicados:

```python
where, params = [], {}
if administradora:
    where.append("ss.administradora = :adm");     params["adm"] = administradora
if inicio_vig:
    where.append("ss.inicio_vig = :inicio_vig");  params["inicio_vig"] = inicio_vig
sql = BASE.replace("/*FILTROS*/", "".join(f"  AND {p}\n" for p in where))
```

### 6.1 `QRY-01` — Administradoras

Legado, linha 1279:
```sql
select * from pessoas pes where pes.status <> 'C' ORDER BY pes.nome
```
Especificado:
```sql
SELECT pes.pessoa, pes.nome, pes.abrev, pes.possui_portal
FROM pessoas pes
WHERE pes.status <> 'C'
ORDER BY pes.nome
```

**`RD-07`** — Projetar apenas o necessário. `abrev` é obrigatória (`RN-20`) e `possui_portal` é usada pelo fluxo em massa.

### 6.2 `QRY-02` — Resolução do código da administradora

Legado, linha 1147:
```sql
SELECT PES.PESSOA FROM PESSOAS PES WHERE PES.NOME = 'nome digitado'
```

**`RF-03`** — Esta consulta **DEVE deixar de existir**. O `<select>` da tela carrega `value` = `pessoa` e texto = `nome`; o código nunca é reconstruído a partir do nome.

> **`DEF-12`** — O legado usa o **nome** como chave, sem filtro de status, e pega a primeira linha se houver mais de uma. Nomes homônimos ou um espaço a mais deixam `Edit1` vazio, e daí `QRY-03` sai sem filtro de administradora — listando apólices de **todas** as administradoras sem nenhum aviso ao operador (linhas 1168-1180). Agravante na linha 1187: dentro do laço de carga das apólices, `Edit1.Text` é sobrescrito pela `administradora` da linha corrente, o que pode trocar o código já resolvido.

### 6.3 `QRY-03` — Apólices

```sql
SELECT ss.apolice, ss.seq
FROM segurados_inc ss
WHERE ss.status_seg <> 'C'
  AND ss.administradora = :adm
  AND (:inicio_vig IS NULL OR ss.inicio_vig = :inicio_vig)
GROUP BY ss.apolice, ss.seq
ORDER BY ss.apolice, ss.seq
```

**`RN-08`** — Rótulo exibido: `f"{apolice}.{seq}"` (linha 1189). É o formato que o operador reconhece.

**`RN-09`** — Decomposição, quando necessária, pela **última** ocorrência do ponto: `apolice, _, seq = rotulo.rpartition(".")`.

> **`DEF-13`** — O legado faz `seq := trim(copy(texto, pos+1, 3))`, truncando a sequência em **3 caracteres**. `seq >= 1000` é lido errado. Ocorre em cinco pontos (linhas 185, 390, 452, 1219, 1318).

**`RF-15`** — Administradora vazia **DEVE** bloquear a listagem de apólices. O legado permite listar apólices de todas as administradoras (`DEF-12`), o que não é um caso de uso e sim consequência da falha de resolução.

### 6.4 `QRY-04` — Faturas

```sql
SELECT ss.fatura
FROM segurados_inc ss
WHERE ss.status_seg <> 'C'
  AND ss.administradora = :adm
  AND ss.apolice = :apolice
  AND ss.seq = :seq
  AND (:inicio_vig IS NULL OR ss.inicio_vig = :inicio_vig)
GROUP BY ss.fatura
ORDER BY 1
```

Corresponde ao trecho do levantamento (linhas 1239-1254), confirmado literalmente.

### 6.5 `QRY-05` — Segurados da fatura *(`GAP-06` fechado)*

Legado: `SQLQuery1` no fluxo manual (`QRY-05a`) e `SQLQuery7` no fluxo em massa (`QRY-05b`). **É a consulta canônica** com os filtros `adm + apolice + seq + fatura`. As duas variantes são a mesma consulta com divergências não intencionais (`DEF-03`) e **DEVEM** ser unificadas em `QRY-05`.

```sql
-- certificado_base + filtros:
  AND ss.administradora = :adm
  AND ss.apolice        = :apolice
  AND ss.seq            = :seq
  AND ss.fatura         = :fatura
```

**`RN-10`** — A ordenação **DEVE** ser a da consulta canônica (`endereco`, `unidade`, `cpf_cnpj`), que agrupa o PDF consolidado por endereço. A tela **PODE** reordenar por nome para facilitar a busca visual, sem alterar a ordem de emissão.

> **`DEF-03`** — As duas cópias divergem: `SQLQuery1` (manual) usa `coalesce(SS.codigo_pedido_port,0)` e **não** filtra `cpf_cnpj <> ''`; `SQLQuery7` (massa) projeta o campo cru e **filtra** `cpf_cnpj <> ''`. Ou seja: o fluxo manual lista segurados sem documento que o fluxo em massa esconde, e a emissão desses falha adiante. Mesma tela, dois comportamentos.

### 6.6 `QRY-06` — Emissão, fluxo manual

Legado `SQLQuery3`. Filtros:
```sql
  AND ss.administradora      = :adm
  AND ss.apolice             = :apolice
  AND ss.seq                 = :seq
  AND ss.fatura              = :fatura
  AND ss.certificado         = :cert
  AND ss.cpf_cnpj            = :cpf
  AND ss.codigo_pedido_port  = :portal      -- ver DEF-04
  AND ss.codigo_pedido_port  > 0            -- ver DEF-04
```

### 6.7 `QRY-09` — Emissão, fluxo em massa

Legado `SQLQuery5`. Filtros:
```sql
  AND ss.administradora = :adm
  AND ss.apolice        = :apolice
  AND ss.seq            = :seq
  AND ss.fatura         = :fatura
  AND ss.certificado    = :cert
```

**`RD-21`** — O sistema novo **DEVE** adotar o conjunto de filtros de `QRY-09`, acrescido de `cpf_cnpj = :cpf` para desambiguar certificados compartilhados (`RD-22`), e **NÃO DEVE** filtrar por `codigo_pedido_port`.

> **`DEF-04` — a contradição mais séria do legado.** O fluxo manual lista com `coalesce(codigo_pedido_port, 0)` e emite exigindo `codigo_pedido_port = :portal AND codigo_pedido_port > 0`. Para todo segurado com `codigo_pedido_port` nulo, o item aparece na lista como `[0]`, e a consulta de emissão recebe `portal = 0` — que satisfaz `= 0` e viola `> 0`. **Resultado: zero linhas, nenhum PDF gerado.**
>
> E o `if not ClientDataSet1.Eof then` da linha 278 envolve **apenas** a exportação. As linhas 345-362 — upload para o S3 e `UPDATE segurados_inc SET link_certificado_aws` — ficam **fora** do teste. Quando a consulta não retorna nada, o sistema:
> 1. não gera o PDF;
> 2. faz upload do `nomearq` **da iteração anterior**, porque a variável não foi reatribuída;
> 3. grava em `segurados_inc` um `link_certificado_aws` que aponta para o certificado de **outro segurado**.
>
> Este é o defeito de maior impacto: contamina dados de produção e produz link errado para o segurado final. Corrigi-lo é `RD-21` + `RF-09`.

> **`GAP-11`** — Os três PDFs de referência têm `codigo_pedido_port = 0` no nome e existem — o que é incompatível com `codigo_pedido_port > 0` do fluxo manual. Duas explicações possíveis: foram gerados pelo fluxo em massa (mas o nome do arquivo tem 5 campos, e o em massa gera 6 — `RN-11b`), ou por um executável mais antigo que o fonte em disco. **Teste decisivo:** emitir no legado um certificado com `codigo_pedido_port` nulo pelo botão **Imprime** e verificar se o PDF aparece. Isso define se `DEF-04` está ativo em produção hoje.

### 6.8 `QRY-07` — Faturamento *(driver do fluxo em massa)*

Legado, linhas 696-724. Montada por concatenação:
```sql
SELECT fat.administradora, fat.apolice, fat.seq, fat.fatura, fat.seguradora,
       endo.codigo_assist_mondial, endo.cob_especiais
FROM faturas fat
LEFT JOIN endossos endo ON endo.sequencial = fat.fatura
LEFT JOIN pessoas  pes  ON pes.pessoa      = fat.administradora
WHERE fat.status = 'A'
  AND (:inicio_vig IS NULL OR fat.dt_ini_vig = :inicio_vig)
  AND (:data_fat   IS NULL OR fat.data_fat   = :data_fat)
  AND (:apolice    IS NULL OR fat.apolice    = :apolice)
  AND (:adm        IS NULL OR fat.administradora = :adm)
  AND (:fatura     IS NULL OR fat.fatura     = :fatura)
ORDER BY fat.administradora, fat.apolice, fat.seq, fat.fatura
```

**`RN-16`** — O `JOIN` `endossos.sequencial = faturas.fatura` estabelece que **o número da fatura é o sequencial do endosso**. Confirmado também em `QRY-11` (linha 239). Essa igualdade é regra de domínio, não coincidência, e **DEVE** ser documentada como tal.

**`RN-22`** — Quando nenhuma apólice é escolhida, o legado restringe a busca a um conjunto fixo (linha 711):
```sql
AND fat.apolice IN ('4008','5008','10008','13008','14008','15008')
```
Essa lista **DEVE** virar configuração (`CERTGEN_APOLICES_MASSA`), não literal em código. Note que ela contém `10008`, `14008` e `15008` — **ausentes** do mapa de produto do fluxo manual (`DEF-09`) — e **não** contém `6008`, `7008` nem `9008`, que o mapa do fluxo em massa trata.

> O `.dfm` guarda uma versão de design-time ainda mais restritiva desta consulta, com `AND PES.possui_portal = 'S'` e `fat.administradora in ('0000004691','0000003170','0000002960')` fixos. É sobrescrita em runtime, mas revela que o filtro por portal já existiu e foi comentado (linhas 717-718). Ver `GAP-12`.

### 6.9 `QRY-10` — Releitura do lote para XML

Legado `SQLQuery9`. Consulta canônica com filtros:
```sql
  AND ss.administradora            = :adm
  AND ss.id_controle_envio_portal  = :idcontrole
```
Usada por `GeraXMLGeral` após a emissão, para reler exatamente o que foi gravado. O `idcontrole` vem de `SELECT GEN_ID(ID_CONTROLE_ENVIO_PORTAL, 1) FROM RDB$DATABASE` (linha 674).

### 6.10 `QRY-11` — Derivação de Faz Tudo Lar e Locação

Legado, linhas 238-248 / 951-961:
```sql
SELECT * FROM endossos en WHERE en.sequencial = :fatura
```

**`RN-18` — Faz Tudo Lar.** `endossos.codigo_assist_mondial = '1003'` ⇒ o produto inclui a assistência *Faz Tudo Lar*, e o template ganha a seção correspondente (visível no PDF `..._13008_380819`, linhas 97-187 do texto extraído).

**`RN-04` — Locação.** `endossos.cod_cat IN ('3','4')` ⇒ apólice de locação.

> **`GAP-05` fechado, e a hipótese anterior estava errada.** A especificação v0.1 supunha que a flag de locação derivava da apólice estar em `{6008, 7008}` e que controlava o bloco de Perda de Aluguel. O código mostra outra coisa: a derivação por apólice existe apenas como **pré-preenchimento** nos eventos `OnExit` (linhas 1235-1237, 793-795) e é **sobrescrita no momento da emissão** pela categoria do endosso. E o efeito não é um bloco: é a **escolha do arquivo `.fr3`** (seção 7.3).
>
> As duas derivações podem discordar: uma apólice `13008` cujo endosso tenha `cod_cat = '3'` é tratada como locação na emissão, embora a tela mostre *Locação* desmarcado. A verdade é o endosso.

### 6.11 `QRY-12` — Dados do portal para o XML

Legado `SQLQuery8`. Projeção distinta, para o XML de envio à Porto:
```sql
SELECT ss.codigo_pedido_port AS codigo_portal, '' AS posto, ss.administradora,
       ss.certificado AS matricula, ss.cpf_cnpj, ss.nome AS nome_segurado,
       '' AS nascimento, ss.cep, ss.endereco, '' AS numero, '' AS complemento,
       ss.unidade, ss.cidade, ss.bairro, ss.uf, ss.nome_cond AS nome_posto,
       pes.nome, pes.pessoa,
       ss.cpf_cnpj || '@' || trim(replace(lower(pes.nome),' ','')) || '.com.br' AS email,
       ss.link_certificado_aws, ss.premio
FROM segurados_inc ss
LEFT JOIN pessoas pes ON pes.pessoa = ss.administradora
WHERE ...
ORDER BY ss.nome_cond, ss.certificado, ss.nome
```

> **`DEF-14`** — O campo `email` é **fabricado** concatenando o CPF do segurado com o nome da administradora: `33016330725@imodataadmdeimoveiseservicosempresariais.com.br`. Não é um endereço real; é um placeholder sintático para satisfazer o schema do parceiro. Está sendo enviado a um sistema externo como se fosse dado de contato. **DEVE** ser decidido explicitamente se o novo sistema mantém a prática — e, se mantiver, o campo **DEVE** ser marcado como sintético no JSON e no XML.

---
### 6.12 `RN-03` — Derivação do produto *(`GAP-07` fechado)*

Não é consulta: é tabela de decisão em código. E os dois fluxos têm mapas **diferentes**.

**Catálogo autoritativo do domínio.** Está num comentário do próprio fonte (linhas 1202-1208) e é a única fonte completa encontrada:

| Código | Descrição no comentário | Item no `ComboBox4` | `txtprod` |
|---|---|---|---|
| `0001` | Incêndio Conteúdo Residencial | `0001 - RESIDENCIAL` | `RESIDENCIAL` |
| `0002` | Incêndio Conteúdo Comercial | `0002 - COMERCIAL` | `COMERCIAL` |
| `0003` | **Garantia do Condomínio** | *ausente* | *ausente* |
| `0004` | Ruptura de Encanamento + Incêndio Conteúdo | `0004 - RUPTURA` | `RUPTURA` |
| `0005` | **Aluguel** (`"Alug"`) | *ausente* | *ausente* |
| `0006` | Locação residencial (apólice 6008) | `0006 - LOCAÇÃO RESIDENCIAL` | `LOC-RES` |
| `0007` | Locação comercial (apólice 7008) | `0007 - LOCAÇÃO COMERCIAL` | `LOC-COM` |

`0003` e `0005` existem no domínio mas **não têm item na combo nem apólice mapeada** — não são emissíveis por esta tela. O rótulo `GARANTIA` presente no template do `15008` é indício de que *Garantia do Condomínio* tem lugar no layout. **`GAP-07` fechado com esta resposta;** resta decidir se o sistema novo os contempla (`GAP-14`).

**Mapa apólice → produto.** União dos dois fluxos:

| Apólice | Produto | Fluxo manual (linha 1221) | Fluxo em massa (linha 776) |
|---|---|---|---|
| `4008` | `0001` RESIDENCIAL | ✓ | ✓ |
| `9008` | `0001` RESIDENCIAL | ✗ | ✓ |
| `10008` | `0001` RESIDENCIAL | ✗ | ✓ |
| `5008` | `0002` COMERCIAL | ✓ | ✓ |
| `13008` | `0004` RUPTURA | ✓ | ✓ |
| `14008` | `0004` RUPTURA | ✗ | ✓ |
| `15008` | `0004` RUPTURA | ✗ | ✓ |
| `6008` | `0006` LOC-RES | ✓ | ✓ |
| `7008` | `0007` LOC-COM | ✓ | ✓ |

**`RN-03.1` — Exceção por administradora.** Linha 785:
```pascal
if ((Edit1.Text = '0000000019') and (apol = '15008')) then
   ComboBox4.ItemIndex := 0 ;   // RESIDENCIAL, não RUPTURA
```
A administradora `0000000019` na apólice `15008` emite como `0001`, não `0004`. É regra de negócio real, específica de um cliente, e **DEVE** ser preservada — porém como **dado**, não como `if` em código.

**`RN-03.2`** — O mapa **DEVE** ser tabela de configuração com as colunas `(apolice, administradora | NULL, produto)`, resolvida pela regra mais específica primeiro. Assim `RN-03.1` deixa de ser exceção codificada e novas apólices entram sem recompilar.

**`RN-03.3`** — Apólice sem produto resolvido **DEVE** abortar a emissão, nomeando a apólice. Ver `DEF-09`.

> **`DEF-09` — o defeito fotografado pelos arquivos de referência.** Os mapas são sequências de `if` sem `else`, e `prod` sai de um `case i of` sem ramo `else`. Quando a apólice não está no mapa, `ComboBox4.ItemIndex` fica `-1`, nenhum ramo casa e `prod` permanece string vazia. É exatamente o que se vê em `0_05554363733__15008_381066.pdf`: campo de produto **vazio** no nome do arquivo. Pior: se o operador já tinha selecionado outra apólice antes, o `ItemIndex` anterior **persiste** e o certificado sai com o produto errado — sem qualquer aviso. As consequências se propagam para o caminho no S3 (`RN-19`) e para o `Memo34` do template.
>
> Nos três arquivos de referência, o defeito atinge o fluxo manual com a apólice `15008`, que o fluxo em massa mapeia corretamente para `0004`. A mesma apólice, na mesma tela, produz resultado diferente conforme o botão apertado.

## 7. Especificação dos artefatos de saída

### 7.1 Modos de saída

**`RF-07`** — Dois modos, controlados pelo checkbox **Individuais** (default marcado):

| Modo | Comportamento no legado | Comportamento especificado |
|---|---|---|
| **Individuais** ✓ | Um PDF por certificado, gravado em disco (linhas 230-364) | Um PDF **+ um JSON** por certificado |
| **Individuais** ✗ | `QRY-05` + `ShowPreparedReport` — abre o **preview** do FastReport, não grava nada (linhas 369-402) | Um PDF consolidado **gravado**, + um JSON com o array |

> **`DEF-15`** — No legado, desmarcar *Individuais* não gera arquivo: apenas abre a pré-visualização, e o `nomearq` construído na linha 398 é a instrução `nomearq := nomearq ;` — uma auto-atribuição sem efeito, resquício de código. O operador que espera um PDF consolidado em disco não o recebe. **Decisão especificada:** o modo consolidado **DEVE** gravar o arquivo (`RN-12`), e a pré-visualização passa a ser uma ação separada (`UC-04`).

**`RF-09`** — A emissão em lote **DEVE** ser resiliente e transacionalmente honesta: falha em um certificado registra o erro, **não** produz efeito colateral algum para aquele certificado (nem upload, nem `UPDATE`) e o lote prossegue. Ao final, o sistema apresenta o balanço `emitidos / falhados` com o motivo de cada falha. Este requisito é a correção direta de `DEF-04`.

**`RF-10`** — O bloco de prêmio **DEVE** ser exibido apenas se *Imprime Premio* estiver marcado. No legado isso é feito alternando `Visible` de componentes localizados por nome em runtime (`frxDBDatasetIncPREMIO`, `Memo43`, `Memo44`, `Memo49`, `Memo50`). No sistema novo é uma condicional de template.

### 7.2 Nomenclatura de arquivos *(`GAP-08` fechado)*

Os dois fluxos geram nomes **diferentes**, com número de campos diferente.

**`RN-11a` — Fluxo manual** (linha 280):
```
{codigo_pedido_port}_{cpf_cnpj}_{produto}_{apolice}_{fatura}.pdf
```
**`RN-11b` — Fluxo em massa** (linha 1004):
```
{codigo_pedido_port}_{cpf_cnpj}_{produto}_{apolice}_{certificado_sanitizado}_{fatura}.pdf
```

Decomposição dos arquivos de referência, agora **confirmada contra o código**:

| Arquivo | portal | cpf_cnpj | produto | apólice | fatura |
|---|---|---|---|---|---|
| `0_33016330725_0004_13008_380819.pdf` | `0` | `33016330725` | `0004` | `13008` | `380819` |
| `0_05554363733__15008_381066.pdf` | `0` | `05554363733` | *(vazio)* | `15008` | `381066` |
| `0_14529138704__15008_381066.pdf` | `0` | `14529138704` | *(vazio)* | `15008` | `381066` |

Três verificações independentes fecham a leitura:

- **O último campo é a fatura, não o certificado.** Os dois arquivos `15008` compartilham `381066` mas têm CPFs distintos — e os PDFs mostram certificados distintos (`3082/01/AP 1302` e `3082/01/AP 1101`). Além disso, o certificado real contém `/` e espaço, impossíveis num nome de arquivo. A v0.1 supunha certificado; estava errado.
- **O primeiro campo é `codigo_pedido_port`**, valendo `0` porque `QRY-05` no fluxo manual aplica `coalesce(codigo_pedido_port, 0)`. A v0.1 supunha `seq`; estava errado.
- **O terceiro campo vazio nos arquivos `15008` é o defeito `DEF-09` fotografado.** A apólice `15008` não existe no mapa do fluxo manual, `ComboBox4.ItemIndex` permanece `-1`, o `case i of` das linhas 191-198 não casa nenhum ramo e `prod` fica string vazia. O nome do arquivo perde o campo e, junto, a informação de produto.

**`RN-11`** — O sistema novo **DEVE** adotar **um** padrão para os dois fluxos, o de 6 campos, sempre com produto resolvido:
```
{portal}_{cpf_cnpj}_{produto}_{apolice}_{certificado_sanitizado}_{fatura}.pdf
{portal}_{cpf_cnpj}_{produto}_{apolice}_{certificado_sanitizado}_{fatura}.json
```
com `portal = codigo_pedido_port` ou `0`, `cpf_cnpj` apenas dígitos, `produto` com 4 dígitos e `certificado_sanitizado` conforme `RN-17b`.

**`RN-17b` — Sanitização do certificado** (linhas 998-1002):
```python
SANITIZE = {"/": "-", "\\": "-", "|": "-", ".": "", " ": ""}
cert_arquivo = certificado.translate(str.maketrans(SANITIZE))
# 'CF1DI/AP.602'     -> 'CF1DI-AP602'
# '3082/01/AP 1302'  -> '3082-01-AP1302'
```
O sistema novo **DEVE** ainda rejeitar `:`, `*`, `?`, `"`, `<`, `>` e caracteres de controle, ausentes da lista do legado.

**`RN-12` — Nome do consolidado:**
```
certificados_{apolice}_{seq}_{fatura}_{YYYYMMDD-HHMMSS}.pdf
certificados_{apolice}_{seq}_{fatura}_{YYYYMMDD-HHMMSS}.json
```

**`RN-13`** — **NÃO DEVE** sobrescrever arquivo existente silenciosamente: em colisão, acrescentar sufixo ` (n)` e registrar no relatório.

**`RN-19` — Competência e estrutura de pastas.** O fluxo em massa cria `{raiz}\{administradora}\{competência}` (linhas 747-766), com:
```pascal
compet := IntToStr(MonthOf(DateEdit1.Date)) + IntToStr(YearOf(DateEdit1.Date)) ;
compet := FormatFloat('000000', StrToInt(compet)) ;
```
Ou seja: mês e ano concatenados **como texto**, convertidos a inteiro e reformatados com 6 dígitos. Para julho/2026 dá `"7" + "2026"` = `72026` → `072026`. Funciona por acidente aritmético. O sistema novo **DEVE** usar `f"{data.month:02d}{data.year}"` diretamente.

> **`DEF-16`** — Se `DateEdit1` estiver vazia no fluxo em massa (permitido, desde que `DateEdit2` esteja preenchida — linha 670), `MonthOf(0)` e `YearOf(0)` retornam mês 12 e ano 1899, e a competência sai `121899`. Os certificados vão para uma pasta datada de 1899 e o caminho no S3 fica igualmente errado.

### 7.3 Matriz de templates *(`GAP-02` fechado)*

O legado escolhe entre **cinco arquivos FastReport** distintos, em função de três variáveis derivadas (linhas 282-341 e 1006-1065):

| `Locação` (`cod_cat ∈ {3,4}`) | `Faz Tudo` (`mondial = 1003`) | Produto | Relatório | Origem |
|---|---|---|---|---|
| ✗ | ✗ | qualquer | `frxReportIncendio` | este form |
| ✗ | ✓ | `0004` | `frxReportCntRupturaFT` | `FrmRepositorioRel` |
| ✗ | ✓ | ≠ `0004` | `frxReportIncW24h` | este form |
| ✓ | ✗ | qualquer | `frxReportLocaSimples` | `FrmRepositorioRel` |
| ✓ | ✓ | qualquer | `frxReportIncIncLocaCFT` | `FrmRepositorioRel` |

Além disso, dentro de `frxReportIncendio` o legado liga e desliga componentes por nome em runtime:

| Componente | Papel inferido | Regra |
|---|---|---|
| `frxDBDatasetIncPREMIO`, `Memo43`, `Memo44`, `Memo49`, `Memo50` | bloco de prêmio | visível se *Imprime Premio* |
| `Memo28` | cabeçalho padrão | oculto se apólice `15008` (linha 889) |
| `Memo45` | cabeçalho alternativo | sempre oculto no fluxo em massa |
| `Picture2` | logotipo padrão | sempre visível |
| `Picture7` | logotipo alternativo | visível **apenas** se apólice `15008` (linha 907) |
| `Memo34` | nome do produto (`RESIDENCIAL`, `COMERCIAL`, `RUPTURA`, `LOC-RES`, `LOC-COM`) | injetado por código |

> **`DEF-17`** — No fluxo manual (`Button1`), `Memo34` recebe `txtprod` **antes** do laço, uma única vez, a partir do `ComboBox4` da tela. No fluxo em massa (`Button4`), a atribuição de `Memo34` acontece na linha 686 — **antes** de `txtprod` receber valor, que só ocorre na linha 806, dentro do laço. Resultado: no fluxo em massa `Memo34` é preenchido com string vazia e o nome do produto **não sai** no certificado. Cabe verificar no `.fr3` se o campo é visível; se for, todos os certificados do fluxo em massa saem sem a modalidade impressa.

**`ADR-05` — Um template condicional em vez de cinco arquivos.**

**Contexto.** Cinco `.fr3` binários e opacos, mais manipulação de visibilidade por nome em runtime, tornam impossível saber o que muda entre um certificado e outro sem abrir o FastReport. Os PDFs de referência comprovam a consequência: dois templates formatam o **mesmo dado** de maneira diferente (`DEF-08`).

**Decisão.** Um único template Jinja2, `certificado.html.j2`, com blocos condicionais governados por um objeto de contexto explícito:
```python
@dataclass(frozen=True)
class ContextoTemplate:
    locacao: bool          # RN-04  — endossos.cod_cat
    faz_tudo_lar: bool     # RN-18  — codigo_assist_mondial
    produto: Produto       # RN-03
    exibe_premio: bool     # RF-10
    marca: Marca           # logotipo/cabeçalho, substitui Picture2/Picture7
```

**Consequências.** A regra fica legível e testável, a formatação passa a ser única por construção (`RN-14`) e cada combinação da matriz vira um caso de teste. Custo: o esforço inicial de portar o layout é maior do que traduzir um template por vez.

**Alternativa rejeitada.** Cinco templates HTML espelhando os cinco `.fr3` — preservaria as divergências de formatação, que são justamente o que se quer eliminar.

### 7.4 Layout do PDF

Estrutura confirmada nos PDFs de referência. O documento se intitula **DEMONSTRATIVO** (não "certificado"), em formato de carteira virtual.

```
┌──────────────────────────────────────────────────────────────────────┐
│  [logo GRUPO / SEGUROS & SERVIÇOS]              DEMONSTRATIVO        │
│                        {produto: "Total Conteúdo"}                   │
│     Parabéns! Você aderiu a um produto feito sob medida para você.   │
│     Este é o demonstrativo da sua Proteção Residencial contratada.   │
├───────────────────────────┬──────────────────────────────────────────┤
│                           │ CONDOMÍNIO        │ VIGÊNCIA             │
│  Beneficiário             │ {nome_cond}       │ {ini}    {fim}       │
│                           ├───────────────────┴──────────────────────┤
│  [texto explicativo da    │ BENEFICIÁRIO      │ CPF                  │
│   carteira virtual]       │ {beneficiario}    │ {documento_seg}      │
│                           ├───────────────────┼──────────────────────┤
│                           │ ENDEREÇO          │ BAIRRO               │
│                           │ {endereco}        │ {bairro}             │
│                           ├───────────────────┼──────────────────────┤
│                           │ CIDADE            │ UF                   │
│                           │ {cidade}          │ {uf}                 │
│                           ├───────────────────┴──────────────────────┤
│                           │ CEP  {cep}                               │
├───────────────────────────┴──────────────────────────────────────────┤
│  Seguro Incêndio                                                     │
│  PROCESSO SUSEP Nº   │ SUC. │ PLANO │ CERTIFICADO      │ [GARANTIA]  │
│  {proc_susep}        │ {?}  │ {?}   │ {certificado}    │             │
│  DATA DE EMISSÃO │ CONTRATO  │ APÓLICE              │ UNIDADE SEGU.  │
│  {hoje}          │ {apolice} │ {apolice_seguradora} │ {unidade}      │
│  ESTIPULANTE                    │ CO-ESTIPULANTE                     │
│  FEDCORP ADMINISTRADORA...      │ {nome_adm}                         │
│  COBERTURA INCÊNDIO │ COB. PERDA DE ALUGUEL │ COB. RC │ COB. RUPTURA │
│  {cob_incendio}     │ {aluguel}             │ {rc}    │ {rup_encan.} │
│  Ao solicitar a Assitência 0800, informe: {cod_0800}                 │
│                                    CÓDIGO SUSEP DA CORRETORA {?}     │
├──────────────────────────────────────────────────────────────────────┤
│  Textos legais das coberturas (fixos por produto)                    │
│  Assistência Residencial Emergencial 24h    [Central 0800 770 4362]  │
│  Assistência Faz Tudo Lar   (só se RN-18)   [Central 0800 770 4362]  │
│  Clube de Vantagens                                                  │
│  Central de Atendimento FedCorp 0800 251 6001 · sac@grupofedcorp...  │
│  PREMIO: {premio}                           (só se RF-10)            │
└──────────────────────────────────────────────────────────────────────┘
```

**Mapeamento de rótulos que o dicionário de dados não deixa óbvio** — três rótulos do PDF não correspondem ao nome do campo, e confundi-los troca informação regulatória:

| Rótulo no PDF | Campo real | Exemplo |
|---|---|---|
| **CONTRATO** | `segurados_inc.apolice` | `13008` |
| **APÓLICE** | `apolice_seguradora.apolice_seguradora` | `40150116/R-ESP` |
| **CO-ESTIPULANTE** | `pessoas.nome` (a administradora) | `IMODATA ADM DE IMOVEIS...` |
| **ESTIPULANTE** | constante `FEDCORP ADMINISTRADORA DE BENEFICIOS LTDA` | — |

> **`GAP-13`** — Quatro campos do PDF **não têm origem identificada** em nenhuma das consultas: `SUC.` (`RJ`), `PLANO` (`RES`, vazio no `15008`), `GARANTIA` (vazio) e `CÓDIGO SUSEP DA CORRETORA` (`00000202049583`). São constantes do `.fr3`, campos de outra tabela, ou derivados de `uf`/produto. **DEVEM** ser localizados abrindo os `.fr3` no FastReport, ou obtidos com o time de negócio.

> **`GAP-09`** — Os textos legais das coberturas e das assistências estão embutidos nos `.fr3` e variam por produto. Foram **extraídos na íntegra** dos PDFs de referência para `docs/legado/textos-legais/` e **DEVEM** ser conferidos por quem responde pela conformidade antes de irem ao template — eles descrevem cobertura contratada e têm efeito jurídico. Note que os PDFs atuais contêm erros de digitação em texto legal (`"dentruindo-o"`, `"extrememamente"`, `"Assitência"`, `"DESINTETIZAÇÃO"`), o que exige decisão: corrigir ou preservar.

**`RN-14` — Formatação.** Moeda `R$ 1.234.567,89`; datas `DD/MM/YYYY`; CPF `000.000.000-00`; CNPJ `00.000.000/0000-00`; CEP `00000-000`.

> **`DEF-08`** — Os templates atuais **discordam entre si** ao formatar o mesmo dado:
>
> | Campo | `frxReportCntRupturaFT` (13008) | `frxReportIncendio` (15008) |
> |---|---|---|
> | CPF | `33016330725` (sem máscara) | `055.543.637-33` (com máscara) |
> | CEP | `22630010` (sem máscara) | `24.120-191` (máscara **inválida**) |
> | Processo SUSEP | `15.414.901282/2014-83` | `15414.901282/2014-83` |
>
> A máscara de CEP `24.120-191` não corresponde a nenhum formato brasileiro válido — o correto é `24120-191`. `RN-14` unifica tudo, e `ADR-05` garante que a unificação não possa regredir.

> **`DEF-06`** — O PDF `..._15008_381066` imprime a vigência como **`01/07/2026  30/12/1899`**. `30/12/1899` é o zero de `TDateTime` no Delphi: `final_vig` está nula ou zero no banco e foi renderizada como data. Um certificado em produção declara cobertura encerrada no século XIX. O sistema novo **DEVE** tratar data nula ou igual ao zero-Delphi como ausente, **DEVE** exibir `—` no PDF e **DEVE** registrar aviso no relatório de emissão.

> **`DEF-18`** — No mesmo PDF, blocos de texto aparecem duplicados e sobrepostos (`"OOSeguro Seguro cobre danos causados..."` — duas cópias do mesmo memo em posições quase coincidentes). É defeito de layout do `.fr3`, visível no documento entregue ao cliente.

**`RNF-01`** — Fidelidade visual. O PDF gerado **DEVE** ser comparado por diferença de imagem, página a página, com os de referência, dentro de tolerância acordada — **exceto** nos pontos em que a especificação decidiu divergir (`DEF-06`, `DEF-08`, `DEF-18`), que **DEVEM** ter teste próprio afirmando o comportamento novo.

**`RNF-02`** — O PDF **DEVE** ter texto selecionável e pesquisável. Os três de referência têm, o que permitiu esta análise e viabiliza `RNF-04`.

---

## 8. Efeitos colaterais da emissão

Seção que não existia na v0.1. O legado faz quatro coisas além de gerar o PDF, e ignorá-las produziria um sistema novo que parece equivalente e não é.

### 8.1 Upload para S3

Após cada PDF (linhas 345-349, 1069-1072):
```pascal
pstfin := administradora + '/' + produto + '/' + competencia + '/' + fatura ;
linha  := 'java -jar d:\Base_Cheque\fedcorp.jar upload certincendioaws us-east-2 '
        + nomearq + ' ' + pstfin + '/' + ExtractFileName(nomearq) ;
WinExec(PAnsiChar(AnsiString(linha)), SW_HIDE) ;
link := 'https://certincendioaws.s3.us-east-2.amazonaws.com/' + pstfin + '/' + ...
```

> **`DEF-19`** — `WinExec` é assíncrono e seu retorno **não é verificado**. O sistema grava no banco um link para um arquivo cujo upload pode ter falhado — JRE ausente, rede fora, credencial expirada. Não há como distinguir, olhando o banco, um certificado publicado de um que só tem o link. O sistema novo **DEVE** usar o SDK (`boto3`), verificar o resultado e só gravar o link após confirmação do upload.

> **`SEC-01` — Ação imediata.** As linhas 138-144 contêm um bloco `CONST` comentado com **`AccountKey` e `AccountName` da AWS em texto claro**. Estão em código-fonte versionado, num compartilhamento de rede acessível a quem tem a unidade `U:` mapeada. Mesmo comentadas, são credenciais expostas. **Recomendação:** rotacionar as chaves imediatamente, independentemente do projeto novo, e remover o bloco do fonte e do histórico do Git. O sistema novo **DEVE** obter credenciais de variável de ambiente ou IAM role (`RNF-06`), nunca do código.

### 8.2 Gravação em `segurados_inc`

```sql
UPDATE segurados_inc ss
   SET ss.link_certificado_aws = :link,
       ss.dt_cria_link         = :agora,
       ss.id_controle_envio_portal = :controle   -- só no fluxo em massa
 WHERE ...
```

**`RD-20`** — O sistema **escreve** no banco. `RNF-05` é revisto: o usuário Firebird precisa de `UPDATE` em `segurados_inc`, e **apenas** nessas três colunas.

**`RF-16`** — A gravação do link **DEVE** ocorrer somente após confirmação de que o PDF foi gerado **e** publicado. Sequência obrigatória: gerar PDF → gerar JSON → validar schema → publicar → gravar link. Falha em qualquer etapa aborta as seguintes para aquele certificado (`RF-09`). Esta é a correção de `DEF-04` e `DEF-19` juntos.

> **`DEF-20`** — O `UPDATE` é montado por concatenação, com a mesma inversão de `ShortDateFormat` de `DEF-01`, e passa `codigo_pedido_port` — campo inteiro — como string entre apóstrofos (linha 360).

### 8.3 XML de envio à Porto Seguro

`GeraXML` (uma fatura) e `GeraXMLGeral` (o lote), alimentados por `QRY-12`. O XML sobe para `s3://certincendioaws/XML-PST/a-processar/`. É a integração com o *envio Porto*.

**`RF-17`** — Fase 7. O contrato do XML **DEVE** ser especificado em documento próprio antes da implementação, porque é interface com terceiro e não pode ser inferida com segurança dos `ChildValues` do código.

### 8.4 E-mail e arquivo de links

Após o XML, `EnviarEmail` envia o anexo por SMTP com credenciais lidas de um `.ini`. O fluxo em massa também grava `linkscert_DDMMYY.txt` com os links gerados.

> **`DEF-21`** — O destinatário do e-mail é a constante `'albertocordeiro@gmail.com'` (linha 430), um endereço pessoal em código de produção. **DEVE** virar configuração.

---
## 9. Especificação do artefato JSON

Requisito novo e principal ganho do projeto. Princípio: **o JSON não é um dump da consulta — é o certificado modelado como dado.**

**`RD-10`** — O JSON **DEVE** conter todo campo impresso no PDF e **NÃO DEVE** conter campo ausente do PDF, exceto os blocos `_meta` e `_origem`, explicitamente marcados como metadados.

### 9.1 Exemplo canônico

Valores retirados do PDF `0_33016330725_0004_13008_380819.pdf`.

```json
{
  "_meta": {
    "versao_schema": "1.0",
    "gerado_em": "2026-09-03T14:22:07-03:00",
    "gerado_por": "gerador-certificados/0.1.0",
    "arquivo_pdf": "0_33016330725_0004_13008_380819_CF1DI-AP602_380819.pdf",
    "template": "incendio_ruptura_faz_tudo",
    "modo_conexao": "firebird-local",
    "avisos": []
  },
  "certificado": {
    "numero": "CF1DI/AP.602",
    "cod_0800": "CF1DI/AP.602",
    "data_emissao": "2026-09-03"
  },
  "produto": {
    "codigo": "0004",
    "descricao": "Ruptura de Encanamento + Incendio Conteudo",
    "descricao_curta": "RUPTURA",
    "locacao": false,
    "faz_tudo_lar": true
  },
  "contrato": {
    "apolice": {
      "codigo": "13008",
      "seq": 0,
      "numero_seguradora": "40150116/R-ESP",
      "cod_seguradora": "1"
    },
    "fatura": 380819,
    "endosso": "380819",
    "processo_susep": "15.414.901282/2014-83",
    "codigo_pedido_porto": null,
    "estipulante": "FEDCORP ADMINISTRADORA DE BENEFICIOS LTDA"
  },
  "administradora": {
    "codigo": "0000004691",
    "nome": "IMODATA ADM DE IMOVEIS E SERVICOS EMPRESARIAIS",
    "abreviacao": null,
    "papel": "CO-ESTIPULANTE"
  },
  "segurado": {
    "nome": "JORGE EDUARDO MONT SERRAT",
    "documento": {
      "tipo": "CPF",
      "numero": "33016330725",
      "formatado": "330.163.307-25"
    }
  },
  "vigencia": {
    "inicio": "2026-07-01",
    "fim": "2026-07-31"
  },
  "local_risco": {
    "endereco": "AV LUCIO COSTA, 3300 BLOCO 2",
    "unidade": "AP.602",
    "condominio": "DIRETORIA IMODATA",
    "bairro": "BARRA DA TIJUA",
    "cidade": "RIO DE JANEIRO",
    "uf": "RJ",
    "cep": "22630010"
  },
  "coberturas": [
    { "codigo": "COB_INCENDIO",    "nome": "Cobertura Incendio",               "importancia_segurada": "100000.00", "contratada": true,  "derivada": true },
    { "codigo": "INC_PREDIO",      "nome": "Incendio - Predio",               "importancia_segurada": "100000.00", "contratada": true },
    { "codigo": "INC_CONTEUDO",    "nome": "Incendio - Conteudo",             "importancia_segurada": null,        "contratada": false },
    { "codigo": "ALUGUEL",         "nome": "Cobertura Perda de Aluguel",      "importancia_segurada": "10000.00",  "contratada": true },
    { "codigo": "RUP_ENCANAMENTO", "nome": "Cobertura Ruptura de Encanamento","importancia_segurada": "5000.00",   "contratada": true },
    { "codigo": "RC",              "nome": "Cobertura RC",                    "importancia_segurada": "20000.00",  "contratada": true },
    { "codigo": "RUP_ENC_TER",     "nome": "Ruptura de Encanamento - Terceiros","importancia_segurada": null,      "contratada": false },
    { "codigo": "RESP_CIVIL",      "nome": "Responsabilidade Civil",          "importancia_segurada": null,        "contratada": false },
    { "codigo": "DANOS_ELETRICOS", "nome": "Danos Eletricos",                 "importancia_segurada": null,        "contratada": false },
    { "codigo": "QUEBRA_VIDRO",    "nome": "Quebra de Vidros",                "importancia_segurada": null,        "contratada": false },
    { "codigo": "ACIDENTE_PESSOAL","nome": "Acidentes Pessoais",              "importancia_segurada": null,        "contratada": false }
  ],
  "premio": {
    "valor_total": "18.90",
    "moeda": "BRL",
    "impresso_no_pdf": true
  },
  "assistencia": {
    "codigo_mondial": "1003",
    "faz_tudo_lar": true,
    "central_atendimento": "0800 770 4362",
    "central_fedcorp": "0800 251 6001"
  },
  "_origem": {
    "banco": "FIREBIRD",
    "consulta": "certificado_base",
    "chave": {
      "administradora": "0000004691",
      "apolice": "13008",
      "seq": 0,
      "fatura": 380819,
      "certificado": "CF1DI/AP.602",
      "cpf_cnpj": "33016330725"
    }
  }
}
```

### 9.2 Regras do schema

**`RD-11`** — O array `coberturas` **DEVE** conter as 11 entradas de `RN-01` **sempre**, inclusive as não contratadas (`contratada: false`, `importancia_segurada: null`). O PDF omite; o JSON declara. O consumidor não precisa conhecer o catálogo para saber que uma cobertura não foi contratada.

**`RD-12`** — `documento.tipo` **DEVE** ser derivado do comprimento de `cpf_cnpj` após remoção de não-dígitos: 11 → `"CPF"`, 14 → `"CNPJ"`, outro → `"INDEFINIDO"` com aviso em `_meta.avisos`. Necessário porque os templates gravam o campo com e sem máscara (`DEF-08`).

**`RD-25`** — *(decisão de 03/09/2026)* O JSON **é** a replicação dos dados impressos no certificado (`RD-10`) acrescida de **um** bloco de guarda, `arquivo`, com a pasta de destino e o link onde o certificado ficará disponível:
```json
"arquivo": {
  "pdf": "0_33016330725_0004_13008_CF1DI-AP602_380819.pdf",
  "pasta_destino": "0000001192/072026",
  "link": null
}
```
`pasta_destino` segue `RN-19` (`{administradora}/{competência}`); `link` é `null` na emissão local e recebe a URL do S3 na Fase 7 (`RD-20`), quando o JSON é regravado após upload confirmado (`RF-16`). Substitui `_meta.arquivo_pdf` do exemplo 9.1.

**`RD-26`** — *(decisão de 03/09/2026)* Opção **JSON único**, independente de *Individuais*: os PDFs continuam um por segurado, mas o lote grava **um só** arquivo JSON, `certificados_{apolice}_{seq}_{fatura}_{YYYYMMDD-HHMMSS}.json` (`RN-12`), na mesma pasta dos PDFs. Estrutura: `_meta` (`formato: "json_unico"`, `chave: "cpf_cnpj|certificado"`, `quantidade`), `lote` e `certificados`, um **objeto indexado por `cpf_cnpj|certificado`** (`RD-22`: o certificado sozinho não é único na fatura), onde cada valor é o documento completo do certificado, com `_meta` próprio e `arquivo.pdf`, validado individualmente antes do PDF (`RD-15`, `RF-16`). Chave duplicada no lote é erro. Tela: checkbox *JSON único*; CLI: `--json-unico`.

**`RD-13`** — Campos nulos no banco **DEVEM** aparecer como `null`. **NÃO DEVEM** ser omitidos nem convertidos em string vazia — a distinção entre *ausente* e *vazio* tem valor de auditoria, e é exatamente ela que revela casos como `abrev` nula (`RN-20`) e `final_vig` zerada (`DEF-06`).

**`RD-23`** — `_meta.avisos` **DEVE** registrar toda anomalia detectada na emissão daquele certificado, com código estável. Vocabulário mínimo:

| Código | Situação |
|---|---|
| `ABREV_ADM_AUSENTE` | `pessoas.abrev` nula — `COD_0800` incompleto (`RN-20`) |
| `FINAL_VIG_AUSENTE` | `final_vig` nula ou zero-Delphi (`DEF-06`) |
| `COB_INCENDIO_DIVERGENTE` | soma recalculada ≠ valor do banco (`RN-02`) |
| `DOCUMENTO_INDEFINIDO` | `cpf_cnpj` sem 11 nem 14 dígitos (`RD-12`) |
| `PORTAL_AUSENTE` | `codigo_pedido_port` nulo (`GAP-11`) |
| `PRODUTO_POR_EXCECAO` | produto resolvido por `RN-03.1` |
| `SUCURSAL_INVALIDA` | `apolices.sucursal` não é UF de 2 letras (`RN-26`) |
| `FAZ_TUDO_LAR_MANUAL` | operador marcou/desmarcou *Faz Tudo Lar* contrariando a derivação `RN-18` (`ADR-06`, `RF-13a`) |
| `RUPTURA_INCONSISTENTE` | produto `0004` sem `rup_encanamento > 0`, ou vice-versa (`RN-27`) |
| `LOGO_SEGURADORA_AUSENTE` | `cod_seguradora` sem entrada em `seguradoras.toml` ou arquivo de logotipo ausente (`RN-28`) |

Este campo é o que torna visível, em dado estruturado e agregável, tudo o que hoje passa silenciosamente pelo legado. É a contrapartida operacional de `ADR-04`.

**`RD-14`** — No modo consolidado, o envelope é:

```json
{
  "_meta": { "quantidade": 37, "arquivo_pdf": "certificados_13008_0_380819_20260903-142207.pdf" },
  "lote": {
    "administradora": "0000004691",
    "apolice": "13008",
    "seq": 0,
    "fatura": 380819,
    "competencia": "072026"
  },
  "certificados": [ { "...": "objeto certificado, sem _meta proprio" } ]
}
```

**`RF-08`** — No modo consolidado, o JSON **DEVE** conter os mesmos certificados do PDF, na mesma ordem (`RN-10`).

**`RD-15`** — Um **JSON Schema** (draft 2020-12) **DEVE** ser mantido em `docs/schema/certificado-1.0.schema.json` e validado contra cada arquivo **antes** da escrita em disco. JSON que não valida não é gravado, e o certificado correspondente conta como falha (`RF-09`).

**`RNF-04`** — Teste de espelhamento PDF↔JSON: para cada certificado emitido, o texto extraído do PDF **DEVE** conter todos os valores formatados presentes no JSON. É a verificação executável de `RD-10`, e a razão de `RNF-02`.

---

## 10. Arquitetura

### 10.1 Camadas

Arquitetura hexagonal, com um objetivo único: a troca *Firebird local → API* deve ser a substituição de **um** adaptador, sem tocar em domínio, template ou serializador.

```
┌──────────────────────────────────────────────────────────────────┐
│  ENTRADA                                                         │
│  web/   FastAPI + página única (cascata, seleção, emissão)        │
│  cli/   comando equivalente, sem UI                               │
└─────────────────────────────┬────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│  APLICAÇÃO   application/                                         │
│  ListarAdministradoras · ListarApolices · ListarFaturas           │
│  ListarSegurados · EmitirCertificados (RF-09, RF-16)              │
└─────────────────────────────┬────────────────────────────────────┘
                              │ depende de PORTAS (Protocol)
┌─────────────────────────────▼────────────────────────────────────┐
│  DOMÍNIO   domain/            ← nenhuma dependência externa       │
│  Certificado · Cobertura · Produto · Vigencia · LocalRisco        │
│  Documento(CPF/CNPJ) · Dinheiro(Decimal) · ContextoTemplate       │
│  regras: RN-01..RN-04, RN-11..RN-22                               │
└──────────────────────────────────────────────────────────────────┘
                              ▲
      ┌───────────────────────┴────────────────────────┐
┌─────┴──────────────────┐                ┌────────────┴───────────┐
│ ADAPTADOR FASE 1       │                │ ADAPTADOR FASE 5       │
│ adapters/firebird/     │                │ adapters/api/          │
│ fdb (Firebird 2.5)     │                │ httpx                  │
│ queries.sql (RD-17)    │                │ mesmos métodos da porta│
└────────────────────────┘                └────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  SAÍDA                                                            │
│  render/     Jinja2 (certificado.html.j2) → Playwright → PDF      │
│  serialize/  Certificado → dict → JSON Schema → arquivo           │
│  publish/    S3 (fase 7) · repositorio de links (RD-20)           │
└──────────────────────────────────────────────────────────────────┘
```

### 10.2 As portas

**`RD-16`** — As interfaces **NÃO DEVEM** vazar nada específico de SQL ou de HTTP.

```python
from typing import Protocol
from datetime import date

class RepositorioCertificados(Protocol):
    def listar_administradoras(self) -> list[Administradora]: ...

    def listar_apolices(
        self, administradora: str, inicio_vig: date | None
    ) -> list[ApoliceRef]: ...

    def listar_faturas(
        self, administradora: str, apolice: str, seq: int, inicio_vig: date | None
    ) -> list[int]: ...

    def listar_segurados(self, lote: ChaveLote) -> list[Certificado]: ...

    def obter_certificado(self, chave: ChaveCertificado) -> Certificado: ...

    def obter_contexto_endosso(self, fatura: int) -> ContextoEndosso: ...   # QRY-11


class PublicadorCertificados(Protocol):
    """Fase 7. Separado do repositório porque escreve, e escrever tem
    outra política de falha (RF-16)."""
    def publicar(self, arquivo: Path, destino: str) -> str: ...
    def registrar_link(self, chave: ChaveCertificado, link: str) -> None: ...
```

**`RD-24`** — `listar_segurados` **DEVE** retornar `Certificado` completo, não um resumo. A consulta canônica já traz todos os campos (`RD-17`), então listar e emitir usam o mesmo objeto — o que elimina por construção a divergência `DEF-03` e permite emitir o lote com **uma** consulta em vez de N+1.

> Esta é uma melhoria material sobre o legado, que executa `QRY-05` para listar e depois `QRY-06` uma vez **por certificado**. Uma fatura de 300 segurados faz 301 consultas onde uma bastaria.

### 10.3 Estrutura de pastas

```
U:\--2021\05-Gerador Certificados\
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docs/
│   ├── ESPECIFICACAO.md                 # este documento
│   ├── schema/certificado-1.0.schema.json
│   ├── adr/ADR-01..ADR-05.md
│   └── legado/
│       ├── ANALISE-DELPHI.md
│       ├── textos-legais/               # GAP-09
│       └── referencia/*.pdf
├── src/certgen/
│   ├── domain/
│   │   ├── certificado.py
│   │   ├── cobertura.py                 # RN-01, RN-02
│   │   ├── produto.py                   # RN-03, RN-03.1, RN-03.3
│   │   ├── documento.py                 # RD-12
│   │   ├── dinheiro.py                  # RD-05
│   │   ├── nomes_arquivo.py             # RN-11, RN-17b
│   │   └── avisos.py                    # RD-23
│   ├── application/
│   │   ├── ports.py                     # RD-16
│   │   ├── listar_cascata.py
│   │   └── emitir_certificados.py       # RF-07, RF-09, RF-16
│   ├── adapters/
│   │   ├── firebird/{conexao,repositorio}.py
│   │   ├── firebird/queries.sql         # RD-17 — fonte única
│   │   └── api/repositorio.py           # fase 5
│   ├── render/
│   │   ├── templates/certificado.html.j2
│   │   ├── templates/certificado.css
│   │   ├── filtros.py                   # RN-14
│   │   └── pdf.py
│   ├── serialize/json_certificado.py    # RD-10..RD-15, RD-23
│   ├── config/produtos.toml             # RN-03.2
│   ├── web/{app.py,static/}
│   └── cli.py
├── tests/{unit,contract,integration,acceptance}/
└── Delphi/                              # legado, somente leitura
```

**`RD-17`** — As consultas **DEVEM** viver em `queries.sql` como blocos nomeados (`-- name: certificado_base`), carregados por nome, com os filtros compostos em Python. Uma fonte da verdade entre especificação e código.

### 10.4 Dependências

| Pacote | Papel | Justificativa |
|---|---|---|
| `fdb` | Firebird **2.5** | O servidor (`192.168.0.6`, `FATURA.GDB`) e 2.5; `firebird-driver` exige 3+. Modelo de conexao copiado de `U:\--2021\04-EnvioPorto` (pool por charset, padrao FedHub-Backend). *Revisado em 03/09/2026.* |
| `python-dotenv` | `.env` | Mesmo mecanismo do EnvioPorto/FedHub |
| `fastapi` + `uvicorn` | API e tela | Assíncrono, tipado |
| `jinja2` | Template | Layout em HTML/CSS, diffável |
| `playwright` | HTML → PDF | Chromium: fidelidade e CSS de impressão real |
| `pydantic` | Validação e serialização | Conhece `Decimal` e `date` |
| `jsonschema` | `RD-15` | Validação antes da escrita |
| `pypdf` | Consolidação e testes | Merge e extração de texto (`RNF-04`) |
| `boto3` | Fase 7 | Substitui `WinExec` do `fedcorp.jar` (`DEF-19`) |
| `pytest` | Testes | — |

---

## 11. Fase 5 — contrato de API

Definido agora, mesmo sem implementação, para que a fase 1 não crie acoplamento impossível de desfazer.

```yaml
openapi: 3.1.0
info:
  title: API Gerador de Certificados
  version: 1.0.0
paths:
  /administradoras:
    get:
      summary: Administradoras ativas (QRY-01)
      responses:
        "200":
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  required: [codigo, nome]
                  properties:
                    codigo:        { type: string, description: "CHAR(10) zero-padded" }
                    nome:          { type: string }
                    abreviacao:    { type: [string, "null"] }
                    possui_portal: { type: boolean }

  /apolices:
    get:
      summary: Apólices da administradora (QRY-03)
      parameters:
        - { name: administradora, in: query, required: true,  schema: { type: string } }
        - { name: inicio_vig,     in: query, required: false, schema: { type: string, format: date } }
      responses:
        "200":
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  required: [apolice, seq, produto]
                  properties:
                    apolice: { type: string }
                    seq:     { type: integer }
                    produto:
                      type: object
                      required: [codigo, descricao]
                      properties:
                        codigo:      { type: string }
                        descricao:   { type: string }
                        por_excecao: { type: boolean, description: "resolvido por RN-03.1" }

  /faturas:
    get:
      summary: Faturas da apólice (QRY-04)
      parameters:
        - { name: administradora, in: query, required: true,  schema: { type: string } }
        - { name: apolice,        in: query, required: true,  schema: { type: string } }
        - { name: seq,            in: query, required: true,  schema: { type: integer } }
        - { name: inicio_vig,     in: query, required: false, schema: { type: string, format: date } }
      responses:
        "200": { description: OK }

  /segurados:
    get:
      summary: Certificados completos da fatura (QRY-05) — ver RD-24
      parameters:
        - { name: administradora, in: query, required: true, schema: { type: string } }
        - { name: apolice,        in: query, required: true, schema: { type: string } }
        - { name: seq,            in: query, required: true, schema: { type: integer } }
        - { name: fatura,         in: query, required: true, schema: { type: integer } }
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                properties:
                  contexto:
                    type: object
                    description: "QRY-11 — vale para a fatura inteira"
                    properties:
                      locacao:      { type: boolean }
                      faz_tudo_lar: { type: boolean }
                  certificados:
                    type: array
                    items: { $ref: "#/components/schemas/Certificado" }

  /certificados:resolver:
    post:
      summary: Dados completos de uma seleção (QRY-09 em lote)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [administradora, apolice, seq, fatura, selecao]
              properties:
                administradora: { type: string }
                apolice:        { type: string }
                seq:            { type: integer }
                fatura:         { type: integer }
                selecao:
                  type: array
                  items:
                    type: object
                    required: [certificado, cpf_cnpj]
                    properties:
                      certificado: { type: string }
                      cpf_cnpj:    { type: string }
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                properties:
                  certificados:
                    type: array
                    items: { $ref: "#/components/schemas/Certificado" }
                  falhas:
                    type: array
                    items:
                      type: object
                      properties:
                        certificado: { type: string }
                        cpf_cnpj:    { type: string }
                        motivo:      { type: string }

  /certificados/link:
    put:
      summary: Registra link de publicação (RD-20, fase 7)
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [chave, link]
              properties:
                chave: { $ref: "#/components/schemas/ChaveCertificado" }
                link:  { type: string, format: uri }
      responses:
        "204": { description: Registrado }

components:
  schemas:
    Certificado:
      description: "Idêntico ao objeto de 9.1, sem os blocos _meta e _origem"
      type: object
    ChaveCertificado:
      type: object
      required: [administradora, apolice, seq, fatura, certificado, cpf_cnpj]
      properties:
        administradora: { type: string }
        apolice:        { type: string }
        seq:            { type: integer }
        fatura:         { type: integer }
        certificado:    { type: string }
        cpf_cnpj:       { type: string }
```

**`RD-18`** — O schema `Certificado` da API e o schema do arquivo JSON **DEVEM** ser o mesmo documento, referenciado dos dois lados. Divergência entre eles é a forma mais provável de a fase 5 quebrar a fase 1.

**`RN-15`** — A renderização (PDF e JSON em disco) permanece **local em todas as fases**. A API fornece dados; não emite documentos. Isso mantém o motor de PDF fora do escopo de negociação com terceiros.

---

## 12. Requisitos não-funcionais

| ID | Requisito | Verificação |
|---|---|---|
| `RNF-01` | Fidelidade visual aos PDFs de referência, salvo divergências declaradas | Diff de imagem no CI |
| `RNF-02` | PDF com texto selecionável | Extração retorna conteúdo |
| `RNF-03` | 300 certificados em ≤ 120 s | Medição em fatura real |
| `RNF-04` | Espelhamento PDF↔JSON | Teste por certificado |
| `RNF-05` | Banco acessado com privilégio mínimo: `SELECT` em tudo, `UPDATE` **apenas** em `segurados_inc.link_certificado_aws`, `.dt_cria_link`, `.id_controle_envio_portal` | Revisão de grants |
| `RNF-06` | Credenciais fora do código-fonte | `.env` não versionado; ver `SEC-01` |
| `RNF-07` | Log estruturado por emissão | Um registro JSON por certificado |
| `RNF-08` | Reprodutibilidade | Mesma chave + mesmo banco ⇒ saída idêntica, exceto `_meta.gerado_em` e `certificado.data_emissao` (`RN-21`) |
| `RNF-09` | Nunca sobrescrever silenciosamente | `RN-13` |
| `RNF-10` | Tela em `127.0.0.1` por padrão | Bind explícito |
| `RNF-10a` | *(04/09/2026)* Para testes e validação pela equipe, `certgen web --rede` aceita conexões da **rede interna** (`0.0.0.0`). Sem autenticação (fora de escopo, `1.3`): **nunca** expor fora da LAN. Os botões *Sair* e *Procurar…* e as APIs correspondentes só respondem ao navegador da própria máquina do servidor; os demais usuários digitam o caminho de destino, que **DEVE** ser uma pasta de rede acessível a todos. | `cliente_local` + teste |
| `RNF-11` | Nenhum efeito colateral sem sucesso confirmado da etapa anterior | `RF-16` |
| `RNF-12` | Locale independente: nenhuma formatação global mutável | Testes com `LANG` variado |

`RNF-12` existe por causa de `DEF-01`. `RNF-11` existe por causa de `DEF-04`. `RNF-08` é o que torna a reemissão confiável e `RNF-01` estável.

---

## 13. Catálogo de defeitos do legado e decisões

Um sistema em produção há anos tem comportamentos que ninguém pretendeu. Cada linha abaixo exige decisão consciente: **corrigir** significa que o sistema novo produzirá saída diferente da atual e precisa de aval; **preservar** significa replicar o comportamento, inclusive errado, por compatibilidade.

| ID | Defeito | Linha | Impacto | Decisão proposta |
|---|---|---|---|---|
| `DEF-01` | `FormatSettings.ShortDateFormat` global invertido para montar SQL — e na linha 1163 **não é restaurado** | 1161-1163, 350-363, 702-728, 1073-1086 | **Alto.** Após escolher administradora com vigência preenchida, a aplicação inteira fica em formato de data americano | **Corrigir** — `RN-06`, `RNF-12` |
| `DEF-02` | Cascata sem invalidação: trocar apólice não limpa a lista de segurados | eventos `OnExit` | Alto — emite certificado de outra apólice | **Corrigir** — `RF-01` |
| `DEF-03` | `QRY-05` tem duas versões divergentes: `coalesce`/sem filtro de CPF no manual, sem `coalesce`/com filtro na massa | `.dfm` SQLQuery1 vs SQLQuery7 | Médio — comportamento diferente por botão | **Corrigir** — `RD-17`, `RD-19` |
| `DEF-04` | Emissão exige `codigo_pedido_port = :portal AND > 0`, listagem oferece `coalesce(...,0)`; efeitos colaterais fora do `if not Eof` | `.dfm` SQLQuery3; linhas 278-362 | **Crítico.** Grava link do certificado anterior no registro de outro segurado | **Corrigir** — `RD-21`, `RF-09`, `RF-16` |
| `DEF-05` | `inc_conteudo + inc_predio` sem `COALESCE`: `NULL` zera o total de incêndio impresso | `.dfm`, 5 cópias | **Crítico.** Certificado declara cobertura de incêndio vazia | **Corrigir** — `RN-02` |
| `DEF-06` | `final_vig` nula impressa como `30/12/1899` | PDF `15008` | Alto — vigência inválida em documento entregue | **Corrigir** — exibir `—` + aviso |
| `DEF-07` | Checkbox *Upload AWS* declarado, inicializado e **nunca lido**: upload sempre ocorre | 32, 609 | Médio — controle enganoso | **Corrigir** — passa a ter efeito |
| `DEF-08` | Templates formatam o mesmo dado diferente: CPF com/sem máscara, CEP `24.120-191` inválido, SUSEP em dois formatos | PDFs de referência | Médio — inconsistência visível ao cliente | **Corrigir** — `RN-14`, `ADR-05` |
| `DEF-09` | Mapa apólice→produto incompleto no fluxo manual; `case` sem `else` deixa produto vazio ou herdado | 191-198, 1221-1233 | **Crítico.** Produto errado ou ausente no nome do arquivo, no S3 e no template | **Corrigir** — `RN-03.2`, `RN-03.3` |
| `DEF-10` | Chave reconstruída por parsing de rótulo com delimitadores `[ ] \|` | 258-263 | Alto — certificado com esses caracteres emite errado | **Corrigir** — `RN-17` |
| `DEF-11` | `LINHA_BRANCA` persistido como `TStringField` entre 8 colunas de cobertura `TFMTBCDField` | `.dfm` | Baixo — comparação e soma incorretas | **Investigar** — pode ser `VARCHAR` no banco (`GAP-15`) |
| `DEF-12` | Administradora resolvida pelo **nome**, sem filtro de status; falha silenciosa lista apólices de todas; `Edit1` sobrescrito no laço | 1147, 1168-1180, 1187-1188 | Alto | **Corrigir** — `RF-03`, `RF-15` |
| `DEF-13` | `seq` truncado em 3 caracteres em 5 pontos | 185, 390, 452, 1219, 1318 | Baixo hoje, alto quando `seq ≥ 1000` | **Corrigir** — `RN-09` |
| `DEF-14` | E-mail fabricado `cpf@nomeadministradora.com.br` enviado a sistema externo | `.dfm` SQLQuery8 | Médio — dado falso em integração | **Decidir com o negócio** |
| `DEF-15` | Modo não-*Individuais* apenas pré-visualiza; `nomearq := nomearq` sem efeito | 369-402 | Médio — operador não recebe o consolidado | **Corrigir** — `RN-12` |
| `DEF-16` | Competência com `DateEdit1` vazia resulta em `121899` | 681-682, 670 | Médio — pasta e caminho S3 errados | **Corrigir** — `RN-19` |
| `DEF-17` | No fluxo em massa, `Memo34` recebe `txtprod` antes de ela ter valor | 684-690 vs 806 | Médio — produto não impresso | **Corrigir** — `ADR-05` |
| `DEF-18` | Blocos de texto duplicados e sobrepostos no `.fr3` | PDF `15008` | Baixo, mas visível ao cliente | **Corrigir** no template novo |
| `DEF-19` | `WinExec` assíncrono sem verificação; link gravado sem confirmar upload | 348, 1071 | Alto — link para arquivo inexistente | **Corrigir** — `boto3`, `RF-16` |
| `DEF-20` | `UPDATE` concatenado; inteiro passado entre apóstrofos | 351-362 | Médio | **Corrigir** — `RN-06` |
| `DEF-21` | Destinatário de e-mail hardcoded (`albertocordeiro@gmail.com`) | 430 | Médio | **Corrigir** — configuração |

### Achado de segurança

| ID | Achado | Ação |
|---|---|---|
| `SEC-01` | Bloco `CONST` comentado com **`AccountKey` e `AccountName` da AWS em texto claro**, em fonte versionado num compartilhamento de rede | **Rotacionar as chaves imediatamente**, independentemente deste projeto. Remover do fonte e do histórico do Git. O sistema novo obtém credenciais de ambiente ou IAM role (`RNF-06`) |

`SEC-01` é a única recomendação deste documento que não deveria esperar pelo projeto novo.

---

## 14. Plano de implementação

Cada fase termina em algo demonstrável, e nenhuma depende de gap aberto que não esteja listado como pré-requisito.

### Fase 0 — Fundação *(sem pré-requisito)*
Estrutura de pastas, `pyproject.toml`, `.env.example`, `git init`, `CLAUDE.md`, esta especificação versionada, conexão Firebird provada por `SELECT 1`.
**Aceitação:** `pytest` roda; a conexão é verificável por comando.

### Fase 1 — Domínio e consultas *(pré-requisito: `GAP-15` para `DEF-11`)*
`domain/` completo; `queries.sql` com a consulta canônica e os filtros; `config/produtos.toml`; adaptador Firebird implementando a porta; testes unitários de cada `RN-*` e de integração de cada `QRY-*`.
**Aceitação:** dada uma chave real, `obter_certificado()` devolve `Certificado` tipado e completo. `RN-03.3` falha como especificado para apólice desconhecida. `RD-23` popula avisos.

### Fase 2 — JSON *(pré-requisito: Fase 1)*
`certificado-1.0.schema.json`; `serialize/json_certificado.py`; validação obrigatória antes da escrita.
**Aceitação:** JSON de certificado real valida; nulos aparecem como `null`; as 11 coberturas sempre presentes; avisos registrados.

> Esta fase entrega valor isolado antes de qualquer pixel de PDF, e é deliberado: o JSON é o requisito novo e o mais fácil de validar objetivamente. Rodando contra os três certificados de referência, ela já produz o dado estruturado que hoje não existe.

### Fase 3 — PDF *(pré-requisitos `GAP-09` e `GAP-13` fechados em 03/09/2026; layout único por `ADR-06`)*
Template único condicional (`ADR-05`); filtros de formatação (`RN-14`); `render/pdf.py`; modo consolidado; testes de fidelidade (`RNF-01`) e espelhamento (`RNF-04`).
**Aceitação:** o layout único renderiza com e sem o bloco Faz Tudo Lar; o diff contra `0_33016330725_0004_13008_380819.pdf` fica na tolerância, com as divergências declaradas (`DEF-06`, `DEF-08`, `RN-23`..`RN-26`) cobertas por teste próprio.

> **Estado em 03/09/2026:** entregue. `render/templates/certificado.html.j2` + `certificado.css` (página única 210 × 650 mm, medida do PDF de referência; imagens extraídas do próprio PDF e embutidas como data URI), `render/filtros.py` (`RN-14`), `render/pdf.py` (Chromium via Playwright, navegador reaproveitado no lote), comando `certgen emitir` (PDF + JSON) e `certgen html` (apoio ao ajuste de layout). Testes: espelhamento PDF↔JSON (`RNF-04`), tamanho de página, texto selecionável (`RNF-02`), Faz Tudo Lar opcional. **Pendente:** o diff de imagem automatizado de `RNF-01` — a conferência visual foi manual, lado a lado com o PDF de referência.

### Fase 4 — Tela web *(pré-requisito: Fases 1-3)*
FastAPI com os endpoints da cascata; página única com a máquina de estados de `5.2`; destino, opções, progresso e relatório final.
**Aceitação:** um operador emite uma fatura completa sem linha de comando, e a cascata invalida corretamente (`RF-01`).

> **Estado em 03/09/2026:** entregue. `certgen web` sobe FastAPI em `127.0.0.1` (`RNF-10`) com o menu de `ADR-07` e a página `/incendio`: cascata de `5.2` com invalidação (`RF-01`), *Imprime* só em S4 (`RF-02`), administradora por código (`RF-03`), marcar/desmarcar e contador `Seg.:N` (`RF-04`), colunas de `RF-05`, pasta validada antes (`RF-06`), *Individuais* com modo consolidado gravado (`RF-07`, `RF-08`, `DEF-15` corrigido), relatório emitidos/falhas (`RF-09`), *Imprime Premio* (`RF-10`), legendas literais (`RF-12`), Produto/Faz Tudo Lar/Locação somente-leitura (`RF-13`), todos marcados ao carregar (`RF-14`), chave estruturada nos itens (`RN-17`). *Só XML de Cert.* passa a significar *só JSON, sem PDF*. *Emissão:*, *Imprime/Geral* e *Upload AWS* aparecem desabilitados até as Fases 6 e 7. Sem autenticação (fora de escopo, `1.3`).

### Fase 5 — Adaptador de API *(pré-requisito: API disponível)*
`adapters/api/repositorio.py`; chave `CERTGEN_REPOSITORIO=firebird|api`; a suíte de domínio roda idêntica nos dois.
**Aceitação:** trocar a variável muda a origem sem alterar PDF nem JSON.

### Fase 6 — Emissão em massa *(pré-requisito: Fase 4)*
`QRY-07` como driver; estrutura `{raiz}/{administradora}/{competência}`; `RN-19` corrigido.
**Aceitação:** uma competência inteira emite com o mesmo caso de uso da Fase 4, parametrizado (`RF-11`).

### Fase 7 — Publicação e integração Porto *(pré-requisito: `SEC-01` resolvido, contrato XML especificado)*
`boto3` no lugar do `fedcorp.jar`; `registrar_link` com `RF-16`; XML de envio; e-mail configurável.
**Aceitação:** nenhum link é gravado sem upload confirmado.

---

## 15. Decisões arquiteturais

### `ADR-01` — Portas e adaptadores para a transição local → API
**Contexto.** Fase 1 lê Firebird; fase 5 lê API. A tentação é escrever contra o driver e "refatorar depois".
**Decisão.** Definir `RepositorioCertificados` desde o primeiro commit. Cada fase é um adaptador; a configuração escolhe.
**Consequências.** Custo de uma indireção. Em troca, a fase 5 é uma classe nova mais uma variável de ambiente, e os testes de domínio rodam sem banco.
**Rejeitada.** Acesso direto com refatoração posterior — na prática o SQL vaza para a regra de negócio e a migração deixa de ser viável. O legado é a demonstração: as cinco cópias da consulta canônica estão espalhadas por um `.dfm` de 70 MB.

### `ADR-02` — HTML + CSS renderizado por Chromium
**Contexto.** Cinco `.fr3` binários, com visibilidade manipulada por nome em runtime. Reproduzir com fidelidade um layout existente.
**Decisão.** Jinja2 → HTML/CSS de impressão → PDF via Playwright/Chromium.
**Consequências.** Layout em texto, diffável, revisável em pull request. Iteração abrindo o HTML no navegador. Custo: Chromium é ~150 MB e exige `playwright install chromium`.
**Rejeitadas.** *ReportLab* — posicionamento absoluto em código, ilegível em revisão. *WeasyPrint* — CSS moderno inferior justamente nos casos difíceis. *Automatizar o executável Delphi* — reintroduz a dependência que se quer eliminar.

### `ADR-03` — `Decimal` para dinheiro, `date` para datas, ISO no JSON
**Contexto.** `DEF-01` — o legado manipula datas como string e alterna o formato global.
**Decisão.** Converter na fronteira para `date`/`Decimal`. `float` proibido para dinheiro. JSON em ISO 8601 e string decimal; formatação brasileira só na apresentação.
**Consequências.** Elimina a classe de bugs de formato e de arredondamento. Exige disciplina de conversão na borda, onde atuam os testes de contrato.
**Nota.** O legado já usa `TFMTBCDField` — BCD, decimal exato. Usar `float` em Python seria regressão.

### `ADR-04` — Falhar alto em vez de emitir documento errado
**Contexto.** `DEF-04`, `DEF-05`, `DEF-06` e `DEF-09` produzem certificados plausíveis e errados, sem aviso.
**Decisão.** Produto indeterminado, consulta com 0 ou >1 linhas, ou JSON inválido **abortam aquele certificado** com erro registrado; o lote prossegue (`RF-09`). Anomalias que não impedem a emissão vão para `_meta.avisos` (`RD-23`).
**Consequências.** Lotes que "funcionavam" passarão a acusar erro — resultado desejado: expõe dados inconsistentes já existentes. **DEVE** haver uma rodada de validação em paralelo antes do corte, comparando a saída dos dois sistemas sobre a mesma competência.

### `ADR-05` — Um template condicional em vez de cinco arquivos
Registrado na seção `7.3`.

### `ADR-07` — Menu com três módulos de certificado
**Contexto.** Decisão do usuário em 03/09/2026: a tela deve ser o ponto de entrada para mais de um tipo de certificado.
**Decisão.** A aplicação web abre num **menu** com três opções: **CERTIFICADO INCENDIO** (este sistema, `/incendio`), **CERTIFICADO PRESTAMISTA/ALUG** (`/prestamista`) e **CERTIFICADO VIDA** (`/vida`). Os dois últimos não têm especificação e são exibidos como *Em preparação* (`GAP-21`, `GAP-22`). Cada módulo futuro entra como pacote próprio (`domain/`, `adapters/`, `render/`) sob o mesmo menu, o mesmo padrão de tela e a mesma porta `RepositorioCertificados`, quando fizer sentido.
**Consequências.** A navegação e o padrão visual ficam definidos antes dos módulos existirem; o Incêndio serve de modelo. Custo: dois cartões sem função até que as especificações cheguem.

### `ADR-06` — Um único layout de referência: o PDF `0_33016330725_0004_13008_380819.pdf`
**Contexto.** A matriz `7.3` tem cinco `.fr3` e só dois têm PDF de referência (`GAP-09`). Os `.fr3` estão embutidos no `.dfm` ou em um form não entregue.
**Decisão (usuário, 03/09/2026).** O layout do sistema novo é o do PDF `0_33016330725_0004_13008_380819.pdf` (`frxReportCntRupturaFT`), para **todos** os produtos e apólices. A única variação é o bloco **Assistência Faz Tudo Lar**, que é **opcional**: hoje governado por `RN-18` (`codigo_assist_mondial = '1003'`), e a regra definitiva de opcionalidade será definida pelo negócio depois — por isso a flag `faz_tudo_lar` do `ContextoTemplate` fica isolada e trocar a regra não toca o template. Ajustes de layout serão tratados conforme surgirem.
**Complemento (usuário, 03/09/2026) — `RF-13a`.** O checkbox **Faz Tudo Lar** da tela deixa de ser somente-leitura: decide se o bloco *Assistência Faz Tudo Lar* é impresso. Vem **pré-marcado** pela derivação `RN-18` e o operador pode alterá-lo antes de *Imprime*. A escolha vale para o lote inteiro, vai ao JSON em `_meta.faz_tudo_lar`, `produto.faz_tudo_lar` e `assistencia.faz_tudo_lar`, e quando divergir da derivação gera o aviso `FAZ_TUDO_LAR_MANUAL` (`RD-23`). Na CLI: `--faz-tudo-lar sim|nao`. **Locação** continua apenas derivada (`RF-13`). O texto do bloco é fixo por enquanto e passará a ser variável (regra a definir).

**Consequências.** `GAP-09` fecha com os textos legais deste PDF (redação A de Incêndio/Raio/Explosão/Perda de Aluguel, Assistência 24h, Faz Tudo Lar, rodapé). Os textos vão ao template **como estão** no PDF, inclusive erros de digitação, até compliance decidir (`GAP-19`). Os PDFs `..._15008_381066` deixam de ser referência de layout e ficam como casos de teste de dados (`RN-03.1`, `DEF-06`, `RD-22`). Os cinco nomes da matriz `7.3` viram apenas rastreabilidade: `_meta.template` passa a ser `"demonstrativo_v1"`, com `_meta.faz_tudo_lar: true|false`. `RNF-01` (fidelidade visual) passa a comparar apenas contra este PDF.
**Rejeitada.** Reproduzir os cinco `.fr3` — exigiria exportá-los do FastReport e triplicaria o esforço de fidelidade sem valor de negócio declarado.

---

## 16. Lacunas abertas

Estado após a análise do legado: **7 fechadas, 3 remanescentes, 5 novas**.

### Fechadas

| ID | Lacuna | Resposta |
|---|---|---|
| `GAP-01` | Fontes Delphi | Lidos: `.pas` 1.678 linhas, `.dfm` 70 MB |
| `GAP-02` | PDF de referência | Três PDFs lidos; matriz de 5 templates em `7.3` |
| `GAP-04` | Papel da Data de Emissão | Filtra `faturas.data_fat`, só no fluxo em massa (`RN-05`). A data impressa é a de geração (`RN-21`) |
| `GAP-05` | Semântica do `CheckBox5` | `endossos.cod_cat ∈ {'3','4'}`; escolhe o `.fr3`, não um bloco (`RN-04`). Hipótese anterior estava errada |
| `GAP-06` | Consulta do CheckListBox | É a consulta canônica com filtros de lote (`QRY-05`); a derivação da v0.1 estava correta |
| `GAP-07` | Produtos `0003` e `0005` | `0003` = Garantia do Condomínio, `0005` = Aluguel. Existem no domínio, não são emissíveis por esta tela |
| `GAP-08` | Primeiro campo do nome de arquivo | `codigo_pedido_port`, com `coalesce(...,0)`. O último campo é a **fatura**, não o certificado |

### Remanescentes

| ID | Lacuna | Bloqueia | Como fechar |
|---|---|---|---|
| `GAP-03` | DDL do Firebird | Tipos, PKs, `DEF-11`, `RSK` de fan-out | `isql -x` ou *Extract Metadata* do IBExpert, em `docs/legado/schema.sql` |
| `GAP-09` | Textos legais por produto | Fase 3 | Extraídos dos PDFs; **DEVEM** ser conferidos por quem responde pela conformidade |
| `GAP-10` | Diferença entre `rc`/`resp_civil` e `rup_encanamento`/`rup_enc_ter` | `RN-01` | Comparar rótulos nos `.fr3` |

### Novas

| ID | Lacuna | Bloqueia | Como fechar |
|---|---|---|---|
| `GAP-11` | Os PDFs de referência têm `portal = 0`, incompatível com o `> 0` do fluxo manual | Confirmar se `DEF-04` está ativo hoje | Emitir pelo botão **Imprime** um certificado com `codigo_pedido_port` nulo e ver se o PDF aparece |
| `GAP-12` | O filtro `pessoas.possui_portal = 'S'` existe no `.dfm` e está comentado no `.pas` | `QRY-07` | Perguntar se o fluxo em massa deve se restringir a administradoras com portal |
| `GAP-13` | Origem de `SUC.`, `PLANO`, `GARANTIA` e `CÓDIGO SUSEP DA CORRETORA` | Fase 3 | Abrir os `.fr3` no FastReport ou consultar o negócio |
| `GAP-14` | Os produtos `0003` e `0005` devem ser emissíveis no sistema novo? | `RN-03.2` | Decisão de negócio |
| `GAP-15` | `LINHA_BRANCA` é `VARCHAR` no banco ou é erro de persistência do `TField`? | `DEF-11`, `RN-01` | Depende de `GAP-03` |

### Fechadas em 03/09/2026, com acesso ao banco

DDL das seis tabelas extraído para `docs/legado/schema.sql` (somente leitura de `rdb$*`). Firebird 2.5 em `192.168.0.6`, `FATURA.GDB`. **Todas as colunas são `CHARACTER SET NONE`**: a decodificação depende do charset do cliente, por isso `FB_CHARSET=WIN1252` é obrigatório para acentos.

| ID | Resposta |
|---|---|
| `GAP-03` | DDL em `docs/legado/schema.sql`. Tipos reais: `FATURA INTEGER`, `SEQ INTEGER`, `CODIGO_PEDIDO_PORT INTEGER`, `CERTIFICADO VARCHAR(30)`, `ENDOSSO VARCHAR(11)`, `CPF_CNPJ VARCHAR(14)`, `INICIO_VIG`/`FINAL_VIG DATE`, monetários `DECIMAL(16,2)`. Confirma `RD-05` e a tabela 4.2. **PK de `segurados_inc` e de `segurados_inc_cob_aux` é `(ENDOSSO, CERTIFICADO)`.** `apolice_seguradora` tem PK `CODIGO`, não `(apolice, cod_seguradora)`. |
| `GAP-15` | `LINHA_BRANCA` é **`VARCHAR(1) DEFAULT 'N'`** no banco, com valores `N` (365.800), `S` (10.994) e `0` (25.905). **Não é importância segurada, é um flag.** O `TStringField` do `.dfm` estava certo; `DEF-11` deixa de ser defeito do legado e passa a ser erro da v0.1 desta especificação. Ver `GAP-16`. |

Verificações empíricas que alteram requisitos:

- **`RD-22` confirmado em escala:** 3.061 pares `(fatura, certificado)` repetidos em `segurados_inc` não cancelados. `certificado` não é único por fatura.
- **`RD-09` — o fan-out existe:** há 1 par `(fatura, certificado)` duplicado em `segurados_inc_cob_aux` e 1 par `(apolice, cod_seguradora)` duplicado em `apolice_seguradora`. Ver `GAP-17` e `GAP-18`.
- **Os PDFs de referência `..._15008_381066` são da administradora `0000000019`.** Logo `RN-03.1` se aplica a eles: o produto correto é **`0001` RESIDENCIAL**, não `0004`, e a emissão registra `PRODUTO_POR_EXCECAO`. No legado o fluxo manual saiu vazio (`DEF-09`) e o fluxo em massa teria saído `0001`. Os dois registros têm `final_vig = 30/12/1899` (`DEF-06` confirmado) e `codigo_pedido_port` nulo (`GAP-11` confirmado).
- **A chave real do PDF de referência `..._13008_380819` é `administradora = '0000001192'`, `seq = 1`, `endosso = '01112380819'`, `status_seg = 'R'`.** O exemplo canônico da seção 9.1 traz `0000004691` e `seq = 0`; ambos estão errados e **DEVEM** ser corrigidos junto com o campo `endosso`. A fatura 380819 tem 5 segurados. Verificado em 03/09/2026; o adaptador Firebird reproduz o certificado a partir dessa chave (teste de integração).
- **`endosso` ≠ `fatura`.** Nos registros acima `endosso = '01112381066'` e `fatura = 381066`. O exemplo canônico da seção 9.1 traz `"endosso": "380819"`, igual à fatura; está errado e **DEVE** ser corrigido quando o certificado real for lido.
- `ENDOSSOS.COD_CAT` assume `1`..`7`; `RN-04` (`{3,4}`) continua válida. `CODIGO_ASSIST_MONDIAL` assume `NULL`, `''`, `0`, `1000`, `1001`, `1002`, `1003`; `RN-18` continua válida.
- `GAP-12`: só 70 de 6.902 pessoas ativas têm `possui_portal = 'S'`. O filtro, se aplicado, reduz drasticamente o fluxo em massa. Decisão de negócio continua pendente.

### Novas em 03/09/2026

| ID | Lacuna | Bloqueia | Como fechar |
|---|---|---|---|
| `GAP-16` | ~~`LINHA_BRANCA` é flag `S`/`N`/`0`, não valor.~~ **Fechado em 03/09/2026 (decisão do negócio):** o campo não é necessário nesta fase. Sai do catálogo `RN-01` (11 coberturas), da projeção da consulta canônica e do JSON. Reabrir se o layout precisar dele. | — | — |
| `GAP-17` | ~~O `JOIN` com `segurados_inc_cob_aux` deve usar `(endosso, certificado)`?~~ **Fechado em 03/09/2026 (aprovado):** a consulta canônica passa a fazer o `JOIN` pela PK `(endosso, certificado)`. `RD-09` permanece como rede de segurança. | — | — |
| `GAP-21` | **CERTIFICADO PRESTAMISTA/ALUG** — módulo do menu (`ADR-07`) sem especificação. | Módulo Prestamista | Fonte/tela do sistema atual, PDFs de referência e consultas, como foi feito para o Incêndio. |
| `GAP-22` | **CERTIFICADO VIDA** — idem. | Módulo Vida | idem |
| `GAP-20` | ~~Logotipo da seguradora~~ **Fechado em 03/09/2026 por `RN-28`** (mapa em `config/seguradoras.toml`). Pendentes apenas os **arquivos** `hdi.png` e `porto.png` em `render/templates/img/seguradoras/`; até chegarem, Sompo/HDI e Porto saem com caixa vazia e aviso. | — | Usuário entrega os dois PNG. |
| `GAP-18` | ~~`apolice_seguradora` tem um par duplicado~~ **Fechado em 03/09/2026:** o par é a apólice `236` / seguradora `0000000003` (`CODIGO` 18 e 19, mesmos valores). Não é apólice de certificado (`RN-03.2`); `RD-09` cobre o caso se aparecer. Sem ação. | — | — |

### Estado de `GAP-09` e `GAP-13` em 03/09/2026

**`GAP-09` — textos legais.** Extraídos com `pypdf` para `docs/legado/textos-legais/*.txt`, um arquivo por PDF de referência. Cobrem **2 dos 5 templates** da matriz `7.3`:

| Template (`ContextoTemplate.nome`) | `.fr3` legado | PDF de referência | Texto |
|---|---|---|---|
| `incendio_ruptura_faz_tudo` | `frxReportCntRupturaFT` | `..._13008_380819` | ✓ extraído |
| `incendio` | `frxReportIncendio` | `..._15008_381066` (2) | ✓ extraído |
| `incendio_faz_tudo_24h` | `frxReportIncW24h` | — | **falta** |
| `locacao_simples` | `frxReportLocaSimples` | — | **falta** |
| `locacao_faz_tudo` | `frxReportIncIncLocaCFT` | — | **falta** |

Blocos identificados nos dois textos: (a) definição de Incêndio/Raio/Explosão/Perda de Aluguel — **duas redações diferentes** entre os templates, e o `15008` imprime as duas (é o `DEF-18`); (b) Assistência Residencial Emergencial 24h (Eletricista, Chaveiro, Bombeiro), idêntico nos dois; (c) Faz Tudo Lar, só no `13008`; (d) rodapé com Central 0800 770 4362, Central FedCorp 0800 251 6001, `sac@grupofedcorp.com.br` e o link das condições gerais. Erros de digitação preservados no `.txt` (`dentruindo-o`, `extremamemnte`, `recepientes`, `Assitência`, `DESINTETIZAÇÃO`).

**`GAP-09` fechado em 03/09/2026 por `ADR-06`:** há um único layout, o do PDF `..._13008_380819`, e seus textos são os do template. Não é mais necessário obter os outros três PDFs. Fica aberto apenas **`GAP-19`**: compliance decidir se os erros de digitação do legado (`dentruindo-o`, `extremamemnte`, `recepientes`, `Assitência`, `DESINTETIZAÇÃO`) são corrigidos ou preservados. Até lá, preservados.

**`GAP-13` — campos sem origem.** Busca nos metadados e nos dados do banco:

| Campo no PDF | Valor visto | Origem encontrada | Situação |
|---|---|---|---|
| `SUC.` | `RJ` | **`apolices.sucursal`** — `RJ` nas apólices `13008`/`0000001192` e `15008`/`0000000019`; 21.004 de 22.584 apólices são `RJ`, 1.573 `SP` (mais `sp`, `RK`, `.`, vazio — dado sujo) | **Fechado.** Projetar via `JOIN apolices ON (apolice, seq, administradora, cod_seguradora)`, que é a FK já existente. Normalizar para maiúsculas; valor fora de UF válida gera aviso `SUCURSAL_INVALIDA`. |
| `PLANO` | `RES` no `13008`, vazio no `15008` | Nenhuma coluna `%PLANO%` no banco | **Fechado em 03/09/2026 (decisão):** o campo sai **vazio** nesta fase. O rótulo permanece no layout; o tratamento será definido depois (`RN-23`). |
| `GARANTIA` | vazio nos dois | Nenhuma coluna `%GARANTIA%` | **Fechado em 03/09/2026 (decisão):** não é texto, é uma **imagem** (selo) que o negócio fornecerá em um segundo momento. Nesta fase o espaço fica reservado e vazio (`RN-24`). |
| `CÓDIGO SUSEP DA CORRETORA` | `00000202049583` | Não existe no banco: `corretores.cod_susep` está vazio para todos | **Fechado em 03/09/2026 (decisão):** valor **fixo** nesta fase. Vive na configuração `CERTGEN_SUSEP_CORRETORA` com esse padrão, e vai ao JSON em `contrato.susep_corretora` (`RN-25`). |

Os `.fr3` não estão na pasta `Delphi/` como arquivos: `frxReportIncendio` e `frxReportIncW24h` estão **embutidos no `.dfm`** deste form (70 MB), e os outros três no form `FrmRepositorioRel`, cujo fonte não foi entregue. Abrir os `.fr3` exige exportá-los do Delphi/FastReport ou permissão para vasculhar o `.dfm`.

Regras derivadas das decisões de 03/09/2026:

- **`RN-23` — PLANO.** Campo impresso **vazio** nesta fase; rótulo mantido. JSON: `contrato.plano: null`. Reabrir quando o negócio definir a regra.
- **`RN-24` — GARANTIA.** Espaço reservado no layout para uma **imagem** a ser fornecida; nesta fase, vazio. Não entra no JSON até existir.
- **`RN-25` — CÓDIGO SUSEP DA CORRETORA.** Constante de configuração `CERTGEN_SUSEP_CORRETORA`, padrão `00000202049583`. Impresso no rodapé e serializado em `contrato.susep_corretora`. Nunca literal no template.
- **`RN-27` — Bloco de texto do produto RUPTURA** *(decisão do usuário, 03/09/2026)*. As três linhas *RUPTURA DE TUBULAÇÕES HIDRÁULICAS … R$ x*, *RESPONSABILIDADE CIVIL TERCEIROS … R$ y* e *Para maiores informações … condicao_geral_fedcorp.pdf* do texto legal **só são impressas quando a Cobertura Ruptura de Encanamento é maior que zero** — o sinal confiável do produto `0004`. Caso contrário são inibidas. Produto `0004` sem valor de ruptura, ou ruptura com valor em outro produto, gera o aviso `RUPTURA_INCONSISTENTE` (`RD-23`), sem impedir a emissão.
- **`RN-28` — Logotipo da seguradora** *(decisão do usuário, 03/09/2026; fecha `GAP-20`)*. A caixa do bloco *Seguro Incêndio* imprime o logotipo escolhido por `segurados_inc.cod_seguradora` através do mapa de configuração `config/seguradoras.toml` (`codigo`, `nome`, `logo`), como o mapa de produtos (`RN-03.2`). Mapa vigente: Bradesco `0000000109` → Bradesco; **Alfa `0000000104` → Bradesco**; HDI `0000000108` → HDI; **Sompo `0000000003` → HDI**; Porto Seguro `0000000006` → Porto (entrará em duas administradoras; apólice ainda não alterada). FedCorp Assistance `0000000004` não entra em certificado. Código sem entrada, ou arquivo de logotipo ausente, imprime a caixa **vazia** e registra `LOGO_SEGURADORA_AUSENTE` (`RD-23`): nunca o logotipo errado em silêncio. O nome da seguradora vai ao JSON em `contrato.apolice.seguradora`. **Achado:** o PDF de referência (`cod_seguradora 0000000104`, Alfa) imprimia Bradesco porque o `.fr3` tinha a imagem fixa; a regra acima preserva esse resultado por decisão, não por acidente.
- **`RN-26` — SUC.** `apolices.sucursal`, projetado pela consulta canônica via `JOIN apolices ON (apolice, seq, administradora, cod_seguradora)`, normalizado para maiúsculas e sem espaços. Valor que não seja UF de 2 letras gera aviso `SUCURSAL_INVALIDA` (`RD-23`) e é impresso como veio. JSON: `contrato.sucursal`.

**`GAP-13` fechado. `GAP-09` fechado (`ADR-06`).** Fases 2, 3 e 4 entregues em 03/09/2026 (`certgen emitir`, `certgen web`). **Próximo passo imediato:** testes de uso pelo operador na tela, a regra definitiva de opcionalidade do Faz Tudo Lar (`ADR-06`) e as especificações dos módulos Prestamista e Vida (`GAP-21`, `GAP-22`).

~~**Próximo passo imediato:** `GAP-03`.~~ O DDL fecha `GAP-15`, dá tipos reais a todo o dicionário de dados e permite confirmar se o `JOIN` de `segurados_inc_cob_aux` por `(fatura, certificado)` pode multiplicar linhas — questão que hoje só se resolve com `RD-09`.

---

## 17. Rastreabilidade

| Origem | Itens gerados |
|---|---|
| Levantamento passo 1 | `QRY-01`, `RD-03`, `RD-07`, `RF-03`, `DEF-12` |
| Levantamento passo 2 | `RN-05`, `RN-21` |
| Levantamento passo 3 | `QRY-03`, `RN-08`, `RN-09`, `DEF-13` |
| Levantamento passo 4 | `QRY-04`, `RN-03`, `RN-06`, `RN-07`, `DEF-01`, `DEF-09` |
| Levantamento passo 5 | `RN-03.1`, `RN-03.2`, `RN-03.3`, `GAP-14` |
| Levantamento passo 6 | `QRY-05`, `RF-04`, `RF-05`, `RF-14`, `RN-10` |
| Levantamento passo 7 | `RF-06`, `RF-07`, `RN-11`, `RN-12`, `RN-13`, `DEF-15` |
| Levantamento passo 8 | `QRY-06`, `RD-01`, `RD-02`, `RD-04`, `RD-08`, `RD-09`, `RN-01`, `RN-02` |
| `.pas` linhas 156-437 (`Button1`) | `RN-11a`, `DEF-04`, `DEF-10`, `RF-09` |
| `.pas` linhas 624-1136 (`Button4`) | `QRY-07`, `RN-11b`, `RN-16`, `RN-19`, `RN-22`, `DEF-16`, `DEF-17` |
| `.pas` linhas 238-248 (`QRY-11`) | `RN-04`, `RN-18`, `GAP-05` fechado |
| `.pas` linhas 1202-1208 (comentário) | Catálogo de 7 produtos, `GAP-07` fechado |
| `.pas` linhas 1139-1193 (`ComboBox1Exit`) | `DEF-01`, `DEF-12`, `RF-15` |
| `.pas` linhas 138-144 | `SEC-01` |
| `.pas` linhas 345-362, 1069-1085 | `RD-20`, `RF-16`, `DEF-19`, `DEF-20`, seção 8 |
| `.dfm` — 7 `TSQLQuery` | `RD-17`, `RD-24`, `DEF-03` |
| `.dfm` — `TField` do `ClientDataSet1` | `RD-05`, `DEF-11` |
| `.dfm` — legendas dos controles | `RF-12`, `RF-13`, `DEF-07` |
| PDF `..._13008_380819` | Layout `7.4`, `RN-20`, `RN-21`, `RN-14` |
| PDFs `..._15008_381066` (par) | `RD-22`, `DEF-06`, `DEF-08`, `DEF-09`, `DEF-18` |
| Requisito novo (JSON) | `RD-10`..`RD-15`, `RD-23`, `RNF-04` |
| Faseamento local → API | `ADR-01`, `RD-16`, `RD-18`, `RN-15`, seção 11 |

**`RD-22`** — Os dois PDFs `..._15008_381066` compartilham fatura e apólice, têm CPFs e certificados distintos e residem na mesma unidade condominial. Confirma que **`certificado` não é único por fatura** e que a chave de emissão precisa de `cpf_cnpj` para desambiguar (`RD-01`, `RD-21`).

**`RD-09`** — A consulta de emissão **DEVE** retornar exatamente 1 linha. `0` ou `>1` **DEVEM** abortar aquele certificado com erro registrado, prosseguindo o lote (`RF-09`). Isso protege contra o fan-out possível do `JOIN` com `segurados_inc_cob_aux`, que usa apenas `(fatura, certificado)` — sem `administradora`, `apolice` nem `seq`. Se a duplicidade se confirmar legítima (`GAP-03`), o `JOIN` **DEVE** ser estendido.

---

## Anexo A — Bootstrap do projeto no VSCode com Claude Code

### A.1 Pré-requisitos

```powershell
python --version      # 3.12+
node --version        # 18+ (o CLI do Claude Code é Node)
git --version
```

### A.2 Instalar o Claude Code

```powershell
npm install -g @anthropic-ai/claude-code
claude --version
```

### A.3 Onde colocar o projeto *(revisado em 03/09/2026)*

**Decisão do usuário:** o desenvolvimento acontece **diretamente na pasta de rede** `U:\--2021\05-Gerador Certificados` (`\\192.168.0.2\Controle\--2021\05-Gerador Certificados`), com a `.venv` nessa pasta. O repositório remoto é o **GitHub da organização**: `https://github.com/fedcorpdesenvolvimento/CertificadosGerador.git`, branch `main`. A recomendação original de *bare repo* em `U:\` + clone em `C:\dev` **não se aplica mais**.

Fluxo de trabalho:
```powershell
cd "U:\--2021\05-Gerador Certificados"
git status                      # o que mudou
git add -A                      # ou arquivos especificos
git commit -m "RN-xx: descricao curta citando o ID"
git pull --rebase origin main   # traz o que houver no GitHub antes de enviar
git push                        # envia
```
Primeiro envio: `git remote add origin <url>` e `git push -u origin main`. O Git para Windows pede login no GitHub pelo navegador na primeira vez e guarda a credencial.

**`RNF-06a` — Dados pessoais no repositório.** `docs/legado/referencia/*.pdf` e `docs/legado/textos-legais/*.txt` contêm nomes, CPFs e endereços de segurados reais e estão versionados como referência de layout e de teste. O repositório do GitHub **DEVE** ser privado. Se a política da empresa exigir, esses arquivos **DEVEM** ser removidos do histórico antes do primeiro `push` (`git filter-repo`) e mantidos apenas na pasta de rede; os testes que os usam pulam quando eles não existem. O `.env` nunca é versionado (`.gitignore`: `.env`, `.env.*`).

*Texto original da v0.2, mantido para histórico:*



O `stage` de arquivos falhou em **todo** arquivo de `U:\` durante esta análise, e funcionou de primeira em `C:\Delphi` — o problema é a unidade de rede mapeada, não o conteúdo. A `.venv` e o cache do Chromium em `U:\` também ficam lentos e podem falhar por permissão ou caminho longo.

Recomendação: **repositório central em `U:\`, trabalho em disco local.**

```powershell
cd "U:\--2021\05-Gerador Certificados"
git init --bare repo.git

cd C:\dev
git clone "U:\--2021\05-Gerador Certificados\repo.git" gerador-certificados
cd gerador-certificados
```

Assim o versionamento fica no servidor, o trabalho roda local e o problema de leitura desaparece.

### A.4 Ambiente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .[dev]     # fdb, python-dotenv, fastapi, jinja2, playwright, pydantic, jsonschema, pypdf, boto3, pytest
playwright install chromium
```

### A.5 `.env.example`

```ini
# Firebird 2.5 - fase 1. Nomes FB_* iguais aos do EnvioPorto / FedHub-Backend,
# para o mesmo .env servir nos dois projetos (revisado em 03/09/2026).
FB_HOST=192.168.0.6
FB_PORT=3050
FB_DATABASE=E:\SISTEMA\BASE_CHEQUE\BASE\FATURA.GDB
FB_USER=
FB_PASSWORD=
FB_CHARSET=WIN1252
FB_POOL_SIZE=5

# Adaptador: firebird | api
CERTGEN_REPOSITORIO=firebird

# Fase 5
CERTGEN_API_BASE_URL=
CERTGEN_API_TOKEN=

# Saida
CERTGEN_PASTA_SAIDA=C:\certificados
CERTGEN_APOLICES_MASSA=4008,5008,10008,13008,14008,15008

# Fase 7 - NUNCA no codigo (SEC-01)
AWS_REGION=us-east-2
AWS_S3_BUCKET=certincendioaws
CERTGEN_EMAIL_DESTINO=
```

**`RNF-06`** — `.gitignore` **DEVE** conter `.env`, `.venv/`, `__pycache__/` e a pasta de saída. Certificado emitido é dado pessoal e não pode ser versionado.

### A.6 `CLAUDE.md`

Lido automaticamente no início de cada sessão. É o que faz o Claude Code trabalhar dentro da especificação em vez de improvisar.

```markdown
# Gerador de Certificados

Sistema Python que emite certificados de seguro incendio/conteudo em PDF
e o JSON espelhado, lendo Firebird. Reescrita de um gerador Delphi legado
(UfrmImprimeCertInc, 1.678 linhas).

## Regra numero um

`docs/ESPECIFICACAO.md` e a fonte da verdade. Todo codigo implementa um
requisito identificado (RF-nn, RN-nn, RD-nn, QRY-nn). Cite o ID no
docstring e na mensagem de commit.

Se a especificacao nao cobre o que preciso decidir, PARE e pergunte.
Nao invente regra de negocio. Itens GAP-nn da secao 16 estao abertos e
NAO devem ser implementados por suposicao.

## Arquitetura

Hexagonal (ADR-01). Dominio sem dependencias externas. Acesso a dados so
pela porta `RepositorioCertificados` — hoje adaptador Firebird, depois
adaptador de API. Nunca chame o driver de dentro do dominio.

## Regras invioláveis

- SQL sempre com bind parameters (RN-06). Nunca concatenar valores.
- Uma consulta canonica em queries.sql, filtros compostos em Python
  (RD-17). O legado tinha 5 copias divergentes; nao repetir isso.
- Dinheiro e `Decimal`; `float` proibido (RD-05).
- Datas sao `date`; ISO 8601 no JSON, dd/MM/yyyy no PDF (RD-06).
- Nenhuma formatacao global mutavel (RNF-12).
- Toda consulta a segurados_inc filtra status_seg <> 'C' e
  cpf_cnpj <> '' (RD-02, RD-19).
- Falhar alto em vez de emitir documento errado (ADR-04). Anomalias que
  nao impedem a emissao vao para _meta.avisos (RD-23).
- Nenhum efeito colateral antes do sucesso confirmado da etapa anterior
  (RF-16, RNF-11).
- O banco recebe UPDATE apenas em link_certificado_aws, dt_cria_link e
  id_controle_envio_portal (RNF-05).

## Comandos

- Testes: `pytest`
- Servidor: `uvicorn certgen.web.app:app --reload --host 127.0.0.1`
- CLI: `python -m certgen.cli --help`

## Legado

`Delphi/` e somente leitura. A analise esta na secao 13 da especificacao
(catalogo de 21 defeitos) e em docs/legado/ANALISE-DELPHI.md.
```

### A.7 `.claude/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Bash(pytest*)",
      "Bash(python*)",
      "Bash(pip*)",
      "Bash(git status*)",
      "Bash(git diff*)",
      "Bash(git log*)"
    ],
    "deny": [
      "Bash(rm*)",
      "Read(./.env)"
    ]
  }
}
```

### A.8 Primeira sessão

Abra a pasta no VSCode, abra o terminal integrado (`Ctrl+'`) e rode `claude`. Primeiro prompt:

```
Leia docs/ESPECIFICACAO.md por completo.

Implemente apenas a Fase 1, camada de dominio: domain/cobertura.py,
domain/produto.py, domain/documento.py, domain/dinheiro.py,
domain/nomes_arquivo.py e domain/avisos.py, cobrindo RN-01, RN-02,
RN-03, RN-03.1, RN-03.2, RN-03.3, RN-04, RN-11, RN-17b, RD-05, RD-12 e
RD-23. O mapa apolice->produto vem de config/produtos.toml (RN-03.2),
nao de if em codigo.

Escreva os testes unitarios junto, um por requisito, nomeados com o ID
(ex.: test_rn_03_3_apolice_desconhecida_aborta). Inclua como casos de
teste os tres arquivos de referencia da secao 7.2, incluindo o de
produto vazio (DEF-09), que deve passar a falhar explicitamente.

Nao toque em banco de dados nem em adaptadores nesta etapa. Nao
implemente nada relacionado a GAP-nn aberto.
```

Depois, uma fase por sessão, sempre citando os IDs. O padrão que funciona: **especificação → teste → implementação → commit citando o ID**.

### A.8a Compartilhar a tela com a equipe *(04/09/2026, `RNF-10a`)*

Na máquina que vai servir (ligada durante os testes, com acesso ao Firebird e com o Chromium do Playwright instalado):
```powershell
cd "U:\--2021\05-Gerador Certificados"
.\.venv\Scripts\python.exe -m certgen.cli web --rede --sem-navegador
```
O comando imprime os endereços `http://<ip-da-maquina>:8000/` que a equipe usa. Libere a porta no Firewall do Windows uma vez, em PowerShell como administrador:
```powershell
New-NetFirewallRule -DisplayName "Gerador de Certificados" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Domain,Private
```
A pasta de destino digitada na tela **DEVE** ser um caminho de rede que o servidor e a equipe enxerguem, por exemplo `\\192.168.0.2\Controle\Certificados`. Os PDFs são gerados pelo servidor; a equipe abre pela rede.

### A.8b Logotipos das seguradoras (`RN-28`)

Copiar os arquivos para `src\certgen\render\templates\img\seguradoras\` com os nomes exatos de `config\seguradoras.toml` (`bradesco.jpg`, `hdi.png`, `porto.png`). PNG com fundo transparente, cerca de 700 × 300 px. Reiniciar o `certgen web`. Sem o arquivo, a caixa sai vazia e o JSON recebe `LOGO_SEGURADORA_AUSENTE`.

### A.9 Extensões úteis

`Python` + `Pylance` · `Ruff` (lint e formatação) · `SQLTools` com driver Firebird, para inspecionar o banco sem sair do editor · `Even Better TOML` para `pyproject.toml` e `produtos.toml`.

---

*Fim do documento. Versão 0.2 — `DRAFT`. Atualize a especificação antes do código, nunca depois.*

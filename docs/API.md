# APIs do Gerador de Certificados

Referência das duas aplicações HTTP do projeto. Escrita a partir do código em
`src/certgen/web/` e da especificação (`docs/ESPECIFICACAO.md`, seções 5, 8, 9 e 11.1);
os IDs entre parênteses apontam para os requisitos que cada comportamento implementa.

| Aplicação | Comando | Porta padrão | Público | Autenticação |
|---|---|---|---|---|
| **API do portal** (`certgen.web.api_portal`) | `python -m certgen.cli api` | 8010 | portal do segurado | header `X-API-Key` (RN-30) |
| **API da tela** (`certgen.web.app`) | `python -m certgen.cli web` | 8000 | operador de emissão, via navegador | nenhuma (LAN, RNF-10) |

As duas usam **o mesmo caso de uso** de emissão, a mesma consulta canônica, o mesmo template de
PDF e o mesmo serializador JSON (RF-11, RNF-08). Um ajuste no certificado vale nos dois canais
sem trabalho adicional. Ambas expõem `/docs` (Swagger) e `/openapi.json` gerados pelo FastAPI.

Nenhuma das duas tem TLS próprio: só na rede interna; exposição externa exige proxy HTTPS
(GAP-23).

---

## 1. API do portal — `certgen api`

### 1.1 Subir

```powershell
python -m certgen.cli api            # 127.0.0.1:8010
python -m certgen.cli api --rede     # 0.0.0.0:8010 — portal chega pela LAN (RNF-10b)
```

Exige no `.env` (SEC-01, RNF-06):

| Variável | Uso |
|---|---|
| `CERTGEN_API_KEY` | chave de 128 bits em hex (32 caracteres). Sem ela o processo **recusa subir**. Gerar: `python -c "import secrets;print(secrets.token_hex(16))"` |
| `FB_*` | conexão Firebird (`FB_HOST`, `FB_PORT`, `FB_DATABASE`, `FB_USER`, `FB_PASSWORD`, `FB_CHARSET`, `FB_POOL_SIZE`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_S3_BUCKET` | publicação no S3 (RN-29). Padrões: `us-east-2`, `certincendioaws` |
| `CERTGEN_PASTA_SAIDA` | cópia local de PDF e JSON, estrutura `{administradora}/{MMAAAA}/` (RN-34, RN-19) |

Operação no servidor da rede: `scripts/iniciar_api.ps1` (reinício automático, log diário em
`logs/api-AAAA-MM-DD.log`). Passo a passo de teste: `docs/TESTE-API-POSTMAN.md`; Collection e
Environments prontos em `docs/postman/`.

### 1.2 Autenticação

Todo endpoint exige o header `X-API-Key: <chave>`. Comparação em tempo constante; a chave nunca
aparece em log, resposta ou erro (RN-30). Chave ausente ou errada:

```
401  {"detail": "chave de autenticacao ausente ou invalida"}
```

Há uma única chave para o portal inteiro; rotação implica janela sem serviço (GAP-24).

### 1.3 `GET /v1/saude`

Valida a chave e devolve a versão do servidor (RF-18).

```json
{"ok": true, "versao": "0.1.0"}
```

### 1.4 `POST /v1/segurados/verificar` — login do segurado (UC-13, RF-20)

Responde se o CPF/CNPJ é segurado da administradora e devolve as vigências mais recentes, para
o portal autenticar o segurado em tempo real e, em seguida, pedir a emissão já apontando a
unidade. **Não grava nada.**

**Corpo**

```json
{"administradora": "0000001192", "cpf_cnpj": "330.163.307-25"}
```

| Campo | Regra |
|---|---|
| `administradora` | código `pessoas.pessoa`, com zeros à esquerda, até 10 caracteres |
| `cpf_cnpj` | pontuação aceita e removida; precisa ter 11 (CPF) ou 14 (CNPJ) dígitos |

**Resposta `200`**

```json
{
  "existe": true,
  "quantidade": 2,
  "certificados": [
    {
      "nome": "JORGE EDUARDO MONT SERRAT",
      "endereco": {"logradouro": "AV LUCIO COSTA, 3300 BLOCO 2", "unidade": "AP.602",
                   "bairro": "BARRA DA TIJUCA", "cidade": "RIO DE JANEIRO", "uf": "RJ",
                   "cep": "22630010", "condominio": "DIRETORIA IMODATA"},
      "inicio_vig": "2026-08-01",
      "final_vig": "2026-08-31",
      "apolice": "13008", "seq": 1, "fatura": 381201, "certificado": "CF1DI/AP.602",
      "produto": {"codigo": "0117", "nome": "...", "descricao_fatura": "...", "descricao_master": "TOTAL CONTEÚDO"}
    }
  ]
}
```

- `existe` é `true` se há **qualquer linha não cancelada** do documento na administradora, sem
  filtro de vigência (RN-35). Vigência encerrada não dá `false`; documento de outra
  administradora, inexistente ou cancelado dá `false` com `quantidade: 0` e lista vazia.
- `certificados` traz as **3 vigências mais recentes** (3 valores distintos de `inicio_vig`),
  com **todas** as unidades de cada uma (RN-35a, RD-30). Ordem: `inicio_vig` decrescente,
  `fatura` decrescente, `certificado`.
- `final_vig` nulo ou `30/12/1899` no banco sai como `null` (DEF-06).
- Guarde `inicio_vig`, `fatura` e `certificado` do item escolhido: são exatamente os campos que
  a emissão aceita (RD-31).

**Erros**

| Código | Situação |
|---|---|
| `400` | administradora vazia ou com mais de 10 caracteres; documento sem 11 ou 14 dígitos |
| `401` | chave ausente ou inválida |
| `422` | corpo malformado (campo faltando, tipo errado) |
| `503` | banco indisponível |

Log (RNF-13): um registro JSON por chamada com administradora, documento, `existe`, chaves das
vigências e duração. Sem chave, sem nome, sem endereço.

Atenção: o endpoint é um oráculo de existência de CPF protegido só pela chave, sem limite de
taxa; a resposta traz dados pessoais (GAP-26). Não expor fora da LAN sem TLS e limite de taxa.

### 1.5 `POST /v1/certificados/emitir` — emissão (UC-12, RF-18)

Localiza o certificado, gera JSON e PDF, publica o PDF no S3, grava o link no Firebird, regrava
o JSON com o link e devolve link e JSON espelho na mesma resposta. Síncrono: um PDF leva alguns
segundos (Chromium). **Sempre reemite** (RN-33): objeto no S3 e arquivos locais são sobrescritos.

**Corpo**

```json
{
  "administradora": "0000001192",
  "cpf_cnpj": "330.163.307-25",
  "vigencia": "2026-08-01",
  "fatura": 381201,
  "certificado": "CF1DI/AP.602"
}
```

| Campo | Regra |
|---|---|
| `administradora` | como na verificação |
| `cpf_cnpj` | como na verificação |
| `vigencia` | ISO 8601 (`AAAA-MM-DD`) e **igual** a `segurados_inc.inicio_vig` (RN-31). Não é "data dentro do período" |
| `fatura` | opcional, inteiro positivo; vem da verificação (RD-31) |
| `certificado` | opcional; vem da verificação (RD-31). Com `fatura` e `certificado`, emite só aquela unidade |

Sem `fatura`/`certificado`, **todos** os certificados do documento naquela vigência são emitidos
(RN-32), um item por certificado.

**Sequência por certificado** (RF-16): localizar → JSON validado contra o schema → PDF →
`publicar` no S3 com confirmação (`head_object`, DEF-19) → `registrar_link` no Firebird
(exatamente 1 linha, RD-20a) → regravar JSON com `arquivo.link`. Falha em qualquer passo
interrompe **aquele** certificado; os demais seguem (RF-09). Nunca se devolve link cuja
gravação no banco não foi confirmada.

**Resposta `200`** (ao menos um item publicado)

```json
{
  "pedido": {"administradora": "0000001192", "cpf_cnpj": "33016330725", "vigencia": "2026-08-01",
             "fatura": 381201, "certificado": "CF1DI/AP.602"},
  "quantidade": 1,
  "certificados": [
    {
      "chave": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 381201,
                "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725"},
      "situacao": "publicado",
      "link": "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192/0004/082026/381201/0_33016330725_0004_13008_CF1DI-AP602_381201.pdf",
      "documento": { "...": "JSON espelho completo (seção 2), com arquivo.link igual ao link" },
      "avisos": ["REEMISSAO"],
      "motivo": null
    }
  ]
}
```

| Campo do item | Significado |
|---|---|
| `situacao` | `publicado` ou `falha` |
| `link` | URL pública do PDF no S3 (RN-29): `https://{bucket}.s3.{região}.amazonaws.com/{administradora}/{produto}/{MMAAAA}/{fatura}/{nome_pdf}` |
| `documento` | o JSON espelho **exatamente** como gravado em disco (RD-29, RNF-08) |
| `avisos` | códigos de `_meta.avisos` (seção 2.3) mais `REEMISSAO` quando a linha já tinha link (RD-28) |
| `motivo` | em `falha`: `[TipoDaExcecao] mensagem` |

**Erros**

| Código | Situação |
|---|---|
| `400` | pedido inválido (mesmas regras da verificação; `vigencia` não ISO; `fatura` não positiva) |
| `401` | chave ausente ou inválida |
| `404` | nenhum certificado para administradora + documento + vigência (+ fatura/certificado), ou apólice sem produto mapeado (RN-03.3). Corpo: `{"erro", "pedido"}` |
| `422` | corpo malformado |
| `502` | **todos** os certificados falharam (S3 fora, credencial AWS ausente, `UPDATE` não afetou 1 linha…). Cada item traz `situacao: "falha"` e `motivo` |
| `503` | Chromium/Playwright indisponível |

Se o S3 confirmou e o `UPDATE` falhou, o objeto fica no bucket e o item sai `falha` com motivo
explícito.

---

## 2. O JSON espelho do certificado

O `documento` da emissão e o arquivo `.json` gravado em disco são o mesmo objeto: **o certificado
modelado como dado**, com tudo que o PDF imprime e nada além disso, exceto os blocos `_meta` e
`_origem` (RD-10). Validado contra `docs/schema/certificado-1.0.schema.json` **antes** do PDF ser
gerado (RD-15, RF-16). Exemplo completo na seção 9.1 da especificação.

### 2.1 Blocos

| Bloco | Conteúdo |
|---|---|
| `_meta` | `versao_schema`, `gerado_em` (ISO com fuso), `gerado_por`, `template`, `faz_tudo_lar`, `modo_conexao`, `avisos[]` |
| `arquivo` | `pdf` (nome do arquivo), `pasta_destino` (`{administradora}/{MMAAAA}`), `link` (URL do S3 após upload confirmado; `null` sem upload) (RD-25) |
| `certificado` | `numero`, `cod_0800` (certificado + abreviação da administradora, RN-20), `data_emissao` |
| `produto` | `codigo` (4 dígitos), `descricao`, `descricao_curta`, `locacao`, `faz_tudo_lar` |
| `contrato` | `apolice{codigo, seq, numero_seguradora, cod_seguradora, seguradora}`, `fatura`, `endosso`, `processo_susep`, `codigo_pedido_porto`, `estipulante`, `sucursal`, `plano`, `susep_corretora` |
| `administradora` | `codigo`, `nome`, `abreviacao`, `papel` |
| `segurado` | `nome`, `documento{tipo, numero, formatado}` |
| `vigencia` | `inicio`, `fim` (ISO; `fim` `null` quando ausente ou zero-Delphi, DEF-06) |
| `local_risco` | `endereco`, `unidade`, `condominio`, `bairro`, `cidade`, `uf`, `cep` |
| `coberturas[]` | **sempre as 11** do catálogo, nesta ordem, com `codigo`, `nome`, `importancia_segurada` (string decimal ou `null`), `contratada`, e `derivada: true` na `COB_INCENDIO` (RN-01, RD-11) |
| `premio` | `valor_total`, `moeda`, `impresso_no_pdf` |
| `assistencia` | `codigo_mondial`, `faz_tudo_lar`, `central_atendimento`, `central_fedcorp` |
| `_origem` | `banco` (`FIREBIRD` ou `API`), `consulta` (`certificado_base`), `chave` (RD-01) |

Convenções (ADR-03): dinheiro como **string decimal** com duas casas (`"100000.00"`), nunca
número de ponto flutuante (RD-05); datas ISO 8601 (RD-06); campo nulo aparece como `null`, nunca
omitido nem string vazia (RD-13).

### 2.2 Campos derivados que o portal deve conhecer

| Campo | Regra |
|---|---|
| `contrato.plano` | `RES` se `segurados_inc.tipo_categoria = 'R'`; `COM` para qualquer outro código; `INC` se nula ou vazia (RN-23, 15/09/2026) |
| `produto.faz_tudo_lar` / `assistencia.faz_tudo_lar` / `_meta.faz_tudo_lar` | `true` se `codigo_assist_mondial = '1003'` **ou** Cobertura Ruptura de Encanamento > 0 (RN-18, RN-18a). Na tela o operador pode alterar; na API vale a derivação |
| `produto.codigo` | resolvido pela apólice (e administradora) em `config/produtos.toml` (RN-03); apólice sem regra aborta o certificado |
| `contrato.apolice.seguradora` | nome resolvido por `cod_seguradora` em `config/seguradoras.toml` (RN-28) |
| `coberturas[COB_INCENDIO]` | `inc_conteudo + inc_predio`, recalculada e conferida com o banco (RN-02) |

### 2.3 Códigos de aviso (`_meta.avisos[].codigo`, RD-23)

Anomalias que **não** impedem a emissão. Cada item tem `codigo` e `detalhe`.

| Código | Situação |
|---|---|
| `ABREV_ADM_AUSENTE` | administradora sem `abrev`; `cod_0800` sai incompleto (RN-20) |
| `FINAL_VIG_AUSENTE` | `final_vig` nula ou `30/12/1899` (DEF-06) |
| `COB_INCENDIO_DIVERGENTE` | soma recalculada difere do valor do banco (RN-02) |
| `DOCUMENTO_INDEFINIDO` | `cpf_cnpj` sem 11 nem 14 dígitos (RD-12) |
| `PORTAL_AUSENTE` | `codigo_pedido_port` nulo (GAP-11) |
| `PRODUTO_POR_EXCECAO` | produto resolvido por regra apólice + administradora (RN-03.1) |
| `SUCURSAL_INVALIDA` | `apolices.sucursal` não é UF (RN-26) |
| `FAZ_TUDO_LAR_MANUAL` | operador da tela contrariou a derivação RN-18/RN-18a |
| `RUPTURA_INCONSISTENTE` | produto `0004` sem ruptura > 0, ou ruptura em outro produto (RN-27) |
| `LOGO_SEGURADORA_AUSENTE` | `cod_seguradora` sem logotipo configurado (RN-28) |
| `REEMISSAO` | só na resposta da API e no relatório: a linha já tinha link e foi substituído (RN-33) |

---

## 3. API da tela — `certgen web`

Backend da página `/incendio`. Sem autenticação: destina-se à rede interna (RNF-10, RNF-10a).
Usa a mesma emissão e o mesmo JSON da API do portal; a diferença é o fluxo em cascata do
operador (seção 5.2 da especificação) e o upload opcional.

```powershell
python -m certgen.cli web                      # 127.0.0.1:8000, abre o navegador
python -m certgen.cli web --rede --sem-navegador   # equipe pela LAN (liberar a porta 8000)
python -m certgen.cli web --reload             # desenvolvimento
```

### 3.1 Páginas

| Rota | Conteúdo |
|---|---|
| `GET /` | menu com os três módulos (ADR-07): Incêndio ativo; Prestamista/Alug e Vida em preparação (GAP-21/22) |
| `GET /incendio` | tela do Incêndio |
| `GET /prestamista`, `GET /vida` | "em preparação" |
| `GET /static/*` | CSS e JS, sempre com `?v=<hash do conteúdo>` e `Cache-Control: no-cache` (ver 3.5) |

### 3.2 Cascata (só leitura)

| Rota | Parâmetros | Resposta |
|---|---|---|
| `GET /api/incendio/administradoras` | — | `[{codigo, nome, abrev, possui_portal}]` (QRY-01) |
| `GET /api/incendio/apolices` | `administradora` (obrigatória, RF-15), `inicio_vig` (ISO, opcional), `data_fat` (ISO, opcional, RN-05a) | `[{apolice, seq, rotulo}]`; rótulo `apolice.seq` (RN-08) |
| `GET /api/incendio/faturas` | `administradora`, `apolice`, `seq`, `inicio_vig`?, `data_fat`? | `[fatura, ...]` |
| `GET /api/incendio/segurados` | `administradora`, `apolice`, `seq`, `fatura` | ver abaixo |

`GET /api/incendio/segurados` devolve o lote completo (RD-24) com os derivados da RF-13:

```json
{
  "lote": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 381201},
  "quantidade": 5,
  "produto": "RUPTURA",
  "faz_tudo_lar": true,
  "locacao": false,
  "segurados": [
    {
      "chave": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 381201,
                "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725"},
      "certificado": "CF1DI/AP.602", "portal": null, "documento": "330.163.307-25",
      "nome": "JORGE EDUARDO MONT SERRAT", "endereco": "AV LUCIO COSTA, 3300 BLOCO 2", "unidade": "AP.602",
      "inicio_vig": "2026-08-01", "final_vig": "2026-08-31", "vigencia": "01/08/2026 a 31/08/2026",
      "produto": "0004", "produto_curto": "RUPTURA", "faz_tudo_lar": true, "locacao": false,
      "avisos": ["ABREV_ADM_AUSENTE", "PORTAL_AUSENTE"]
    }
  ]
}
```

A `chave` viaja estruturada (RD-01, RN-17) e é o que a emissão recebe em `selecionados`; o texto
das colunas é só apresentação. `faz_tudo_lar` do lote pré-marca o checkbox da tela (RF-13a,
RN-18/RN-18a). `422` quando a apólice não tem produto mapeado (RN-03.3).

### 3.3 `POST /api/incendio/emitir` — emissão pela tela (UC-01..05)

**Corpo**

```json
{
  "administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 381201,
  "pasta": "C:\\Temporario",
  "selecionados": null,
  "imprime_premio": false,
  "faz_tudo_lar": true,
  "individuais": true,
  "json_unico": false,
  "so_xml": false,
  "competencia": null,
  "upload_aws": true,
  "versao_tela": "0.1.0"
}
```

| Campo | Padrão | Significado |
|---|---|---|
| `pasta` | — | pasta de destino; validada como existente e gravável **antes** de emitir (RF-06) |
| `selecionados` | `null` | lista de `chave`; `null` = todos os segurados do lote (RF-14) |
| `imprime_premio` | `false` | imprime a linha PREMIO no rodapé (RF-10) |
| `faz_tudo_lar` | `null` | escolha do operador; `null` = derivação RN-18/RN-18a. Divergência gera `FAZ_TUDO_LAR_MANUAL` (RF-13a) |
| `individuais` | `true` | `false` = um PDF consolidado do lote + um JSON com o array (RF-07) |
| `json_unico` | `false` | PDFs individuais e **um** JSON do lote indexado por `cpf_cnpj\|certificado` (RD-26) |
| `so_xml` | `false` | só JSON, sem PDF |
| `competencia` | `null` | data ISO para a pasta `{MMAAAA}`; padrão `inicio_vig` (RN-19) |
| `upload_aws` | `false` | publica cada PDF no S3, grava o link no banco e no JSON (RF-21). Exige PDF; vale nos três modos, inclusive consolidado |
| `versao_tela` | — | versão do servidor gravada na página; a tela envia sozinha (ver 3.5) |

Campo desconhecido no corpo é `422`.

**Resposta `200`** (relatório da emissão, RF-09)

```json
{
  "lote": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 381201},
  "pasta": "C:\\Temporario",
  "emitidos": [
    {
      "chave": {"...": "..."},
      "json": "C:\\Temporario\\0000001192\\082026\\0_33016330725_0004_13008_CF1DI-AP602_381201.json",
      "pdf":  "C:\\Temporario\\0000001192\\082026\\0_33016330725_0004_13008_CF1DI-AP602_381201.pdf",
      "avisos": ["ABREV_ADM_AUSENTE", "PORTAL_AUSENTE"],
      "colisao": false,
      "link": "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192/0004/082026/381201/0_33016330725_0004_13008_CF1DI-AP602_381201.pdf",
      "vigencia": "01/08/2026 a 31/08/2026"
    }
  ],
  "falhas": [
    {"chave": {"...": "..."}, "tipo": "ErroPublicacao", "motivo": "..."}
  ],
  "consolidado_pdf": null,
  "consolidado_json": null,
  "json_unico": null,
  "publicados": 1
}
```

- `colisao: true` = já havia arquivo com o mesmo nome e o novo saiu com sufixo ` (1)` (RN-13; a
  tela **não** sobrescreve, diferente da API do portal).
- `link` só vem com `upload_aws`; `publicados` conta os itens com link.
- Falha de um certificado (JSON inválido, produto indeterminado, S3, `UPDATE`) vai para `falhas`
  com o tipo da exceção; os demais seguem (RF-09).

**Erros**

| Código | Situação |
|---|---|
| `400` | pasta inexistente/sem escrita (RF-06); `upload_aws` com `so_xml` (RF-21) |
| `409` | `versao_tela` ausente ou diferente da versão do servidor: "Tela desatualizada, recarregue com Ctrl+F5" |
| `422` | corpo malformado ou campo desconhecido; apólice sem produto (RN-03.3) |
| `503` | Chromium/Playwright indisponível |

Nomes dos arquivos (RN-11): `{portal}_{cpf_cnpj}_{produto}_{apolice}_{certificado}_{fatura}.pdf|json`
em `{pasta}\{administradora}\{MMAAAA}\`; consolidado e JSON único:
`certificados_{apolice}_{seq}_{fatura}_{AAAAMMDD-HHMMSS}.pdf|json` (RN-12).

### 3.4 Auxiliares

| Rota | Uso |
|---|---|
| `GET /api/saude` | `{"ok": true, "versao": "..."}` |
| `POST /api/escolher-pasta` `{"inicial": "C:\\..."}` | abre o diálogo nativo de pastas **na máquina do servidor**; `403` se o navegador não for local; `501` sem sessão gráfica |
| `POST /api/encerrar` | botão *Sair* do menu; encerra o servidor. `403` se não for local |

"Local" = navegador em loopback ou em qualquer IP da própria máquina do servidor (RNF-10a).

### 3.5 Versão da tela e cache

Em 15/09/2026 o navegador reutilizou `incendio.js` do cache depois de uma alteração: a página
nova mostrava o checkbox *Upload AWS*, o script antigo não enviava o campo e a emissão saía sem
upload e sem erro. Proteções em vigor:

- estáticos servidos em `/static/*?v=<hash do conteúdo>` e com `Cache-Control: no-cache`;
- a página grava a versão do servidor em `data-versao` e o JS envia `versao_tela` em cada
  emissão; divergência ou ausência é `409` com instrução de recarregar;
- campo desconhecido no pedido é `422`.

Após atualizar o código: reinicie o processo (`certgen web` e `certgen api` não recarregam
sozinhos) e, na primeira abertura, `Ctrl+F5`.

---

## 4. Referências

- `docs/ESPECIFICACAO.md` — fonte da verdade; seção 11.1 (API do portal), 5 (tela), 8 (S3 e
  banco), 9 (JSON), 16 (lacunas abertas).
- `docs/schema/certificado-1.0.schema.json` — schema do JSON espelho.
- `docs/TESTE-API-POSTMAN.md` e `docs/postman/` — teste manual e operação da API na rede.
- `/docs` em cada aplicação — Swagger gerado pelo FastAPI, sempre atualizado com o código.

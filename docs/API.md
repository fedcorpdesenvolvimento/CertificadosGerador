# APIs do Gerador de Certificados

Referência das duas aplicações HTTP do projeto. Escrita a partir do código em
`src/certgen/web/` e da especificação (`docs/ESPECIFICACAO.md`, seções 5, 8, 9 e 11.1);
os IDs entre parênteses apontam para os requisitos que cada comportamento implementa.

| Aplicação | Comando | Porta padrão | Público | Autenticação |
|---|---|---|---|---|
| **API do portal** (`certgen.web.api_portal`) | `python -m certgen.cli api` | 8010 | portal do segurado | header `X-API-Key`: chave por cliente, cadastrada na tela (RN-30 revista, ADR-09) |
| **API da tela** (`certgen.web.app`) | `python -m certgen.cli web` | 8000 | operador de emissão, via navegador | sessão com login (ADR-08) |

As duas usam **o mesmo caso de uso** de emissão, a mesma consulta canônica, o mesmo template de
PDF e o mesmo serializador JSON (RF-11, RNF-08). Um ajuste no certificado vale nos dois canais
sem trabalho adicional. A API do portal expõe o contrato em `/v1/docs` e `/v1/openapi.json`;
a tela não publica OpenAPI (ADR-08).

Nenhuma das duas tem TLS próprio: fora da LAN só atrás do proxy HTTPS da hospedagem
(`certgen servidor --proxy`).

---

## 1. API do portal — `certgen api`

### 1.0 Changelog do contrato `/v1`

Regra de versionamento (ADR-09): mudança **compatível** (campo novo, aviso novo, código de erro
novo) entra em `/v1` e aparece aqui; mudança **incompatível** vira `/v2` com período de
convivência.

| Data | Mudança | Compatível? |
|---|---|---|
| 28/10/2026 | Envelope único de erro `{codigo, mensagem, request_id, detalhes}` em todo erro de `/v1` (antes: `detail`, `erro` ou o formato do framework) | **não** (feita antes de o portal programar contra o formato antigo) |
| 28/10/2026 | `link` passa a ser URL **assinada com prazo**; novo campo `link_expira_em`; o link permanente fica em `documento.arquivo.link` | não (quem guardava `link` deve guardar os identificadores) |
| 28/10/2026 | Novos: `POST /v1/certificados/link`, `GET /v1/administradoras`, header `X-Request-Id`, `429` com `Retry-After`, `403` fora do escopo da chave, `cliente`/`chave`/`administradoras` em `/v1/saude`, `/v1/openapi.json` e `/v1/docs` | sim |
| 14/09/2026 | Verificação devolve as 3 vigências com dados (RD-30); emissão aceita `fatura`/`certificado` (RD-31) | sim |
| 10/09/2026 | Primeira versão: `/v1/saude`, `/v1/certificados/emitir` | — |

### 1.1 Subir

```powershell
python -m certgen.cli api            # 127.0.0.1:8010
python -m certgen.cli api --rede     # 0.0.0.0:8010 — portal chega pela LAN (RNF-10b)
python -m certgen.cli servidor --rede --proxy --porta 8000   # tela + /v1 (Render)
```

Variáveis (SEC-01, RNF-06):

| Variável | Uso |
|---|---|
| `CERTGEN_USUARIOS_DB` | SQLite com usuários **e chaves da API** (ADR-08/ADR-09). No Render: `/data/usuarios.sqlite` |
| `CERTGEN_API_KEY` | **opcional, transição** (ADR-09): se presente, vale como chave com acesso a todas as administradoras. Cadastre as chaves na tela e remova |
| `CERTGEN_LINK_VALIDADE_SEG` | validade da URL assinada do PDF, em segundos (padrão `900`, faixa 60–86400) |
| `FB_*` | conexão Firebird (`FB_HOST`, `FB_PORT`, `FB_DATABASE`, `FB_USER`, `FB_PASSWORD`, `FB_CHARSET`, `FB_POOL_SIZE`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_S3_BUCKET` | publicação no S3 (RN-29) e assinatura dos links. O bucket é **privado** (Block Public Access); a credencial precisa de `s3:PutObject` e `s3:GetObject` |
| `CERTGEN_PASTA_SAIDA` | cópia local de PDF e JSON, estrutura `{administradora}/{MMAAAA}/` (RN-34, RN-19) |

Operação no servidor da rede: `scripts/iniciar_api.ps1`. Teste manual: `docs/TESTE-API-POSTMAN.md`;
Collection e Environments em `docs/postman/`. Contrato OpenAPI: `/v1/openapi.json` e `/v1/docs`.

### 1.2 Autenticação, escopo e limites (RN-30 revista, ADR-09)

Todo endpoint exige o header `X-API-Key: <chave>`. As chaves são cadastradas pelo ADMIN na tela
(`/chaves`, seção 3.7): **uma por cliente integrador**, com a lista de administradoras que ela
pode consultar, IPs de origem opcionais e revogação imediata. O banco guarda só o SHA-256; a
chave aparece uma única vez, ao ser criada. Comparação em tempo constante; a chave nunca
aparece em log, resposta ou erro.

| Situação | Resposta |
|---|---|
| chave ausente, errada ou revogada | `401 CHAVE_INVALIDA` |
| IP de origem fora da lista da chave | `403 ORIGEM_NAO_PERMITIDA` |
| `administradora` fora do escopo da chave | `403 ADMINISTRADORA_NAO_PERMITIDA` (antes de consultar o banco) |
| mais de 60 chamadas por minuto com a mesma chave | `429 LIMITE_EXCEDIDO` + `Retry-After` |
| 30 chaves erradas em 15 min do mesmo IP | `429 LIMITE_EXCEDIDO` para qualquer chave desse IP, até liberar |

Rotação: criar a chave nova, entregar, revogar a antiga. As duas convivem no intervalo.

**`X-Request-Id`.** O portal pode enviar o seu (`[A-Za-z0-9._:-]`, até 64); senão a API gera.
Vai em toda resposta de `/v1` (header e, nos erros, no corpo) e no log de cada chamada, com o
prefixo da chave e o IP de origem (RNF-13). Abrir um chamado = informar o `request_id`.

**Envelope de erro.** Todo erro de `/v1` tem o mesmo formato; trate pelo `codigo`:

```json
{"codigo": "ADMINISTRADORA_NAO_PERMITIDA", "mensagem": "esta chave nao tem acesso a administradora informada",
 "request_id": "9f1c...", "detalhes": {"administradora": "0000000019"}}
```

| HTTP | `codigo` | `detalhes` |
|---|---|---|
| `400` | `PEDIDO_INVALIDO` | — |
| `401` | `CHAVE_INVALIDA` | — |
| `403` | `ADMINISTRADORA_NAO_PERMITIDA`, `ORIGEM_NAO_PERMITIDA` | `administradora` |
| `404` | `CERTIFICADO_NAO_ENCONTRADO` | `pedido` normalizado |
| `422` | `CORPO_MALFORMADO` | `campos[{campo, erro}]` |
| `429` | `LIMITE_EXCEDIDO` | — (header `Retry-After`) |
| `500` | `ERRO_INTERNO` | — (nenhum detalhe interno; use o `request_id`) |
| `502` | `PUBLICACAO_FALHOU` | `pedido`, `quantidade`, `certificados[]` com `situacao: "falha"` e `motivo` |
| `503` | `BANCO_INDISPONIVEL`, `GERADOR_INDISPONIVEL` | `pedido` (gerador) |

### 1.3 `GET /v1/saude`

Valida a chave e devolve a versão do servidor e o escopo da chave (RF-18, ADR-09).

```json
{"ok": true, "versao": "0.1.0", "cliente": "Portal W2BIT", "chave": "fc_Ab12c", "administradoras": "todas"}
```

`administradoras` é `"todas"` ou a lista de códigos permitidos.

### 1.3a `GET /v1/administradoras` (ADR-09)

Código, nome, abreviação e `possui_portal` das administradoras que **esta chave** pode consultar
(QRY-01, filtrado pelo escopo). Serve para o portal mapear o cadastro dele com o código FedCorp.

```json
{"quantidade": 1, "administradoras": [{"codigo": "0000001192", "nome": "IMODATA ADM", "abreviacao": null, "possui_portal": false}]}
```

### 1.4 `POST /v1/segurados/verificar` — segurado da administradora? (UC-13, RF-20)

Responde se o CPF/CNPJ é segurado da administradora e devolve as vigências mais recentes, para
o portal pedir a emissão já apontando a unidade. **Não grava nada.** Não é prova de
identidade: o portal autentica o segurado por conta própria e chama a verificação com o
documento do usuário logado (ADR-09; CPF não é segredo).

**Corpo**

```json
{"administradora": "0000001192", "cpf_cnpj": "330.163.307-25"}
```

| Campo | Regra |
|---|---|
| `administradora` | código `pessoas.pessoa`, com zeros à esquerda, até 10 caracteres; dentro do escopo da chave |
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
      "inicio_vig": "2026-10-01",
      "final_vig": "2026-10-31",
      "apolice": "13008", "seq": 1, "fatura": 382196, "certificado": "CF1DI/AP.602",
      "produto": {"codigo": "0271", "nome": "...", "descricao_fatura": "...", "descricao_master": "..."}
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
- `final_vig` nulo ou `30/12/1899` no banco sai como `null` (DEF-06): a vigência não tem fim
  cadastrado. Exiba como "vigência em aberto".
- Guarde `inicio_vig`, `fatura` e `certificado` do item escolhido: são exatamente os campos que
  a emissão e o link aceitam (RD-31).
- **Latência dos dados**: as vigências são mensais, uma linha por fatura, e a fatura do mês
  entra no banco com atraso; um segurado novo aparece em torno de **30 dias** após a
  contratação. Até lá `existe` é `false`.

**Erros**: `400 PEDIDO_INVALIDO`, `401`, `403`, `422`, `429`, `503 BANCO_INDISPONIVEL` (seção 1.2).

Log (RNF-13): um registro JSON por chamada com `request_id`, prefixo da chave, IP,
administradora, documento, `existe`, chaves das vigências e duração. Sem chave, sem nome,
sem endereço.

### 1.5 `POST /v1/certificados/emitir` — emissão (UC-12, RF-18)

Localiza o certificado, gera JSON e PDF, publica o PDF no S3 (bucket privado), grava o link
permanente no Firebird, regrava o JSON com o link e devolve o **link assinado** e o JSON
espelho na mesma resposta. Síncrono: um PDF leva alguns segundos (Chromium). **Sempre
reemite** (RN-33): objeto no S3 e arquivos locais são sobrescritos. Repetir após timeout é
seguro: o resultado é o mesmo arquivo no mesmo endereço.

**Corpo**

```json
{
  "administradora": "0000001192",
  "cpf_cnpj": "330.163.307-25",
  "vigencia": "2026-10-01",
  "fatura": 382196,
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
(exatamente 1 linha, RD-20a) → regravar JSON com `arquivo.link` → assinar o link (ADR-09).
Falha em qualquer passo interrompe **aquele** certificado; os demais seguem (RF-09). Nunca se
devolve link cuja gravação no banco não foi confirmada.

**Resposta `200`** (ao menos um item publicado)

```json
{
  "pedido": {"administradora": "0000001192", "cpf_cnpj": "33016330725", "vigencia": "2026-10-01",
             "fatura": 382196, "certificado": "CF1DI/AP.602"},
  "quantidade": 1,
  "certificados": [
    {
      "chave": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 382196,
                "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725"},
      "situacao": "publicado",
      "link": "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192/0004/102026/382196/0_33016330725_0004_13008_CF1DI-AP602_382196.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=900&...",
      "link_expira_em": "2026-10-28T13:35:00+00:00",
      "documento": { "...": "JSON espelho completo (seção 2); arquivo.link = link permanente, sem assinatura" },
      "avisos": ["REEMISSAO"],
      "motivo": null
    }
  ]
}
```

| Campo do item | Significado |
|---|---|
| `situacao` | `publicado` ou `falha` |
| `link` | URL **assinada** do PDF, válida até `link_expira_em` (padrão 15 min). Entregue ao segurado na hora; não guarde: peça outra em `/v1/certificados/link` |
| `link_expira_em` | ISO 8601 com fuso |
| `documento` | o JSON espelho **exatamente** como gravado em disco (RD-29, RNF-08); `arquivo.link` é o link permanente (não abre sem assinatura) |
| `avisos` | códigos de `_meta.avisos` (seção 2.3) mais `REEMISSAO` quando a linha já tinha link (RD-28) |
| `motivo` | em `falha`: `[TipoDaExcecao] mensagem` |

**Erros**: `400`, `401`, `403`, `404 CERTIFICADO_NAO_ENCONTRADO` (nenhum certificado para
administradora + documento + vigência (+ fatura/certificado), ou apólice sem produto mapeado,
RN-03.3), `422`, `429`, `502 PUBLICACAO_FALHOU` (**todos** os certificados falharam; cada item em
`detalhes.certificados` traz `motivo`), `503 GERADOR_INDISPONIVEL` / `BANCO_INDISPONIVEL`.

Se o S3 confirmou e o `UPDATE` falhou, o objeto fica no bucket e o item sai `falha` com motivo
explícito.

### 1.6 `POST /v1/certificados/link` — link assinado sem reemitir (ADR-09)

Mesmo corpo da emissão. Devolve um link assinado novo para cada certificado **já emitido**
(linha com `link_certificado_aws`, RD-28), sem gerar nada. É o que o portal chama quando o
segurado clica para abrir o PDF de novo depois que o link anterior expirou.

```json
{
  "pedido": {"...": "..."},
  "quantidade": 1,
  "certificados": [
    {"chave": {"...": "..."}, "situacao": "disponivel",
     "link": "https://...pdf?X-Amz-...", "link_expira_em": "2026-10-28T13:35:00+00:00"}
  ]
}
```

| `situacao` | Significado |
|---|---|
| `disponivel` | link assinado em `link` |
| `nao_emitido` | a linha existe mas nunca recebeu link: chame a emissão |
| `falha` | o link gravado não pertence ao bucket ou a assinatura falhou; `motivo` explica |

Erros: `404 CERTIFICADO_NAO_ENCONTRADO` quando o conjunto não existe; demais como na emissão.

**Reemissão e mudança de cadastro.** O PDF reflete o cadastro no momento da emissão. Se o
cadastro muda (correção, endosso), o PDF só muda quando alguém reemite. Não há data de última
alteração em `segurados_inc`; o portal deve reemitir por ação explícita do segurado ou da
administradora.

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

Backend da página `/incendio`. Desde 23/10/2026 (ADR-08) **toda página e toda rota `/api/*`
exigem sessão** (login por e-mail e senha, seção 3.0). Usa a mesma emissão e o mesmo JSON da
API do portal; a diferença é o fluxo em cascata do operador (seção 5.2 da especificação) e o
upload opcional.

```powershell
python -m certgen.cli web                      # 127.0.0.1:8000, abre o navegador
python -m certgen.cli web --rede --sem-navegador   # equipe pela LAN (liberar a porta 8000)
python -m certgen.cli web --reload             # desenvolvimento
python -m certgen.cli servidor --rede --proxy --porta 8000   # tela + /v1 no mesmo processo (Render)
```

### 3.0 Autenticação da tela (ADR-08)

Modelo do Sistema de Sinistros FedCorp. Cookie de sessão `certgen_sessao` (httpOnly,
SameSite=Lax, Secure em HTTPS, 8 h). Toda chamada que altera dados (`POST`/`PUT`/`PATCH`/
`DELETE`) precisa do header `X-Requested-With: fetch` (CSRF), senão `403`. Sem sessão: página
→ `302 /login?next=...`; `/api/*` → `401 {"erro": ...}`. Com senha temporária pendente só
`/trocar-senha` responde (API: `403`).

| Rota | Corpo / resposta |
|---|---|
| `GET /login` | página de login (redireciona para `/` se já logado) |
| `POST /api/auth/login` | `{"email","senha"}` → `200` usuário (`id, nome, email, perfil, perfil_nome, trocar_senha, ...`) + cookie; `400` campos vazios; `401` *E-mail ou senha inválidos* (mensagem única); `403` desativado; `429` após 10 falhas do mesmo e-mail+IP em 15 min (`Retry-After`) |
| `POST /api/auth/logout` | `{"ok": true}`; apaga a sessão e o cookie |
| `GET /api/auth/me` | usuário da sessão |
| `POST /api/auth/trocar-senha` | `{"senha_atual","nova_senha"}` → `{"ok": true}`; `400` senha atual errada, política (mín. 8, letras e números, máx. 72) ou igual à atual. Mantém a sessão atual e encerra as outras |
| `GET /trocar-senha` | página; obrigatória no primeiro acesso com senha temporária |

ADMIN inicial: `CERTGEN_ADMIN_EMAIL` + `CERTGEN_ADMIN_SENHA`, semeado na subida só quando não há
ADMIN ativo. Usuários em `CERTGEN_USUARIOS_DB` (SQLite; padrão `dados/usuarios.sqlite`).

Cabeçalhos em toda resposta: `Content-Security-Policy` (`default-src 'self'`, sem script inline),
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`,
`Permissions-Policy`, HSTS em HTTPS, `Cache-Control: no-store` em `/api/*`. A tela não expõe
`/docs` nem `/openapi.json`.

### 3.1 Páginas

| Rota | Conteúdo |
|---|---|
| `GET /` | menu com os três módulos (ADR-07): Incêndio ativo; Prestamista/Alug e Vida em preparação (GAP-21/22) |
| `GET /incendio` | tela do Incêndio |
| `GET /prestamista`, `GET /vida` | "em preparação" |
| `GET /usuarios` | cadastro de usuários (só ADMIN; seção 3.6) |
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
| `POST /api/encerrar` | botão *Encerrar sistema* do menu; encerra o servidor. `403` se não for local |

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

### 3.6 Usuários (só perfil ADMIN; ADR-08)

Perfis: `ADMIN` (Administrador do Sistema: tudo + cadastro de usuários) e `OPERADOR`
(módulos de certificado). Não há envio de e-mail: a senha temporária é devolvida **uma vez**
na resposta e o administrador a entrega por canal seguro; o usuário é obrigado a trocá-la no
primeiro acesso.

| Rota | Corpo / resposta |
|---|---|
| `GET /api/usuarios` | lista (`id, nome, email, perfil, perfil_nome, ativo, trocar_senha, ultimo_login, criado_em`); nunca o hash |
| `POST /api/usuarios` | `{"nome","email","perfil"}` → `201` usuário + `senha_temporaria`; `400` nome/e-mail/perfil inválidos; `409` e-mail já cadastrado; `422` campo desconhecido ou nome curto |
| `PUT /api/usuarios/{id}` | `{"nome","email","perfil"}` → usuário; `400` se rebaixaria o único ADMIN ativo; `404`; `409`. Mudar o perfil encerra as sessões do usuário |
| `POST /api/usuarios/{id}/ativo` | `{"ativo": bool}` → usuário. Desativar derruba as sessões na hora. `400` ao desativar a si mesmo ou o único ADMIN ativo |
| `POST /api/usuarios/{id}/resetar-senha` | → `{"ok": true, "senha_temporaria"}`; sessões encerradas; `400` para o próprio usuário (use trocar-senha) |

Todas respondem `401` sem sessão e `403` para `OPERADOR`.

### 3.7 Chaves da API do portal (só perfil ADMIN; ADR-09)

Página `/chaves`. Uma chave por cliente integrador, com escopo de administradoras (ou "todas"),
IPs de origem opcionais (IP ou CIDR) e revogação imediata e irreversível. A chave é devolvida
**uma vez** na criação; o banco guarda só o SHA-256. `GET /api/incendio/administradoras`
alimenta a lista de seleção.

| Rota | Corpo / resposta |
|---|---|
| `GET /api/chaves` | lista (`id, nome, prefixo, administradoras, todas, ips, ativa, criada_em, criada_por, revogada_em, ultimo_uso, ultimo_ip`); nunca a chave nem o hash |
| `POST /api/chaves` | `{"nome", "administradoras": [...], "todas": bool, "ips": [...]}` → `201` registro + `chave` (texto, só agora); `400` sem escopo, código ou IP inválido; `422` campo desconhecido ou nome curto |
| `PUT /api/chaves/{id}` | mesmo corpo → registro (a chave em si não muda); `400`; `404` |
| `POST /api/chaves/{id}/revogar` | → registro com `ativa: false`; a API responde `401` para essa chave na hora; `404` |

Todas respondem `401` sem sessão e `403` para `OPERADOR`. A tela também recebe, no relatório
de emissão com Upload AWS, `link_temporario` em cada item emitido (URL assinada; `link`
continua o permanente).

---

## 4. Referências

- `docs/ESPECIFICACAO.md` — fonte da verdade; seção 11.1 (API do portal), 5 (tela), 8 (S3 e
  banco), 9 (JSON), 16 (lacunas abertas).
- `docs/schema/certificado-1.0.schema.json` — schema do JSON espelho.
- `docs/TESTE-API-POSTMAN.md` e `docs/postman/` — teste manual e operação da API na rede.
- `/v1/docs` e `/v1/openapi.json` — contrato OpenAPI da API do portal (também no modo combinado);
  a tela não publica o seu (ADR-08).
- `docs/GUIA-INTEGRACAO-PORTAL.md` — guia entregue ao integrador; PDF e Postman em `entregas/`.

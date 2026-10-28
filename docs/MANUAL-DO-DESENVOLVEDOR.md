# Manual do desenvolvedor — Gerador de Certificados

Para: quem vai manter, evoluir ou estudar este projeto, inclusive quem nunca programou em
Python. O manual explica o que o sistema faz, como ele está organizado, por que foi feito
assim, e propõe uma trilha de estudo que parte do zero e termina no ponto em que o projeto
foi entregue (28/10/2026, ADR-09).

Como usar: a parte I é leitura. A parte II é a trilha de aprendizado, com módulos numerados;
cada módulo diz o que estudar, onde isso aparece no projeto e um exercício. A parte III é o
passo a passo para analisar o código na ordem certa. A parte IV é referência rápida.

---

## Parte I — O que é este projeto

### 1. O problema de negócio

A FedCorp administra seguros de incêndio e conteúdo para condomínios. Cada morador segurado
tem direito a um **certificado**: um PDF de uma página que mostra quem é o segurado, o
endereço do risco, a apólice, a vigência, as coberturas contratadas e o valor do prêmio.

Até 2026 esse certificado era gerado por um programa Delphi antigo (`UfrmImprimeCertInc`,
1.678 linhas, pasta `Delphi/`, somente leitura). Ele tinha 21 defeitos catalogados na
especificação (seção 13), entre eles gravar o link do certificado de um segurado na linha
de outro. Este projeto é a **reescrita** desse gerador em Python, com três canais de uso:

| Canal | Quem usa | Como |
|---|---|---|
| Tela web | operador da FedCorp, no navegador | escolhe administradora → apólice → fatura → segurados, emite PDF/JSON, opcionalmente publica no S3 |
| Linha de comando (CLI) | operador técnico, automações | `python -m certgen.cli emitir ...` |
| API do portal | sistemas de terceiros (portal do condomínio) | HTTP com chave: verifica o segurado, emite, devolve link assinado |

O dado vem de um banco **Firebird 2.5** (`FATURA.GDB`), o mesmo do sistema legado. O PDF
publicado vai para um bucket **S3** privado, e o link permanente é gravado de volta no
Firebird, em três colunas apenas.

### 2. As regras que nunca se quebram

Estão no `CLAUDE.md` e na seção "Regras invioláveis". As mais importantes, com o porquê:

- **A especificação é a fonte da verdade.** `docs/ESPECIFICACAO.md` tem 2.300 linhas com
  requisitos identificados (`RF-nn` funcionais, `RN-nn` regras de negócio, `RD-nn` regras de
  dados, `QRY-nn` consultas, `RNF-nn` não funcionais, `ADR-nn` decisões, `GAP-nn` lacunas).
  Todo trecho de código cita o ID que implementa. Se a spec não cobre, pára-se e pergunta.
- **Dinheiro é `Decimal`, nunca `float`.** `0.1 + 0.2` em ponto flutuante dá
  `0.30000000000000004`; num certificado de seguro isso é inaceitável.
- **Datas são `date`.** ISO 8601 (`2026-10-01`) no JSON, `dd/MM/yyyy` no PDF.
- **SQL só com parâmetros.** Nunca se monta SQL colando texto do usuário (injeção de SQL).
- **Falhar alto.** Diante de dado inconsistente, o sistema recusa emitir em vez de emitir
  errado. Anomalias toleráveis viram "avisos" no JSON.
- **Nenhum efeito colateral antes do sucesso da etapa anterior.** O PDF só é gerado depois
  de o JSON ser validado; o link só é gravado no banco depois de o S3 confirmar o upload.
- **O banco só recebe UPDATE em três colunas.** Tudo o mais é leitura.
- **Segredos só no `.env` ou nas variáveis de ambiente.** Nunca no código, nunca no git.

### 3. Mapa do projeto

```
05-Gerador Certificados/
├── CLAUDE.md                  regras do projeto para quem desenvolve (humano ou assistente)
├── README.md                  instalação, comandos, estado das fases
├── pyproject.toml             nome do pacote, dependências, ferramentas
├── .env.example               modelo das variáveis de ambiente (o .env real não vai ao git)
├── Dockerfile, render.yaml    como o serviço sobe no Render (homologação)
├── docs/
│   ├── ESPECIFICACAO.md       A fonte da verdade (requisitos, consultas, ADRs, lacunas)
│   ├── API.md                 referência das duas APIs e do JSON espelho
│   ├── GUIA-INTEGRACAO-PORTAL.md  o que o integrador externo recebe
│   ├── DEPLOY-RENDER.md       como publicar e diagnosticar no Render
│   ├── TESTE-API-POSTMAN.md   teste manual da API
│   ├── MANUAL-DO-DESENVOLVEDOR.md  este manual
│   ├── schema/certificado-1.0.schema.json   contrato do JSON espelho
│   ├── postman/               collection e environments
│   └── legado/referencia/     PDFs do sistema antigo usados como gabarito visual
├── src/certgen/               o pacote Python (tudo que roda)
│   ├── domain/                REGRAS DE NEGÓCIO puras: sem banco, sem HTTP, sem arquivo
│   ├── application/           CASOS DE USO: orquestram o domínio e as portas
│   ├── adapters/              o MUNDO EXTERNO: Firebird e S3
│   ├── render/                HTML (Jinja2) → PDF (Chromium via Playwright)
│   ├── serialize/             o JSON espelho e sua validação
│   ├── web/                   tela (FastAPI + HTML/JS) e API do portal
│   ├── config/                leitura do .env, catálogos TOML
│   └── cli.py                 comandos de terminal
├── tests/unit/                testes rápidos, sem banco (fakes)
├── tests/integration/         testes contra Firebird/Chromium reais (pulam sem .env)
├── entregas/                  pacotes para clientes (fora do git)
└── Delphi/                    o legado, só leitura
```

Linhas de código por camada (28/10/2026): domínio ≈ 1.140; aplicação ≈ 980; adaptadores
≈ 770; render + serialize ≈ 530; web ≈ 2.390; CLI + config ≈ 490. Testes unitários: 346.

### 4. A arquitetura em uma figura

O projeto segue **arquitetura hexagonal** (ADR-01), também chamada "portas e adaptadores".
A ideia: o núcleo (domínio + casos de uso) não sabe que existe Firebird, S3, HTTP ou
Chromium. Ele fala com o mundo através de **portas** (interfaces em `application/ports.py`),
e cada tecnologia é um **adaptador** que implementa a porta.

```
                 ┌───────────────────────────────────────────────┐
  tela (web/app) │                 APPLICATION                   │  adapters/firebird
  CLI (cli.py)   │  emitir_lote, emitir_um, publicar_emitido,    │  (RepositorioCertificados,
  API (api_portal)──▶ emitir_para_portal, verificar_segurado,   │   RegistroLinks)
                 │  links_para_portal, Cascata                   │
                 │        │                                      │  adapters/s3
                 │        ▼                                      │  (PublicadorArquivos)
                 │   ┌─────────────────── DOMAIN ─────────────┐  │
                 │   │ Certificado, Cobertura, Documento,      │  │  render/ (HTML→PDF)
                 │   │ Produto, Dinheiro, NomesArquivo, Portal │  │  serialize/ (JSON)
                 │   └─────────────────────────────────────────┘  │
                 └───────────────────────────────────────────────┘
```

Por que isso importa: a Fase 5 prevê trocar o Firebird por uma API de dados. Com portas,
isso é um adaptador novo; o domínio e os casos de uso não mudam. Os testes unitários usam
"fakes" (adaptadores de mentira em memória) exatamente por isso.

### 5. Roadmap dos processos

Cada processo abaixo é uma sequência fixa. Os números apontam o arquivo onde cada passo vive.

#### 5.1 Emissão de um certificado (o coração de tudo)

```
1. localizar as linhas no banco          adapters/firebird/repositorio.py  (queries.sql, QRY-05/13)
2. montar o objeto Certificado           repositorio._montar → domain/certificado.py
   - coberturas sempre as 11             domain/cobertura.py (RN-01, RN-02)
   - produto pela apólice                domain/produto.py + config/produtos.toml (RN-03)
   - PLANO RES/COM/INC, Faz Tudo Lar     domain/certificado.py (RN-23, RN-18)
3. gerar o dicionário JSON               serialize/json_certificado.certificado_para_dict
4. VALIDAR contra o schema               serialize.validar (RD-15)  ← se falhar, nada é gravado
5. gravar o .json                        serialize.gravar_json
6. renderizar HTML                       render/html.py + templates/certificado.html.j2
7. HTML → PDF                            render/pdf.py (Chromium headless)
8. (opcional) publicar no S3             adapters/s3/publicador.publicar (confirma com head_object)
9. (opcional) gravar o link no banco     repositorio.registrar_link (exatamente 1 linha, RD-20a)
10. regravar o JSON com arquivo.link     application/emitir_certificados.publicar_emitido
```

A função que amarra 1–7 é `emitir_um`; `emitir_lote` repete para todos os segurados de uma
fatura e monta o relatório; `publicar_emitido` faz 8–10. Tela, CLI e API chamam **as
mesmas funções** (RF-11): não existe lógica duplicada por canal.

#### 5.2 Tela do operador (cascata)

```
login (/login) ──▶ menu (/) ──▶ /incendio
   administradoras ──▶ apólices ──▶ faturas ──▶ segurados   (application/listar_cascata.Cascata)
   marcar opções (prêmio, Faz Tudo Lar, JSON único, Upload AWS) ──▶ POST /api/incendio/emitir
   ──▶ emitir_lote (+ publicar_emitido se Upload AWS) ──▶ relatório com link assinado
```

#### 5.3 API do portal (integrador externo)

```
X-API-Key ──▶ autenticar (web/api_portal.py): chave no SQLite, IP, limite 60/min
GET  /v1/saude                 escopo da chave
GET  /v1/administradoras       QRY-01 filtrada pelo escopo
POST /v1/segurados/verificar   verificar_segurado (QRY-14, RN-35): existe + 3 vigências
POST /v1/certificados/emitir   emitir_para_portal: 5.1 completo + link assinado (15 min)
POST /v1/certificados/link     links_para_portal: reassina sem reemitir
erro em qualquer ponto         envelope {codigo, mensagem, request_id, detalhes}
```

#### 5.4 Segurança da tela (ADR-08) e da API (ADR-09)

```
usuários    SQLite (web/usuarios.py): bcrypt, sessão httpOnly, CSRF, limite de login
chaves      SQLite (web/chaves_api.py): SHA-256 da chave, escopo de administradoras, IPs,
            revogação; criadas em /chaves pelo ADMIN
bucket      privado; links assinados por PublicadorS3.link_temporario
```

#### 5.5 Linha do tempo das entregas

| Fase | Entrega | Quando |
|---|---|---|
| 0 | fundação: pacote, config, conexão Firebird com pool | set/2026 |
| 1 | domínio + consultas canônicas + adaptador Firebird | set/2026 |
| 2 | JSON espelho com schema, `emitir-json` | set/2026 |
| 3 | PDF por HTML/Chromium, layout único (ADR-06) | set/2026 |
| 4 | tela web com menu de módulos (ADR-07) | 03–04/09/2026 |
| 7 | S3 + `registrar_link` + Upload AWS na tela | 10–15/09/2026 |
| 8 | API do portal: emissão e verificação | 10–14/09/2026 |
| — | login da tela, usuários, Render (ADR-08) | 23/10/2026 |
| — | chaves por cliente, bucket privado, envelope de erro, limite de taxa (ADR-09) | 28/10/2026 |
| 5, 6 | adaptador de API; emissão em massa | pendentes |

---

## Parte II — Trilha de aprendizado: do zero ao projeto

Cada módulo tem: **o que aprender**, **onde está no projeto** (abra o arquivo e leia com o
conceito em mente) e **exercício**. Faça na ordem. Um módulo por dia ou dois é um ritmo bom;
a trilha inteira leva de seis a dez semanas para quem começa do zero.

### Módulo 0 — Preparar a máquina

**Aprender:** o que é o interpretador Python, o que é um ambiente virtual (`.venv`), o que é
`pip`, o que é um terminal.

**No projeto:** `README.md` seção Instalação. O ambiente virtual isola as bibliotecas deste
projeto das de outros; `pip install -e .[dev]` instala o pacote em modo editável, ou seja, o
código em `src/` é usado direto, sem copiar.

```powershell
cd "U:\--2021\05-Gerador Certificados"
.\.venv\Scripts\Activate.ps1
python --version          # 3.12 ou 3.14
python -m pytest -q       # 346 testes devem passar
```

**Exercício:** rode `python -m certgen.cli --help` e leia o que cada subcomando faz.

### Módulo 1 — O básico da linguagem

**Aprender:** variáveis, tipos (`str`, `int`, `bool`, `None`), `if`, `for`, funções com
`def`, listas, dicionários, strings com f-string, `import`.

**No projeto:** `src/certgen/domain/documento.py` (72 linhas). Leia `somente_digitos`,
`formatar_cpf`, `formatar_cnpj`. São funções puras: entram dados, saem dados, nada mais.
Depois `domain/dinheiro.py`: veja `para_dinheiro` converter texto ou número em `Decimal`.

**Exercício:** escreva uma função `formatar_cep("22630010") -> "22630-010"` e compare com
`render/filtros.cep`.

### Módulo 2 — Tipos de dados que não mentem

**Aprender:** por que `float` erra em dinheiro; `Decimal`; `date` e `datetime`; `Enum`;
type hints (`def f(x: int) -> str`).

**No projeto:** `domain/dinheiro.py` inteiro; `domain/documento.py` (`TipoDocumento` é um
`StrEnum`); `domain/certificado.py` linhas 123–145 (`Vigencia` com `date`). Note que o JSON
grava dinheiro como string `"100000.00"` (ADR-03): o consumidor nunca recebe um float.

**Exercício:** no terminal Python, calcule `0.1 + 0.2` com float e com `Decimal("0.1") +
Decimal("0.2")`. Explique a diferença em uma frase.

### Módulo 3 — Classes e dataclasses

**Aprender:** `class`, atributos, métodos, `@property`, `@dataclass(frozen=True)`
(objetos imutáveis), `@classmethod` como construtor alternativo.

**No projeto:** `domain/certificado.py`. `ChaveCertificado` identifica uma linha do banco
(administradora, apólice, seq, fatura, certificado, cpf_cnpj). `Certificado` é o objeto
central: junta administradora, contrato, segurado, local de risco, vigência, coberturas.
Observe que tudo é `frozen=True`: depois de montado, ninguém altera um certificado por
acidente. Em `application/emitir_portal.py`, `PedidoPortal.criar` é um `classmethod` que
valida e normaliza antes de construir.

**Exercício:** crie uma dataclass `Endereco` com `logradouro`, `cidade`, `uf` e uma
property `resumo` que devolve `"cidade/UF"`.

### Módulo 4 — Erros e exceções

**Aprender:** `try/except`, criar exceções próprias (`class X(ValueError)`), `raise ... from`,
a diferença entre "falhar alto" e "engolir erro".

**No projeto:** `domain/produto.py` (`ProdutoIndeterminado`), `domain/nomes_arquivo.py`
(`NomeArquivoInvalido`), `application/ports.py` (`ErroPublicacao`, `LinkNaoRegistrado`).
Veja em `application/emitir_portal._tratar_um` como cada certificado que falha vira um item
`falha` com motivo, sem derrubar os outros (RF-09), e em `serialize/json_certificado.validar`
como um JSON inválido impede o PDF (ADR-04).

**Exercício:** leia o teste `tests/unit/test_emitir_portal.py` que simula S3 fora do ar e
explique por que o banco não recebe nenhum UPDATE nesse caso.

### Módulo 5 — Módulos, pacotes e organização

**Aprender:** o que é um pacote (`__init__.py`), imports absolutos, `src/` layout, separar
"o que o negócio é" de "como falamos com o mundo".

**No projeto:** a árvore da seção 3. Regra prática: `domain/` não importa nada de
`adapters/`, `web/` ou `render/`. Confira com um `grep -r "import" src/certgen/domain`.
Isso é a arquitetura hexagonal na prática.

**Exercício:** desenhe em papel quais pastas importam quais. Compare com a figura da seção 4.

### Módulo 6 — Protocolos e injeção de dependência

**Aprender:** `typing.Protocol` (interfaces estruturais), passar dependências como
parâmetros em vez de criá-las dentro da função, "fakes" para testes.

**No projeto:** `application/ports.py` define `RepositorioCertificados`,
`PublicadorArquivos`, `RegistroLinks`. `application/emitir_certificados.emitir_lote` recebe
`repo`, `publicador`, `registro` como parâmetros. Em `tests/unit/test_emitir_portal.py`,
`RepoFalso`, `PublicadorFalso` e `RegistroFalso` implementam as mesmas portas em memória, e
por isso os testes rodam em segundos sem banco nem rede.

**Exercício:** escreva um `PublicadorFalso` seu que falha na segunda chamada e veja o
relatório sair com um publicado e uma falha.

### Módulo 7 — Testes automatizados

**Aprender:** `pytest`, `assert`, fixtures, `monkeypatch`, marcar testes de integração,
rodar um teste só.

**No projeto:** `tests/unit/conftest.py` (fixtures da tela: SQLite temporário, admin
semeado, cliente logado), `tests/unit/test_dinheiro.py` (o mais simples),
`tests/unit/test_api_portal.py` (o mais completo: chaves, escopo, envelope, limite de taxa).
Os testes de integração em `tests/integration/` só rodam com `.env` e Firebird acessíveis.

```powershell
python -m pytest -q tests/unit/test_dinheiro.py
python -m pytest -q -k "escopo"            # só testes com 'escopo' no nome
```

**Exercício:** quebre de propósito `calcular_cob_incendio` em `domain/cobertura.py` e veja
qual teste acusa. Desfaça.

### Módulo 8 — Arquivos, caminhos e configuração

**Aprender:** `pathlib.Path`, ler/gravar texto com `encoding="utf-8"`, variáveis de
ambiente, `.env` com `python-dotenv`, TOML.

**No projeto:** `config/settings.py` (`Config.do_ambiente()` lê tudo do ambiente, e a
`__repr__` esconde segredos); `config/produtos.toml` e `seguradoras.toml` (catálogos que o
negócio mantém sem tocar em código); `domain/nomes_arquivo.py` (nome e pasta de cada PDF,
RN-19). Repare em `resolver_colisao`: nunca sobrescreve um arquivo por engano.

**Exercício:** adicione uma seguradora fictícia em `seguradoras.toml` e rode os testes de
`test_seguradora.py`.

### Módulo 9 — Banco de dados e SQL seguro

**Aprender:** o que é uma consulta SQL, `SELECT ... WHERE ... = ?` com parâmetros, por que
nunca concatenar, pool de conexões, cursor.

**No projeto:** `adapters/firebird/queries.sql` (todas as consultas, nomeadas `QRY-nn`, uma
consulta canônica em vez de cinco cópias, RD-17); `adapters/firebird/consultas.py`
(`Filtros` monta o `WHERE` só com `?` e lista de parâmetros); `adapters/firebird/conexao.py`
(pool LIFO por charset, modelo do FedHub); `adapters/firebird/repositorio.py` (`_montar`
transforma uma linha do banco num `Certificado`). A única escrita é `registrar_link`, que
exige exatamente uma linha afetada.

**Exercício:** `python -m certgen.cli check-conexao` (precisa do `.env`). Depois leia QRY-13
em `queries.sql` e diga quais filtros a API do portal acrescenta.

### Módulo 10 — JSON e contratos de dados

**Aprender:** `json.dumps/loads`, JSON Schema, por que validar antes de gravar, `null` x
campo ausente.

**No projeto:** `serialize/json_certificado.py` e `docs/schema/certificado-1.0.schema.json`.
`certificado_para_dict` monta o espelho do PDF (tudo que o PDF imprime, nada além, RD-10);
`validar` compara com o schema; `gravar_json` só grava depois. Seção 2 de `docs/API.md`
explica cada bloco.

**Exercício:** gere um JSON com `python -m certgen.cli emitir-json ...` e confira à mão que
`coberturas` tem sempre 11 itens.

### Módulo 11 — Templates e geração de PDF

**Aprender:** Jinja2 (`{{ }}`, `{% if %}`, filtros), HTML/CSS básico para impressão, por que
usar um navegador (Chromium) para gerar PDF.

**No projeto:** `render/templates/certificado.html.j2` (um template condicional para todos
os produtos, ADR-05) com os blocos `faz_tudo_lar` e `assistencia_24h`; `render/filtros.py`
(`moeda`, `data_br`, `cep`); `render/html.py` (`renderizar_html`, imagens embutidas em
base64); `render/pdf.py` (`RenderizadorPdf` abre um Chromium e imprime). O PDF de referência
do legado está em `docs/legado/referencia/` (ADR-06).

**Exercício:** `python -m certgen.cli html ...` gera o HTML; abra no navegador, mude uma cor
no CSS do template e veja o efeito.

### Módulo 12 — Linha de comando

**Aprender:** `argparse`, subcomandos, códigos de saída, `if __name__ == "__main__"`.

**No projeto:** `cli.py`. Cada subcomando chama um caso de uso; a CLI não tem regra de
negócio. `_cmd_servidor` mostra como subir a tela e a API no mesmo processo.

**Exercício:** adicione um subcomando `versao` que imprime `certgen.__version__`.

### Módulo 13 — HTTP, FastAPI e a tela

**Aprender:** o que é uma requisição HTTP (método, caminho, headers, corpo, status), JSON na
web, FastAPI (`@app.get`, `Depends`, Pydantic para validar corpo), templates HTML servidos
pelo servidor, JavaScript mínimo com `fetch`.

**No projeto:** `web/app.py` (páginas e `/api/incendio/*`), `web/templates/incendio.html` +
`web/static/incendio.js` (a cascata no navegador), `web/static/sessao.js` (o `fetch` comum,
que adiciona o header de CSRF e trata 401). Note `versao_tela`: a emissão recusa um
JavaScript antigo com 409.

**Exercício:** suba `python -m certgen.cli web`, abra as ferramentas do navegador (F12, aba
Rede) e acompanhe as chamadas da cascata.

### Módulo 14 — Segurança de aplicações web

**Aprender:** hash de senha (bcrypt) e por que não se guarda senha; sessão por cookie
httpOnly; CSRF; limite de tentativas; cabeçalhos de segurança (CSP, HSTS); princípio do
menor privilégio.

**No projeto:** `web/auth.py` (política de senha, `LimiteTentativas`, `LimiteTaxa`, CSRF,
cabeçalhos, middleware de sessão), `web/usuarios.py` (SQLite com WAL, sessões com SHA-256 do
token), `web/chaves_api.py` (chaves da API com SHA-256, escopo, IPs, revogação). O ADR-08 e o
ADR-09 na spec contam o raciocínio por trás de cada escolha.

**Exercício:** explique por que o banco guarda o SHA-256 da chave da API e não a chave, e o
que acontece se o SQLite vazar.

### Módulo 15 — A API do portal

**Aprender:** desenho de API: autenticação por chave, escopo, envelope único de erro,
`X-Request-Id`, limite de taxa, OpenAPI, versionamento.

**No projeto:** `web/api_portal.py` inteiro, `docs/API.md` seção 1, `docs/GUIA-INTEGRACAO-PORTAL.md`,
`docs/postman/`. Veja como `instalar_portal` registra os tratadores de erro de modo que
**todo** erro de `/v1` saia no mesmo formato, e como `autenticar` resolve chave → IP → limite.

**Exercício:** importe a collection no Postman, suba `python -m certgen.cli api` e rode a
pasta "Erros esperados".

### Módulo 16 — Nuvem: S3, Docker, Render

**Aprender:** armazenamento de objetos (bucket, chave, URL assinada), credenciais IAM,
contêiner Docker, variáveis de ambiente em hospedagem, disco persistente.

**No projeto:** `adapters/s3/publicador.py` (`publicar` confirma com `head_object`;
`link_temporario` assina com SigV4 no endpoint regional), `Dockerfile` (instala o Chromium e
roda os testes no build), `render.yaml`, `docs/DEPLOY-RENDER.md`. Lição aprendida em
28/10/2026: sem disco persistente em `/data`, o SQLite some a cada deploy.

**Exercício:** leia o `Dockerfile` linha a linha e diga o que acontece se um teste falhar.

### Módulo 17 — Trabalhar com especificação e ADRs

**Aprender:** ler requisitos com ID, registrar decisões (ADR), manter changelog, não
implementar por suposição.

**No projeto:** `docs/ESPECIFICACAO.md` seções 11.1 (API), 15 (ADRs), 16 (lacunas) e Anexo B
(registro de alterações); `docs/API.md` seção 1.0 (changelog). Escolha um `GAP-nn` aberto e
veja o que seria preciso decidir para fechá-lo.

**Exercício:** escreva um ADR-10 fictício para o GAP-27 (emissão assíncrona) com contexto,
decisão, consequências e alternativas rejeitadas.

---

## Parte III — Passo a passo para analisar o projeto

Esta é a ordem de leitura que faz o projeto "abrir" com menos esforço. Reserve um bloco de
tempo para cada passo e anote dúvidas com o ID do requisito ao lado.

1. **`README.md`** (10 min): instale, rode os testes, rode `--help`.
2. **`CLAUDE.md`** (10 min): as regras. Qualquer mudança que você fizer tem de respeitá-las.
3. **Spec, seções 1 a 3** (30 min): contexto, glossário, atores e casos de uso.
4. **`domain/`** (2 h), nesta ordem: `dinheiro.py`, `documento.py`, `cobertura.py`,
   `produto.py`, `certificado.py`, `nomes_arquivo.py`, `portal.py`. A cada arquivo, abra o
   teste correspondente em `tests/unit/`.
5. **`application/ports.py`** (20 min): as três portas. Depois `emitir_certificados.py`
   seguindo `emitir_um` → `emitir_lote` → `publicar_emitido`.
6. **`serialize/json_certificado.py`** e o schema (40 min). Gere um JSON de verdade.
7. **`render/`** (40 min). Gere um HTML e um PDF.
8. **`adapters/firebird/`** (1 h): `queries.sql` primeiro, depois `consultas.py`, depois
   `repositorio.py`. Compare `_montar` com a seção 4 da spec (dicionário de dados).
9. **`adapters/s3/publicador.py`** (20 min).
10. **`cli.py`** (20 min): veja como cada comando chama a aplicação.
11. **`web/app.py` + templates + JS** (1,5 h): suba a tela e acompanhe cada clique no código.
12. **`web/auth.py`, `usuarios.py`, `chaves_api.py`** (1 h): segurança.
13. **`web/api_portal.py`** (1 h) com `docs/API.md` ao lado e o Postman aberto.
14. **Spec, seções 13, 15, 16** (1 h): defeitos do legado, decisões, lacunas. Aqui você
    entende *por que* o código é como é.
15. **Anexo B da spec** (20 min): o histórico de mudanças com datas.

Ao final você consegue responder: onde entra uma regra de negócio nova? (domínio e spec);
onde entra uma coluna nova do banco? (queries.sql, repositorio._montar, certificado.py,
schema, template); onde entra um campo novo da API? (api_portal, emitir_portal, API.md,
changelog, Postman).

---

## Parte IV — Referência rápida

### Comandos

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q                          # testes (integração pula sem .env)
python -m ruff check .                       # lint
python -m certgen.cli check-conexao          # Firebird
python -m certgen.cli web                    # tela em 127.0.0.1:8000 (login)
python -m certgen.cli api                    # API do portal em 127.0.0.1:8010 (/v1/docs)
python -m certgen.cli servidor --rede --proxy --porta 8000   # tela + API (Render)
python -m certgen.cli emitir --administradora 0000001192 --apolice 13008 --seq 1 --fatura 382196 --saida C:\certificados [--upload-aws]
python -m certgen.cli emitir-json ...        # só JSON
python -m certgen.cli html ... --certificado "CF1DI/AP.602" --saida x.html
```

### Variáveis de ambiente (`.env`)

| Grupo | Variáveis | Para quê |
|---|---|---|
| Firebird | `FB_HOST`, `FB_PORT`, `FB_DATABASE`, `FB_USER`, `FB_PASSWORD`, `FB_CHARSET`, `FB_POOL_SIZE` | conexão (modelo FedHub) |
| AWS | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_S3_BUCKET` | publicar e assinar links |
| Tela | `CERTGEN_ADMIN_EMAIL`, `CERTGEN_ADMIN_SENHA`, `CERTGEN_USUARIOS_DB` | admin inicial e SQLite |
| API | `CERTGEN_API_KEY` (transição, opcional), `CERTGEN_LINK_VALIDADE_SEG` | chave antiga; validade do link |
| Saída | `CERTGEN_PASTA_SAIDA`, `CERTGEN_SUSEP_CORRETORA`, `CERTGEN_APOLICES_MASSA` | pastas e constantes |

### Decisões de arquitetura (resumo)

| ADR | Decisão | Motivo |
|---|---|---|
| 01 | portas e adaptadores | trocar Firebird por API sem tocar o domínio |
| 02 | HTML + CSS → Chromium | layout fiel e fácil de ajustar |
| 03 | `Decimal`, `date`, ISO no JSON | nunca errar dinheiro nem data |
| 04 | falhar alto | documento errado é pior que nenhum documento |
| 05 | um template condicional | o legado tinha cinco arquivos divergentes |
| 06 | um PDF de referência | gabarito visual único |
| 07 | menu com três módulos | Prestamista e Vida virão com spec própria |
| 08 | login da tela, usuários em SQLite | tela publicada na web com segurança |
| 09 | chaves por cliente, bucket privado, envelope de erro, limite de taxa | retorno do integrador; fechar GAP-23/24/26 |

### Glossário

- **Administradora**: empresa que administra condomínios; código `pessoas.pessoa` de 10 caracteres.
- **Apólice / seq**: contrato com a seguradora e sua sequência.
- **Fatura**: cobrança mensal; cada mês de vigência é uma linha por segurado.
- **Certificado**: documento individual do segurado; `CF1DI/AP.602` identifica a unidade.
- **Vigência**: período coberto; `inicio_vig` é a chave que a API usa.
- **Produto**: tipo de cobertura (0004 Ruptura, 0117, 0271...), resolvido pela apólice.
- **Faz Tudo Lar**: assistência extra, derivada por código Mondial 1003 ou ruptura > 0.
- **JSON espelho**: o certificado como dado, idêntico ao que o PDF imprime.
- **Link permanente**: URL do objeto no S3, gravada no banco; não abre sem assinatura.
- **Link assinado**: URL com validade curta que abre o PDF.
- **Porta / adaptador**: interface do núcleo / implementação concreta de uma tecnologia.
- **Fake**: adaptador de mentira usado em teste.
- **RF / RN / RD / QRY / RNF / ADR / GAP**: famílias de IDs da especificação.

### Checklist de estudo

- [ ] Rodei os testes e todos passaram.
- [ ] Sei explicar por que dinheiro é `Decimal`.
- [ ] Desenhei a arquitetura hexagonal sem olhar.
- [ ] Emiti um certificado pela CLI e pela tela.
- [ ] Li QRY-13 e entendi os filtros da API.
- [ ] Rodei a collection do Postman contra a API local.
- [ ] Sei onde entraria um campo novo no JSON (quatro lugares).
- [ ] Li ADR-08 e ADR-09 e sei explicar as três camadas de segurança.
- [ ] Escolhi um GAP e escrevi um rascunho de ADR para ele.

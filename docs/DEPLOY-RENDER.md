# Deploy de teste no Render — tela com login + API do portal

Data: 2026-10-23. Escopo: subir no Render, ligado ao Firebird da rede local, **a tela com
login** (ADR-08) e, no mesmo processo, a **API do portal** (`/v1/segurados/verificar` e
`/v1/certificados/emitir`, RN-30). O processo e `certgen servidor --rede --proxy` (CMD do
`Dockerfile`).

Decisao do usuario (23/10/2026): a tela e o padrao no Render e a API roda junto. Antes
disso so a API subia; a tela nao tinha autenticacao (RNF-10a, revisto).

## 0. Login e usuarios (ADR-08)

- Endereco: `https://<servico>.onrender.com/` abre a tela de login; `/v1/...` continua
  respondendo ao portal com `X-API-Key`, sem sessao.
- O primeiro administrador vem de `CERTGEN_ADMIN_EMAIL` e `CERTGEN_ADMIN_SENHA`
  (preenchidos no painel), criado so quando nao existe nenhum ADMIN. Depois, troque a senha
  pela tela; as variaveis nao a alteram mais.
- Novos usuarios: menu *USUARIOS* (so ADMIN). A senha temporaria aparece uma vez; o
  usuario e obrigado a troca-la no primeiro acesso.
- Os usuarios ficam em `CERTGEN_USUARIOS_DB=/data/usuarios.sqlite`, no **disco persistente**
  do `render.yaml` (1 GB). Sem o disco, o arquivo e recriado a cada deploy: o ADMIN volta,
  mas os usuarios criados pela tela se perdem. O disco limita o servico a 1 instancia e
  faz o deploy ter uma breve interrupcao.
- Health check do Render: `/api/saude` (publico). `/docs` nao existe na tela; a referencia
  dos endpoints e `docs/API.md`.
- A pasta de saida da emissao pela tela e `/app/saida` (efemera); o que persiste e o PDF
  no S3 (marque *Upload AWS*) e o link no Firebird. *Encerrar sistema* e *Procurar...*
  nao aparecem (o navegador nao esta na maquina do servidor).

## 1. Como o FedHub chega ao banco (e por que isso nao se copia)

O FedHub-Backend **nao roda na web**. Pelo `CLAUDE.md` e `GATEWAY.md` do repositorio
(`Fedcorp-Desenvolvimentos/FedHub-Backend`):

- roda em Docker numa maquina da rede local, ao lado do Firebird (`192.168.0.6`);
- e exposto a internet por **ngrok** (plano pago, dominio fixo), atras de Caddy + Kong;
- e o unico componente com acesso ao Firebird *justamente por rodar na LAN*.

Ou seja: o FedHub nao tem um "modo de conectar no banco local pela web". O que
este projeto ja copiou do FedHub (`conexao.py`, `settings.py`, variaveis `FB_*`) e
tudo o que ha para copiar. Um servico no Render so alcanca o Firebird se a porta
3050 da rede local estiver alcancavel pela internet.

## 2. Abrir o caminho ate o Firebird (escolher UM)

### Opcao A — tunel TCP do ngrok (mais rapido para o teste de hoje)

Na maquina da rede local onde o ngrok ja esta configurado (a mesma do FedHub):

```powershell
ngrok tcp 192.168.0.6:3050
```

O ngrok devolve um endereco como `0.tcp.sa.ngrok.io:14523`. No Render:

| Variavel | Valor |
|---|---|
| `FB_HOST` | `0.tcp.sa.ngrok.io` |
| `FB_PORT` | `14523` |

Com o plano pago da conta e possivel reservar um endereco TCP fixo
(`ngrok tcp --remote-addr=...`), senao a porta muda a cada reinicio do tunel.

Atencao: isso expoe o Firebird 2.5 (autenticacao so por usuario/senha) a qualquer
IP da internet enquanto o tunel estiver aberto. Para a area de teste, aceitavel;
derrube o tunel ao terminar.

### Opcao B — encaminhamento de porta no roteador, restrito aos IPs do Render

1. No Render, em *Settings > Outbound* do servico, anotar os IPs de saida fixos
   (disponiveis em planos pagos).
2. No roteador/firewall da empresa, encaminhar uma porta externa para
   `192.168.0.6:3050` aceitando **somente** esses IPs.
3. `FB_HOST` = IP publico ou DDNS da empresa; `FB_PORT` = porta externa.

Mais segura que a opcao A e estavel; exige acesso ao roteador.

### Opcao C — API no FedHub (ADR-01, Fase 5)

A arquitetura ja previu o adaptador `CERTGEN_REPOSITORIO=api`: o Render nao falaria
com o Firebird, e sim com o FedHub pelo gateway. Esse adaptador **nao esta
implementado** (devolve 501) e as consultas QRY-nn nao existem como rotas no FedHub.
Nao e caminho para hoje; e o caminho definitivo.

## 3. Variaveis no Render

Os nomes sao os **mesmos do `.env`** deste projeto (secao "Firebird" do
`.env.example`), que sao os do FedHub: `FB_HOST`, `FB_PORT`, `FB_DATABASE`,
`FB_USER`, `FB_PASSWORD`, `FB_CHARSET`, `FB_POOL_SIZE`.

O FedHub tem ainda `APP_ENVIRONMENT` e o conjunto `FB_*_DEV` (banco de
desenvolvimento). **Este projeto ignora essas variaveis**: aqui so existe um banco
(`CERTGEN_REPOSITORIO=firebird`). Se o `.env` local recebeu o bloco do FedHub, so o
que estiver nos nomes `FB_*` sem sufixo e lido.

Lista completa com o que preencher no painel: `render.yaml` (os itens `sync: false`).
A chave `CERTGEN_API_KEY` pode ser a mesma da LAN ou uma nova:
`python -c "import secrets;print(secrets.token_hex(16))"`.

## 4. Subir

1. Commit e push de `Dockerfile`, `.dockerignore`, `render.yaml` e desta pagina para o
   GitHub (`fedcorpdesenvolvimento/CertificadosGerador`).
2. render.com > *New* > *Blueprint* > escolher o repositorio. O Render le o
   `render.yaml` e pede os valores `sync: false`.
3. O build instala `libfbclient2`, o pacote, o Chromium do Playwright e roda os 309
   testes unitarios/contrato. Dura alguns minutos na primeira vez.
4. Quando o log mostrar `API do portal em http://0.0.0.0:<porta>/v1`, testar:

```bash
curl -X POST https://certgen-api.onrender.com/v1/segurados/verificar \
  -H "X-API-Key: <chave>" -H "Content-Type: application/json" \
  -d '{"administradora":"0000001192","cpf_cnpj":"33016330725"}'
```

Depois a emissao, como em `docs/TESTE-API-POSTMAN.md` (trocar a base URL da colecao).

## 5. O que esperar e como diagnosticar

| Sintoma | Causa provavel | Onde olhar |
|---|---|---|
| Build para em `pytest` | teste quebrado no commit | log do build |
| Deploy sobe e cai com `CERTGEN_API_KEY ausente` | variavel nao preenchida | Environment do servico |
| `502` com "Nao foi possivel conectar em host/porta:..." | tunel fechado, porta errada ou firewall | `ngrok` / roteador; `FB_HOST`/`FB_PORT` |
| Emissao demora > 30 s ou `Out of memory` | Chromium no plano Starter | subir para `standard` |
| `502` na emissao com credencial AWS | `AWS_*` ausentes (SEC-01) | `docs/TESTE-API-POSTMAN.md`, diagnostico do 502 |
| Verificacao funciona e emissao nao | banco OK, falta S3 ou Chromium | log da chamada (RNF-13) |

Latencia: cada consulta atravessa Ohio -> Brasil pelo tunel; a cascata de QRY faz
varias idas. Para o teste e aceitavel; em producao a opcao C elimina isso.

## 6. Diferencas em relacao ao servidor da LAN

- `scripts/iniciar_api.ps1` continua valendo para a LAN; no Render o processo e o
  `CMD` do `Dockerfile` e o reinicio e do Render.
- Logs (RNF-13) vao para o stdout, visiveis em *Logs* do servico, em vez de `logs/`.
- O disco e efemero: `/app/saida` e limpo a cada deploy. O que persiste e o PDF no S3
  (RF-21) e o link gravado em `segurados_inc` (RD-20a).
- Health check do Render bate em `/openapi.json` (sem chave). `/v1/saude` continua
  exigindo `X-API-Key` (RN-30).

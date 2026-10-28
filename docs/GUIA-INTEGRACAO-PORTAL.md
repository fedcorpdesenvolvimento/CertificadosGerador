# Guia de integração — emissão de certificados pela API

Para: equipe técnica do portal que vai consultar segurados e gerar o certificado de
seguro incêndio/conteúdo da FedCorp.

Versão do guia: 28/10/2026 (contrato ADR-09). Referência completa dos campos: `docs/API.md`
(seções 1 e 2). Contrato OpenAPI: `{base}/v1/docs` e `{base}/v1/openapi.json`.

## 1. O que você recebe da FedCorp

| Item | Valor |
|---|---|
| Endereço base (homologação) | `https://certificadosgerador.onrender.com` |
| Chave de acesso | enviada por canal seguro, separada deste guia; vai no header `X-API-Key` |
| Administradoras da sua chave | `GET /v1/administradoras` devolve código (10 caracteres) e nome |
| CPF/CNPJ de teste | enviado em separado (dado pessoal); cada emissão é real |

Regras da chave: use **somente no servidor** do portal, nunca no navegador ou em app
móvel. A chave é por cliente integrador e tem escopo: só as administradoras cadastradas
para ela respondem; as demais dão `403`. Chave ausente ou errada devolve `401`. Rotação:
a FedCorp cria a nova, entrega, e revoga a antiga; as duas convivem no intervalo.
Homologação e produção terão chaves diferentes.

## 2. Fluxo

```
1. GET  /v1/saude                       -> a chave funciona? qual o escopo?
1b. GET /v1/administradoras             -> códigos FedCorp para mapear o cadastro do portal
2. POST /v1/segurados/verificar         -> o CPF/CNPJ é segurado? quais vigências e unidades?
3. POST /v1/certificados/emitir         -> gera o PDF, devolve link ASSINADO (15 min) + JSON
4. POST /v1/certificados/link           -> link assinado novo para certificado já emitido
```

A verificação só lê dados. A emissão grava: PDF publicado no bucket privado da FedCorp e
link permanente registrado no banco. Repetir a emissão é permitido, **sempre** gera de
novo e é seguro após timeout (mesmo arquivo, mesmo endereço).

## 3. Convenções

- JSON em UTF-8; datas ISO 8601 (`AAAA-MM-DD`); dinheiro como string decimal com duas
  casas; campo sem valor é `null`, nunca omitido.
- CPF/CNPJ com ou sem pontuação; precisa ter 11 ou 14 dígitos. Nunca em query string.
- `X-Request-Id`: envie o seu (`[A-Za-z0-9._:-]`, até 64 caracteres) e ele volta em toda
  resposta; sem ele a API gera um. Todo chamado de suporte começa pelo `request_id`.
- Limite: 60 chamadas por minuto por chave. Acima disso, `429` com `Retry-After` em
  segundos.
- Timeouts: verificação responde em ~1 s; emissão leva de 10 a 30 s (geração do PDF). Na
  homologação o serviço dorme quando ocioso e a primeira chamada pode levar 60 s. Use
  timeout de 90 s na emissão e trate `503` com nova tentativa após alguns segundos.

## 4. Erros: um envelope só

Todo erro de `/v1` tem o mesmo formato. Trate pelo `codigo`, nunca pelo texto:

```json
{"codigo": "ADMINISTRADORA_NAO_PERMITIDA",
 "mensagem": "esta chave nao tem acesso a administradora informada",
 "request_id": "9f1c0c2e4b7d4c0e8d1a2b3c4d5e6f70",
 "detalhes": {"administradora": "0000000019"}}
```

| HTTP | `codigo` | Quando | O que fazer |
|---|---|---|---|
| `400` | `PEDIDO_INVALIDO` | documento sem 11/14 dígitos; administradora vazia ou > 10 caracteres; `fatura` não positiva | corrigir o pedido |
| `401` | `CHAVE_INVALIDA` | header ausente, chave errada ou revogada | conferir a chave |
| `403` | `ADMINISTRADORA_NAO_PERMITIDA` | código fora do escopo da chave | usar só os códigos de `/v1/administradoras` |
| `403` | `ORIGEM_NAO_PERMITIDA` | IP fora da lista da chave (quando configurada) | avisar a FedCorp o IP de saída |
| `404` | `CERTIFICADO_NAO_ENCONTRADO` | nenhum certificado para administradora + documento + vigência (+ fatura/certificado) | refazer a verificação e usar os campos devolvidos |
| `422` | `CORPO_MALFORMADO` | campo faltando, tipo errado, data fora de ISO; `detalhes.campos` lista | corrigir o JSON |
| `429` | `LIMITE_EXCEDIDO` | mais de 60/min por chave, ou muitas chaves erradas do mesmo IP | esperar `Retry-After` |
| `500` | `ERRO_INTERNO` | falha não prevista | informar o `request_id` à FedCorp |
| `502` | `PUBLICACAO_FALHOU` | todos os certificados do pedido falharam; `detalhes.certificados[].motivo` | mostrar os motivos e avisar a FedCorp |
| `503` | `BANCO_INDISPONIVEL`, `GERADOR_INDISPONIVEL` | banco ou gerador de PDF fora | tentar de novo mais tarde |

## 5. Endpoints

### 5.1 `GET /v1/saude`

```bash
curl https://certificadosgerador.onrender.com/v1/saude -H "X-API-Key: SUA_CHAVE"
```

```json
{"ok": true, "versao": "0.1.0", "cliente": "Portal W2BIT", "chave": "fc_Ab12c", "administradoras": "todas"}
```

`administradoras` é `"todas"` ou a lista de códigos permitidos.

### 5.2 `GET /v1/administradoras`

```json
{"quantidade": 2, "administradoras": [
  {"codigo": "0000001192", "nome": "IMODATA ADM", "abreviacao": null, "possui_portal": false},
  {"codigo": "0000000019", "nome": "PROTEST", "abreviacao": "19PAEL", "possui_portal": true}]}
```

Guarde o `codigo` no cadastro de administradoras do portal. Novas administradoras: a
FedCorp cadastra, inclui no escopo da chave e avisa; a lista passa a trazê-la.

### 5.3 `POST /v1/segurados/verificar`

```bash
curl -X POST https://certificadosgerador.onrender.com/v1/segurados/verificar \
  -H "X-API-Key: SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"administradora": "0000001192", "cpf_cnpj": "330.163.307-25"}'
```

Resposta `200` (resumida):

```json
{"existe": true, "quantidade": 6, "certificados": [
  {"nome": "NOME DO SEGURADO",
   "endereco": {"logradouro": "...", "unidade": "AP.602", "bairro": "...", "cidade": "...", "uf": "RJ", "cep": "22630010", "condominio": "..."},
   "inicio_vig": "2026-10-01", "final_vig": "2026-10-31",
   "apolice": "13008", "seq": 1, "fatura": 382196, "certificado": "CF1DI/AP.602",
   "produto": {"codigo": "0271", "nome": "...", "descricao_fatura": "...", "descricao_master": "..."}}]}
```

- `existe: false` com `quantidade: 0`: o documento não é segurado dessa administradora.
- `existe: true`: lista com as 3 vigências mais recentes e todas as unidades de cada uma.
  Mostre ao segurado e deixe-o escolher. Guarde do item escolhido **`inicio_vig`,
  `fatura` e `certificado`**: são os campos que a emissão e o link pedem.
- **Não é autenticação.** CPF não é segredo. O portal autentica o morador por conta
  própria e chama a verificação com o documento do usuário logado.
- **Latência dos dados.** As vigências são mensais, uma linha por fatura, e a fatura do mês
  entra no banco com atraso. Um morador que contrata hoje aparece em torno de **30 dias**
  depois. Até lá, `existe` é `false`: mostre algo como "certificado disponível após o
  fechamento da fatura".
- `final_vig: null`: a vigência não tem fim cadastrado. Exiba "vigência em aberto".
- Vigência encerrada não dá `false`: `existe` olha qualquer linha não cancelada.

### 5.4 `POST /v1/certificados/emitir`

```bash
curl -X POST https://certificadosgerador.onrender.com/v1/certificados/emitir \
  -H "X-API-Key: SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"administradora": "0000001192", "cpf_cnpj": "330.163.307-25",
       "vigencia": "2026-10-01", "fatura": 382196, "certificado": "CF1DI/AP.602"}'
```

- `vigencia` é o `inicio_vig` devolvido pela verificação, exato. Não é "uma data dentro do
  período".
- `fatura` e `certificado` são opcionais. Sem eles, a API emite **todos** os certificados
  daquele documento naquela vigência, um item por certificado. Recomendado: sempre enviar.

Resposta `200` (resumida):

```json
{"pedido": {"administradora": "0000001192", "cpf_cnpj": "33016330725", "vigencia": "2026-10-01", "fatura": 382196, "certificado": "CF1DI/AP.602"},
 "quantidade": 1,
 "certificados": [{
   "chave": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 382196, "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725"},
   "situacao": "publicado",
   "link": "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192/0004/102026/382196/0_33016330725_0004_13008_CF1DI-AP602_382196.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=900&...",
   "link_expira_em": "2026-10-28T13:35:00+00:00",
   "documento": {"...": "JSON espelho completo; documento.arquivo.link é o endereço permanente, que NÃO abre sem assinatura"},
   "avisos": ["REEMISSAO"],
   "motivo": null}]}
```

- `link` é uma URL **assinada**, válida até `link_expira_em` (15 minutos). Entregue ao
  segurado na hora (abrir em nova aba ou baixar). **Não guarde o link**: guarde os
  identificadores (`inicio_vig`, `fatura`, `certificado`) e peça outro em `/v1/certificados/link`
  quando o morador clicar de novo.
- O bucket é privado e o nome do arquivo não é adivinhável sem a assinatura.
- `documento` é o certificado em JSON, se o portal quiser mostrar os dados sem abrir o PDF.
  Não precisa persistir.
- `avisos` são informativos (`REEMISSAO` = já havia link e foi substituído; `ABREV_ADM_AUSENTE`,
  `PORTAL_AUSENTE` e outros vêm do cadastro e não impedem a emissão).
- Item `situacao: "falha"` traz `motivo`; os demais itens da mesma resposta podem ter sido
  publicados. Trate cada item individualmente.

### 5.5 `POST /v1/certificados/link`

Mesmo corpo da emissão. Devolve um link assinado novo para certificado já emitido, **sem
reemitir**:

```json
{"pedido": {"...": "..."}, "quantidade": 1, "certificados": [
  {"chave": {"...": "..."}, "situacao": "disponivel", "link": "https://...pdf?X-Amz-...", "link_expira_em": "2026-10-28T13:35:00+00:00"}]}
```

`situacao`: `disponivel` (use `link`), `nao_emitido` (nunca foi emitido: chame a emissão),
`falha` (`motivo`).

**Reemissão.** O PDF reflete o cadastro no momento da emissão; se o cadastro mudar
(correção, endosso) o PDF só muda quando alguém reemite. Não há "data de última
alteração" disponível; reemita por ação explícita do morador ou da administradora.

## 6. Roteiro de teste de aceitação

1. `GET /v1/saude` com a chave: `200`, `cliente` e `administradoras` corretos.
2. `GET /v1/saude` sem a chave: `401 CHAVE_INVALIDA` no envelope.
3. `GET /v1/administradoras`: `200`, lista com os códigos esperados.
4. Verificação com o CPF de teste: `200`, `existe: true`, ao menos um item.
5. Verificação com CPF inexistente (`000.000.000-00`): `200`, `existe: false`.
6. Verificação com CPF de 9 dígitos: `400 PEDIDO_INVALIDO`.
7. Verificação com administradora fora do escopo: `403 ADMINISTRADORA_NAO_PERMITIDA`
   (se a chave for "todas", `200`).
8. Emissão com `vigencia`, `fatura` e `certificado` do passo 4: `200`, item `publicado`,
   `link` abre o PDF, `link_expira_em` preenchido.
9. Emissão com `vigencia` de um mês sem fatura (`2020-01-01`): `404`.
10. Repetir o passo 8: `200` com `avisos` contendo `REEMISSAO`.
11. `POST /v1/certificados/link` com os mesmos campos: `200`, `disponivel`, link novo abre.
12. Esperar 15 minutos e abrir o `link` do passo 8: `AccessDenied` (esperado).
13. Enviar `X-Request-Id: teste-001` em qualquer chamada: o header volta igual.

A collection do Postman (`FedCorp-Certificados-API.postman_collection.json`) cobre os
passos acima; o environment vem com `api_key` **em branco**: preencha com a chave recebida e
`cpf_cnpj` com o documento de teste.

## 7. Boas práticas e limites

- Não guarde o CPF/CNPJ nem o endereço devolvidos além do necessário para a sessão do
  segurado: são dados pessoais (LGPD). Persista só os identificadores.
- Não chame a verificação em laço para "descobrir" CPFs: há limite por chave e cada
  chamada é registrada com `request_id`, administradora, documento, resultado, IP e duração.
- Mostre o link assinado apenas ao segurado autenticado; ele expira sozinho.
- Se a chave vazar, avise a FedCorp: a chave nova é criada e a antiga revogada na hora, sem
  janela de indisponibilidade.
- Versionamento: mudanças compatíveis (campo novo, aviso novo, código novo) entram em `/v1`
  e no changelog de `docs/API.md`; mudança incompatível vira `/v2` com convivência.

## 8. Contato

Dúvidas de integração, pedido de CPFs de teste e incidentes com a chave:
alberto@grupofedcorp.com.br. Informe sempre o `request_id`.

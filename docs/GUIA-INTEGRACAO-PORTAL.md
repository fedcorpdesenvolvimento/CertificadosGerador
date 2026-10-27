# Guia de integração — emissão de certificados pela API

Para: equipe técnica do portal que vai consultar segurados e gerar o certificado de
seguro incêndio/conteúdo da FedCorp.

Versão do guia: 27/10/2026. Referência completa dos campos: `docs/API.md` (seções 1 e 2).

## 1. O que você recebe da FedCorp

| Item | Valor |
|---|---|
| Endereço base (homologação) | `https://certificadosgerador.onrender.com` |
| Chave de acesso | enviada por canal seguro; vai no header `X-API-Key` |
| Código da administradora | ex.: `0000001192` (10 caracteres, com zeros à esquerda) |
| CPF/CNPJ de teste | combinado com a FedCorp (cada emissão é real: gera PDF e grava link) |

Regras da chave: use **somente no servidor** do portal, nunca no navegador ou em app
móvel. Toda chamada é por HTTPS. Chave ausente ou errada devolve `401`.

## 2. Fluxo em três chamadas

```
1. GET  /v1/saude                       -> a chave funciona?
2. POST /v1/segurados/verificar         -> o CPF/CNPJ é segurado? quais vigências?
3. POST /v1/certificados/emitir         -> gera o PDF, devolve o link e o JSON
```

A verificação só lê dados. A emissão grava: PDF publicado no bucket da FedCorp e link
registrado no banco. Repetir a emissão é permitido e **sempre** gera de novo (o link
devolvido é o mesmo endereço, com o arquivo sobrescrito).

## 3. Passo a passo

### 3.1 Testar a chave

```bash
curl https://certificadosgerador.onrender.com/v1/saude \
  -H "X-API-Key: SUA_CHAVE"
```

Resposta esperada:

```json
{"ok": true, "versao": "0.1.0"}
```

Se vier `401`, a chave está errada ou o header não foi enviado.

### 3.2 Verificar o segurado (login do portal)

```bash
curl -X POST https://certificadosgerador.onrender.com/v1/segurados/verificar \
  -H "X-API-Key: SUA_CHAVE" \
  -H "Content-Type: application/json" \
  -d '{"administradora": "0000001192", "cpf_cnpj": "330.163.307-25"}'
```

Pontuação no CPF/CNPJ é aceita e removida. Precisa ter 11 ou 14 dígitos.

Resposta `200` (resumida):

```json
{
  "existe": true,
  "quantidade": 2,
  "certificados": [
    {
      "nome": "NOME DO SEGURADO",
      "endereco": {"logradouro": "...", "unidade": "AP.602", "bairro": "...", "cidade": "...", "uf": "RJ", "cep": "22630010", "condominio": "..."},
      "inicio_vig": "2026-08-01",
      "final_vig": "2026-08-31",
      "apolice": "13008", "seq": 1, "fatura": 381201, "certificado": "CF1DI/AP.602",
      "produto": {"codigo": "0117", "nome": "...", "descricao_master": "TOTAL CONTEÚDO"}
    }
  ]
}
```

Como usar:

- `existe: false` com `quantidade: 0`: o documento não é segurado dessa administradora.
  Não autentique.
- `existe: true`: a lista traz as 3 vigências mais recentes, com todas as unidades de cada
  uma. Mostre ao segurado e deixe-o escolher a unidade/vigência que quer imprimir.
- Guarde do item escolhido **três campos**: `inicio_vig`, `fatura` e `certificado`. São
  exatamente os que a emissão pede.

### 3.3 Emitir o certificado

```bash
curl -X POST https://certificadosgerador.onrender.com/v1/certificados/emitir \
  -H "X-API-Key: SUA_CHAVE" \
  -H "Content-Type: application/json" \
  -d '{
    "administradora": "0000001192",
    "cpf_cnpj": "330.163.307-25",
    "vigencia": "2026-08-01",
    "fatura": 381201,
    "certificado": "CF1DI/AP.602"
  }'
```

- `vigencia` é o `inicio_vig` devolvido pela verificação, no formato `AAAA-MM-DD`. Não é
  "uma data dentro do período": tem de ser igual ao início.
- `fatura` e `certificado` são opcionais. Sem eles, a API emite **todos** os certificados
  daquele documento naquela vigência, um item por certificado.
- A chamada é síncrona e leva alguns segundos (geração do PDF). Configure timeout de ao
  menos 60 segundos no cliente HTTP.

Resposta `200` (resumida):

```json
{
  "pedido": {"administradora": "0000001192", "cpf_cnpj": "33016330725", "vigencia": "2026-08-01", "fatura": 381201, "certificado": "CF1DI/AP.602"},
  "quantidade": 1,
  "certificados": [
    {
      "chave": {"administradora": "0000001192", "apolice": "13008", "seq": 1, "fatura": 381201, "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725"},
      "situacao": "publicado",
      "link": "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192/0004/082026/381201/0_33016330725_0004_13008_CF1DI-AP602_381201.pdf",
      "documento": {"...": "JSON espelho completo do certificado"},
      "avisos": ["REEMISSAO"],
      "motivo": null
    }
  ]
}
```

Como usar:

- Para cada item com `situacao: "publicado"`, `link` é a URL do PDF. Entregue ao segurado
  (abrir em nova aba ou baixar).
- `documento` é o conteúdo do certificado em JSON, se o portal quiser mostrar os dados na
  tela sem abrir o PDF.
- `avisos` são informativos. `REEMISSAO` significa que já havia link gravado e ele foi
  substituído.
- Item com `situacao: "falha"` traz o `motivo`. Os demais itens da mesma resposta podem
  ter sido publicados normalmente.

## 4. Códigos de resposta

| Código | Verificação | Emissão | O que fazer |
|---|---|---|---|
| `200` | ok | ao menos um certificado publicado | usar `link` |
| `400` | administradora vazia ou > 10 caracteres; documento sem 11/14 dígitos | idem, mais `vigencia` fora do formato ISO | corrigir o pedido |
| `401` | chave ausente ou inválida | idem | conferir o header `X-API-Key` |
| `404` | — | nenhum certificado para o conjunto administradora + documento + vigência (+ fatura/certificado) | refazer a verificação e usar os campos devolvidos |
| `422` | corpo malformado (campo faltando, tipo errado) | idem | corrigir o JSON |
| `502` | — | todos os certificados falharam (armazenamento ou banco) | mostrar os `motivo`s e avisar a FedCorp |
| `503` | banco indisponível | gerador de PDF indisponível | tentar de novo mais tarde |

Observação do ambiente de homologação: o serviço fica em suspensão quando ocioso. A
primeira chamada depois de um tempo parado pode levar de 30 a 60 segundos para responder.
Trate isso como normal e mantenha o timeout alto.

## 5. Roteiro de teste de aceitação

1. `GET /v1/saude` com a chave: `200`.
2. `GET /v1/saude` sem a chave: `401`.
3. Verificação com um CPF de teste fornecido pela FedCorp: `200`, `existe: true`, lista
   com ao menos um item.
4. Verificação com um CPF inexistente (ex.: `000.000.000-00`): `200`, `existe: false`.
5. Verificação com CPF de 9 dígitos: `400`.
6. Emissão com `vigencia`, `fatura` e `certificado` copiados do item do passo 3: `200`,
   um item `publicado`, `link` abre o PDF no navegador.
7. Emissão com `vigencia` de um mês sem fatura (ex.: `2020-01-01`): `404`.
8. Repetir o passo 6: `200` com `avisos: ["REEMISSAO"]`.

Uma coleção do Postman com as mesmas chamadas está em `docs/postman/`
(`Certgen-API.postman_collection.json`). Troque a variável de ambiente `base_url` para o
endereço acima e preencha `api_key`.

## 6. Boas práticas e limites

- Não guarde o CPF/CNPJ nem o endereço devolvidos além do necessário para a sessão do
  segurado: são dados pessoais.
- Não chame a verificação em laço para "descobrir" CPFs: cada chamada é registrada com
  administradora, documento, resultado e duração.
- O link do PDF é público (quem tem a URL abre o arquivo). Mostre-o apenas ao segurado
  autenticado.
- Uma única chave atende o portal inteiro. Se ela vazar, avise a FedCorp para rotacionar;
  haverá uma breve janela de indisponibilidade na troca.

## 7. Contato

Dúvidas de integração e pedido de CPFs de teste: alberto@grupofedcorp.com.br.

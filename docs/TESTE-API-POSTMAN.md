# Testar a API do portal com o Postman

Guia para validar `certgen api` (Fase 8, seção 11.1 da especificação) a partir do Postman.
São dois endpoints com a mesma chave:

- **Verificação** (`/v1/segurados/verificar`): o portal pergunta se o CPF/CNPJ é segurado
  ativo hoje daquela administradora e recebe só `{"existe": true|false}`. É a chamada do
  login do segurado; só lê o banco.
- **Emissão** (`/v1/certificados/emitir`): emite o certificado, publica o PDF no S3, grava o
  link no Firebird e devolve o link **e o JSON espelho** do certificado.

> Atenção: cada chamada com `200` é uma emissão **real**: gera PDF e JSON em
> `CERTGEN_PASTA_SAIDA`, envia o PDF ao bucket e grava `link_certificado_aws`
> na `segurados_inc`. Use segurados de teste ou combine antes com o usuário.

## 1. Preparar o servidor

1. Abra o PowerShell na pasta `U:\--2021\05-Gerador Certificados`.
2. Ative o ambiente:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
3. Confirme o `.env`: `FB_*` preenchidos, `CERTGEN_API_KEY` com 32 caracteres
   hexadecimais, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (ou perfil AWS),
   `AWS_REGION`, `AWS_S3_BUCKET`, `CERTGEN_PASTA_SAIDA`.
   Para gerar uma chave nova:
   ```powershell
   python -c "import secrets; print(secrets.token_hex(16))"
   ```
4. Teste o Firebird:
   ```powershell
   python -m certgen.cli check-conexao
   ```
5. Suba a API:
   ```powershell
   python -m certgen.cli api                # só nesta máquina: http://127.0.0.1:8010
   python -m certgen.cli api --rede         # Postman em outra máquina da LAN
   python -m certgen.cli api --porta 8011   # outra porta, se a 8010 estiver ocupada
   ```
   Sem `CERTGEN_API_KEY` o processo recusa subir (RN-30). Com `--rede`, libere a
   porta 8010 no firewall do Windows e use o IP da máquina no Postman.
6. Abra `http://127.0.0.1:8010/docs` no navegador: é o contrato OpenAPI gerado.

## 2. Configurar o Postman

1. Crie uma **Collection** chamada `Certgen API`.
2. Crie um **Environment** chamado `Certgen local` com as variáveis:

   | Variável | Valor inicial | Observação |
   |---|---|---|
   | `base_url` | `http://127.0.0.1:8010` | ou `http://<ip-da-maquina>:8010` |
   | `api_key` | a chave do `.env` | marque o tipo **secret** |

3. Selecione o environment no canto superior direito.
4. Na aba **Authorization** da Collection escolha **API Key**:
   Key `X-API-Key`, Value `{{api_key}}`, Add to **Header**.
   Todas as requests herdam essa configuração (Type = *Inherit auth from parent*).

## 3. Requests

### 3.1 Saúde (valida a chave)

- **GET** `{{base_url}}/v1/saude`
- Esperado: `200`
  ```json
  {"ok": true, "versao": "x.y.z"}
  ```

### 3.2 Verificar segurado (login do portal)

- **POST** `{{base_url}}/v1/segurados/verificar`
- Aba **Body** → **raw** → **JSON**:
  ```json
  {
    "administradora": "0000001192",
    "cpf_cnpj": "330.163.307-25"
  }
  ```
  Não há vigência: a pergunta é "é segurado ativo **hoje**?" (`inicio_vig <= hoje <= final_vig`, RN-35).
- Esperado: `200` e **só** isto:
  ```json
  {"existe": true}
  ```
  `false` quando o CPF não é da administradora, não existe, está cancelado ou a vigência
  já terminou. Nenhum dado do segurado sai. Esta chamada não grava nada e não gera arquivo.
- Teste também com um CPF de outra administradora (deve dar `false`) e com a mesma
  administradora e um CPF com vigência encerrada (`false`).

### 3.3 Emitir certificado

- **POST** `{{base_url}}/v1/certificados/emitir`
- Aba **Body** → **raw** → **JSON**:
  ```json
  {
    "administradora": "0000001192",
    "cpf_cnpj": "330.163.307-25",
    "vigencia": "2026-07-01"
  }
  ```
  - `administradora`: código de `pessoas.pessoa`, com os zeros à esquerda.
  - `cpf_cnpj`: pontuação é aceita e removida antes da consulta.
  - `vigencia`: ISO 8601 (`AAAA-MM-DD`) e **igual** a `segurados_inc.inicio_vig` (RN-31).
    Não é "data dentro do período".
- Esperado na primeira chamada: `200`
  ```json
  {
    "pedido": {"administradora": "0000001192", "cpf_cnpj": "33016330725", "vigencia": "2026-07-01"},
    "quantidade": 1,
    "certificados": [
      {
        "chave": {"administradora": "0000001192", "apolice": "13008", "seq": 1,
                  "fatura": 380819, "certificado": "CF1DI/AP.602", "cpf_cnpj": "33016330725"},
        "situacao": "publicado",
        "link": "https://certincendioaws.s3.us-east-2.amazonaws.com/0000001192/0004/072026/380819/....pdf",
        "documento": { "...": "o JSON espelho completo do certificado, com arquivo.link igual ao link acima" },
        "avisos": [],
        "motivo": null
      }
    ]
  }
  ```
- A resposta demora alguns segundos: o PDF é renderizado no Chromium do Playwright.
  Se o Postman der timeout, aumente em *Settings → General → Request timeout*.

### 3.4 Repetir o mesmo pedido

- Reenvie a request 3.3 sem alterar nada.
- Esperado: `200`, `situacao` = `"ja_publicado"`, mesmo `link`, mesmo `documento`
  (relido do JSON em disco) e **nenhum** arquivo novo em `CERTGEN_PASTA_SAIDA` (RN-33).
- Se o link já estava no banco mas o JSON não está na pasta de saída (emitido pela tela
  em outra pasta, ou pelo legado), o item sai como `falha` com motivo `DocumentoAusente`
  e a resposta é `502`. Reemita pela tela para regravar o JSON.

## 4. Casos de erro a verificar

| # | Como provocar | Esperado |
|---|---|---|
| 1 | Desmarcar a Authorization (Type = *No Auth*) | `401` `{"detail": "chave de autenticacao ausente ou invalida"}` |
| 2 | `api_key` com um caractere trocado | `401`, mesma mensagem; nada gravado no banco |
| 3 | `vigencia` como `01/07/2026` | `422` (validação do FastAPI, corpo inválido) |
| 4 | Corpo sem `cpf_cnpj` | `422` |
| 5 | `cpf_cnpj` com letras ou tamanho errado (nos dois endpoints) | `400` `{"erro": "..."}` |
| 6 | CPF que existe, mas `vigencia` de outro mês | `404` `{"erro": "...", "pedido": {...}}` |
| 7 | Administradora inexistente | `404` |
| 8 | Firebird parado ou `FB_*` errado | `500`/`503`, e nada publicado |
| 9 | Credenciais AWS inválidas | `502`: item com `situacao` = `"falha"` e `motivo` do S3; banco **não** recebe link |

O código `502` só aparece quando **nenhum** certificado do pedido pôde ser
publicado. Se um CPF tiver duas unidades (RD-22) e uma falhar, a resposta é
`200` com um item `publicado` e outro `falha` (RN-32).

## 5. Conferir o efeito de cada emissão

1. **Arquivos**: em `CERTGEN_PASTA_SAIDA\<administradora>\<produto>\<competência>\<fatura>\`
   devem existir o PDF e o JSON. O JSON deve ter `arquivo.link` igual ao link devolvido.
2. **S3**: abra o `link` da resposta no navegador; o PDF deve baixar (URL pública, GAP-23).
3. **Banco** (leitura, no ISQL ou no FlameRobin):
   ```sql
   SELECT administradora, apolice, seq, fatura, certificado, cpf_cnpj,
          link_certificado_aws, dt_cria_link
     FROM segurados_inc
    WHERE administradora = '0000001192' AND cpf_cnpj = '33016330725'
      AND inicio_vig = '2026-07-01' AND status_seg <> 'C';
   ```
   `link_certificado_aws` igual ao da resposta e `dt_cria_link` com a data/hora da chamada.
4. **Log**: o terminal do `certgen api` mostra uma linha JSON por chamada
   (`"evento": "emissao_portal"`) com pedido, chaves, situação e duração.
   Ela **não** deve conter a chave da API nem o nome do segurado (RNF-13).

## 6. Escolher dados de teste no banco

Para achar um segurado ainda sem link:

```sql
SELECT FIRST 10 administradora, cpf_cnpj, inicio_vig, apolice, fatura, certificado
  FROM segurados_inc
 WHERE status_seg <> 'C' AND cpf_cnpj <> ''
   AND (link_certificado_aws IS NULL OR link_certificado_aws = '')
   AND administradora = '0000001192'
 ORDER BY inicio_vig DESC;
```

Use `administradora`, `cpf_cnpj` e `inicio_vig` dessa linha no corpo do POST.

## 7. Testes automáticos no Postman (opcional)

Na aba **Tests** da request 3.2 (verificação):

```javascript
pm.test("status 200", () => pm.response.to.have.status(200));
const v = pm.response.json();
pm.test("so o booleano", () => pm.expect(Object.keys(v)).to.eql(["existe"]));
pm.test("existe e boolean", () => pm.expect(v.existe).to.be.a("boolean"));
```

Na aba **Tests** da request 3.3 (emissão):

```javascript
pm.test("status 200", () => pm.response.to.have.status(200));
const r = pm.response.json();
pm.test("tem certificados", () => pm.expect(r.quantidade).to.be.above(0));
pm.test("todo item tem link ou motivo", () => {
  r.certificados.forEach(c => {
    if (c.situacao === "falha") pm.expect(c.motivo).to.be.a("string");
    else pm.expect(c.link).to.match(/^https:\/\/.+\.pdf$/);
  });
});
pm.test("cpf so digitos", () => pm.expect(r.pedido.cpf_cnpj).to.match(/^\d+$/));
pm.test("documento acompanha o link", () => {
  r.certificados.filter(c => c.link).forEach(c =>
    pm.expect(c.documento.arquivo.link).to.eql(c.link));
});
```

Na request 3.1:

```javascript
pm.test("saude ok", () => pm.expect(pm.response.json().ok).to.be.true);
```

## 8. Entregar ao portal

Exporte a Collection e o Environment (**...** → *Export*) **removendo o valor**
de `api_key` antes. A chave vai por canal seguro, nunca junto com o arquivo
exportado nem pelo repositório (RN-30, SEC-01).

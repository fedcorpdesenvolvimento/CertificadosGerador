# Testar a API do portal com o Postman

Guia para validar `certgen api` (Fase 8, seção 11.1 da especificação) a partir do Postman.
São dois endpoints com a mesma chave:

- **Verificação** (`/v1/segurados/verificar`): o portal pergunta se o CPF/CNPJ é segurado
  (não cancelado) daquela administradora e recebe `existe` mais as 3 vigências mais
  recentes, com nome, endereço, apólice, seq, fatura, certificado e produto. É a chamada
  do login do segurado; só lê o banco. Não olha vigência (RN-35, 14/09/2026).
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
  Não há vigência: a pergunta é "este CPF/CNPJ tem alguma linha não cancelada nesta
  administradora?" (RN-35, revista em 14/09/2026).
- Esperado: `200` com `existe`, `quantidade` e a lista `certificados` das 3 vigências mais
  recentes (todas as unidades de cada mês):
  ```json
  {
    "existe": true,
    "quantidade": 3,
    "certificados": [
      {
        "nome": "...",
        "endereco": {"logradouro": "...", "unidade": "AP 1302", "bairro": "...", "cidade": "...",
                     "uf": "RJ", "cep": "...", "condominio": "..."},
        "inicio_vig": "2026-08-01", "final_vig": "2026-08-31",
        "apolice": "15008", "seq": 1, "fatura": 381529, "certificado": "3082/01/AP 1302",
        "produto": {"codigo": "0117", "nome": "...", "descricao_fatura": "INCENDIO CONTEUDO RESIDENCIAL ...",
                    "descricao_master": "TOTAL CONTEÚDO"}
      }
    ]
  }
  ```
  `existe: false` vem com `quantidade: 0` e lista vazia, quando o CPF não é da
  administradora, não existe ou está cancelado. Vigência encerrada **não** dá `false`.
  Esta chamada não grava nada.
- Guarde `inicio_vig`, `fatura` e `certificado` do item escolhido: são exatamente os
  campos que a emissão (3.3) aceita para apontar aquela unidade. A Collection importada
  faz isso sozinha (variáveis `vigencia`, `fatura`, `certificado`).
- Teste também com um CPF de outra administradora (`existe: false`) e com um CPF
  inventado (`false`).

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
  - `fatura` e `certificado` (opcionais, RD-31): valores vindos da verificação, para
    emitir só aquela unidade quando o CPF tem mais de uma no mesmo mês. Acrescente
    `"fatura": 380819, "certificado": "CF1DI/AP.602"` ao body.
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
- Esperado (RN-33 revista em 14/09/2026): `200`, `situacao` = `"publicado"` de novo, o
  **mesmo** `link` (mesma chave no S3, objeto sobrescrito), `documento` novo e o aviso
  `"REEMISSAO"` em `avisos`. Em `CERTGEN_PASTA_SAIDA` o PDF e o JSON são sobrescritos no
  mesmo nome, sem cópia ` (1)`.
- Segurado cujo link no banco veio do Delphi (formato `.../0000000019//072026/...`, sem
  produto) também sai `publicado` com `REEMISSAO`, e o link passa a ser o novo. O PDF antigo
  fica órfão no S3.

## 4. Casos de erro a verificar

| # | Como provocar | Esperado |
|---|---|---|
| 1 | Desmarcar a Authorization (Type = *No Auth*) | `401` `{"detail": "chave de autenticacao ausente ou invalida"}` |
| 2 | `api_key` com um caractere trocado | `401`, mesma mensagem; nada gravado no banco |
| 3 | `vigencia` como `01/07/2026` | `422` (validação do FastAPI, corpo inválido) |
| 4 | Corpo sem `cpf_cnpj` | `422` |
| 5 | `cpf_cnpj` com letras ou tamanho errado (nos dois endpoints) | `400` `{"erro": "..."}` |
| 5a | `administradora` com mais de 10 caracteres, por exemplo `"{0000000019}"` com chaves digitadas no body | `400`. No Postman, variável é `{{nome}}` com **duas** chaves; com uma só vira texto literal. Use `"{{administradora}}"` ou o código puro `"0000000019"` |
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

---

## 9. Esta máquina como servidora das duas APIs (LAN)

Levantado em 11/09/2026: computador `TI-Alberto`, IP `192.168.10.101` (adaptador Wi-Fi).
O portal e o Postman de outras máquinas chegam por `http://192.168.10.101:8010`.

### 9.1 IP fixo

O IP muda se o roteador redistribuir o DHCP; o portal precisa de um endereço estável.
Peça ao responsável pela rede uma **reserva de DHCP** para o MAC desta máquina, ou fixe
o IP em *Configurações → Rede e Internet → Wi-Fi → Propriedades → Atribuição de IP →
Manual*. Prefira cabo (Ethernet) a Wi-Fi para um servidor.

### 9.2 Firewall do Windows (uma vez, PowerShell como administrador)

```powershell
New-NetFirewallRule -DisplayName "Certgen API 8010" -Direction Inbound -Protocol TCP `
  -LocalPort 8010 -Action Allow -Profile Private,Domain -RemoteAddress LocalSubnet
```

`-RemoteAddress LocalSubnet` limita a regra à rede interna (GAP-23: sem TLS, nunca abrir
para a internet). Se o perfil da rede estiver como *Público*, mude para *Privado* em
*Configurações → Rede → Propriedades da rede*, senão a regra não se aplica.

### 9.3 Subir a API aceitando a rede

Manual, no PowerShell:

```powershell
cd "U:\--2021\05-Gerador Certificados"
.\.venv\Scripts\Activate.ps1
python -m certgen.cli api --rede
```

Ou pelo script, que reinicia sozinho se o processo cair e grava o log em `logs\api-AAAA-MM-DD.log`:

```powershell
.\scripts\iniciar_api.ps1
```

**Primeira subida é lenta.** O projeto e a `.venv` ficam na pasta de rede `U:`; só
carregar os módulos leva de 30 s a mais de 2 min a frio (medido em 14/09/2026: 34 s de
importação). A janela parece travada e não imprime nada nesse tempo. Espere a linha
`Uvicorn running on http://0.0.0.0:8010`. Nas subidas seguintes, com o cache do Windows
quente, leva 2 a 5 s.

Confirme na própria máquina: `http://127.0.0.1:8010/docs` deve abrir. De outra máquina
da rede, no navegador: `http://192.168.10.101:8010/docs`. Se não abrir de fora mas abrir
localmente, o problema é firewall (9.2) ou perfil de rede.

**Perfil de rede Público bloqueia tudo.** A regra de 9.2 vale só para *Privado* e
*Domínio*. Verifique e corrija (PowerShell como administrador):

```powershell
Get-NetConnectionProfile | Select-Object Name, NetworkCategory, InterfaceAlias
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
```

Em 14/09/2026 a rede `FEDCORPWF 3` desta máquina estava como **Public**: nenhuma máquina
da rede conseguia chegar, embora a API respondesse `200` localmente e pelo IP
`192.168.10.101` a partir da própria máquina.

### 9.4 Subir junto com o Windows (Agendador de Tarefas)

1. *Agendador de Tarefas → Criar Tarefa*.
2. Geral: nome `Certgen API`; marcar *Executar estando o usuário conectado ou não* e
   *Executar com privilégios mais altos* desmarcado (não precisa).
3. Disparadores: *Ao fazer logon* (ou *Na inicialização*, se a unidade `U:` estiver
   mapeada por GPO antes do logon; se não, use logon).
4. Ações: *Iniciar um programa*
   - Programa: `powershell.exe`
   - Argumentos: `-ExecutionPolicy Bypass -WindowStyle Hidden -File "U:\--2021\05-Gerador Certificados\scripts\iniciar_api.ps1"`
5. Condições: desmarcar *Iniciar a tarefa somente se o computador estiver ligado à rede elétrica*.
6. Configurações: marcar *Se a tarefa falhar, reiniciar a cada 1 minuto*.

Atenção: o projeto roda direto da pasta de rede `U:`. Se a unidade não estiver mapeada
quando a tarefa disparar, a API não sobe. Para um servidor definitivo, copiar o projeto
para um disco local é o caminho.

### 9.5 O que precisa estar de pé

| Dependência | Onde | Se faltar |
|---|---|---|
| Firebird 2.5 | `192.168.0.6` (FATURA.GDB) | verificação e emissão respondem `5xx`; o script reinicia a API |
| Chromium do Playwright | `python -m playwright install chromium` nesta máquina | emissão falha (`503`); verificação continua |
| Credenciais AWS | `.env` (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) | emissão sai `502` com `falha`; nada gravado no banco |
| `CERTGEN_API_KEY` | `.env` | a API recusa subir |
| Pasta `CERTGEN_PASTA_SAIDA` | disco local ou rede acessível a este usuário | emissão falha antes de publicar |

Esta máquina precisa ficar ligada e sem suspender: *Configurações → Sistema → Energia →
Tela e suspensão → Nunca* quando conectado.

## 10. Postman apontando para o servidor da rede

1. Duplique o environment `Certgen local` como `Certgen rede` e troque `base_url` para
   `http://192.168.10.101:8010`. A `api_key` é a mesma.
2. Com o environment `Certgen rede` selecionado, rode primeiro `GET /v1/saude` (3.1).
   `200` prova chave, firewall e rota de rede de uma vez.
3. Rode a verificação (3.2) com um CPF ativo e um inativo; depois a emissão (3.3) e a
   repetição (3.4). A ordem importa: a emissão grava no banco e no S3.
4. Use *Collection Runner* (botão *Run* na Collection) para executar as quatro requests em
   sequência com os testes da seção 7. Para repetir sem efeitos, mantenha só saúde e
   verificação no runner.
5. Para entregar ao portal, exporte Collection e Environment sem o valor de `api_key`
   (seção 8) e informe separadamente o endereço `http://192.168.10.101:8010` e a chave.

## 11. Importar tudo pronto

Em vez de criar Collection e Environments à mão (seções 2 e 3), importe os arquivos de
`docs/postman/`:

| Arquivo | O que é |
|---|---|
| `Certgen-API.postman_collection.json` | Collection com as requests em ordem (saúde, verificação, emissão por vigência, emissão apontando fatura + certificado, repetição), a pasta *Erros esperados* e os testes automáticos |
| `Certgen-local.postman_environment.json` | Environment `Certgen local` (`http://127.0.0.1:8010`) |
| `Certgen-rede.postman_environment.json` | Environment `Certgen rede` (`http://192.168.10.101:8010`) |

1. Postman → *Import* → arraste os três arquivos (ou *Upload Files*).
2. Selecione o environment desejado e preencha `api_key` com a chave do `.env`
   (*Current value*; o arquivo vem com o valor vazio de propósito, RN-30).
3. Ajuste `administradora` e `cpf_cnpj` para o segurado de teste. As requests usam essas
   variáveis; não é preciso editar o body. A request 2 (verificação) preenche sozinha
   `vigencia`, `fatura` e `certificado` com a vigência mais recente devolvida.
4. Rode na ordem 1 → 2 → 3 (ou 3b) → 4. As requests 3, 3b e 4 gravam no S3 e no banco.
   Os testes de cada request aparecem na aba *Test Results*.
5. *Run collection* executa tudo em sequência; desmarque as requests 3, 3b e 4 para
   repetir sem efeito.

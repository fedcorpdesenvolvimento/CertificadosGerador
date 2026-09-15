# Gerador de Certificados

Emite certificados de seguro incêndio/conteúdo em PDF e o JSON espelhado,
lendo o Firebird da FedCorp. Reescrita do formulário Delphi
`UfrmImprimeCertInc`.

A especificação completa está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md).
Ela é a fonte da verdade: cada módulo cita os IDs (`RF`, `RN`, `RD`, `QRY`)
que implementa.

Documentação das APIs (portal e tela, com o JSON espelho e os códigos de aviso):
[docs/API.md](docs/API.md). Teste manual da API do portal: [docs/TESTE-API-POSTMAN.md](docs/TESTE-API-POSTMAN.md).

## Repositório

- Remoto: `https://github.com/fedcorpdesenvolvimento/CertificadosGerador.git` (privado — contém PDFs de referência com dados pessoais, ver RNF-06a).
- Trabalho direto na pasta de rede `U:\--2021\05-Gerador Certificados`.
- Fluxo: `git add -A` → `git commit -m "..."` → `git pull --rebase origin main` → `git push`.

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .[dev]
copy .env.example .env      # ou copiar o .env do U:\--2021\04-EnvioPorto (mesmas variaveis FB_*)
```

O PDF exige o Chromium do Playwright: `python -m playwright install chromium` (uma vez por máquina).

## Verificação

```powershell
pytest                              # suite de testes (integração pula sem .env)
python -m certgen.cli check-conexao  # SELECT 1 no Firebird (Fase 0)

# Tela web (Fase 4): menu com CERTIFICADO INCENDIO / PRESTAMISTA-ALUG / VIDA
python -m certgen.cli web            # abre em http://127.0.0.1:8000/

# PDF + JSON de todos os certificados de uma fatura (Fases 2 e 3)
python -m certgen.cli emitir --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --saida C:\certificados
# ... e publicar cada PDF no S3, gravando o link no banco e no JSON (RF-21; a tela tem o checkbox Upload AWS)
python -m certgen.cli emitir --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --saida C:\certificados --upload-aws

# Compartilhar na rede interna para a equipe testar (RNF-10a; liberar a porta 8000 no firewall)
python -m certgen.cli web --rede --sem-navegador

# APIs para o portal (Fase 8, secao 11.1 da spec): exige CERTGEN_API_KEY no .env
python -m certgen.cli api                 # http://127.0.0.1:8010/docs
python -m certgen.cli api --rede          # portal chega pela rede interna (sem TLS: so na LAN)
# Emissao (link + JSON espelho): curl -X POST http://127.0.0.1:8010/v1/certificados/emitir -H "X-API-Key: <chave>" -H "Content-Type: application/json" -d "{\"administradora\":\"0000001192\",\"cpf_cnpj\":\"33016330725\",\"vigencia\":\"2026-07-01\"}"
# Verificacao para o login do portal (existe + 3 vigencias mais recentes com fatura/certificado/produto): curl -X POST http://127.0.0.1:8010/v1/segurados/verificar -H "X-API-Key: <chave>" -H "Content-Type: application/json" -d "{\"administradora\":\"0000001192\",\"cpf_cnpj\":\"33016330725\"}"
# Referencia completa dos endpoints e respostas: docs/API.md; passo a passo no Postman: docs/TESTE-API-POSTMAN.md

# So o JSON
python -m certgen.cli emitir-json --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --saida C:\certificados

# HTML de um certificado, para ajustar o layout no navegador
python -m certgen.cli html --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --certificado "CF1DI/AP.602" --saida C:\certificados\teste.html
```

Os arquivos saem em `{saida}\{administradora}\{MMYYYY}\{portal}_{cpf}_{produto}_{apolice}_{certificado}_{fatura}.{pdf,json}`.
O JSON é validado contra `docs/schema/certificado-1.0.schema.json` antes da gravação; o PDF só é gerado depois do JSON válido.

**Após atualizar o código**, reinicie os processos `certgen web` e `certgen api` (não recarregam sozinhos) e, na primeira abertura da tela, use `Ctrl+F5`. A tela recusa emissão com script desatualizado (HTTP 409).

## Estado

| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Fundação | feita |
| 1 | Domínio + consultas + adaptador Firebird | feita |
| 2 | JSON (schema, serializador, `emitir-json`) | feita |
| 3 | PDF (layout único, ADR-06, `emitir`) | feita; diff de imagem automatizado pendente |
| 4 | Tela web (`web`): menu de 3 módulos (ADR-07) + cascata do Incêndio; `--rede` para a equipe (RNF-10a) | feita; Prestamista e Vida aguardam especificação |
| — | Ajustes de 03–04/09/2026: JSON único (RD-26), Faz Tudo Lar pelo operador (RF-13a), bloco Ruptura (RN-27), logotipos por seguradora (RN-28), filtro Emissão (RN-05a), textos novos das assistências, página de altura variável | feitos — ver Anexo B da spec |
| — | Ajustes de 15/09/2026: PLANO por `tipo_categoria` (`RES`/`COM`/`INC`, RN-23), Faz Tudo Lar também por ruptura (RN-18a), caixa Cobertura Incêndio Prédio (RD-32), cartão do beneficiário +2 pt (RD-33), site da assistência no Faz Tudo Lar (RD-34), vigência na lista e no relatório (RF-05a), painel de emissão acima da lista, cache-busting e versão da tela (409) | feitos — ver Anexo B da spec |
| 5 | Adaptador de API (origem de dados) | pendente |
| 6 | Emissão em massa | pendente |
| 7 | Publicação S3 (`adapters/s3`, RN-29), `registrar_link` (RD-20a) e **Upload AWS na emissão manual** (checkbox da tela e `--upload-aws`, RF-21; link no banco e no JSON em todos os modos) | S3 e link feitos em 10/09; upload manual em 15/09/2026 com teste real; XML Porto e e-mail pendentes; rotação das chaves AWS do legado (SEC-01) é ação do usuário |
| 8 | APIs para o portal (`api`, seção 11.1, [docs/API.md](docs/API.md)): emissão (`X-API-Key`, administradora + CPF + vigência [+ fatura/certificado] → link no S3 + JSON espelho, RD-29/RD-31) e verificação para o login (`/v1/segurados/verificar`: existe + 3 vigências mais recentes, RF-20/RN-35/RN-35a) | feitas em 10–14/09/2026, testadas com Postman contra Firebird e S3 reais; integração com o portal em andamento |

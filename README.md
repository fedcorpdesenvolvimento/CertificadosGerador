# Gerador de Certificados

Emite certificados de seguro incêndio/conteúdo em PDF e o JSON espelhado,
lendo o Firebird da FedCorp. Reescrita do formulário Delphi
`UfrmImprimeCertInc`.

A especificação completa está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md).
Ela é a fonte da verdade: cada módulo cita os IDs (`RF`, `RN`, `RD`, `QRY`)
que implementa.

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

Para a Fase 3 (PDF) será necessário `playwright install chromium`.

## Verificação

```powershell
pytest                              # suite de testes (integração pula sem .env)
python -m certgen.cli check-conexao  # SELECT 1 no Firebird (Fase 0)

# Tela web (Fase 4): menu com CERTIFICADO INCENDIO / PRESTAMISTA-ALUG / VIDA
python -m certgen.cli web            # abre em http://127.0.0.1:8000/

# PDF + JSON de todos os certificados de uma fatura (Fases 2 e 3)
python -m certgen.cli emitir --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --saida C:\certificados

# So o JSON
python -m certgen.cli emitir-json --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --saida C:\certificados

# HTML de um certificado, para ajustar o layout no navegador
python -m certgen.cli html --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --certificado "CF1DI/AP.602" --saida C:\certificados\teste.html
```

Os arquivos saem em `{saida}\{administradora}\{MMYYYY}\{portal}_{cpf}_{produto}_{apolice}_{certificado}_{fatura}.{pdf,json}`.
O JSON é validado contra `docs/schema/certificado-1.0.schema.json` antes da gravação; o PDF só é gerado depois do JSON válido.
O PDF exige o Chromium do Playwright: `python -m playwright install chromium` (uma vez por máquina).

## Estado

| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Fundação | feita |
| 1 | Domínio + consultas + adaptador Firebird | feita |
| 2 | JSON (schema, serializador, `emitir-json`) | feita |
| 3 | PDF (layout único, ADR-06, `emitir`) | feita; diff de imagem automatizado pendente |
| 4 | Tela web (`web`): menu de 3 módulos (ADR-07) + cascata do Incêndio | feita; Prestamista e Vida aguardam especificação |
| 4 | Tela web | pendente |
| 5 | Adaptador de API | pendente |
| 6 | Emissão em massa | pendente |
| 7 | Publicação S3 / Porto | bloqueada por SEC-01 |

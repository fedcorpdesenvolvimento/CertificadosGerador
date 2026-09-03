# Gerador de Certificados

Emite certificados de seguro incêndio/conteúdo em PDF e o JSON espelhado,
lendo o Firebird da FedCorp. Reescrita do formulário Delphi
`UfrmImprimeCertInc`.

A especificação completa está em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md).
Ela é a fonte da verdade: cada módulo cita os IDs (`RF`, `RN`, `RD`, `QRY`)
que implementa.

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

# Fase 2 — JSON de todos os certificados de uma fatura
python -m certgen.cli emitir-json --administradora 0000001192 --apolice 13008 --seq 1 --fatura 380819 --saida C:\certificados
```

Os arquivos saem em `{saida}\{administradora}\{MMYYYY}\{portal}_{cpf}_{produto}_{apolice}_{certificado}_{fatura}.json`,
validados contra `docs/schema/certificado-1.0.schema.json` antes da gravação.

## Estado

| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Fundação | feita |
| 1 | Domínio + consultas + adaptador Firebird | feita |
| 2 | JSON (schema, serializador, `emitir-json`) | feita |
| 3 | PDF (layout único, ADR-06) | próxima |
| 4 | Tela web | pendente |
| 5 | Adaptador de API | pendente |
| 6 | Emissão em massa | pendente |
| 7 | Publicação S3 / Porto | bloqueada por SEC-01 |

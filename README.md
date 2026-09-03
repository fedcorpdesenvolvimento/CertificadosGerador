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
copy .env.example .env      # preencher credenciais
```

Para a Fase 3 (PDF) será necessário `playwright install chromium`.

## Verificação

```powershell
pytest                              # suite de testes
python -m certgen.cli check-conexao  # SELECT 1 no Firebird (Fase 0)
```

## Estado

| Fase | Conteúdo | Situação |
|---|---|---|
| 0 | Fundação | feita |
| 1 | Domínio + consultas + adaptador Firebird | domínio feito, adaptador pendente |
| 2 | JSON | pendente |
| 3 | PDF | bloqueada por GAP-09, GAP-13 |
| 4 | Tela web | pendente |
| 5 | Adaptador de API | pendente |
| 6 | Emissão em massa | pendente |
| 7 | Publicação S3 / Porto | bloqueada por SEC-01 |

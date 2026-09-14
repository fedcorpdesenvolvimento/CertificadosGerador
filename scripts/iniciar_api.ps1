# Sobe a API do portal nesta maquina, aceitando conexoes da rede interna (RNF-10b).
# Uso manual:  .\scripts\iniciar_api.ps1
# Uso no Agendador de Tarefas: powershell -ExecutionPolicy Bypass -File "U:\--2021\05-Gerador Certificados\scripts\iniciar_api.ps1"
#
# O log de cada chamada (RNF-13) vai para logs\api-AAAA-MM-DD.log dentro da pasta do projeto.
# Sem TLS: so na LAN (GAP-23). Exige CERTGEN_API_KEY no .env (RN-30).

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$python = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv nao encontrada em $python - rode: python -m venv .venv; pip install -e .[dev]" }
if (-not (Test-Path (Join-Path $raiz ".env"))) { throw ".env ausente na pasta do projeto (copie .env.example)" }

$logs = Join-Path $raiz "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs ("api-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

# O uvicorn escreve os logs em stderr; no PowerShell 5.1, com ErrorActionPreference=Stop,
# isso viraria NativeCommandError e abortaria o script. Daqui em diante stderr e texto comum.
$ErrorActionPreference = "Continue"

# Reinicia sozinho se o processo cair (ex.: banco fora no momento de subir).
while ($true) {
    "$(Get-Date -Format s) iniciando certgen api --rede" | Tee-Object -FilePath $log -Append
    & $python -m certgen.cli api --rede 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
    "$(Get-Date -Format s) processo encerrou (codigo $LASTEXITCODE); nova tentativa em 15 s" | Tee-Object -FilePath $log -Append
    Start-Sleep -Seconds 15
}

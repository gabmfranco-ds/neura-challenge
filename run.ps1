# Sobe tudo em http://127.0.0.1:8787
#
# Uso:
#   $env:NEURALAKE_API_KEY = "sua-chave"
#   .\run.ps1
#
# Ou ponha a chave num arquivo .env na raiz do projeto (ele esta no .gitignore):
#   NEURALAKE_API_KEY=sua-chave

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $raiz

if (-not $env:NEURALAKE_API_KEY) {
    $envFile = Join-Path $raiz ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*NEURALAKE_API_KEY\s*=\s*(.+)\s*$') {
                $env:NEURALAKE_API_KEY = $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
}

if (-not $env:NEURALAKE_API_KEY) {
    Write-Host ""
    Write-Host "ERRO: nao achei a chave da NeuraLake." -ForegroundColor Red
    Write-Host "Faca uma das duas coisas:" -ForegroundColor Yellow
    Write-Host '  1) $env:NEURALAKE_API_KEY = "sua-chave"   e rode de novo'
    Write-Host '  2) crie um arquivo .env na raiz com a linha NEURALAKE_API_KEY=sua-chave'
    Write-Host ""
    Write-Host "A chave nunca entra no git: .env esta no .gitignore."
    exit 1
}

$venvPython = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Criando a venv em .venv ..."
    python -m venv .venv
    & $venvPython -m pip install --quiet --upgrade pip
}

Write-Host "Instalando dependencias ..."
& $venvPython -m pip install --quiet -r requirements.txt

Write-Host ""
Write-Host "Tela em http://127.0.0.1:8787" -ForegroundColor Green
Write-Host ""
& $venvPython -m uvicorn servidor:app --host 127.0.0.1 --port 8787

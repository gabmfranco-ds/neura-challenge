#!/usr/bin/env bash
# Sobe tudo em http://127.0.0.1:8787
#
# Uso:
#   export NEURALAKE_API_KEY="sua-chave"
#   ./run.sh
#
# Ou ponha a chave num arquivo .env na raiz (ele esta no .gitignore):
#   NEURALAKE_API_KEY=sua-chave

set -euo pipefail
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$raiz"

if [ -z "${NEURALAKE_API_KEY:-}" ] && [ -f .env ]; then
  valor="$(grep -E '^[[:space:]]*NEURALAKE_API_KEY[[:space:]]*=' .env | head -1 | cut -d= -f2- | tr -d '\r\n"'"'"' ' || true)"
  if [ -n "$valor" ]; then export NEURALAKE_API_KEY="$valor"; fi
fi

if [ -z "${NEURALAKE_API_KEY:-}" ]; then
  echo ""
  echo "ERRO: nao achei a chave da NeuraLake."
  echo "Faca uma das duas coisas:"
  echo '  1) export NEURALAKE_API_KEY="sua-chave"   e rode de novo'
  echo '  2) crie um arquivo .env na raiz com a linha NEURALAKE_API_KEY=sua-chave'
  echo ""
  echo "A chave nunca entra no git: .env esta no .gitignore."
  exit 1
fi

if [ -d .venv/Scripts ]; then
  py=".venv/Scripts/python.exe"
else
  py=".venv/bin/python"
fi

if [ ! -x "$py" ]; then
  echo "Criando a venv em .venv ..."
  python -m venv .venv
  "$py" -m pip install --quiet --upgrade pip
fi

echo "Instalando dependencias ..."
"$py" -m pip install --quiet -r requirements.txt

echo ""
echo "Tela em http://127.0.0.1:8787"
echo ""
exec "$py" -m uvicorn servidor:app --host 127.0.0.1 --port 8787

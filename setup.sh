#!/usr/bin/env bash
# Cripto Wallet — установка под Linux/macOS.
# Создаёт venv, ставит зависимости, готовит .env.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

echo "==> Python: $("$PY" --version)"

if [ ! -d ".venv" ]; then
  echo "==> Создаю виртуальное окружение .venv"
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Обновляю pip и ставлю зависимости"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  echo "==> Создаю .env из .env.example (впишите свои ключи)"
  cp .env.example .env
fi

echo
echo "✅ Готово. Дальше:"
echo "   1) при необходимости впишите API-ключи в .env"
echo "   2) для XMR-баланса/отправки: ./scripts/get_monero.sh (скачает monero-wallet-rpc)"
echo "   3) запуск: ./run.sh"

#!/usr/bin/env bash
# Cripto Wallet — запуск под Linux/macOS.
# Если venv ещё нет — поднимет его через setup.sh, затем запустит кошелёк.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "==> .venv не найден — запускаю первичную установку (setup.sh)"
  ./setup.sh
fi

# shellcheck disable=SC1091
source .venv/bin/activate
exec python final_skript.py

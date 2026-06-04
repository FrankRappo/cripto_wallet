#!/usr/bin/env bash
# Скачивает официальный Monero CLI (getmonero.org) и кладёт monero-wallet-rpc
# в vendor/monero/. Нужен только если хотите баланс/историю/отправку XMR.
#   Linux x86_64:  ./scripts/get_monero.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DEST="vendor/monero"
mkdir -p "$DEST"

UNAME_M="$(uname -m)"
case "$UNAME_M" in
  x86_64|amd64) URL="https://downloads.getmonero.org/cli/linux64" ;;
  aarch64|arm64) URL="https://downloads.getmonero.org/cli/linuxarm8" ;;
  *) echo "Неизвестная архитектура: $UNAME_M — скачайте Monero CLI вручную с getmonero.org"; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Скачиваю Monero CLI: $URL"
if command -v curl >/dev/null 2>&1; then
  curl -fL "$URL" -o "$TMP/monero.tar.bz2"
else
  wget -O "$TMP/monero.tar.bz2" "$URL"
fi

echo "==> Распаковываю"
tar -xjf "$TMP/monero.tar.bz2" -C "$TMP"

RPC="$(find "$TMP" -type f -name monero-wallet-rpc | head -n1)"
if [ -z "$RPC" ]; then
  echo "❌ monero-wallet-rpc не найден в архиве"; exit 1
fi
cp "$RPC" "$DEST/monero-wallet-rpc"
chmod +x "$DEST/monero-wallet-rpc"

echo "✅ Готово: $DEST/monero-wallet-rpc"
echo "   Пропишите путь к нему в MONERO_WALLET_RPC_BIN в .env (см. .env.example)."

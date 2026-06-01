"""Авто-запуск monero-wallet-rpc (Вариант A — кошелёк локально, нода удалённая).

`final_skript.py` дёргает `ensure_monero_rpc()` на старте:
  • демон уже слушает порт → ничего не делаем;
  • иначе поднимаем его с открытым кошельком и ждём готовности;
  • если не настроено (нет бинаря/файла кошелька) → тихо выходим, XMR остаётся
    в режиме «только генерация адресов» (баланс/история/отправка недоступны).

Конфиг берётся из переменных окружения (их кладёт загрузчик .env в final_skript):
  MONERO_WALLET_RPC, MONERO_WALLET_RPC_BIN, MONERO_WALLET_DIR,
  MONERO_WALLET_NAME, MONERO_WALLET_PASSWORD, MONERO_DAEMON_ADDR, MONERO_RPC_PORT
"""

import json
import os
import subprocess
import time
import urllib.request


def _rpc(url: str, method: str, params: dict | None = None, timeout: int = 5) -> dict:
    data = json.dumps(
        {"jsonrpc": "2.0", "id": "0", "method": method, "params": params or {}}
    ).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def is_up(url: str | None = None) -> bool:
    url = url or os.environ.get("MONERO_WALLET_RPC", "")
    if not url:
        return False
    try:
        _rpc(url, "get_version", timeout=3)
        return True
    except Exception:
        return False


def ensure_monero_rpc(verbose: bool = True, wait_seconds: int = 40) -> bool:
    """Гарантирует, что monero-wallet-rpc запущен. Возвращает True, если демон готов."""
    url = os.environ.get("MONERO_WALLET_RPC", "")
    if not url:
        return False
    if is_up(url):
        return True

    bin_ = os.environ.get("MONERO_WALLET_RPC_BIN", "")
    wdir = os.environ.get("MONERO_WALLET_DIR", "")
    name = os.environ.get("MONERO_WALLET_NAME", "")
    pw = os.environ.get("MONERO_WALLET_PASSWORD", "")
    daemon = os.environ.get("MONERO_DAEMON_ADDR", "")
    port = os.environ.get("MONERO_RPC_PORT", "18083")
    wallet_file = os.path.join(wdir, name) if (wdir and name) else ""

    if not (bin_ and os.path.exists(bin_) and wallet_file and os.path.exists(wallet_file)):
        if verbose:
            print("ℹ️  XMR: monero-wallet-rpc не настроен — доступна только генерация адресов.")
        return False

    # Пароль во временный файл (чтобы не светить в `ps`), 0600.
    pw_file = os.path.join(wdir, ".rpc-pw")
    try:
        with open(pw_file, "w", encoding="utf-8") as f:
            f.write(pw)
        os.chmod(pw_file, 0o600)
    except OSError as e:
        if verbose:
            print(f"⚠️  XMR: не удалось подготовить запуск: {e}")
        return False

    cmd = [
        bin_,
        "--wallet-file", wallet_file,
        "--password-file", pw_file,
        "--rpc-bind-ip", "127.0.0.1",
        "--rpc-bind-port", str(port),
        "--disable-rpc-login",
        "--daemon-address", daemon,
        "--untrusted-daemon",
        "--log-file", os.path.join(wdir, "wallet-rpc.log"),
        "--max-concurrency", "1",
    ]
    if verbose:
        print(f"⏳ XMR: запускаю monero-wallet-rpc (нода {daemon})…")
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # переживает выход CLI — работает как сервис
        )
    except OSError as e:
        if verbose:
            print(f"⚠️  XMR: не удалось запустить wallet-rpc: {e}")
        return False

    for _ in range(max(1, wait_seconds)):
        if is_up(url):
            if verbose:
                print("✅ XMR: monero-wallet-rpc готов.")
            return True
        time.sleep(1)
    if verbose:
        print("⚠️  XMR: wallet-rpc не ответил вовремя — баланс/история могут быть недоступны.")
    return False


if __name__ == "__main__":
    # Ручной запуск/проверка: python3 monero_daemon.py
    ok = ensure_monero_rpc()
    print("monero-wallet-rpc up:", ok)

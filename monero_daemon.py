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


def _resolve_bin(bin_: str) -> str:
    """Возвращает путь к бинарю с учётом ОС.

    На Windows бинарь называется `monero-wallet-rpc.exe`; в .env можно указать
    путь как с расширением, так и без — добавим `.exe`, если так файл находится.
    """
    if not bin_:
        return bin_
    if os.path.exists(bin_):
        return bin_
    if os.name == "nt" and not bin_.lower().endswith(".exe"):
        cand = bin_ + ".exe"
        if os.path.exists(cand):
            return cand
    return bin_


def _detached_popen_kwargs() -> dict:
    """Флаги запуска фонового процесса-«сервиса», переживающего выход CLI.

    POSIX: start_new_session=True (новая сессия, отвязка от управляющего терминала).
    Windows: аргумента start_new_session нет — нужны creationflags
    DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP.
    """
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


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

    bin_ = _resolve_bin(os.environ.get("MONERO_WALLET_RPC_BIN", ""))
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

    cmd = [
        bin_,
        "--wallet-file", wallet_file,
        "--rpc-bind-ip", "127.0.0.1",
        "--rpc-bind-port", str(port),
        "--disable-rpc-login",
        "--daemon-address", daemon,
        "--untrusted-daemon",
        "--log-file", os.path.join(wdir, "wallet-rpc.log"),
        "--max-concurrency", "1",
    ]

    if os.name == "nt":
        # На Windows чтение --password-file ломается на не-ASCII путях (например
        # кириллица в пути): "the password file specified could not be read".
        # Передаём пароль аргументом — argv приходит в Unicode. Демон слушает только
        # 127.0.0.1 (single-user), поэтому видимость пароля в локальном tasklist приемлема.
        cmd += ["--password", pw]
    else:
        # POSIX: пароль через файл 0600, чтобы не светить в `ps`.
        pw_file = os.path.join(wdir, ".rpc-pw")
        try:
            with open(pw_file, "w", encoding="utf-8") as f:
                f.write(pw)
            os.chmod(pw_file, 0o600)
        except OSError as e:
            if verbose:
                print(f"⚠️  XMR: не удалось подготовить запуск: {e}")
            return False
        cmd += ["--password-file", pw_file]
    if verbose:
        print(f"⏳ XMR: запускаю monero-wallet-rpc (нода {daemon})…")
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # переживает выход CLI — работает как сервис (POSIX/Windows, см. helper)
            **_detached_popen_kwargs(),
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

"""utils.py — IP-проверка, выбор пути JSON, валидация адресов.

Запуск:  python3 /work/cripto/utils.py
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
from datetime import datetime, timezone
from typing import Optional

import requests

try:
    import base58
except ImportError:
    base58 = None

try:
    from web3 import Web3
    _HAS_WEB3 = True
except ImportError:
    _HAS_WEB3 = False

try:
    from solders.pubkey import Pubkey as _SoldersPubkey
    _HAS_SOLDERS = True
except ImportError:
    _HAS_SOLDERS = False


# ──────────────────────────────────────────────────────────────────────────────
# IP
# ──────────────────────────────────────────────────────────────────────────────
_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)


def get_external_ip() -> Optional[str]:
    for url in _IP_SERVICES:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                ip = r.text.strip()
                if _looks_like_ipv4(ip):
                    return ip
        except requests.RequestException:
            continue
    return None


def _looks_like_ipv4(s: str) -> bool:
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit():
            return False
        n = int(p)
        if n < 0 or n > 255:
            return False
    return True


def get_local_ips() -> list[str]:
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except socket.gaierror:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        if not ip.startswith("127."):
            ips.add(ip)
        s.close()
    except OSError:
        pass
    return sorted(ips)


def print_startup_banner() -> None:
    ext = get_external_ip() or "(unavailable)"
    local = get_local_ips()
    print("=== Cripto Wallet ===")
    print(f"External IP: {ext}")
    print(f"Local IPs: {local}")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")


# ──────────────────────────────────────────────────────────────────────────────
# JSON path
# ──────────────────────────────────────────────────────────────────────────────
def choose_json_path(default: str = "wallet.json") -> str:
    raw = input(f"Путь для сохранения JSON [{default}]: ").strip()
    path = raw or default
    abs_path = os.path.abspath(path)
    dir_ = os.path.dirname(abs_path) or "."
    if not os.path.isdir(dir_):
        ans = input(f"Каталог {dir_} не существует. Создать? [y/N]: ").strip().lower()
        if ans == "y":
            os.makedirs(dir_, exist_ok=True)
        else:
            raise RuntimeError(f"Каталог не существует: {dir_}")
    if not os.access(dir_, os.W_OK):
        raise RuntimeError(f"Каталог не доступен для записи: {dir_}")
    return abs_path


# ──────────────────────────────────────────────────────────────────────────────
# Address validation
# ──────────────────────────────────────────────────────────────────────────────
_BECH32_CHARS = set("qpzry9x8gf2tvdw0s3jn54khce6mua7l")


def _b58_check_decode(s: str) -> Optional[bytes]:
    if base58 is None:
        try:
            decoded = _b58_decode_fallback(s)
        except ValueError:
            return None
    else:
        try:
            decoded = base58.b58decode(s)
        except Exception:
            return None
    if len(decoded) < 5:
        return None
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        return None
    return payload


_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58_decode_fallback(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _B58_ALPHABET:
            raise ValueError(f"non-base58 char: {ch!r}")
        n = n * 58 + _B58_ALPHABET.index(ch)
    full = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + full


def _b58_decode_any(s: str) -> Optional[bytes]:
    if base58 is not None:
        try:
            return base58.b58decode(s)
        except Exception:
            return None
    try:
        return _b58_decode_fallback(s)
    except ValueError:
        return None


def _validate_btc(address: str) -> tuple[bool, str]:
    if address.lower().startswith("bc1"):
        return _validate_bech32_like(address, "bc")
    if address[:1] in ("1", "3"):
        payload = _b58_check_decode(address)
        if payload is None:
            return False, "BTC: base58check invalid"
        if len(payload) != 21:
            return False, "BTC: payload length != 21"
        if payload[0] not in (0x00, 0x05):
            return False, "BTC: version byte invalid"
        return True, "ok"
    return False, "BTC: unknown prefix"


def _validate_ltc(address: str) -> tuple[bool, str]:
    if address.lower().startswith("ltc1"):
        return _validate_bech32_like(address, "ltc")
    if address[:1] in ("L", "M", "3"):
        payload = _b58_check_decode(address)
        if payload is None:
            return False, "LTC: base58check invalid"
        if len(payload) != 21:
            return False, "LTC: payload length != 21"
        if payload[0] not in (0x30, 0x32, 0x05):
            return False, "LTC: version byte invalid"
        return True, "ok"
    return False, "LTC: unknown prefix"


def _validate_bech32_like(address: str, hrp: str) -> tuple[bool, str]:
    a = address.lower()
    if not a.startswith(hrp + "1"):
        return False, f"bech32: hrp mismatch ({hrp})"
    data = a[len(hrp) + 1:]
    if len(data) < 6 or len(data) > 90:
        return False, "bech32: invalid length"
    for ch in data:
        if ch not in _BECH32_CHARS:
            return False, f"bech32: invalid char {ch!r}"
    return True, "ok"


_ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_eth(address: str) -> tuple[bool, str]:
    if _HAS_WEB3:
        try:
            if Web3.is_address(address):
                return True, "ok"
            return False, "ETH: web3.is_address rejected"
        except Exception as e:
            return False, f"ETH: {e}"
    if not _ETH_RE.match(address):
        return False, "ETH: must be 0x + 40 hex"
    return True, "ok"


def _validate_sol(address: str) -> tuple[bool, str]:
    if _HAS_SOLDERS:
        try:
            _SoldersPubkey.from_string(address)
            return True, "ok"
        except Exception as e:
            return False, f"SOL: {e}"
    if not (32 <= len(address) <= 44):
        return False, "SOL: length out of range"
    decoded = _b58_decode_any(address)
    if decoded is None:
        return False, "SOL: base58 decode failed"
    if len(decoded) != 32:
        return False, f"SOL: decoded length {len(decoded)} != 32"
    return True, "ok"


_TON_FRIENDLY_RE = re.compile(r"^[A-Za-z0-9_-]{48}$")
_TON_RAW_RE = re.compile(r"^-?\d+:[a-fA-F0-9]{64}$")


def _validate_ton(address: str) -> tuple[bool, str]:
    if _TON_RAW_RE.match(address):
        return True, "ok"
    if _TON_FRIENDLY_RE.match(address) and address[:2] in ("EQ", "UQ", "kQ", "0Q", "Ef", "Uf"):
        import base64
        try:
            raw = base64.urlsafe_b64decode(address + "=" * (-len(address) % 4))
        except Exception:
            return False, "TON: base64url decode failed"
        if len(raw) != 36:
            return False, f"TON: decoded length {len(raw)} != 36"
        return True, "ok"
    return False, "TON: unknown format"


def _validate_trx(address: str) -> tuple[bool, str]:
    if not address.startswith("T") or len(address) != 34:
        return False, "TRX: expected T + 33 chars"
    payload = _b58_check_decode(address)
    if payload is None:
        return False, "TRX: base58check invalid"
    if len(payload) != 21 or payload[0] != 0x41:
        return False, "TRX: version byte != 0x41"
    return True, "ok"


def _validate_xmr(address: str) -> tuple[bool, str]:
    if address[:1] not in ("4", "8"):
        return False, "XMR: must start with 4 or 8"
    if len(address) not in (95, 106):
        return False, f"XMR: length {len(address)} not in (95, 106)"
    for ch in address:
        if ch not in _B58_ALPHABET:
            return False, f"XMR: invalid base58 char {ch!r}"
    return True, "ok"


def validate_address(symbol: str, address: str) -> tuple[bool, str]:
    if not isinstance(address, str) or not address:
        return False, "empty address"
    sym = symbol.upper().strip()
    if sym == "USDT":
        sym = "TRX"
    if sym == "BNB":
        sym = "BSC"
    handlers = {
        "BTC": _validate_btc,
        "LTC": _validate_ltc,
        "ETH": _validate_eth,
        "BSC": _validate_eth,
        "SOL": _validate_sol,
        "TON": _validate_ton,
        "TRX": _validate_trx,
        "XMR": _validate_xmr,
    }
    fn = handlers.get(sym)
    if fn is None:
        return False, f"unsupported symbol: {symbol}"
    return fn(address)


if __name__ == "__main__":
    print_startup_banner()
    test_addrs = [
        ("BTC", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),
        ("LTC", "LhK2kQwiaAvhjWY799cZvMyYwnQAcxkarr"),
        ("ETH", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"),
        ("TRX", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
        ("XMR", "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"),
    ]
    for sym, a in test_addrs:
        print(sym, validate_address(sym, a))

"""
networks/ — унифицированные Wallet-классы по сетям.

Каждый модуль предоставляет:
    Wallet(private_key=None)
        .SYMBOL, .NAME
        .address, .private_key_hex
        .get_balance() -> {"native": float, "tokens": {...}}
        .validate_address(addr) -> bool
        .send(to, amount) -> {"success": bool, "txid": str|None, "error": str|None}
        .get_history(limit=20) -> list[dict]
"""

from . import btc, ltc, eth, bsc, sol, ton, monero

__all__ = ["btc", "ltc", "eth", "bsc", "sol", "ton", "monero"]

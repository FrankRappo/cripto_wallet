"""Monero Wallet — generates keys via `monero` lib; send/balance/history
require a running `monero-wallet-rpc` (not bundled here).

v1 reality: only address+key generation works fully. balance/history/send
return a clear "requires local monero-wallet-rpc" error unless WALLET_RPC_URL
is configured.

TODO: integrate full monero-wallet-rpc (spawn locally or expect external).
"""

import os
import sys
from datetime import datetime, timezone

# Файл называется monero.py — он бы шадовил установленный пакет `monero`.
# Удаляем директорию модуля из sys.path до импорта пакета.
_this_dir = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != _this_dir]
# И вычищаем себя из кэша модулей, чтобы импорт пакета прошёл к установленному.
sys.modules.pop("monero", None)

import requests
from monero.seed import Seed  # type: ignore  # pkg, not our file

NODE_RPC = os.environ.get(
    "MONERO_NODE_RPC", "http://xmr-node.cakewallet.com:18089/json_rpc"
)
WALLET_RPC_URL = os.environ.get("MONERO_WALLET_RPC", "")  # e.g. http://127.0.0.1:18083/json_rpc
ATOMIC = 1_000_000_000_000  # 1 XMR = 1e12 piconero

UNSUPPORTED = {
    "success": False,
    "txid": None,
    "error": "Monero send requires local monero-wallet-rpc — not implemented in v1",
}


def _node_call(method: str, params: dict | None = None) -> dict:
    r = requests.post(
        NODE_RPC,
        json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params or {}},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _wallet_call(method: str, params: dict | None = None) -> dict:
    if not WALLET_RPC_URL:
        raise RuntimeError("MONERO_WALLET_RPC not configured")
    r = requests.post(
        WALLET_RPC_URL,
        json={"jsonrpc": "2.0", "id": "0", "method": method, "params": params or {}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


class Wallet:
    SYMBOL = "XMR"
    NAME = "Monero"

    def __init__(self, private_key: str | None = None):
        # private_key here = monero "mnemonic" phrase (preferred) or
        # 32-byte hex seed (treated as spend-key seed)
        if private_key:
            try:
                if " " in private_key:
                    self._seed = Seed(private_key)
                else:
                    # 32-byte hex seed -> use as spend key
                    self._seed = Seed(private_key)
            except Exception as e:
                raise ValueError(f"Invalid Monero key: {e}")
        else:
            self._seed = Seed()

        self._address = str(self._seed.public_address())
        self._spend = self._seed.secret_spend_key()
        self._view = self._seed.secret_view_key()
        self._phrase = self._seed.phrase

    @property
    def address(self) -> str:
        return self._address

    @property
    def private_key_hex(self) -> str:
        # Spend key is the canonical "private key" for Monero
        return self._spend

    @property
    def view_key(self) -> str:
        return self._view

    @property
    def mnemonic(self) -> str:
        return self._phrase

    def validate_address(self, addr: str) -> bool:
        if not isinstance(addr, str):
            return False
        # Standard mainnet: 95 chars, starts with 4
        # Integrated: 106 chars; subaddress: 95 chars, starts with 8
        return len(addr) in (95, 106) and addr[0] in ("4", "8")

    def get_balance(self) -> dict:
        if not WALLET_RPC_URL:
            return {
                "native": 0.0,
                "tokens": {},
                "error": "balance requires monero-wallet-rpc (set MONERO_WALLET_RPC env)",
            }
        try:
            res = _wallet_call("get_balance")
            result = res.get("result", {})
            unlocked = result.get("unlocked_balance", 0)
            return {"native": unlocked / ATOMIC, "tokens": {}}
        except Exception as e:
            return {"native": 0.0, "tokens": {}, "error": str(e)}

    def send(self, to: str, amount: float) -> dict:
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid Monero address"}
        if not WALLET_RPC_URL:
            return UNSUPPORTED
        try:
            res = _wallet_call("transfer", {
                "destinations": [{"amount": int(amount * ATOMIC), "address": to}],
                "ring_size": 16,
                "get_tx_key": True,
            })
            if "error" in res:
                return {"success": False, "txid": None, "error": str(res["error"])}
            return {"success": True, "txid": res.get("result", {}).get("tx_hash"), "error": None}
        except Exception as e:
            return {"success": False, "txid": None, "error": str(e)}

    def get_history(self, limit: int = 20) -> list[dict]:
        if not WALLET_RPC_URL:
            return []
        try:
            res = _wallet_call("get_transfers", {"in": True, "out": True})
            result = res.get("result", {})
            out = []
            for direction_key, direction in (("in", "in"), ("out", "out")):
                for t in result.get(direction_key, [])[:limit]:
                    out.append({
                        "txid": t.get("txid"),
                        "from": t.get("address") if direction == "in" else self.address,
                        "to": t.get("address") if direction == "out" else self.address,
                        "amount": int(t.get("amount", 0)) / ATOMIC,
                        "time": _iso(int(t.get("timestamp", 0))),
                        "direction": direction,
                    })
            out.sort(key=lambda x: x["time"], reverse=True)
            return out[:limit]
        except Exception:
            return []

    def node_info(self) -> dict:
        """Quick check of public node — not key-dependent."""
        try:
            res = _node_call("get_info")
            return res.get("result", {})
        except Exception as e:
            return {"error": str(e)}


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"spend key: {w.private_key_hex[:16]}...")
    print(f"view key:  {w.view_key[:16]}...")
    print(f"mnemonic:  {w.mnemonic[:40]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"WALLET_RPC configured: {bool(WALLET_RPC_URL)}")

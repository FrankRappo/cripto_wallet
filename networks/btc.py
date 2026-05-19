"""BTC Wallet — mempool.space API + `bit` library."""

import os
from datetime import datetime, timezone

import requests
from bit import Key

API_BASE = os.environ.get("MEMPOOL_API_BASE", "https://mempool.space/api")
SAT = 100_000_000


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class Wallet:
    SYMBOL = "BTC"
    NAME = "Bitcoin"

    def __init__(self, private_key: str | None = None):
        if private_key:
            # bit accepts WIF or hex; normalise to hex path
            try:
                self._key = Key.from_hex(private_key)
            except Exception:
                self._key = Key(private_key)
        else:
            self._key = Key()

    @property
    def address(self) -> str:
        return self._key.address

    @property
    def private_key_hex(self) -> str:
        return self._key.to_hex()

    def validate_address(self, addr: str) -> bool:
        if not isinstance(addr, str) or len(addr) < 26 or len(addr) > 90:
            return False
        # Legacy 1..., P2SH 3..., bech32 bc1...
        return addr.startswith(("1", "3", "bc1"))

    def get_balance(self) -> dict:
        try:
            r = requests.get(f"{API_BASE}/address/{self.address}", timeout=30)
            r.raise_for_status()
            data = r.json()
            funded = int(data.get("chain_stats", {}).get("funded_txo_sum", 0))
            spent = int(data.get("chain_stats", {}).get("spent_txo_sum", 0))
            sat_balance = funded - spent
            return {"native": sat_balance / SAT, "tokens": {}}
        except Exception as e:
            return {"native": 0.0, "tokens": {}, "error": str(e)}

    def send(self, to: str, amount: float) -> dict:
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid BTC address"}
        try:
            # bit handles UTXO selection, fee, signing automatically
            txid = self._key.send([(to, amount, "btc")])
            return {"success": True, "txid": txid, "error": None}
        except Exception as e:
            return {"success": False, "txid": None, "error": str(e)}

    def get_history(self, limit: int = 20) -> list[dict]:
        try:
            r = requests.get(f"{API_BASE}/address/{self.address}/txs", timeout=30)
            r.raise_for_status()
            txs = r.json()[:limit]
        except Exception:
            return []

        out = []
        my = self.address
        for tx in txs:
            # Сумма поступившая и потраченная на этот адрес
            received = sum(
                v.get("value", 0)
                for v in tx.get("vout", [])
                if v.get("scriptpubkey_address") == my
            )
            spent = sum(
                vin.get("prevout", {}).get("value", 0)
                for vin in tx.get("vin", [])
                if vin.get("prevout", {}).get("scriptpubkey_address") == my
            )
            net = received - spent
            direction = "in" if net >= 0 else "out"
            # "from" — отправитель (для in) либо self
            counter_in = next(
                (vin.get("prevout", {}).get("scriptpubkey_address")
                 for vin in tx.get("vin", [])
                 if vin.get("prevout", {}).get("scriptpubkey_address") != my),
                None,
            )
            counter_out = next(
                (v.get("scriptpubkey_address")
                 for v in tx.get("vout", [])
                 if v.get("scriptpubkey_address") != my),
                None,
            )
            out.append({
                "txid": tx.get("txid"),
                "from": counter_in if direction == "in" else my,
                "to": counter_out if direction == "out" else my,
                "amount": abs(net) / SAT,
                "time": _iso(tx.get("status", {}).get("block_time", 0)),
                "direction": direction,
            })
        return out


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex: {w.private_key_hex[:10]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"balance: {w.get_balance()}")

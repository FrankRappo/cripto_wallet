"""TON Wallet — toncenter.com/api/v2 + tonsdk (WalletV4R2)."""

import os
import secrets
from datetime import datetime, timezone

import requests
from nacl.signing import SigningKey
from tonsdk.contract.wallet import WalletV4ContractR2
from tonsdk.utils import bytes_to_b64str

TONCENTER_KEY = os.environ.get("TONCENTER_API_KEY", "")
API_BASE = os.environ.get("TONCENTER_API_BASE", "https://toncenter.com/api/v2")

NANO = 1_000_000_000


def _ton_call(method: str, params: dict | None = None) -> dict:
    headers = {}
    if TONCENTER_KEY:
        headers["X-API-Key"] = TONCENTER_KEY
    r = requests.post(
        f"{API_BASE}/jsonRPC",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


class Wallet:
    SYMBOL = "TON"
    NAME = "Toncoin"

    def __init__(self, private_key: str | None = None):
        if private_key:
            seed = bytes.fromhex(private_key)
            if len(seed) != 32:
                raise ValueError("TON private key must be 32 bytes hex (seed)")
        else:
            seed = secrets.token_bytes(32)
        sk = SigningKey(seed)
        self._seed = seed
        self._pub = bytes(sk.verify_key)
        # tonsdk expects 64-byte private key (seed + pub)
        self._priv64 = sk.encode() + self._pub
        self._wallet = WalletV4ContractR2(
            public_key=self._pub, private_key=self._priv64, wc=0
        )
        self._address = self._wallet.address.to_string(True, True, True)

    @property
    def address(self) -> str:
        return self._address

    @property
    def private_key_hex(self) -> str:
        # 32-byte seed (recoverable: full priv64 = seed + pub)
        return self._seed.hex()

    def validate_address(self, addr: str) -> bool:
        if not isinstance(addr, str):
            return False
        # User-friendly base64url is 48 chars; raw is "<wc>:<hex>"
        if ":" in addr:
            parts = addr.split(":")
            return len(parts) == 2 and len(parts[1]) == 64
        return 40 < len(addr) < 70 and addr[0] in ("E", "U", "k")

    def get_balance(self) -> dict:
        try:
            res = _ton_call("getAddressBalance", {"address": self.address})
            nano = int(res.get("result", 0))
            return {"native": nano / NANO, "tokens": {}}
        except Exception as e:
            return {"native": 0.0, "tokens": {}, "error": str(e)}

    def _get_seqno(self) -> int:
        try:
            res = _ton_call("runGetMethod", {
                "address": self.address,
                "method": "seqno",
                "stack": [],
            })
            result = res.get("result", {})
            stack = result.get("stack") or []
            if stack:
                v = stack[0]
                if isinstance(v, list) and len(v) >= 2:
                    return int(v[1], 16) if isinstance(v[1], str) and v[1].startswith("0x") else int(v[1])
            return 0
        except Exception:
            return 0

    def send(self, to: str, amount: float) -> dict:
        if not TONCENTER_KEY:
            return {"success": False, "txid": None, "error": "TONCENTER_API_KEY missing"}
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid TON address"}
        try:
            seqno = self._get_seqno()
            query = self._wallet.create_transfer_message(
                to_addr=to,
                amount=int(amount * NANO),
                seqno=seqno,
                payload="",
            )
            boc = bytes_to_b64str(query["message"].to_boc(False))
            headers = {"X-API-Key": TONCENTER_KEY} if TONCENTER_KEY else {}
            r = requests.post(
                f"{API_BASE}/sendBoc",
                json={"boc": boc},
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                return {"success": False, "txid": None, "error": str(data)}
            # Toncenter doesn't return txid synchronously; use BOC hash placeholder
            return {"success": True, "txid": data.get("result", {}).get("@type", "sent"), "error": None}
        except Exception as e:
            return {"success": False, "txid": None, "error": str(e)}

    def get_history(self, limit: int = 20) -> list[dict]:
        try:
            res = _ton_call("getTransactions", {"address": self.address, "limit": limit})
            txs = res.get("result", []) or []
        except Exception:
            return []
        out = []
        for tx in txs:
            in_msg = tx.get("in_msg") or {}
            out_msgs = tx.get("out_msgs") or []
            ts = tx.get("utime", 0)
            txid = (tx.get("transaction_id") or {}).get("hash", "")
            if in_msg.get("value") and int(in_msg["value"]) > 0 and in_msg.get("source"):
                out.append({
                    "txid": txid,
                    "from": in_msg.get("source"),
                    "to": self.address,
                    "amount": int(in_msg["value"]) / NANO,
                    "time": _iso(ts),
                    "direction": "in",
                })
            for m in out_msgs:
                if int(m.get("value", 0)) > 0:
                    out.append({
                        "txid": txid,
                        "from": self.address,
                        "to": m.get("destination"),
                        "amount": int(m["value"]) / NANO,
                        "time": _iso(ts),
                        "direction": "out",
                    })
        return out[:limit]


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex (seed): {w.private_key_hex[:16]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"TONCENTER_API_KEY set: {bool(TONCENTER_KEY)}")

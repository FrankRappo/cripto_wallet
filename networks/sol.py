"""SOL Wallet — Helius RPC + solders."""

import base64
import os
from datetime import datetime, timezone

import requests
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

HELIUS_KEY = os.environ.get("HELIUS_API_KEY", "")
RPC_URL = os.environ.get("SOL_RPC", "") or (
    f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"
    if HELIUS_KEY
    else "https://solana-rpc.publicnode.com"  # keyless public fallback
)

LAMPORTS_PER_SOL = 1_000_000_000


def _rpc(method: str, params: list) -> dict:
    r = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


class Wallet:
    SYMBOL = "SOL"
    NAME = "Solana"

    def __init__(self, private_key: str | None = None):
        if private_key:
            pk_bytes = bytes.fromhex(private_key)
            if len(pk_bytes) == 32:
                self._kp = Keypair.from_seed(pk_bytes)
            elif len(pk_bytes) == 64:
                self._kp = Keypair.from_bytes(pk_bytes)
            else:
                raise ValueError("SOL private key must be 32 or 64 bytes hex")
        else:
            self._kp = Keypair()

    @property
    def address(self) -> str:
        return str(self._kp.pubkey())

    @property
    def private_key_hex(self) -> str:
        # Full 64-byte secret (seed + pubkey)
        return bytes(self._kp).hex()

    def validate_address(self, addr: str) -> bool:
        try:
            Pubkey.from_string(addr)
            return True
        except Exception:
            return False

    def get_balance(self) -> dict:
        try:
            res = _rpc("getBalance", [self.address])
            lamports = res.get("result", {}).get("value", 0)
            return {"native": lamports / LAMPORTS_PER_SOL, "tokens": {}}
        except Exception as e:
            return {"native": 0.0, "tokens": {}, "error": str(e)}

    def send(self, to: str, amount: float) -> dict:
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid SOL address"}
        try:
            to_pk = Pubkey.from_string(to)
            from_pk = self._kp.pubkey()
            lamports = int(amount * LAMPORTS_PER_SOL)
            ix = transfer(TransferParams(from_pubkey=from_pk, to_pubkey=to_pk, lamports=lamports))

            blockhash_res = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])
            blockhash_str = blockhash_res["result"]["value"]["blockhash"]
            blockhash = Hash.from_string(blockhash_str)

            msg = Message.new_with_blockhash([ix], from_pk, blockhash)
            tx = Transaction.new_unsigned(msg)
            tx.sign([self._kp], blockhash)
            raw_b64 = base64.b64encode(bytes(tx)).decode()

            res = _rpc("sendTransaction", [raw_b64, {"encoding": "base64"}])
            if "error" in res:
                return {"success": False, "txid": None, "error": str(res["error"])}
            return {"success": True, "txid": res["result"], "error": None}
        except Exception as e:
            return {"success": False, "txid": None, "error": str(e)}

    def get_history(self, limit: int = 20) -> list[dict]:
        try:
            sigs_res = _rpc("getSignaturesForAddress", [self.address, {"limit": limit}])
            sigs = sigs_res.get("result", [])
            out = []
            for s in sigs:
                txid = s.get("signature")
                ts = s.get("blockTime", 0)
                try:
                    tx_res = _rpc(
                        "getTransaction",
                        [txid, {"encoding": "json", "maxSupportedTransactionVersion": 0}],
                    )
                    tx_data = tx_res.get("result") or {}
                    meta = tx_data.get("meta") or {}
                    pre = meta.get("preBalances") or []
                    post = meta.get("postBalances") or []
                    acct_keys = (
                        tx_data.get("transaction", {})
                        .get("message", {})
                        .get("accountKeys", [])
                    )
                    my_idx = next(
                        (i for i, k in enumerate(acct_keys) if k == self.address), -1
                    )
                    if my_idx >= 0 and my_idx < len(pre) and my_idx < len(post):
                        delta = (post[my_idx] - pre[my_idx]) / LAMPORTS_PER_SOL
                        direction = "in" if delta >= 0 else "out"
                        amount = abs(delta)
                    else:
                        direction = "in"
                        amount = 0.0
                    other = next((k for k in acct_keys if k != self.address), None)
                except Exception:
                    direction = "in"
                    amount = 0.0
                    other = None

                out.append({
                    "txid": txid,
                    "from": other if direction == "in" else self.address,
                    "to": other if direction == "out" else self.address,
                    "amount": amount,
                    "time": _iso(ts),
                    "direction": direction,
                })
            return out
        except Exception:
            return []


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex: {w.private_key_hex[:16]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"HELIUS_API_KEY set: {bool(HELIUS_KEY)}")

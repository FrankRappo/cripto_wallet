"""BSC Wallet — public RPC (bsc-dataseed) + BscScan for history."""

import os
from datetime import datetime, timezone

import requests
from eth_account import Account
from web3 import Web3

RPC_URL = os.environ.get("BSC_RPC", "https://bsc-dataseed.binance.org")
BSCSCAN_KEY = os.environ.get("BSCSCAN_API_KEY", "")
BSCSCAN_API = "https://api.bscscan.com/api"

# USDT BEP20
USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
USDT_DECIMALS = 18
ERC20_BALANCE_SIG = "0x70a08231"
ERC20_TRANSFER_SIG = "0xa9059cbb"

CHAIN_ID = 56


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
    SYMBOL = "BNB"
    NAME = "BNB Smart Chain"

    def __init__(self, private_key: str | None = None):
        if private_key:
            if private_key.startswith("0x"):
                private_key = private_key[2:]
            self._account = Account.from_key(bytes.fromhex(private_key))
        else:
            self._account = Account.create()

    @property
    def address(self) -> str:
        return self._account.address

    @property
    def private_key_hex(self) -> str:
        return self._account.key.hex()

    def validate_address(self, addr: str) -> bool:
        try:
            return Web3.is_address(addr)
        except Exception:
            return False

    def get_balance(self) -> dict:
        try:
            wei_hex = _rpc("eth_getBalance", [self.address, "latest"])["result"]
            bnb_balance = int(wei_hex, 16) / 1e18
        except Exception as e:
            return {"native": 0.0, "tokens": {}, "error": str(e)}

        tokens = {}
        try:
            padded = self.address.lower().replace("0x", "").zfill(64)
            data = ERC20_BALANCE_SIG + padded
            raw = _rpc("eth_call", [{"to": USDT_CONTRACT, "data": data}, "latest"])["result"]
            tokens["USDT"] = int(raw, 16) / (10 ** USDT_DECIMALS)
        except Exception:
            pass

        return {"native": bnb_balance, "tokens": tokens}

    def send(self, to: str, amount: float) -> dict:
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid BSC address"}
        try:
            to = Web3.to_checksum_address(to)
            nonce_hex = _rpc("eth_getTransactionCount", [self.address, "latest"])["result"]
            nonce = int(nonce_hex, 16)
            gas_price_hex = _rpc("eth_gasPrice", [])["result"]
            gas_price = int(gas_price_hex, 16)
            tx = {
                "nonce": nonce,
                "to": to,
                "value": int(amount * 1e18),
                "gas": 21000,
                "gasPrice": gas_price,
                "chainId": CHAIN_ID,
            }
            signed = self._account.sign_transaction(tx)
            raw = signed.raw_transaction.hex()
            if not raw.startswith("0x"):
                raw = "0x" + raw
            res = _rpc("eth_sendRawTransaction", [raw])
            if "error" in res:
                return {"success": False, "txid": None, "error": str(res["error"])}
            return {"success": True, "txid": res["result"], "error": None}
        except Exception as e:
            return {"success": False, "txid": None, "error": str(e)}

    def get_history(self, limit: int = 20) -> list[dict]:
        if not BSCSCAN_KEY:
            return []
        try:
            params = {
                "module": "account",
                "action": "txlist",
                "address": self.address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": limit,
                "sort": "desc",
                "apikey": BSCSCAN_KEY,
            }
            r = requests.get(BSCSCAN_API, params=params, timeout=30)
            r.raise_for_status()
            data = r.json().get("result", [])
            my = self.address.lower()
            out = []
            for t in data:
                direction = "in" if t.get("to", "").lower() == my else "out"
                out.append({
                    "txid": t.get("hash"),
                    "from": t.get("from"),
                    "to": t.get("to"),
                    "amount": int(t.get("value", "0")) / 1e18,
                    "time": _iso(int(t.get("timeStamp", 0))),
                    "direction": direction,
                })
            return out
        except Exception:
            return []


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex: {w.private_key_hex[:10]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"BSCSCAN_API_KEY set: {bool(BSCSCAN_KEY)}")

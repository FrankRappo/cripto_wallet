"""ETH Wallet — Alchemy RPC + web3.py."""

import os
from datetime import datetime, timezone

import requests
from eth_account import Account
from web3 import Web3

ALCHEMY_KEY = os.environ.get("ALCHEMY_API_KEY", "")
RPC_URL = (
    f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"
    if ALCHEMY_KEY
    else "https://eth.llamarpc.com"  # public fallback for read-only / address gen
)

# USDT ERC20
USDT_CONTRACT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_DECIMALS = 6
ERC20_BALANCE_SIG = "0x70a08231"
ERC20_TRANSFER_SIG = "0xa9059cbb"

CHAIN_ID = 1


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
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class Wallet:
    SYMBOL = "ETH"
    NAME = "Ethereum"

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
            eth_balance = int(wei_hex, 16) / 1e18
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

        return {"native": eth_balance, "tokens": tokens}

    def send(self, to: str, amount: float) -> dict:
        if not ALCHEMY_KEY:
            return {"success": False, "txid": None, "error": "ALCHEMY_API_KEY missing"}
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid ETH address"}
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
        if not ALCHEMY_KEY:
            return []
        try:
            # Alchemy asset transfers — incoming + outgoing
            results = []
            for direction_field, addr_filter in (("to", "in"), ("from", "out")):
                params = [{
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    direction_field + "Address": self.address,
                    "category": ["external", "erc20"],
                    "maxCount": hex(limit),
                    "order": "desc",
                }]
                r = _rpc("alchemy_getAssetTransfers", params)
                transfers = r.get("result", {}).get("transfers", [])
                for t in transfers:
                    ts = 0
                    md = t.get("metadata", {})
                    if md.get("blockTimestamp"):
                        try:
                            ts = int(datetime.fromisoformat(
                                md["blockTimestamp"].replace("Z", "+00:00")
                            ).timestamp())
                        except Exception:
                            ts = 0
                    results.append({
                        "txid": t.get("hash"),
                        "from": t.get("from"),
                        "to": t.get("to"),
                        "amount": float(t.get("value") or 0),
                        "time": _iso(ts),
                        "direction": addr_filter,
                    })
            results.sort(key=lambda x: x["time"], reverse=True)
            return results[:limit]
        except Exception:
            return []


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex: {w.private_key_hex[:10]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"ALCHEMY_API_KEY set: {bool(ALCHEMY_KEY)}")

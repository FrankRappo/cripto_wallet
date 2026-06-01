"""ETH Wallet — keyless public RPC (balance/send) + Etherscan V2 (history)."""

import os
from datetime import datetime, timezone

import requests
from eth_account import Account
from web3 import Web3

# Keyless public RPC — balance + broadcast (eth_sendRawTransaction). Override via ETH_RPC.
RPC_URL = os.environ.get("ETH_RPC", "https://ethereum-rpc.publicnode.com")
# History via Etherscan (free, email-only key — no phone). Recommended, not required.
ETHERSCAN_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
ETHERSCAN_API = os.environ.get("ETHERSCAN_API_BASE", "https://api.etherscan.io/v2/api")
ETH_CHAIN_ID = 1

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
        # Etherscan V2 — native ETH (txlist) + ERC-20 transfers (tokentx).
        if not ETHERSCAN_KEY:
            return []
        addr_lc = self.address.lower()
        results = []
        for action, is_token in (("txlist", False), ("tokentx", True)):
            params = {
                "chainid": ETH_CHAIN_ID,
                "module": "account",
                "action": action,
                "address": self.address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": max(1, min(limit, 100)),
                "sort": "desc",
                "apikey": ETHERSCAN_KEY,
            }
            try:
                r = requests.get(ETHERSCAN_API, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
            except Exception:
                continue
            if str(data.get("status")) != "1":
                continue
            for t in (data.get("result") or []):
                try:
                    if is_token:
                        dec = int(t.get("tokenDecimal", "18") or "18")
                        amount = float(t.get("value", "0")) / (10 ** dec)
                    else:
                        amount = float(t.get("value", "0")) / 1e18
                except (ValueError, TypeError):
                    amount = 0.0
                frm = t.get("from", "") or ""
                results.append({
                    "txid": t.get("hash", ""),
                    "from": frm,
                    "to": t.get("to", "") or "",
                    "amount": amount,
                    "time": _iso(int(t.get("timeStamp", 0) or 0)),
                    "direction": "out" if frm.lower() == addr_lc else "in",
                })
        results.sort(key=lambda x: x["time"], reverse=True)
        return results[:limit]


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex: {w.private_key_hex[:10]}...")
    print(f"valid: {w.validate_address(w.address)}")
    print(f"RPC: {RPC_URL}")
    print(f"ETHERSCAN_API_KEY set: {bool(ETHERSCAN_KEY)}")

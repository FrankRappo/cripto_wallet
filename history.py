"""Транзакционная история по адресу для поддерживаемых сетей.

Публичное API:
    fetch_history(symbol, address, limit=20) -> list[dict]
    format_history(items) -> str

Каждый элемент списка содержит:
    txid, from, to, amount, symbol, time (ISO-8601 UTC),
    direction ("in"|"out"), block (int), fee (float),
    status ("confirmed"|"pending"|"failed").
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s [history] %(levelname)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

SUPPORTED = {"BTC", "LTC", "ETH", "BSC", "SOL", "TON", "TRX", "XMR"}
HTTP_TIMEOUT = 30


def _iso_from_ts(ts: float | int) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


def _shorten(s: str, head: int = 8, tail: int = 6) -> str:
    if not s:
        return ""
    if len(s) <= head + tail + 1:
        return s
    return f"{s[:head]}…{s[-tail:]}"


def _http_get(url: str, params: dict | None = None, headers: dict | None = None) -> Any:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


def _http_post(url: str, payload: dict, headers: dict | None = None) -> Any:
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("POST %s failed: %s", url, e)
        return None


# ============================================================
#  BTC / LTC  (UTXO — mempool.space-совместимые API)
# ============================================================
def _fetch_utxo(symbol: str, address: str, limit: int) -> list[dict]:
    base = {
        "BTC": "https://mempool.space/api",
        "LTC": "https://litecoinspace.org/api",
    }[symbol]
    data = _http_get(f"{base}/address/{address}/txs")
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for tx in data[:limit]:
        vin = tx.get("vin") or []
        vout = tx.get("vout") or []
        in_sum = sum(
            int((v.get("prevout") or {}).get("value", 0))
            for v in vin
            if (v.get("prevout") or {}).get("scriptpubkey_address") == address
        )
        out_sum = sum(
            int(v.get("value", 0))
            for v in vout
            if v.get("scriptpubkey_address") == address
        )
        if in_sum > out_sum:
            direction = "out"
            amount = (in_sum - out_sum) / 1e8
            counterparts = [
                v.get("scriptpubkey_address", "")
                for v in vout
                if v.get("scriptpubkey_address") != address
            ]
            counter = counterparts[0] if counterparts else ""
            from_addr, to_addr = address, counter
        else:
            direction = "in"
            amount = (out_sum - in_sum) / 1e8
            senders = [
                (v.get("prevout") or {}).get("scriptpubkey_address", "")
                for v in vin
                if (v.get("prevout") or {}).get("scriptpubkey_address") != address
            ]
            counter = senders[0] if senders else ""
            from_addr, to_addr = counter, address

        status_obj = tx.get("status") or {}
        confirmed = bool(status_obj.get("confirmed"))
        block = int(status_obj.get("block_height") or 0)
        block_time = status_obj.get("block_time")
        ts_iso = _iso_from_ts(block_time) if block_time else ""
        fee = float(tx.get("fee", 0)) / 1e8

        out.append({
            "txid": tx.get("txid", ""),
            "from": from_addr,
            "to": to_addr,
            "amount": amount,
            "symbol": symbol,
            "time": ts_iso,
            "direction": direction,
            "block": block,
            "fee": fee,
            "status": "confirmed" if confirmed else "pending",
        })
    return out


# ============================================================
#  ETH — Etherscan V2 (free, email-only key — no phone)
# ============================================================
ETHERSCAN_API = os.getenv("ETHERSCAN_API_BASE", "https://api.etherscan.io/v2/api")
ETH_CHAIN_ID = 1


def _etherscan_eth(action: str, address: str, limit: int, key: str) -> list[dict]:
    params = {
        "chainid": ETH_CHAIN_ID,
        "module": "account", "action": action, "address": address,
        "startblock": 0, "endblock": 99999999,
        "page": 1, "offset": max(1, min(limit, 100)),
        "sort": "desc", "apikey": key,
    }
    data = _http_get(ETHERSCAN_API, params=params)
    if not isinstance(data, dict):
        return []
    if str(data.get("status")) != "1":
        msg = str(data.get("message", ""))
        if "No transactions" not in msg and "No records" not in msg:
            logger.warning("Etherscan %s: %s", action, msg)
        return []
    return data.get("result") or []


def _fetch_eth(address: str, limit: int) -> list[dict]:
    key = os.getenv("ETHERSCAN_API_KEY", "")
    if not key:
        logger.warning("ETH history: ETHERSCAN_API_KEY not set")
        return []
    addr_lc = address.lower()
    items: list[dict] = []

    # native ETH transfers
    for t in _etherscan_eth("txlist", address, limit, key):
        from_addr = t.get("from", "") or ""
        try:
            amount = float(t.get("value", "0")) / 1e18
        except (ValueError, TypeError):
            amount = 0.0
        try:
            fee = (int(t.get("gasUsed", "0")) * int(t.get("gasPrice", "0"))) / 1e18
        except (ValueError, TypeError):
            fee = 0.0
        try:
            block = int(t.get("blockNumber", "0"))
        except (ValueError, TypeError):
            block = 0
        items.append({
            "txid": t.get("hash", ""),
            "from": from_addr,
            "to": t.get("to", "") or "",
            "amount": amount,
            "symbol": "ETH",
            "time": _iso_from_ts(t.get("timeStamp", 0)),
            "direction": "out" if from_addr.lower() == addr_lc else "in",
            "block": block,
            "fee": fee,
            "status": "failed" if str(t.get("isError", "0")) == "1" else "confirmed",
        })

    # ERC-20 token transfers (USDT etc.)
    for t in _etherscan_eth("tokentx", address, limit, key):
        from_addr = t.get("from", "") or ""
        try:
            dec = int(t.get("tokenDecimal", "18") or "18")
        except (ValueError, TypeError):
            dec = 18
        try:
            amount = float(t.get("value", "0")) / (10 ** dec)
        except (ValueError, TypeError):
            amount = 0.0
        try:
            block = int(t.get("blockNumber", "0"))
        except (ValueError, TypeError):
            block = 0
        items.append({
            "txid": t.get("hash", ""),
            "from": from_addr,
            "to": t.get("to", "") or "",
            "amount": amount,
            "symbol": t.get("tokenSymbol", "ERC20") or "ERC20",
            "time": _iso_from_ts(t.get("timeStamp", 0)),
            "direction": "out" if from_addr.lower() == addr_lc else "in",
            "block": block,
            "fee": 0.0,
            "status": "confirmed",
        })

    # dedup by (txid, direction, amount, symbol)
    seen = set()
    uniq = []
    for it in items:
        k = (it["txid"], it["direction"], it["amount"], it["symbol"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    uniq.sort(key=lambda x: x.get("time", ""), reverse=True)
    return uniq[:limit]


# ============================================================
#  BSC — BscScan
# ============================================================
def _fetch_bsc(address: str, limit: int) -> list[dict]:
    key = os.getenv("BSCSCAN_API_KEY", "")
    url = "https://api.bscscan.com/api"
    params = {
        "module": "account", "action": "txlist", "address": address,
        "startblock": 0, "endblock": 99999999,
        "page": 1, "offset": max(1, min(limit, 100)),
        "sort": "desc",
    }
    if key:
        params["apikey"] = key
    data = _http_get(url, params=params)
    if not isinstance(data, dict):
        return []
    if str(data.get("status")) != "1":
        msg = data.get("message", "")
        if "No transactions" not in str(msg):
            logger.warning("BscScan: %s", msg)
        return []
    items = []
    addr_lc = address.lower()
    for t in (data.get("result") or [])[:limit]:
        from_addr = t.get("from", "") or ""
        to_addr = t.get("to", "") or ""
        direction = "out" if from_addr.lower() == addr_lc else "in"
        try:
            amount = float(t.get("value", "0")) / 1e18
        except (ValueError, TypeError):
            amount = 0.0
        try:
            gas_used = int(t.get("gasUsed", "0"))
            gas_price = int(t.get("gasPrice", "0"))
            fee = (gas_used * gas_price) / 1e18
        except (ValueError, TypeError):
            fee = 0.0
        try:
            block = int(t.get("blockNumber", "0"))
        except (ValueError, TypeError):
            block = 0
        ts_iso = _iso_from_ts(t.get("timeStamp", 0))
        is_error = str(t.get("isError", "0")) == "1"
        status = "failed" if is_error else "confirmed"
        items.append({
            "txid": t.get("hash", ""),
            "from": from_addr,
            "to": to_addr,
            "amount": amount,
            "symbol": "BNB",
            "time": ts_iso,
            "direction": direction,
            "block": block,
            "fee": fee,
            "status": status,
        })
    return items


# ============================================================
#  SOL — Helius
# ============================================================
SOL_RPC = os.getenv("SOL_RPC", "https://solana-rpc.publicnode.com")
LAMPORTS_PER_SOL = 1_000_000_000


def _fetch_sol(address: str, limit: int) -> list[dict]:
    # Helius обогащает/ускоряет, но не обязателен — без ключа идём через публичный RPC.
    key = os.getenv("HELIUS_API_KEY", "")
    if not key:
        return _fetch_sol_rpc(address, limit)
    base = f"https://api.helius.xyz/v0/addresses/{address}/transactions"
    data = _http_get(base, params={"api-key": key, "limit": max(1, min(limit, 100))})
    if not isinstance(data, list):
        return []
    items = []
    for t in data[:limit]:
        sig = t.get("signature", "")
        ts = t.get("timestamp")
        ts_iso = _iso_from_ts(ts) if ts else ""
        block = int(t.get("slot") or 0)
        err = t.get("transactionError")
        status = "failed" if err else "confirmed"
        from_addr = t.get("feePayer", "") or ""
        to_addr = ""
        amount = 0.0
        direction = "out" if from_addr == address else "in"

        native = t.get("nativeTransfers") or []
        match = None
        for nt in native:
            if nt.get("fromUserAccount") == address or nt.get("toUserAccount") == address:
                match = nt
                break
        if match:
            lamports = int(match.get("amount", 0) or 0)
            amount = lamports / 1e9
            from_addr = match.get("fromUserAccount", "") or from_addr
            to_addr = match.get("toUserAccount", "") or ""
            direction = "out" if from_addr == address else "in"

        try:
            fee = float(t.get("fee", 0) or 0) / 1e9
        except (ValueError, TypeError):
            fee = 0.0

        items.append({
            "txid": sig,
            "from": from_addr,
            "to": to_addr,
            "amount": amount,
            "symbol": "SOL",
            "time": ts_iso,
            "direction": direction,
            "block": block,
            "fee": fee,
            "status": status,
        })
    return items


def _fetch_sol_rpc(address: str, limit: int) -> list[dict]:
    """SOL история без ключа — публичный RPC (getSignaturesForAddress + getTransaction)."""
    sigs = _http_post(SOL_RPC, {
        "jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
        "params": [address, {"limit": max(1, min(limit, 100))}],
    })
    sig_list = (sigs or {}).get("result") or []
    items = []
    for s in sig_list[:limit]:
        txid = s.get("signature", "")
        ts = s.get("blockTime") or 0
        block = int(s.get("slot") or 0)
        status = "failed" if s.get("err") else "confirmed"
        amount, fee = 0.0, 0.0
        from_addr, to_addr, direction = "", "", "in"
        txres = _http_post(SOL_RPC, {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [txid, {"encoding": "json", "maxSupportedTransactionVersion": 0}],
        })
        tx = (txres or {}).get("result") or {}
        meta = tx.get("meta") or {}
        try:
            fee = float(meta.get("fee", 0) or 0) / LAMPORTS_PER_SOL
        except (ValueError, TypeError):
            fee = 0.0
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        acct_keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
        my_idx = next((i for i, k in enumerate(acct_keys) if k == address), -1)
        if 0 <= my_idx < len(pre) and my_idx < len(post):
            delta = (post[my_idx] - pre[my_idx]) / LAMPORTS_PER_SOL
            direction = "in" if delta >= 0 else "out"
            amount = abs(delta)
        other = next((k for k in acct_keys if k != address), None)
        if direction == "in":
            from_addr, to_addr = other or "", address
        else:
            from_addr, to_addr = address, other or ""
        items.append({
            "txid": txid,
            "from": from_addr,
            "to": to_addr,
            "amount": amount,
            "symbol": "SOL",
            "time": _iso_from_ts(ts) if ts else "",
            "direction": direction,
            "block": block,
            "fee": fee,
            "status": status,
        })
    return items


# ============================================================
#  TON — toncenter
# ============================================================
def _fetch_ton(address: str, limit: int) -> list[dict]:
    key = os.getenv("TONCENTER_API_KEY", "")
    headers = {"X-API-Key": key} if key else None
    params = {"address": address, "limit": max(1, min(limit, 100))}
    data = _http_get(
        "https://toncenter.com/api/v2/getTransactions",
        params=params, headers=headers,
    )
    if not isinstance(data, dict) or not data.get("ok"):
        return []
    items = []
    for t in (data.get("result") or [])[:limit]:
        in_msg = t.get("in_msg") or {}
        out_msgs = t.get("out_msgs") or []
        ts_iso = _iso_from_ts(t.get("utime", 0))
        block = int((t.get("transaction_id") or {}).get("lt", 0) or 0)
        try:
            fee = float(t.get("fee", "0")) / 1e9
        except (ValueError, TypeError):
            fee = 0.0
        txid = (t.get("transaction_id") or {}).get("hash", "")

        if out_msgs:
            msg = out_msgs[0]
            try:
                amount = float(msg.get("value", "0")) / 1e9
            except (ValueError, TypeError):
                amount = 0.0
            from_addr = msg.get("source", "") or address
            to_addr = msg.get("destination", "") or ""
            direction = "out"
        else:
            try:
                amount = float(in_msg.get("value", "0")) / 1e9
            except (ValueError, TypeError):
                amount = 0.0
            from_addr = in_msg.get("source", "") or ""
            to_addr = in_msg.get("destination", "") or address
            direction = "in"

        items.append({
            "txid": txid,
            "from": from_addr,
            "to": to_addr,
            "amount": amount,
            "symbol": "TON",
            "time": ts_iso,
            "direction": direction,
            "block": block,
            "fee": fee,
            "status": "confirmed",
        })
    return items


# ============================================================
#  TRX — trongrid (native TRX + TRC20)
# ============================================================
def _fetch_trx(address: str, limit: int) -> list[dict]:
    key = os.getenv("TRONGRID_API_KEY", "")
    headers = {"TRON-PRO-API-KEY": key} if key else None
    items: list[dict] = []

    data = _http_get(
        f"https://api.trongrid.io/v1/accounts/{address}/transactions",
        params={"limit": max(1, min(limit, 200))},
        headers=headers,
    )
    if isinstance(data, dict):
        for t in (data.get("data") or [])[:limit]:
            raw = t.get("raw_data") or {}
            contracts = raw.get("contract") or []
            if not contracts:
                continue
            c = contracts[0]
            ctype = c.get("type", "")
            params = ((c.get("parameter") or {}).get("value") or {})
            from_hex = params.get("owner_address", "")
            to_hex = params.get("to_address", "")
            amount_sun = params.get("amount", 0)

            from_addr = _hex_to_tron(from_hex) or ""
            to_addr = _hex_to_tron(to_hex) or ""
            try:
                amount = float(amount_sun or 0) / 1e6
            except (ValueError, TypeError):
                amount = 0.0
            direction = "out" if from_addr == address else "in"
            ts_iso = _iso_from_ts((t.get("block_timestamp") or 0) / 1000)
            ret = (t.get("ret") or [{}])[0]
            ret_status = ret.get("contractRet", "")
            status = "confirmed" if ret_status == "SUCCESS" else (
                "failed" if ret_status else "pending"
            )
            try:
                fee = float(t.get("net_fee", 0) or 0) / 1e6
            except (ValueError, TypeError):
                fee = 0.0
            items.append({
                "txid": t.get("txID", ""),
                "from": from_addr,
                "to": to_addr,
                "amount": amount,
                "symbol": "TRX" if ctype == "TransferContract" else ctype,
                "time": ts_iso,
                "direction": direction,
                "block": 0,
                "fee": fee,
                "status": status,
            })

    trc20 = _http_get(
        f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20",
        params={"limit": max(1, min(limit, 200))},
        headers=headers,
    )
    if isinstance(trc20, dict):
        for t in (trc20.get("data") or [])[:limit]:
            from_addr = t.get("from", "") or ""
            to_addr = t.get("to", "") or ""
            token = (t.get("token_info") or {})
            decimals = int(token.get("decimals", 6) or 6)
            try:
                amount = float(t.get("value", "0")) / (10 ** decimals)
            except (ValueError, TypeError):
                amount = 0.0
            sym = token.get("symbol", "TRC20")
            ts_iso = _iso_from_ts((t.get("block_timestamp") or 0) / 1000)
            direction = "out" if from_addr == address else "in"
            items.append({
                "txid": t.get("transaction_id", ""),
                "from": from_addr,
                "to": to_addr,
                "amount": amount,
                "symbol": sym,
                "time": ts_iso,
                "direction": direction,
                "block": 0,
                "fee": 0.0,
                "status": "confirmed",
            })

    items.sort(key=lambda x: x.get("time", ""), reverse=True)
    return items[:limit]


def _hex_to_tron(hex_addr: str) -> str:
    if not hex_addr:
        return ""
    try:
        import base58
        raw = bytes.fromhex(hex_addr)
        if len(raw) != 21:
            return ""
        import hashlib
        checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
        return base58.b58encode(raw + checksum).decode()
    except Exception:
        return ""


# ============================================================
#  XMR — через локальный monero-wallet-rpc (его автозапускает monero_daemon)
# ============================================================
ATOMIC_XMR = 1_000_000_000_000


def _fetch_xmr(address: str, limit: int) -> list[dict]:
    url = os.getenv("MONERO_WALLET_RPC", "")
    if not url:
        logger.warning("Monero history requires monero-wallet-rpc (MONERO_WALLET_RPC)")
        return []
    res = _http_post(url, {
        "jsonrpc": "2.0", "id": "0", "method": "get_transfers",
        "params": {"in": True, "out": True},
    })
    if not isinstance(res, dict):
        return []
    result = res.get("result") or {}
    items = []
    for direction in ("in", "out"):
        for t in (result.get(direction) or []):
            try:
                amount = int(t.get("amount", 0) or 0) / ATOMIC_XMR
            except (ValueError, TypeError):
                amount = 0.0
            try:
                fee = int(t.get("fee", 0) or 0) / ATOMIC_XMR
            except (ValueError, TypeError):
                fee = 0.0
            if direction == "out":
                dests = t.get("destinations") or []
                to_addr = dests[0].get("address", "") if dests else ""
                from_addr = address
            else:
                to_addr = t.get("address", "") or address
                from_addr = ""
            items.append({
                "txid": t.get("txid", ""),
                "from": from_addr,
                "to": to_addr,
                "amount": amount,
                "symbol": "XMR",
                "time": _iso_from_ts(t.get("timestamp", 0)),
                "direction": direction,
                "block": int(t.get("height", 0) or 0),
                "fee": fee,
                "status": "pending" if t.get("type") in ("pending", "pool") else "confirmed",
            })
    items.sort(key=lambda x: x.get("time", ""), reverse=True)
    return items[:limit]


# ============================================================
#  Публичное API
# ============================================================
_DISPATCH = {
    "BTC": lambda a, n: _fetch_utxo("BTC", a, n),
    "LTC": lambda a, n: _fetch_utxo("LTC", a, n),
    "ETH": _fetch_eth,
    "BSC": _fetch_bsc,
    "SOL": _fetch_sol,
    "TON": _fetch_ton,
    "TRX": _fetch_trx,
    "XMR": _fetch_xmr,
}


def fetch_history(symbol: str, address: str, limit: int = 20) -> list[dict]:
    sym = (symbol or "").upper().strip()
    if sym not in SUPPORTED:
        logger.warning("Unsupported symbol: %s", symbol)
        return []
    if not address:
        return []
    if limit <= 0:
        return []
    try:
        return _DISPATCH[sym](address, limit) or []
    except Exception as e:
        logger.warning("fetch_history(%s) failed: %s", sym, e)
        return []


def format_history(items: list[dict]) -> str:
    if not items:
        return "(нет транзакций)"

    rows = []
    for it in items:
        t = it.get("time", "") or ""
        date = t[:19].replace("T", " ") if t else "—"
        direction = it.get("direction", "")
        arrow = "←" if direction == "in" else ("→" if direction == "out" else "·")
        try:
            amount = float(it.get("amount") or 0)
        except (ValueError, TypeError):
            amount = 0.0
        sym = it.get("symbol", "") or ""
        amt_str = f"{arrow} {amount:.8f} {sym}".rstrip("0").rstrip(".") if amount else f"{arrow} 0 {sym}"
        counter = it.get("from") if direction == "in" else it.get("to")
        counter = _shorten(counter or "", 6, 6)
        txid = _shorten(it.get("txid", ""), 8, 6)
        status = it.get("status", "")
        rows.append((date, amt_str, counter, txid, status))

    headers = ("Дата", "Сумма", "Контрагент", "TxID", "Статус")
    widths = [
        max(len(headers[i]), max((len(r[i]) for r in rows), default=0))
        for i in range(5)
    ]
    sep = " | "
    lines = [sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("-+-".join("-" * w for w in widths))
    for r in rows:
        lines.append(sep.join(r[i].ljust(widths[i]) for i in range(5)))
    return "\n".join(lines)


if __name__ == "__main__":
    samples = [
        ("BTC", "bc1qxhmdufsvnuaaaer4ynz88fspdsxq2h9e9cetdj"),
        ("TRX", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
    ]
    for sym, addr in samples:
        items = fetch_history(sym, addr, limit=5)
        print(f"\n=== {sym} ===")
        print(format_history(items))

"""Volatility metrics for supported crypto symbols via CoinGecko market_chart."""

import math
import statistics
import requests

try:
    from rates import COINGECKO_IDS
except Exception:
    COINGECKO_IDS = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "TRX": "tron",
        "LTC": "litecoin",
        "BCH": "bitcoin-cash",
        "DOGE": "dogecoin",
        "XMR": "monero",
        "USDT": "tether",
        "BNB": "binancecoin",
        "SOL": "solana",
        "XRP": "ripple",
        "ADA": "cardano",
    }

_API = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
_TIMEOUT = 15


def get_volatility(symbol: str, days: int) -> dict | None:
    sym = symbol.upper()
    cg_id = COINGECKO_IDS.get(sym)
    if not cg_id:
        return None
    try:
        resp = requests.get(
            _API.format(id=cg_id),
            params={"vs_currency": "usd", "days": days},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    prices_raw = data.get("prices") or []
    prices = [float(p[1]) for p in prices_raw if p and len(p) >= 2 and p[1] is not None]
    if len(prices) < 2:
        return None

    log_returns = []
    for prev, cur in zip(prices, prices[1:]):
        if prev > 0 and cur > 0:
            log_returns.append(math.log(cur / prev))

    stddev_pct = statistics.stdev(log_returns) * 100 if len(log_returns) >= 2 else 0.0
    first, last = prices[0], prices[-1]
    change_pct = (last - first) / first * 100 if first > 0 else 0.0

    return {
        "symbol": sym,
        "days": days,
        "min": min(prices),
        "max": max(prices),
        "stddev_pct": stddev_pct,
        "change_pct": change_pct,
        "current": last,
        "samples": len(prices),
    }


def get_volatility_report(symbol: str) -> dict:
    return {
        "30d": get_volatility(symbol, 30),
        "90d": get_volatility(symbol, 90),
        "180d": get_volatility(symbol, 180),
    }


if __name__ == "__main__":
    import json
    r = get_volatility_report("BTC")
    print(json.dumps(r, indent=2, default=str))

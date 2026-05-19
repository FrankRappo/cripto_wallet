import time
import requests

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "LTC": "litecoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "BSC": "binancecoin",
    "SOL": "solana",
    "TON": "the-open-network",
    "TRX": "tron",
    "USDT": "tether",
    "XMR": "monero",
}

_CACHE_TTL = 60
_TIMEOUT = 10
_cache: dict = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if not entry:
        return None
    value, ts = entry
    if time.time() - ts > _CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value) -> None:
    _cache[key] = (value, time.time())


def _fetch_coingecko(ids: list[str]) -> dict | None:
    if not ids:
        return {}
    key = "cg:" + ",".join(sorted(set(ids)))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(sorted(set(ids))), "vs_currencies": "usd,rub"},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        _cache_set(key, data)
        return data
    except Exception:
        return None


def _fetch_moex_usd_rub() -> float | None:
    cached = _cache_get("moex:usdrub")
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            "https://iss.moex.com/iss/engines/currency/markets/selt/securities/USD000UTSTOM.json",
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        securities = data.get("securities", {})
        columns = securities.get("columns", [])
        rows = securities.get("data", [])
        if not rows or not columns:
            return None
        row = rows[0]
        rec = dict(zip(columns, row))
        price = rec.get("LAST") or rec.get("PREVPRICE")
        if price is None:
            return None
        rate = float(price)
        _cache_set("moex:usdrub", rate)
        return rate
    except Exception:
        return None


def get_rate(symbol: str, vs: str = "usd") -> float | None:
    sym = symbol.upper()
    cg_id = COINGECKO_IDS.get(sym)
    if not cg_id:
        return None
    data = _fetch_coingecko([cg_id])
    if not data:
        return None
    entry = data.get(cg_id)
    if not entry:
        return None
    value = entry.get(vs.lower())
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_rate_rub_moex(symbol: str) -> float | None:
    usd_price = get_rate(symbol, "usd")
    if usd_price is None:
        return None
    usd_rub = _fetch_moex_usd_rub()
    if usd_rub is None:
        return None
    return usd_price * usd_rub


def get_all_rates(symbols: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    ids = []
    sym_to_id: dict[str, str] = {}
    for s in symbols:
        sym = s.upper()
        cg_id = COINGECKO_IDS.get(sym)
        if cg_id:
            ids.append(cg_id)
            sym_to_id[sym] = cg_id

    cg_data = _fetch_coingecko(ids) if ids else None
    moex_rate: float | None = None
    moex_fetched = False

    for s in symbols:
        sym = s.upper()
        cg_id = sym_to_id.get(sym)
        usd_val: float | None = None
        rub_val: float | None = None
        source = "coingecko"

        if cg_data and cg_id:
            entry = cg_data.get(cg_id) or {}
            u = entry.get("usd")
            r = entry.get("rub")
            if u is not None:
                try:
                    usd_val = float(u)
                except (TypeError, ValueError):
                    usd_val = None
            if r is not None:
                try:
                    rub_val = float(r)
                except (TypeError, ValueError):
                    rub_val = None

        if rub_val is None and usd_val is not None:
            if not moex_fetched:
                moex_rate = _fetch_moex_usd_rub()
                moex_fetched = True
            if moex_rate is not None:
                rub_val = usd_val * moex_rate
                source = "moex"

        if usd_val is None and rub_val is None:
            result[sym] = {"usd": None, "rub": None, "source": None}
        else:
            result[sym] = {"usd": usd_val, "rub": rub_val, "source": source}

    return result


if __name__ == "__main__":
    print(get_all_rates(["BTC", "ETH", "TRX", "USDT", "XMR"]))

"""Cripto Wallet — мультисетевой CLI (BTC/LTC/ETH/BSC/SOL/TON/TRX/XMR).

TRX-функции (Stake V1/V2, диагностика заморозок) сохранены из legacy-версии
и доступны только когда активная сеть — TRX.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
import base58


def _enable_utf8_console() -> None:
    """Windows: консоль (cmd/PowerShell) по умолчанию не UTF-8 — эмодзи в выводе
    (✅ ⚠️ 💾) и кириллица могут ронять print() через UnicodeEncodeError.
    Переключаем потоки на UTF-8. На POSIX это no-op (там и так UTF-8)."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


_enable_utf8_console()

from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
import urllib3


def _load_dotenv(path: str | None = None) -> None:
    """Минимальный загрузчик .env (без зависимостей).

    Вызывается ДО импорта networks/* — модули читают ключи на этапе импорта.
    Уже заданные переменные окружения не перезатираются.
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)
    except OSError:
        pass


_load_dotenv()

import utils
import rates
import volatility
import history
import monero_daemon
from networks import btc as net_btc
from networks import ltc as net_ltc
from networks import eth as net_eth
from networks import bsc as net_bsc
from networks import sol as net_sol
from networks import ton as net_ton
from networks import monero as net_xmr

urllib3.disable_warnings()

# === TRON-конфиг (legacy) ===
NETWORK = "mainnet"
API_KEY = os.environ.get("TRONGRID_API_KEY", "")  # TRON-PRO-API-KEY из .env (опционален)
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
API_BASE = "https://api.trongrid.io"
# Без ключа TronGrid тоже работает (ниже лимиты) — провайдер без api_key.
provider = HTTPProvider(api_key=API_KEY, timeout=60) if API_KEY else HTTPProvider(timeout=60)

MAX_FEE_LIMIT = 100_000_000  # 100 TRX
MIN_TRX_BALANCE = 8

NETWORKS = ["BTC", "LTC", "ETH", "BSC", "SOL", "TON", "TRX", "XMR"]


# === TRON helpers (legacy) ===
def validate_tron_address(address: str) -> bool:
    return isinstance(address, str) and address.startswith("T") and len(address) == 34


def to_sun(amount_trx: float) -> int:
    return int(amount_trx * 1_000_000)


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


def tron_b58_to_hex(addr: str) -> str:
    raw = base58.b58decode_check(addr)
    return raw.hex()


def http_headers():
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["TRON-PRO-API-KEY"] = API_KEY
    return headers


def post_wallet(path: str, payload: dict) -> dict:
    url = f"{API_BASE}{path}"
    r = requests.post(url, headers=http_headers(), json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def sign_and_broadcast(tx: dict, pk: PrivateKey) -> dict:
    txid = tx.get("txID")
    if not txid:
        raise RuntimeError(f"Нет txID в транзакции: {tx}")
    sig = pk.sign_msg_hash(bytes.fromhex(txid)).hex()
    tx_signed = dict(tx)
    sig_list = list(tx_signed.get("signature", []))
    sig_list.append(sig)
    tx_signed["signature"] = sig_list
    res = post_wallet("/wallet/broadcasttransaction", tx_signed)
    return {"txid": txid, "broadcast_result": res, "signed_tx": tx_signed}


class TronWallet:
    SYMBOL = "TRX"
    NAME = "Tron"

    def __init__(self, private_key=None):
        self.client = Tron(network=NETWORK, provider=provider)
        if private_key:
            self.pk = PrivateKey(bytes.fromhex(private_key))
        else:
            self.pk = PrivateKey.random()
        self.address = self.pk.public_key.to_base58check_address()
        self.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def private_key_hex(self) -> str:
        return self.pk.hex()

    def get_balances(self):
        trx_balance = 0
        usdt_balance = 0
        activated = False
        frozen_energy = 0.0
        frozen_bandwidth = 0.0

        try:
            acc = self.client.get_account(self.address)
            trx_balance = acc.get("balance", 0) / 1_000_000
            activated = trx_balance > 0 or "account_resource" in acc

            if "frozen" in acc:
                for f in acc.get("frozen", []) or []:
                    frozen_bandwidth += f.get("frozen_balance", 0) / 1_000_000

            fr_energy_legacy = acc.get("account_resource", {}).get("frozen_balance_for_energy")
            if isinstance(fr_energy_legacy, dict):
                frozen_energy += fr_energy_legacy.get("frozen_balance", 0) / 1_000_000

            def add_frozen_v2(entries):
                nonlocal frozen_energy, frozen_bandwidth
                for item in entries or []:
                    typ = (item.get("type") or item.get("resource") or "").upper()
                    amt = item.get("amount", item.get("frozen_balance", 0)) / 1_000_000
                    if typ == "ENERGY":
                        frozen_energy += amt
                    elif typ == "BANDWIDTH":
                        frozen_bandwidth += amt
                    else:
                        frozen_bandwidth += amt

            add_frozen_v2(acc.get("frozenV2", []))
            add_frozen_v2(acc.get("delegatedFrozenV2", []))
            add_frozen_v2(acc.get("delegated_frozenV2", []))

            contract = self.client.get_contract(USDT_CONTRACT)
            usdt_balance = contract.functions.balanceOf(self.address) / 1_000_000
        except Exception as e:
            print(f"⚠️ Ошибка получения баланса: {e}")

        self.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "trx": trx_balance,
            "usdt": usdt_balance,
            "activated": activated,
            "frozen_energy": frozen_energy,
            "frozen_bandwidth": frozen_bandwidth,
        }

    def get_resources(self):
        try:
            resources = self.client.get_account_resource(self.address)
            energy = resources.get('EnergyLimit', 0) - resources.get('EnergyUsed', 0)
            bandwidth = resources.get('FreeNetLimit', 0) - resources.get('FreeNetUsed', 0)
            return {'energy': energy, 'bandwidth': bandwidth}
        except Exception as e:
            print(f"Ошибка получения ресурсов: {e}")
            return {'energy': 0, 'bandwidth': 0}

    def send_usdt(self, to_address, amount):
        if not validate_tron_address(to_address):
            return {"success": False, "error": "Неверный формат адреса TRON."}
        try:
            contract = self.client.get_contract(USDT_CONTRACT)
            txn_builder = (
                contract.functions.transfer(to_address, to_sun(amount))
                .with_owner(self.address)
            )
            txn = txn_builder.fee_limit(MAX_FEE_LIMIT).build()
            balances = self.get_balances()
            if balances["trx"] < MIN_TRX_BALANCE:
                return {"success": False, "error": f"Недостаточно TRX для комиссии (минимум {MIN_TRX_BALANCE})."}

            txn_signed = txn.sign(self.pk)
            txn_result = txn_signed.broadcast().wait()
            receipt = txn_result.get('receipt', {})
            total_fee = (receipt.get('energy_fee', 0) + receipt.get('net_fee', 0)) / 1_000_000
            print(f"✅ Отправлено! Комиссия: {total_fee} TRX")
            return {"success": True, "txid": txn_signed.txid, "result": txn_result, "total_fee_trx": total_fee}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_trx(self, to_address, amount):
        if not validate_tron_address(to_address):
            return {"success": False, "error": "Неверный формат адреса TRON."}
        try:
            txn_builder = self.client.trx.transfer(self.address, to_address, to_sun(amount))
            txn = txn_builder.fee_limit(MAX_FEE_LIMIT).build()
            balances = self.get_balances()
            if balances["trx"] < MIN_TRX_BALANCE + amount:
                return {"success": False, "error": f"Недостаточно TRX для отправки+комиссии (минимум {MIN_TRX_BALANCE + amount})."}

            txn_signed = txn.sign(self.pk)
            txn_result = txn_signed.broadcast().wait()
            receipt = txn_result.get('receipt', {})
            total_fee = (receipt.get('energy_fee', 0) + receipt.get('net_fee', 0)) / 1_000_000
            print(f"✅ Отправлено! Комиссия: {total_fee} TRX")
            return {"success": True, "txid": txn_signed.txid, "result": txn_result, "total_fee_trx": total_fee}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def freeze_trx_v1(self, amount, resource="ENERGY"):
        try:
            txn = self.client.trx.freeze_balance(
                owner=self.address,
                amount=to_sun(amount),
                duration=3,
                resource=resource,
                receiver=None,
            )
            txn_built = txn.fee_limit(MAX_FEE_LIMIT).build()
            txn_signed = txn_built.sign(self.pk)
            txn_result = txn_signed.broadcast().wait()
            print(f"✅ Заморозка V1 {amount} TRX для {resource} выполнена!")
            return {"success": True, "txid": txn_signed.txid, "result": txn_result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unfreeze_trx_v1(self, resource="ENERGY"):
        try:
            txn = self.client.trx.unfreeze_balance(owner=self.address, resource=resource, receiver=None)
            txn_built = txn.fee_limit(MAX_FEE_LIMIT).build()
            txn_signed = txn_built.sign(self.pk)
            txn_result = txn_signed.broadcast().wait()
            print(f"✅ Разморозка V1 для {resource} выполнена!")
            return {"success": True, "txid": txn_signed.txid, "result": txn_result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unfreeze_trx_v2_http(self, amount, resource="ENERGY"):
        try:
            if resource not in ("ENERGY", "BANDWIDTH"):
                return {"success": False, "error": "resource должен быть ENERGY или BANDWIDTH"}
            payload = {
                "owner_address": tron_b58_to_hex(self.address),
                "unfreeze_balance": to_sun(amount),
                "resource": resource,
            }
            tx = post_wallet("/wallet/unfreezebalancev2", payload)
            if not isinstance(tx, dict) or not tx.get("txID"):
                return {"success": False, "stage": "build", "response": tx}

            signed = sign_and_broadcast(tx, self.pk)
            ok = bool(signed["broadcast_result"].get("result"))
            if ok:
                print(f"✅ V2 Unfreeze (unstake) отправлена: {amount} TRX ({resource})")
            else:
                print(f"❌ Ошибка broadcast V2: {signed['broadcast_result']}")
            return {"success": ok, "txid": signed["txid"], "response": signed}
        except requests.HTTPError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def withdraw_unfreeze_v2_http(self):
        try:
            payload = {"owner_address": tron_b58_to_hex(self.address)}
            tx = post_wallet("/wallet/withdrawexpireunfreeze", payload)
            if not isinstance(tx, dict) or not tx.get("txID"):
                return {"success": False, "stage": "build", "response": tx}

            signed = sign_and_broadcast(tx, self.pk)
            ok = bool(signed["broadcast_result"].get("result"))
            if ok:
                print("✅ V2 Withdraw выполнен (вывод зрелых разморозок).")
            else:
                print(f"❌ Ошибка broadcast V2 withdraw: {signed['broadcast_result']}")
            return {"success": ok, "txid": signed["txid"], "response": signed}
        except requests.HTTPError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def debug_freeze_info(self):
        try:
            acc = self.client.get_account(self.address)
            now_ms = int(time.time() * 1000)
            now_iso = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat()

            print("\n=== Диагностика заморозок ===")
            print(f"Адрес: {self.address}")
            print(f"Сейчас (UTC): {now_iso}")

            f1 = acc.get("account_resource", {}).get("frozen_balance_for_energy") or {}
            if f1:
                amount = f1.get("frozen_balance", 0) / 1_000_000
                exp = f1.get("expire_time", 0)
                exp_iso = datetime.fromtimestamp(exp / 1000, tz=timezone.utc).isoformat() if exp else "-"
                left_sec = max(0, (exp - now_ms) // 1000)
                print(f"- V1 ENERGY: {amount} TRX, expire: {exp_iso}, осталось ~{left_sec // 3600} ч")
            else:
                print("- V1 ENERGY: 0 TRX")

            v1_bw = acc.get("frozen", []) or []
            if v1_bw:
                total = sum((i.get("frozen_balance", 0) for i in v1_bw)) / 1_000_000
                print(f"- V1 BANDWIDTH всего: {total} TRX")
            else:
                print("- V1 BANDWIDTH: 0 TRX")

            v2 = acc.get("frozenV2", []) or []
            if v2:
                print("- V2 self frozen:")
                for i, it in enumerate(v2, 1):
                    typ = (it.get("type") or it.get("resource") or "").upper()
                    amt = it.get("amount", it.get("frozen_balance", 0)) / 1_000_000
                    print(f"   [{i}] {typ}: {amt} TRX")
            else:
                print("- V2 self frozen: пусто")

            dv2 = acc.get("delegatedFrozenV2", []) or acc.get("delegated_frozenV2", []) or []
            if dv2:
                print("- V2 delegatedFrozenV2 есть")
            else:
                print("- V2 delegatedFrozenV2: пусто")

            print("=== Конец диагностики ===\n")
        except Exception as e:
            print(f"Ошибка диагностики: {e}")


# === Реестр сетей ===
WALLETS_CLS = {
    "TRX": TronWallet,
    "BTC": net_btc.Wallet,
    "LTC": net_ltc.Wallet,
    "ETH": net_eth.Wallet,
    "BSC": net_bsc.Wallet,
    "SOL": net_sol.Wallet,
    "TON": net_ton.Wallet,
    "XMR": net_xmr.Wallet,
}


# === Общие helpers ===
def short_addr(addr: str) -> str:
    if not addr:
        return ""
    if len(addr) <= 18:
        return addr
    return f"{addr[:10]}...{addr[-6:]}"


def get_priv_hex(wallet) -> str:
    return wallet.private_key_hex


def save_wallet_json(wallet, symbol: str, path: str) -> str:
    data = {
        "symbol": symbol,
        "private_key": get_priv_hex(wallet),
        "address": wallet.address,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def load_wallet_json(path: str):
    with open(path, "r") as f:
        data = json.load(f)
    sym = (data.get("symbol") or "").upper().strip()
    pk = data.get("private_key")
    if sym not in WALLETS_CLS:
        raise ValueError(f"Неизвестная сеть в JSON: {sym!r}")
    if not pk:
        raise ValueError("В JSON отсутствует private_key")
    cls = WALLETS_CLS[sym]
    return sym, cls(private_key=pk)


def format_rate_suffix(symbol: str, amount: float) -> str:
    if amount is None or amount == 0:
        return ""
    info = rates.get_all_rates([symbol]).get(symbol.upper()) or {}
    usd = info.get("usd")
    rub = info.get("rub")
    src = info.get("source") or "—"
    if usd is None and rub is None:
        return ""
    usd_s = f"${amount * usd:,.2f}" if usd is not None else "$?"
    rub_s = f"₽{amount * rub:,.2f}" if rub is not None else "₽?"
    return f"  ≈ {usd_s} | {rub_s} (источник: {src})"


def show_balances(symbol: str, wallet) -> None:
    if symbol == "TRX":
        b = wallet.get_balances()
        r = wallet.get_resources()
        trx_amt = b["trx"]
        usdt_amt = b["usdt"]
        print(f"\nTRX:  {trx_amt}{format_rate_suffix('TRX', trx_amt)}")
        print(f"USDT: {usdt_amt}{format_rate_suffix('USDT', usdt_amt)}")
        print(f"Energy: {r['energy']} | Bandwidth: {r['bandwidth']}")
        print(f"Frozen for Energy: {b['frozen_energy']} | Frozen for Bandwidth: {b['frozen_bandwidth']}")
        print(f"Статус: {'✅ Активирован' if b['activated'] else '❌ Неактивен'}")
        return

    b = wallet.get_balance()
    native = b.get("native", 0.0) or 0.0
    tokens = b.get("tokens") or {}
    err = b.get("error")
    print(f"\n{symbol}: {native}{format_rate_suffix(symbol, native)}")
    for tname, tval in tokens.items():
        suffix = format_rate_suffix(tname, tval or 0.0)
        print(f"{tname}: {tval}{suffix}")
    if err:
        print(f"⚠️ {err}")


def do_send(symbol: str, wallet) -> None:
    if symbol == "TRX":
        asset = (input("Что отправить (TRX/USDT) [TRX]: ").strip().upper() or "TRX")
        if asset not in ("TRX", "USDT"):
            print("❌ Поддерживаются только TRX и USDT.")
            return
        to = input("Адрес получателя: ").strip()
        ok, reason = utils.validate_address("TRX", to)
        if not ok:
            print(f"❌ {reason}")
            return
        try:
            amt = float(input(f"Сумма {asset}: "))
        except ValueError:
            print("❌ Некорректная сумма.")
            return
        if asset == "USDT":
            print(wallet.send_usdt(to, amt))
        else:
            print(wallet.send_trx(to, amt))
        return

    to = input("Адрес получателя: ").strip()
    ok, reason = utils.validate_address(symbol, to)
    if not ok:
        print(f"❌ {reason}")
        return
    try:
        amt = float(input(f"Сумма {symbol}: "))
    except ValueError:
        print("❌ Некорректная сумма.")
        return
    print(wallet.send(to, amt))


def show_history(symbol: str, wallet) -> None:
    items = history.fetch_history(symbol, wallet.address, limit=20)
    print()
    print(history.format_history(items))


def show_all_rates() -> None:
    data = rates.get_all_rates(NETWORKS + ["USDT"])
    headers = ("Монета", "USD", "RUB", "Источник")
    rows = []
    for sym in NETWORKS + ["USDT"]:
        info = data.get(sym) or {}
        usd = info.get("usd")
        rub = info.get("rub")
        src = info.get("source") or "—"
        rows.append((
            sym,
            f"{usd:,.4f}" if usd is not None else "—",
            f"{rub:,.4f}" if rub is not None else "—",
            src,
        ))
    widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(4)]
    sep = " | "
    print()
    print(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(sep.join(r[i].ljust(widths[i]) for i in range(4)))


def show_volatility(symbol: str) -> None:
    rpt = volatility.get_volatility_report(symbol)
    print(f"\n=== Волатильность {symbol} ===")
    label_map = {"30d": "30 дней", "90d": "3 мес", "180d": "6 мес"}
    for key, label in label_map.items():
        v = rpt.get(key)
        if not v:
            print(f"{label}: данных нет")
            continue
        print(
            f"{label}: σ={v['stddev_pct']:.2f}% | "
            f"Δ={v['change_pct']:+.2f}% | "
            f"min=${v['min']:.4f} max=${v['max']:.4f} | "
            f"текущая=${v['current']:.4f}"
        )


def choose_network() -> str | None:
    print("\nДоступные сети:")
    for i, sym in enumerate(NETWORKS, 1):
        print(f"  {i}. {sym}")
    raw = input("Номер сети (0 — отмена): ").strip()
    if raw in ("0", ""):
        return None
    try:
        idx = int(raw)
    except ValueError:
        print("❌ Некорректный номер.")
        return None
    if not (1 <= idx <= len(NETWORKS)):
        print("❌ Номер вне диапазона.")
        return None
    return NETWORKS[idx - 1]


# === CLI ===
def main_menu():
    utils.print_startup_banner()
    # XMR: поднимаем monero-wallet-rpc (если настроен в .env) — баланс/история/отправка.
    monero_daemon.ensure_monero_rpc()

    wallet = None
    symbol = None

    while True:
        print("\n==================================================")
        print(" Cripto Wallet — мультисетевой CLI")
        print("==================================================")
        if wallet is not None and symbol:
            print(f"Активный кошелёк: {symbol}  {short_addr(wallet.address)}")
        else:
            print("Активный кошелёк: (не выбран)")
        print("\n 1. Выбрать сеть (BTC/LTC/ETH/BSC/SOL/TON/TRX/XMR)")
        print(" 2. Создать новый кошелёк")
        print(" 3. Импортировать кошелёк (private key hex)")
        print(" 4. Сохранить кошелёк в JSON (с выбором пути)")
        print(" 5. Загрузить кошелёк из JSON")
        print(" 6. Балансы (native + USDT для EVM/TRX, + USD/RUB)")
        print(" 7. Отправить (с валидацией адреса)")
        print(" 8. История транзакций (последние 20)")
        print(" 9. Курсы всех монет (USD/RUB)")
        print("10. Волатильность активной монеты (30д/3м/6м)")
        print("11. [TRON] Заморозка/разморозка V1 (legacy)")
        print("12. [TRON] Stake V2 / Withdraw (legacy)")
        print("13. [TRON] Диагностика заморозок (legacy)")
        print(" 0. Выход")
        try:
            choice = input("> ").strip()
        except EOFError:
            print("\nВыход (EOF).")
            return

        if choice == "0":
            print("Выход...")
            return

        if choice == "1":
            sym = choose_network()
            if sym:
                symbol = sym
                wallet = None
                print(f"✅ Активная сеть: {symbol} (кошелёк не загружен)")

        elif choice == "2":
            if not symbol:
                print("❌ Сначала выберите сеть (пункт 1).")
                continue
            try:
                cls = WALLETS_CLS[symbol]
                wallet = cls()
                print(f"\n✅ Кошелёк создан: {wallet.address}")
                print(f"🔑 Приватный ключ: {get_priv_hex(wallet)}")
                print("⚠️ Сохрани его безопасно!")
            except Exception as e:
                print(f"❌ Ошибка создания: {e}")

        elif choice == "3":
            if not symbol:
                print("❌ Сначала выберите сеть (пункт 1).")
                continue
            key = input("Введите приватный ключ (hex): ").strip()
            try:
                cls = WALLETS_CLS[symbol]
                wallet = cls(private_key=key)
                print(f"\n✅ Импорт успешно. Адрес: {wallet.address}")
            except Exception as e:
                print(f"❌ Ошибка импорта: {e}")

        elif choice == "4":
            if wallet is None or not symbol:
                print("❌ Кошелёк не загружен.")
                continue
            try:
                path = utils.choose_json_path(f"{symbol.lower()}_wallet.json")
                save_wallet_json(wallet, symbol, path)
                print(f"\n💾 Кошелёк сохранён в: {path}")
            except Exception as e:
                print(f"❌ Ошибка сохранения: {e}")

        elif choice == "5":
            path = input("Путь к JSON: ").strip()
            if not path:
                print("❌ Пустой путь.")
                continue
            if not os.path.isfile(path):
                print(f"❌ Файл не найден: {path}")
                continue
            try:
                symbol, wallet = load_wallet_json(path)
                print(f"\n✅ Загружено: {symbol}  {wallet.address}")
            except Exception as e:
                print(f"❌ Ошибка загрузки: {e}")

        elif choice == "6":
            if wallet is None or not symbol:
                print("❌ Кошелёк не загружен.")
                continue
            show_balances(symbol, wallet)

        elif choice == "7":
            if wallet is None or not symbol:
                print("❌ Кошелёк не загружен.")
                continue
            do_send(symbol, wallet)

        elif choice == "8":
            if wallet is None or not symbol:
                print("❌ Кошелёк не загружен.")
                continue
            show_history(symbol, wallet)

        elif choice == "9":
            show_all_rates()

        elif choice == "10":
            if not symbol:
                print("❌ Сначала выберите сеть (пункт 1).")
                continue
            show_volatility(symbol)

        elif choice == "11":
            if symbol != "TRX" or wallet is None:
                print("❌ Доступно только для активного TRX-кошелька.")
                continue
            sub = input("1 — заморозить, 2 — разморозить: ").strip()
            if sub == "1":
                try:
                    amount = float(input("Сколько TRX заморозить (V1): "))
                    resource = (input("Ресурс (ENERGY/BANDWIDTH) [ENERGY]: ").strip().upper() or "ENERGY")
                    if resource not in ("ENERGY", "BANDWIDTH"):
                        print("❌ Ресурс должен быть ENERGY или BANDWIDTH.")
                        continue
                    print(wallet.freeze_trx_v1(amount, resource))
                except ValueError:
                    print("❌ Некорректная сумма.")
            elif sub == "2":
                resource = (input("Ресурс (ENERGY/BANDWIDTH) [ENERGY]: ").strip().upper() or "ENERGY")
                if resource not in ("ENERGY", "BANDWIDTH"):
                    print("❌ Ресурс должен быть ENERGY или BANDWIDTH.")
                    continue
                print(wallet.unfreeze_trx_v1(resource))
            else:
                print("❌ Неверный выбор.")

        elif choice == "12":
            if symbol != "TRX" or wallet is None:
                print("❌ Доступно только для активного TRX-кошелька.")
                continue
            sub = input("1 — Stake V2 unfreeze, 2 — Withdraw зрелых: ").strip()
            if sub == "1":
                try:
                    amount = float(input("Сколько TRX разморозить (V2): "))
                    resource = (input("Ресурс (ENERGY/BANDWIDTH) [ENERGY]: ").strip().upper() or "ENERGY")
                    print(wallet.unfreeze_trx_v2_http(amount, resource))
                except ValueError:
                    print("❌ Некорректная сумма.")
            elif sub == "2":
                print(wallet.withdraw_unfreeze_v2_http())
            else:
                print("❌ Неверный выбор.")

        elif choice == "13":
            if symbol != "TRX" or wallet is None:
                print("❌ Доступно только для активного TRX-кошелька.")
                continue
            wallet.debug_freeze_info()

        else:
            print("❌ Неверный выбор.")


if __name__ == "__main__":
    main_menu()

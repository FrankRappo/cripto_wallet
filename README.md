# Cripto Wallet

Мультивалютный CLI-кошелёк: BTC, LTC, ETH, BSC, SOL, TON, TRON (USDT-TRC20), Monero.

## Возможности
- Создание / импорт кошельков
- Просмотр балансов в native, USD и RUB (CoinGecko, MOEX fallback)
- Отправка с валидацией адреса
- История транзакций
- Волатильность 30д / 3м / 6м
- TRON: заморозка/разморозка Stake V1 и V2, диагностика
- IP-проверка при запуске
- Сохранение/загрузка JSON-кошельков (произвольный путь)

Кроссплатформенный: один и тот же код работает на **Linux/macOS и Windows**.

## Запуск

### Linux / macOS
```bash
./setup.sh        # создаст .venv, поставит зависимости, сделает .env из .env.example
# впишите свои API-ключи в .env (по желанию — без ключей работает большинство сетей)
./run.sh          # запуск кошелька
```

### Windows
Нужен Python 3.10+ ([python.org](https://python.org), при установке отметьте «Add Python to PATH»).
Двойной клик по `setup.bat`, затем по `run.bat` — или из cmd/PowerShell:
```bat
setup.bat
run.bat
```

### Вручную (любая ОС)
```bash
pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
python final_skript.py
```

## API-ключи
- `ETHERSCAN_API_KEY` (ETH — только история; регистрация по email, без телефона)
- `HELIUS_API_KEY` (SOL, опционально — баланс/история работают и без него)
- `TONCENTER_API_KEY` (TON — нужен для отправки)
- `BSCSCAN_API_KEY` (BSC, опционально)
- `TRONGRID_API_KEY` (TRX)
- `ETH_RPC`, `SOL_RPC` (опционально — свои узлы; по умолчанию публичные PublicNode)

ETH (баланс/отправка) и SOL (баланс/отправка/история) работают **без ключей**
через публичные RPC. Helius для SOL — лишь опциональный ускоритель.
BTC, LTC, CoinGecko, MOEX — без ключей.

## Monero
Баланс/история/отправка требуют локального `monero-wallet-rpc` — `final_skript.py`
**автоматически поднимает его на старте** (если настроены `MONERO_*` в `.env`):
- бинарь — официальный CLI-bundle с getmonero.org, качается под вашу ОС:
  - Linux/macOS: `./scripts/get_monero.sh` → `vendor/monero/monero-wallet-rpc`
  - Windows: `powershell -ExecutionPolicy Bypass -File scripts\get_monero.ps1` → `vendor\monero\monero-wallet-rpc.exe`
- кошелёк — `.monero/<MONERO_WALLET_NAME>` (создаётся отдельно, см. `.env.example`);
- нода — удалённая публичная (`MONERO_DAEMON_ADDR`), полную цепочку качать не нужно.

Демон работает как сервис (переживает выход CLI); повторный запуск его переиспользует.
Запуск процесса кроссплатформенный (POSIX `start_new_session` / Windows `DETACHED_PROCESS`);
на Windows путь к бинарю можно указывать без `.exe` — он подставится автоматически.
Без `MONERO_*` Monero остаётся в режиме «только генерация адресов».
Каталоги `vendor/` и `.monero/` в git не коммитятся (см. `.gitignore`) — бинарь у каждого свой под ОС.

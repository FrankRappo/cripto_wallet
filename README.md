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
📄 Подробная инструкция и решение типичных проблем — в **[README_WINDOWS.md](README_WINDOWS.md)**
(путь только латиницей, нюансы Monero/Defender).

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
- `TRONGRID_API_KEY` (TRX — опционально; без ключа TronGrid работает на пониженных лимитах)
- `ETH_RPC`, `SOL_RPC` (опционально — свои узлы; по умолчанию публичные PublicNode)

Все ключи читаются из `.env` (в код не хардкодятся). Файл `.env` в git не коммитится.

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

### Monero на Windows — два важных нюанса
1. **Путь к проекту только латиницей** (`C:\cripto\...`, не `C:\крипто\...`). `monero-wallet-rpc`
   на Windows не открывает файлы кошелька по не-ASCII (кириллическому) пути — падает с
   `system:3 / "opened by another wallet program"`. Остальные сети работают на любом пути.
2. **Windows Defender удаляет `monero-wallet-rpc.exe`** (ложноположительное срабатывание
   на Monero-бинари). Добавьте папку в исключения — в PowerShell **от администратора**:
   ```powershell
   Add-MpPreference -ExclusionPath 'C:\cripto'
   ```
   затем верните бинарь: `powershell -ExecutionPolicy Bypass -File scripts\get_monero.ps1`.

Пароль кошелька на Windows передаётся `monero-wallet-rpc` аргументом `--password` (на POSIX —
через файл `0600`): узкочарный ридер password-файла на Windows тоже спотыкается на не-ASCII путях.

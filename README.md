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

## Запуск
```bash
pip install -r requirements.txt
cp .env.example .env  # вписать свои API-ключи
python3 final_skript.py
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
- бинарь — `vendor/monero/monero-wallet-rpc` (CLI-bundle с getmonero.org);
- кошелёк — `.monero/<MONERO_WALLET_NAME>` (создаётся отдельно, см. `.env.example`);
- нода — удалённая публичная (`MONERO_DAEMON_ADDR`), полную цепочку качать не нужно.

Демон работает как сервис (переживает выход CLI); повторный запуск его переиспользует.
Без `MONERO_*` Monero остаётся в режиме «только генерация адресов».
Каталоги `vendor/` и `.monero/` в git не коммитятся (см. `.gitignore`).

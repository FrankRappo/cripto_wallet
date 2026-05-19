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
- `ALCHEMY_API_KEY` (ETH)
- `HELIUS_API_KEY` (SOL)
- `TONCENTER_API_KEY` (TON)
- `BSCSCAN_API_KEY` (BSC, опционально)
- `TRONGRID_API_KEY` (TRX)

BTC, LTC, Monero, CoinGecko, MOEX — без ключей.

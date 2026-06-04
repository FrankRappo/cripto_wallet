# Cripto Wallet — запуск на Windows

Практическая инструкция для Windows 10/11. Тот же код, что и на Linux, — отличается
только запуск и пара нюансов с Monero.

## Что нужно
- **Windows 10/11**
- **Python 3.10+** — [python.org](https://python.org), при установке отметь галочку
  **«Add Python to PATH»**. Проверка: в cmd `py -3 --version`.
- **Папка проекта — только латиницей**, например `C:\cripto\multi`
  (без кириллицы и желательно без пробелов). Это критично для Monero — см. ниже.

## Быстрый старт
1. Положи проект в латинский путь, например `C:\cripto\multi`
   (или `git clone https://github.com/FrankRappo/cripto_wallet.git`).
2. Двойной клик по **`setup.bat`** — создаст `.venv` и поставит зависимости (1–3 мин).
3. (по желанию) впиши свои API-ключи в **`.env`** — большинство сетей работает и без них.
4. Двойной клик по **`run.bat`** — запуск кошелька.

Дальше при каждом запуске — только **`run.bat`**.

## Monero (XMR) — отдельные шаги
XMR требует локального `monero-wallet-rpc.exe`. Без него работают остальные 7 сетей
(BTC/LTC/ETH/BSC/SOL/TON/TRX), а XMR — только генерация адреса.

1. Скачать бинарь:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\get_monero.ps1
   ```
2. **Windows Defender удалит этот .exe** (ложное срабатывание на Monero-бинари).
   Добавь папку в исключения — PowerShell **от имени администратора**:
   ```powershell
   Add-MpPreference -ExclusionPath 'C:\cripto'
   ```
   после этого повтори шаг 1, если exe уже был удалён.
3. Заполни `MONERO_*` в `.env` (пути латиницей, примеры — в `.env.example`).
4. Запускай `run.bat` — демон поднимется сам и переиспользуется между запусками.

## Где что лежит (в git не попадает — личное)
- `.env` — твои API-ключи и пароль Monero.
- `.monero\` — кошелёк Monero (ключи). **Беречь, не публиковать.**
- `.venv\` — окружение Python (создаёт `setup.bat`).
- `vendor\monero\monero-wallet-rpc.exe` — бинарь Monero (качается скриптом).

## Меню (после `run.bat`)
1 — выбрать сеть · 2/3 — создать/импортировать кошелёк · 4/5 — сохранить/загрузить JSON ·
6 — балансы (+USD/RUB) · 7 — отправка · 8 — история · 9 — курсы · 10 — волатильность ·
11–13 — TRON-заморозки (Stake V1/V2, диагностика) · 0 — выход.

## Если что-то не работает
- **`setup.bat` мигает и закрывается / появляется файл `Обновляю`** — у `.bat` неверные
  концы строк (LF вместо CRLF). Лучше всего `git clone` (в репо есть `.gitattributes`,
  он выдаёт CRLF), либо пересохрани `.bat` в CRLF.
- **«Python не найден»** — переустанови Python с галочкой «Add Python to PATH»,
  либо проверь `py -3 --version`.
- **Monero: `system:3` / «opened by another wallet program»** — путь к проекту содержит
  кириллицу/не-ASCII. Перенеси проект в латинский путь (`C:\cripto\...`).
- **Monero: `monero-wallet-rpc.exe` исчезает** — это Defender. Добавь исключение (выше).
- **Кириллица в консоли «кракозябрами»** — приложение само включает UTF-8; при ручном
  запуске выполни `chcp 65001`.

## Запуск вручную (без `.bat`)
```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe final_skript.py
```

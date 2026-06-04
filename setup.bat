@echo off
REM Cripto Wallet -- установка под Windows. Создаёт venv, ставит зависимости, готовит .env.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM Ищем Python: сначала launcher "py -3", затем "python".
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [ОШИБКА] Python не найден. Установите Python 3.10+ с https://python.org
  echo          и отметьте "Add Python to PATH".
  exit /b 1
)

echo ==^> Python:
%PY% --version

if not exist ".venv\Scripts\python.exe" (
  echo ==^> Создаю виртуальное окружение .venv
  %PY% -m venv .venv
)

echo ==^> Обновляю pip и ставлю зависимости
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ОШИБКА] Не удалось установить зависимости.
  exit /b 1
)

if not exist ".env" (
  echo ==^> Создаю .env из .env.example (впишите свои ключи^)
  copy /Y ".env.example" ".env" >nul
)

echo.
echo [ГОТОВО] Дальше:
echo    1^) при необходимости впишите API-ключи в .env
echo    2^) для XMR-баланса/отправки: powershell -ExecutionPolicy Bypass -File scripts\get_monero.ps1
echo    3^) запуск: run.bat
endlocal

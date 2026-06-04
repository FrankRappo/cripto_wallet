@echo off
REM Cripto Wallet -- запуск под Windows.
REM Если venv ещё нет -- поднимет его через setup.bat, затем запустит кошелёк.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv" (
  echo ==^> .venv не найден -- запускаю первичную установку (setup.bat^)
  call setup.bat
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
python final_skript.py
endlocal

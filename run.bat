@echo off
REM Cripto Wallet -- запуск под Windows.
REM Если venv ещё нет -- поднимет его через setup.bat, затем запустит кошелёк.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ==^> .venv не найден -- запускаю первичную установку (setup.bat^)
  call setup.bat
  if errorlevel 1 exit /b 1
)

REM Зовём venv-питон напрямую (без activate) -- так папку можно свободно переименовать.
".venv\Scripts\python.exe" final_skript.py
endlocal

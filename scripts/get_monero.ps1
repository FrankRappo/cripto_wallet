# Скачивает официальный Monero CLI (getmonero.org) и кладёт monero-wallet-rpc.exe
# в vendor\monero\. Нужен только если хотите баланс/историю/отправку XMR.
#   Запуск:  powershell -ExecutionPolicy Bypass -File scripts\get_monero.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "vendor\monero"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$url = "https://downloads.getmonero.org/cli/win64"
$tmpZip = Join-Path $env:TEMP "monero-cli.zip"
$tmpDir = Join-Path $env:TEMP "monero-cli-extract"

Write-Host "==> Скачиваю Monero CLI: $url"
Invoke-WebRequest -Uri $url -OutFile $tmpZip

if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
Write-Host "==> Распаковываю"
Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

$rpc = Get-ChildItem -Path $tmpDir -Recurse -Filter "monero-wallet-rpc.exe" | Select-Object -First 1
if (-not $rpc) {
    Write-Error "monero-wallet-rpc.exe не найден в архиве"
    exit 1
}
Copy-Item $rpc.FullName -Destination (Join-Path $dest "monero-wallet-rpc.exe") -Force

Remove-Item -Force $tmpZip
Remove-Item -Recurse -Force $tmpDir

Write-Host "✅ Готово: $(Join-Path $dest 'monero-wallet-rpc.exe')"
Write-Host "   Пропишите путь к нему в MONERO_WALLET_RPC_BIN в .env (см. .env.example)."

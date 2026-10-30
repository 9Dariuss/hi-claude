# Desinstala Hi Claude! de Windows.
#
#   powershell -ExecutionPolicy Bypass -File desinstalar.ps1 [-Todo]
#
# -Todo borra también tu configuración (config.toml). Las conversaciones las guarda Claude Code
# en %USERPROFILE%\.claude\projects y no se tocan. El modelo de Whisper queda en
# %USERPROFILE%\.cache\huggingface (bórralo a mano si quieres recuperar ~480 MB).

param([switch]$Todo)

$AppDir = Join-Path $env:LOCALAPPDATA "hi-claude"
$Bin = Join-Path $AppDir "bin"

Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
    Where-Object { $_.CommandLine -like "*hi-claude.pyw*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$Programs = [Environment]::GetFolderPath("Programs")
$Startup = [Environment]::GetFolderPath("Startup")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Programs "Hi Claude!.lnk"), (Join-Path $Programs "Hi Claude! (recorte).lnk"), (Join-Path $Startup "Hi Claude! (atajos).lnk")

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath) {
    [Environment]::SetEnvironmentVariable("Path", (($UserPath -split ";") | Where-Object { $_ -and $_ -ne $Bin }) -join ";", "User")
}

Start-Sleep -Milliseconds 500
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $AppDir
if ($Todo) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $env:APPDATA "hi-claude") }
Write-Host "Hi Claude! se ha desinstalado." -ForegroundColor Green

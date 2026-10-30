# Instalador de Hi Claude! para Windows (no necesita permisos de administrador).
#
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-NoShortcuts] [-Destino <carpeta>]
#
# O doble clic en «Instalar Hi Claude.cmd». Se puede repetir cuando quieras: actualiza la app
# y conserva tu configuración.

param(
    [switch]$NoShortcuts,   # no crear accesos directos, atajos globales ni el comando en el PATH
    [string]$Destino = (Join-Path $env:LOCALAPPDATA "hi-claude")
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = $Destino
$Venv = Join-Path $AppDir "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Pyw = Join-Path $Venv "Scripts\pythonw.exe"
$Launcher = Join-Path $AppDir "hi-claude.pyw"
$Icon = Join-Path $AppDir "hi_claude\hi-claude.ico"

function Say($text) { Write-Host "==> $text" -ForegroundColor DarkYellow }
function Warn($text) { Write-Host "  ! $text" -ForegroundColor Yellow }

# ------------------------------------------------------------------ Python
function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "-3.14", "-3.13", "-3.12", "-3.11", "-3") {
            try { $exe = (& py $v -c "import sys; print(sys.executable)" 2>$null) } catch { $exe = $null }
            if ($exe) { $candidates += $exe.Trim() }
        }
    }
    foreach ($name in "python3", "python") {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $candidates += $cmd.Source }
    }
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:LOCALAPPDATA\Python\pythoncore-3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object FullName
    foreach ($exe in $candidates) {
        try { $ok = (& $exe -c "import sys; print(sys.version_info >= (3, 11))" 2>$null) } catch { $ok = $null }
        if ($ok -eq "True") { return $exe }
    }
    return $null
}

Say "Buscando Python 3.11 o más reciente"
$SysPy = Find-Python
if (-not $SysPy) {
    Warn "No encuentro Python 3.11+. Instálalo desde https://www.python.org/downloads/ (o con: winget install Python.Python.3.13)"
    Warn "y vuelve a ejecutar este instalador."
    exit 1
}
$SysVer = (& $SysPy -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
Write-Host "    Python $SysVer en $SysPy"

# ------------------------------------------------------------------ programa
Say "Copiando la app a $AppDir"
New-Item -ItemType Directory -Force $AppDir | Out-Null
if (Test-Path (Join-Path $AppDir "hi_claude")) { Remove-Item -Recurse -Force (Join-Path $AppDir "hi_claude") }
Copy-Item -Recurse (Join-Path $Here "hi_claude") (Join-Path $AppDir "hi_claude")
Get-ChildItem (Join-Path $AppDir "hi_claude") -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Copy-Item (Join-Path $Here "hi-claude.pyw"), (Join-Path $Here "config.example.toml") $AppDir -Force

# El entorno se rehace si cambió la versión de Python
$VenvVer = $null
if (Test-Path $Py) { try { $VenvVer = (& $Py -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null).Trim() } catch {} }
if ($VenvVer -ne $SysVer) {
    Say "Creando entorno de Python $SysVer"
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    & $SysPy -m venv $Venv
}
Say "Instalando dependencias (Claude Agent SDK, faster-whisper, pywebview, …)"
& $Py -m pip install -q --disable-pip-version-check --upgrade pip
& $Py -m pip install -q --disable-pip-version-check --upgrade -r (Join-Path $Here "requirements.txt")
if ($LASTEXITCODE -ne 0) { Warn "Falló la instalación de dependencias (mira los mensajes de arriba)"; exit 1 }
$Smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($Smi -and (& $Smi.Source -L 2>$null)) {
    Say "GPU NVIDIA detectada: instalando cuBLAS y cuDNN para Whisper (~1,2 GB la primera vez)"
    & $Py -m pip install -q --disable-pip-version-check -r (Join-Path $Here "requirements-gpu.txt")
}

# ------------------------------------------------------------------ voz
$Model = (& $Py -c "import sys; sys.path.insert(0, r'$AppDir'); from hi_claude.config import Config; print(Config.load().model)").Trim()
Say "Descargando el modelo de voz de Whisper «$Model» (~480 MB el «small»; solo la primera vez)"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
& $Py -c "from faster_whisper.utils import download_model; download_model('$Model')" 2>$null
if ($LASTEXITCODE -ne 0) { Warn "No se pudo descargar ahora; se descargará la primera vez que hables." }

# ------------------------------------------------------------------ Claude Code
$Claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $Claude) { $Claude = Join-Path $Venv "Lib\site-packages\claude_agent_sdk\_bundled\claude.exe" }
Say "Comprobando la sesión de Claude Code"
$LoggedIn = $false
try { $LoggedIn = ((& $Claude auth status 2>$null) | Out-String | ConvertFrom-Json).loggedIn } catch {}
if (-not $LoggedIn) {
    Warn "Claude Code no tiene la sesión iniciada en este usuario de Windows."
    Write-Host "    Se abrirá el navegador para iniciar sesión con tu cuenta de Claude (solo esta vez)."
    & $Claude auth login
}

# ------------------------------------------------------------------ comando, accesos directos y atajos
$Bin = Join-Path $AppDir "bin"
New-Item -ItemType Directory -Force $Bin | Out-Null
# hi-claude desde una terminal: usa python.exe para que se vean los mensajes y errores
Set-Content -Encoding ASCII (Join-Path $Bin "hi-claude.cmd") "@`"$Py`" `"$Launcher`" %*"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $NoShortcuts -and -not (($UserPath -split ";") -contains $Bin)) {
    Say "Añadiendo el comando hi-claude al PATH de tu usuario"
    [Environment]::SetEnvironmentVariable("Path", (($UserPath.TrimEnd(";"), $Bin) -join ";").TrimStart(";"), "User")
}

if (-not $NoShortcuts) {
    $Shell = New-Object -ComObject WScript.Shell
    function New-Shortcut($path, $arguments, $description) {
        $lnk = $Shell.CreateShortcut($path)
        $lnk.TargetPath = $Pyw
        $lnk.Arguments = "`"$Launcher`" $arguments".Trim()
        $lnk.WorkingDirectory = $env:USERPROFILE
        $lnk.IconLocation = "$Icon,0"
        $lnk.Description = $description
        $lnk.Save()
    }
    $Programs = [Environment]::GetFolderPath("Programs")
    $Startup = [Environment]::GetFolderPath("Startup")
    Say "Creando accesos directos en el menú Inicio"
    New-Shortcut (Join-Path $Programs "Hi Claude!.lnk") "" "Claude Code en una ventana, con voz y recortes"
    New-Shortcut (Join-Path $Programs "Hi Claude! (recorte).lnk") "--snip" "Recorta la pantalla y pregunta a Claude"

    Say "Activando los atajos globales (arrancan con Windows)"
    New-Shortcut (Join-Path $Startup "Hi Claude! (atajos).lnk") "--atajos" "Atajos de teclado de Hi Claude!"
    Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
        Where-Object { $_.CommandLine -like "*hi-claude.pyw*--atajos*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 300
    Start-Process -FilePath $Pyw -ArgumentList "`"$Launcher`" --atajos" -WorkingDirectory $env:USERPROFILE
}

Write-Host ""
Write-Host "Hi Claude! está instalado." -ForegroundColor Green
$Cfg = & $Py -c "import sys; sys.path.insert(0, r'$AppDir'); from hi_claude.config import Config; c = Config.load(); print(c.hotkey_open + '|' + c.hotkey_voice + '|' + c.hotkey_snip)"
$Keys = $Cfg.Trim() -split "\|"
Write-Host "  $($Keys[0])   abrir"
Write-Host "  $($Keys[1])   abrir y hablar"
Write-Host "  $($Keys[2])   recortar la pantalla y preguntar"
Write-Host "  También está en el menú Inicio, y como comando: hi-claude (en una terminal nueva)."

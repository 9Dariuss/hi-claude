@echo off
rem Doble clic para instalar (o actualizar) Hi Claude! en este usuario de Windows.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause

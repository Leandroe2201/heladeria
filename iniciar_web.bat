@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
    echo.
    echo ERROR: Primero ejecute instalar_dependencias.bat
    echo.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
for /f %%i in ('python -c "from app.database import init_database; init_database(); from app.settings_service import get_setting; print(get_setting('web_port','5050'))"') do set WEBPORT=%%i
echo.
echo ==============================================
echo       PANEL WEB - HELADERIA
echo ==============================================
echo En esta PC: http://127.0.0.1:%WEBPORT%
echo PIN inicial: 2580
    echo.
echo Para abrir desde el celular use mejor:
echo Opciones ^> Panel Web / Control remoto
echo porque el sistema muestra automaticamente la IP de red.
echo.
echo NO CIERRE ESTA VENTANA mientras use el Panel Web.
echo ==============================================
echo.
python -u -m app.web_server
if errorlevel 1 (
    echo.
    echo El servidor termino con un error.
    pause
)

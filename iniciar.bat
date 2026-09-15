@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
    echo Primero ejecute instalar_dependencias.bat
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python main.py
if errorlevel 1 pause

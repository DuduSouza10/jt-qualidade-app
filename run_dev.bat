@echo off
title JMS Coletor Waybill - DEV
cd /d "%~dp0"

echo.
echo Instalando/validando dependencias...
python -m pip install -r requirements.txt

echo.
echo Iniciando sistema...
python app.py

pause
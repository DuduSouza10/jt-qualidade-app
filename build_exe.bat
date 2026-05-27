@echo off
title Gerar EXE - JMS Coletor Waybill
cd /d "%~dp0"

echo.
echo Atualizando pip...
python -m pip install --upgrade pip

echo.
echo Instalando dependencias...
python -m pip install -r requirements.txt

echo.
echo Garantindo PyInstaller e Selenium atualizados...
python -m pip install --upgrade pyinstaller selenium

echo.
echo Limpando builds antigas...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo.
echo Gerando Atualizador.exe separado...
python -m PyInstaller ^
  --onefile ^
  --noconsole ^
  --clean ^
  --name "Atualizador" ^
  updater.py

if errorlevel 1 (
  echo.
  echo ERRO ao gerar Atualizador.exe.
  pause
  exit /b 1
)

echo.
echo Gerando EXE principal...
python -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "Verificacao_IDs_JT_Express" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --collect-all webview ^
  --collect-all selenium ^
  --hidden-import selenium.webdriver.chrome.webdriver ^
  --hidden-import selenium.webdriver.chrome.service ^
  --hidden-import selenium.webdriver.chrome.options ^
  --hidden-import selenium.webdriver.chromium.webdriver ^
  --hidden-import selenium.webdriver.chromium.service ^
  --hidden-import selenium.webdriver.chromium.options ^
  --hidden-import selenium.webdriver.common.by ^
  --hidden-import selenium.webdriver.common.keys ^
  --hidden-import selenium.webdriver.support.ui ^
  --hidden-import selenium.webdriver.support.expected_conditions ^
  app.py

if errorlevel 1 (
  echo.
  echo ERRO ao gerar EXE principal.
  pause
  exit /b 1
)

set APP_DIST=dist\Verificacao_IDs_JT_Express

copy /y "dist\Atualizador.exe" "%APP_DIST%\Atualizador.exe" >nul
copy /y "version.json" "%APP_DIST%\version.json" >nul
copy /y "update_config.json" "%APP_DIST%\update_config.json" >nul

echo.
echo Finalizado.
echo O EXE vai estar em:
echo %cd%\%APP_DIST%\Verificacao_IDs_JT_Express.exe
echo.
pause

@echo off
title Gerar EXE - JMS Coletor Waybill
cd /d "%~dp0"

set "APP_FOLDER_NAME=JMS_Coletor_Waybill"
set "APP_EXE_BASENAME=Verificacao_IDs_JT_Express"
set "APP_EXE_NAME=%APP_EXE_BASENAME%.exe"
set "RAW_DIST=dist\%APP_EXE_BASENAME%"
set "APP_DIST=dist\%APP_FOLDER_NAME%"

echo.
echo ============================================================
echo GERAR EXE - JMS COLETOR WAYBILL
echo Pasta principal: %APP_FOLDER_NAME%
echo EXE principal: %APP_EXE_NAME%
echo ============================================================
echo.

echo.
echo Atualizando pip...
python -m pip install --upgrade pip

if errorlevel 1 (
  echo.
  echo ERRO ao atualizar pip.
  pause
  exit /b 1
)

echo.
echo Instalando dependencias...
python -m pip install -r requirements.txt

if errorlevel 1 (
  echo.
  echo ERRO ao instalar dependencias.
  pause
  exit /b 1
)

echo.
echo Garantindo PyInstaller e Selenium atualizados...
python -m pip install --upgrade pyinstaller selenium

if errorlevel 1 (
  echo.
  echo ERRO ao instalar/atualizar PyInstaller/Selenium.
  pause
  exit /b 1
)

echo.
echo Fechando processos antigos, se estiverem abertos...
taskkill /F /IM "%APP_EXE_NAME%" >nul 2>nul
taskkill /F /IM "Atualizador.exe" >nul 2>nul
timeout /t 2 /nobreak >nul

echo.
echo Limpando builds antigas...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

if exist "dist" (
  echo.
  echo ERRO: Nao consegui apagar a pasta dist.
  echo Feche o app, o Atualizador, Chrome, Explorer aberto na pasta dist e tente novamente.
  pause
  exit /b 1
)

if exist "build" (
  echo.
  echo ERRO: Nao consegui apagar a pasta build.
  pause
  exit /b 1
)

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

if not exist "dist\Atualizador.exe" (
  echo.
  echo ERRO: dist\Atualizador.exe nao foi encontrado.
  pause
  exit /b 1
)

echo.
echo Gerando EXE principal...
python -m PyInstaller ^
  --onedir ^
  --noconsole ^
  --clean ^
  --name "%APP_EXE_BASENAME%" ^
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

if not exist "%RAW_DIST%\%APP_EXE_NAME%" (
  echo.
  echo ERRO: EXE principal nao encontrado em %RAW_DIST%.
  pause
  exit /b 1
)

echo.
echo Renomeando pasta principal do build para %APP_FOLDER_NAME%...
if exist "%APP_DIST%" rmdir /s /q "%APP_DIST%" 2>nul
ren "%RAW_DIST%" "%APP_FOLDER_NAME%"

if not exist "%APP_DIST%\%APP_EXE_NAME%" (
  echo.
  echo ERRO: Nao consegui preparar a pasta final em %APP_DIST%.
  pause
  exit /b 1
)

echo.
echo Copiando arquivos de atualizacao para a pasta final...
copy /y "dist\Atualizador.exe" "%APP_DIST%\Atualizador.exe" >nul
copy /y "version.json" "%APP_DIST%\version.json" >nul
copy /y "update_config.json" "%APP_DIST%\update_config.json" >nul

echo.
echo Copiando templates e static atualizados ao lado do EXE...
echo Isso garante que HTML/CSS/JS novos, incluindo animacoes, estejam disponiveis no EXE.
rmdir /s /q "%APP_DIST%\templates" 2>nul
rmdir /s /q "%APP_DIST%\static" 2>nul

robocopy "templates" "%APP_DIST%\templates" /MIR /R:5 /W:2 /NFL /NDL /NJH /NJS /NP
set "ROBO_TEMPLATES=%ERRORLEVEL%"
if %ROBO_TEMPLATES% GEQ 8 (
  echo.
  echo ERRO ao copiar templates para a pasta final.
  echo Codigo Robocopy: %ROBO_TEMPLATES%
  pause
  exit /b 1
)

robocopy "static" "%APP_DIST%\static" /MIR /R:5 /W:2 /NFL /NDL /NJH /NJS /NP
set "ROBO_STATIC=%ERRORLEVEL%"
if %ROBO_STATIC% GEQ 8 (
  echo.
  echo ERRO ao copiar static para a pasta final.
  echo Codigo Robocopy: %ROBO_STATIC%
  pause
  exit /b 1
)

if not exist "%APP_DIST%\templates\index.html" (
  echo.
  echo ERRO: templates\index.html nao foi copiado.
  pause
  exit /b 1
)

if not exist "%APP_DIST%\static\css\style.css" (
  echo.
  echo ERRO: static\css\style.css nao foi copiado.
  pause
  exit /b 1
)

if not exist "%APP_DIST%\static\js\script.js" (
  echo.
  echo ERRO: static\js\script.js nao foi copiado.
  pause
  exit /b 1
)

echo.
echo Finalizado.
echo O EXE vai estar em:
echo %cd%\%APP_DIST%\%APP_EXE_NAME%
echo.
echo Estrutura final:
echo %APP_DIST%
echo   %APP_EXE_NAME%
echo   templates\
echo   static\
echo.
pause

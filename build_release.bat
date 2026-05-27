@echo off
setlocal enabledelayedexpansion
title Build Release - JMS Coletor Waybill
cd /d "%~dp0"

echo.
echo ============================================================
echo BUILD DE RELEASE - JMS COLETOR WAYBILL
echo ============================================================
echo.

set /p APP_VERSION=Digite a versao da release. Exemplo 1.0.1: 

if "%APP_VERSION%"=="" (
  echo Versao nao informada.
  pause
  exit /b 1
)

echo.
echo Fechando processos antigos do sistema, se estiverem abertos...
taskkill /F /IM "Verificacao_IDs_JT_Express.exe" >nul 2>nul
taskkill /F /IM "Atualizador.exe" >nul 2>nul
timeout /t 2 /nobreak >nul

echo.
echo Atualizando version.json e app.py para v%APP_VERSION%...
python set_version.py %APP_VERSION%

if errorlevel 1 (
  echo.
  echo ERRO ao atualizar versao.
  pause
  exit /b 1
)

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
echo Garantindo PyInstaller atualizado...
python -m pip install --upgrade pyinstaller

if errorlevel 1 (
  echo.
  echo ERRO ao instalar/atualizar PyInstaller.
  pause
  exit /b 1
)

echo.
echo Limpando builds antigas...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
rmdir /s /q release_staging 2>nul
if not exist release mkdir release

if exist "dist" (
  echo.
  echo ERRO: Nao consegui apagar a pasta dist.
  echo Feche o app, o Atualizador, janelas do Explorer dentro da pasta dist e tente de novo.
  pause
  exit /b 1
)

if exist "build" (
  echo.
  echo ERRO: Nao consegui apagar a pasta build.
  echo Feche qualquer processo usando a pasta e tente de novo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo Gerando Atualizador.exe separado...
echo ============================================================
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
echo ============================================================
echo Gerando EXE principal...
echo ============================================================
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

set "APP_DIST=dist\Verificacao_IDs_JT_Express"

if not exist "%APP_DIST%\Verificacao_IDs_JT_Express.exe" (
  echo.
  echo ERRO: EXE principal nao encontrado em %APP_DIST%.
  pause
  exit /b 1
)

echo.
echo Copiando arquivos de atualizacao para a pasta final...
copy /y "dist\Atualizador.exe" "%APP_DIST%\Atualizador.exe" >nul
copy /y "version.json" "%APP_DIST%\version.json" >nul
copy /y "update_config.json" "%APP_DIST%\update_config.json" >nul
copy /y "README_ATUALIZACAO.md" "%APP_DIST%\README_ATUALIZACAO.md" >nul

if not exist "%APP_DIST%\Atualizador.exe" (
  echo.
  echo ERRO: Atualizador.exe nao foi copiado para a pasta final.
  pause
  exit /b 1
)

echo.
echo Aguardando o Windows/antivirus liberar os arquivos gerados...
timeout /t 4 /nobreak >nul

echo.
echo Criando pasta temporaria para compactacao...
set "STAGE_ROOT=release_staging"
set "STAGE_DIR=%STAGE_ROOT%\Verificacao_IDs_JT_Express"
rmdir /s /q "%STAGE_ROOT%" 2>nul
mkdir "%STAGE_DIR%"

echo.
echo Copiando build para a pasta temporaria com retentativas...
robocopy "%APP_DIST%" "%STAGE_DIR%" /MIR /R:12 /W:3 /NFL /NDL /NJH /NJS /NP
set "ROBO_RC=%ERRORLEVEL%"

if %ROBO_RC% GEQ 8 (
  echo.
  echo ERRO: Nao consegui copiar os arquivos para compactar.
  echo Algum arquivo ainda esta em uso. Feche o app, Chrome, Explorer e tente novamente.
  echo Codigo Robocopy: %ROBO_RC%
  pause
  exit /b 1
)

echo.
echo Criando ZIP da release...
set "ZIP_NAME=Verificacao_IDs_JT_Express-v%APP_VERSION%.zip"
set "ZIP_PATH=release\%ZIP_NAME%"
if exist "%ZIP_PATH%" del /f /q "%ZIP_PATH%" >nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; $src=(Resolve-Path 'release_staging\Verificacao_IDs_JT_Express').Path; $dest=(Join-Path (Resolve-Path 'release').Path '%ZIP_NAME%'); if(Test-Path $dest){Remove-Item $dest -Force}; for($i=1; $i -le 8; $i++){ try { [System.IO.Compression.ZipFile]::CreateFromDirectory($src, $dest, [System.IO.Compression.CompressionLevel]::Optimal, $true); exit 0 } catch { Write-Host ('Tentativa ' + $i + ' falhou: ' + $_.Exception.Message); Start-Sleep -Seconds 2 } }; exit 1"

if errorlevel 1 (
  echo.
  echo ERRO ao compactar ZIP da release.
  echo Dica: feche o app, o Chrome, o Explorer na pasta dist e tente rodar o build como Administrador.
  pause
  exit /b 1
)

rmdir /s /q "%STAGE_ROOT%" 2>nul

echo.
echo ============================================================
echo RELEASE GERADA COM SUCESSO
echo ============================================================
echo.
echo Arquivo para subir no GitHub Releases:
echo %cd%\%ZIP_PATH%
echo.
echo Pasta do app para teste local:
echo %cd%\%APP_DIST%
echo.
pause

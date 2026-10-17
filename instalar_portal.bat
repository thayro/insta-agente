@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo   STUDIOLAB - INSTALANDO PORTAL + INTEGRACOES
echo ============================================================
echo.

echo [1/3] Preparando instalacao isolada do StudioLab...

echo [1/3] Criando ambiente virtual isolado do portal...
if not exist ".venv_portal\Scripts\python.exe" (
  python -m venv .venv_portal
  if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao criar .venv_portal.
    pause
    exit /b 1
  )
) else (
  echo Ambiente .venv_portal ja existe.
)

echo.
echo [2/3] Atualizando pip do ambiente do portal...
".venv_portal\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 (
  echo.
  echo [ERRO] Falha ao atualizar o pip do portal.
  pause
  exit /b 1
)

echo.
echo [3/3] Instalando dependencias do portal no ambiente isolado...
".venv_portal\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements_portal.txt
if errorlevel 1 (
  echo.
  echo [ERRO] Falha ao instalar as dependencias do portal.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo [OK] STUDIOLAB INSTALADO COM AMBIENTE ISOLADO
echo ============================================================
echo.
echo Portal: .venv_portal
echo Dependencias instaladas somente no ambiente isolado.
echo.
echo Agora execute iniciar_portal.bat
echo O inicializador tentara subir Ollama e ComfyUI CPU automaticamente.
echo Telegram e Instagram serao configurados dentro do portal.
pause
endlocal

@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem UTF-8 para console, Python e processos filhos.
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8:replace"
set "PYTHONLEGACYWINDOWSSTDIO=0"
set "PYTHONUNBUFFERED=1"

set "LOG_DIR=%CD%\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

del /q "%LOG_DIR%\portal.pid" "%LOG_DIR%\comfyui.pid" "%LOG_DIR%\ollama.pid" >nul 2>&1

cls
echo ============================================================
echo   STUDIOLAB - AMBIENTE LOCAL
echo ============================================================
echo   Portal : http://127.0.0.1:5005/
echo   ComfyUI: http://127.0.0.1:8188/
echo   Ollama : http://127.0.0.1:11434/
echo   Social : Telegram + Instagram
echo ============================================================
echo.
echo Uma unica janela controla o ambiente.
echo Os servicos rodam em segundo plano e nao recebem o teclado.
echo Logs detalhados: %LOG_DIR%
echo.

if not exist ".venv_portal\Scripts\python.exe" (
  echo [ERRO] Ambiente virtual do StudioLab nao encontrado.
  echo Execute primeiro: instalar_portal.bat
  echo.
  pause
  exit /b 1
)

rem ============================================================
rem 1. OLLAMA
rem ============================================================
echo [1/4] Verificando Ollama...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:11434/api/tags'; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; exit 1" >nul 2>&1

if errorlevel 1 (
  where ollama >nul 2>&1
  if errorlevel 1 (
    echo [AVISO] Ollama nao encontrado no PATH.
  ) else (
    echo       Iniciando Ollama em segundo plano...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%LOG_DIR%\ollama.log' -RedirectStandardError '%LOG_DIR%\ollama_error.log'; Set-Content -LiteralPath '%LOG_DIR%\ollama.pid' -Value $p.Id" >nul 2>&1
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(40); do { try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:11434/api/tags'; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 800 } while ((Get-Date) -lt $deadline); exit 1" >nul 2>&1
    if errorlevel 1 (
      echo [AVISO] Ollama ainda nao respondeu. Consulte logs\ollama_error.log
    ) else (
      echo [OK] Ollama ativo.
    )
  )
) else (
  echo [OK] Ollama ja estava ativo.
)

echo.

rem ============================================================
rem 2. COMFYUI
rem ============================================================
echo [2/4] Verificando ComfyUI...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8188/system_stats'; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; exit 1" >nul 2>&1

if errorlevel 1 (
  where comfy >nul 2>&1
  if errorlevel 1 (
    echo [AVISO] O comando comfy nao foi encontrado no PATH.
  ) else (
    echo       Iniciando ComfyUI em CPU, em segundo plano...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath 'comfy' -ArgumentList @('launch','--','--cpu') -WindowStyle Hidden -PassThru -RedirectStandardOutput '%LOG_DIR%\comfyui.log' -RedirectStandardError '%LOG_DIR%\comfyui_error.log'; Set-Content -LiteralPath '%LOG_DIR%\comfyui.pid' -Value $p.Id" >nul 2>&1
    echo       Aguardando ComfyUI responder...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(150); do { try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:8188/system_stats'; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1" >nul 2>&1
    if errorlevel 1 (
      echo [AVISO] ComfyUI ainda nao respondeu. Consulte logs\comfyui_error.log
    ) else (
      echo [OK] ComfyUI ativo.
    )
  )
) else (
  echo [OK] ComfyUI ja estava ativo.
)

echo.

rem ============================================================
rem 3. AMBIENTE PORTAL
rem ============================================================
echo [3/4] Verificando ambiente StudioLab...
".venv_portal\Scripts\python.exe" -c "import flask, ollama, PIL, requests, instagrapi" >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Dependencias do portal incompletas.
  echo Execute novamente: instalar_portal.bat
  echo.
  pause
  goto :ENCERRAR_INICIADOS
)
echo [OK] Ambiente StudioLab pronto.

echo.

rem ============================================================
rem 4. PORTAL - SEMPRE REINICIA PARA CARREGAR A VERSAO ATUAL
rem ============================================================
echo [4/4] Reiniciando StudioLab...
echo       Encerrando instancia antiga da porta 5005, se existir...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ids=@(Get-NetTCPConnection -LocalPort 5005 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach($processId in $ids){ if($processId -and $processId -ne 0){ try { Stop-Process -Id $processId -Force -ErrorAction Stop } catch {} } }" >nul 2>&1
timeout /t 1 /nobreak >nul

del /q "%LOG_DIR%\portal.pid" >nul 2>&1

echo       Iniciando portal atualizado em segundo plano...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8:replace'; $env:PYTHONUNBUFFERED='1'; $p=Start-Process -FilePath '%CD%\.venv_portal\Scripts\python.exe' -ArgumentList 'app.py' -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru -RedirectStandardOutput '%LOG_DIR%\portal.log' -RedirectStandardError '%LOG_DIR%\portal_error.log'; Set-Content -LiteralPath '%LOG_DIR%\portal.pid' -Value $p.Id" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(35); do { try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:5005/api/status'; if ($r.StatusCode -ge 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 800 } while ((Get-Date) -lt $deadline); exit 1" >nul 2>&1
if errorlevel 1 (
  echo [ERRO] StudioLab nao respondeu. Consulte logs\portal_error.log
) else (
  echo [OK] StudioLab atualizado e ativo.
)

echo.
echo ------------------------------------------------------------
echo   STUDIOLAB ONLINE
echo ------------------------------------------------------------
echo   Portal : http://127.0.0.1:5005/
echo   ComfyUI: http://127.0.0.1:8188/
echo   Ollama : http://127.0.0.1:11434/
echo ------------------------------------------------------------
echo.
echo O console fica limpo; polling HTTP nao e exibido aqui.
echo Para encerrar, use a opcao abaixo. Nao use Ctrl+C.
echo.

:MENU
choice /C SN /N /M "Deseja encerrar o StudioLab e os servicos iniciados por este .bat? [S/N]: "
if errorlevel 2 (
  echo.
  echo [INFO] Ambiente mantido em execucao.
  echo        Pressione S quando quiser encerrar.
  echo.
  goto :MENU
)
if errorlevel 1 goto :ENCERRAR_INICIADOS
goto :MENU

:ENCERRAR_INICIADOS
echo.
echo [INFO] Encerrando processos iniciados por este StudioLab...

call :KILL_PIDFILE "%LOG_DIR%\portal.pid" "Portal"
call :KILL_PIDFILE "%LOG_DIR%\comfyui.pid" "ComfyUI"
call :KILL_PIDFILE "%LOG_DIR%\ollama.pid" "Ollama"

echo.
echo [OK] Encerramento concluido.
echo.
endlocal
exit /b 0

:KILL_PIDFILE
set "PIDFILE=%~1"
set "SERVICO=%~2"
if exist "%PIDFILE%" (
  set /p PID=<"%PIDFILE%"
  if defined PID (
    taskkill /PID !PID! /T /F >nul 2>&1
    if errorlevel 1 (
      echo [INFO] %SERVICO% ja estava encerrado.
    ) else (
      echo [OK] %SERVICO% encerrado.
    )
  )
  del /q "%PIDFILE%" >nul 2>&1
) else (
  echo [INFO] %SERVICO% nao foi iniciado por este .bat; mantido ativo.
)
exit /b 0

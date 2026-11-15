@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo  Tradely - starting FastAPI + React (Vite)
echo ============================================================
echo.

rem ---------------------------------------------------------------------------
rem 1. Python: Tradely needs 3.11-3.14. Python 3.15+ has no pandas wheel yet,
rem    so "pip install -r requirements.txt" would try to compile pandas and fail.
rem ---------------------------------------------------------------------------
set "PYTHON="
for %%V in (3.14 3.13 3.12 3.11) do (
    if not defined PYTHON (
        py -%%V -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PYTHON=py -%%V"
    )
)
if not defined PYTHON (
    python -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
    echo [Tradely] ERROR: no compatible Python interpreter found.
    echo [Tradely] Install Python 3.11, 3.12, 3.13 or 3.14 and run this file again.
    echo [Tradely] Python 3.15 is not supported yet because pandas has no wheel for it.
    goto :fail
)

rem ---------------------------------------------------------------------------
rem 2. Node.js / npm: required for the React frontend.
rem ---------------------------------------------------------------------------
where node >nul 2>&1
if errorlevel 1 (
    echo [Tradely] ERROR: Node.js was not found on PATH.
    echo [Tradely] Install Node.js 20 or newer from https://nodejs.org/ and run this file again.
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [Tradely] ERROR: npm was not found on PATH.
    echo [Tradely] Reinstall Node.js with npm included, then run this file again.
    goto :fail
)
for /f "tokens=*" %%V in ('node --version') do echo [Tradely] Node.js %%V detected.

rem ---------------------------------------------------------------------------
rem 3. Python virtual environment (created once, reused afterwards).
rem ---------------------------------------------------------------------------
set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [Tradely] Existing .venv uses an unsupported Python version; recreating it...
        rmdir /s /q .venv
    )
)

if not exist "%VENV_PY%" (
    echo [Tradely] Creating virtual environment with %PYTHON%...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :fail
)

rem ---------------------------------------------------------------------------
rem 4. Backend dependencies (pip installs only what is missing).
rem ---------------------------------------------------------------------------
echo [Tradely] Validating backend dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [Tradely] ERROR: backend dependency installation failed. See the pip output above.
    goto :fail
)

if not exist .env copy .env.example .env >nul

rem ---------------------------------------------------------------------------
rem 5. TradingView library + local bridge (Python talks to Node over loopback).
rem ---------------------------------------------------------------------------
set "TV_LIB=TradingView-API\TradingView-API-main"
if not exist "%TV_LIB%\dist\index.js" (
    echo [Tradely] Building the bundled TradingView library ^(first run^)...
    pushd "%TV_LIB%"
    call npm install --no-fund --no-audit
    if errorlevel 1 (
        popd
        echo [Tradely] ERROR: TradingView library dependency installation failed.
        goto :fail
    )
    call npm run build
    if errorlevel 1 (
        popd
        echo [Tradely] ERROR: TradingView library build failed.
        goto :fail
    )
    popd
) else if not exist "%TV_LIB%\node_modules\ws" (
    echo [Tradely] Installing the TradingView library runtime dependency...
    pushd "%TV_LIB%"
    call npm install --omit=dev --no-fund --no-audit
    if errorlevel 1 (
        popd
        echo [Tradely] ERROR: TradingView library dependency installation failed.
        goto :fail
    )
    popd
)

set "BRIDGE_ALREADY=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 set "BRIDGE_ALREADY=1"

if "%BRIDGE_ALREADY%"=="1" (
    echo [Tradely] TradingView bridge is already running on http://127.0.0.1:8010 - reusing it.
) else (
    echo [Tradely] Starting the TradingView bridge on http://127.0.0.1:8010 ...
    start "Tradely Bridge" /d "%~dp0tradingview-bridge" cmd /k "npm start"
    call :wait_for "http://127.0.0.1:8010/health" 40
    if errorlevel 1 (
        echo [Tradely] ERROR: the TradingView bridge did not become ready on port 8010.
        echo [Tradely] Open the "Tradely Bridge" window to read the error.
        goto :fail
    )
    echo [Tradely] TradingView bridge is ready.
)

rem ---------------------------------------------------------------------------
rem 6. Frontend dependencies (installed only when node_modules is absent).
rem ---------------------------------------------------------------------------
if not exist "frontend\package.json" (
    echo [Tradely] ERROR: frontend\package.json is missing.
    goto :fail
)
if not exist "frontend\node_modules" (
    echo [Tradely] Installing frontend dependencies ^(first run, this can take a minute^)...
    pushd frontend
    call npm install --no-fund --no-audit
    if errorlevel 1 (
        popd
        echo [Tradely] ERROR: npm install failed. See the npm output above.
        goto :fail
    )
    popd
)

rem ---------------------------------------------------------------------------
rem 7. Start FastAPI on 127.0.0.1:8000 unless a healthy instance is already up.
rem ---------------------------------------------------------------------------
set "API_ALREADY=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 set "API_ALREADY=1"

if "%API_ALREADY%"=="1" (
    echo [Tradely] FastAPI is already running on http://127.0.0.1:8000 - reusing it.
) else (
    echo [Tradely] Starting FastAPI on http://127.0.0.1:8000 ...
    start "Tradely API" /d "%~dp0" cmd /k ""%VENV_PY%" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload"
    call :wait_for "http://127.0.0.1:8000/api/health" 40
    if errorlevel 1 (
        echo [Tradely] ERROR: FastAPI did not become ready on port 8000.
        echo [Tradely] Open the "Tradely API" window to read the traceback.
        echo [Tradely] A common cause is port 8000 already being used by another program.
        goto :fail
    )
    echo [Tradely] FastAPI is ready.
)

rem ---------------------------------------------------------------------------
rem 8. Start the Vite dev server on 127.0.0.1:5173 unless it is already up.
rem ---------------------------------------------------------------------------
set "UI_ALREADY=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 set "UI_ALREADY=1"

if "%UI_ALREADY%"=="1" (
    echo [Tradely] Vite is already running on http://localhost:5173 - reusing it.
) else (
    echo [Tradely] Starting Vite on http://localhost:5173 ...
    start "Tradely UI" /d "%~dp0frontend" cmd /k "npm run dev"
    call :wait_for "http://127.0.0.1:5173/" 60
    if errorlevel 1 (
        echo [Tradely] ERROR: the Vite dev server did not become ready on port 5173.
        echo [Tradely] Open the "Tradely UI" window to read the error.
        goto :fail
    )
    echo [Tradely] Vite is ready.
)

rem ---------------------------------------------------------------------------
rem 9. Open the app.
rem ---------------------------------------------------------------------------
echo.
echo [Tradely] Application ready: http://localhost:5173
echo [Tradely] API docs:         http://127.0.0.1:8000/docs
echo [Tradely] Close the "Tradely Bridge", "Tradely API" and "Tradely UI" windows to stop.
echo.
start "" "http://localhost:5173"
goto :eof

rem ---------------------------------------------------------------------------
rem Helper: poll a URL until it answers, up to %2 attempts of ~0.75s.
rem ---------------------------------------------------------------------------
:wait_for
powershell -NoProfile -Command "$u = '%~1'; for ($i = 0; $i -lt %~2; $i++) { try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } } catch {}; Start-Sleep -Milliseconds 750 }; exit 1"
exit /b %errorlevel%

:fail
echo.
echo [Tradely] Startup failed. The application is not fully running.
echo [Tradely] Fix the error above and run run.bat again.
pause
exit /b 1

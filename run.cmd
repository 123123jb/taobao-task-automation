@echo off
setlocal
set "PYTHONUTF8=1"
if not defined ADBUTILS_ADB_PATH if exist "%~dp0.venv\Lib\site-packages\adbutils\binaries\adb.exe" set "ADBUTILS_ADB_PATH=%~dp0.venv\Lib\site-packages\adbutils\binaries\adb.exe"
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Missing .venv. See LOCAL_SETUP.md.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
exit /b %errorlevel%

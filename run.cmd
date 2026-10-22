@echo off
setlocal
set PYTHONUTF8=1
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" douyin_guaji.py %*
) else (
  python douyin_guaji.py %*
)
set "result=%ERRORLEVEL%"
popd
exit /b %result%

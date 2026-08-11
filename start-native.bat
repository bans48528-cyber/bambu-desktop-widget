@echo off
cd /d "%~dp0"
set "CODEX_PY=C:\Users\64264\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CODEX_PY%" (
  "%CODEX_PY%" "%~dp0native_widget.py"
  exit /b %errorlevel%
)
py -3 "%~dp0native_widget.py"
if errorlevel 1 python "%~dp0native_widget.py"

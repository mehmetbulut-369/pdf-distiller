@echo off
REM Windows: double-click. The first run sets things up (1-2 min).
cd /d "%~dp0"
if not exist .venv (
  echo First-time setup...
  py -3 -m venv .venv || python -m venv .venv || (echo Python 3 not found: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip -q
  .venv\Scripts\pip install -r requirements.txt -q || (echo Setup failed. & pause & exit /b 1)
)
.venv\Scripts\python run.py
pause

@echo off
REM Windows: cift tiklayin. Ilk calistirmada kurulum yapar (1-2 dk).
cd /d "%~dp0"
if not exist .venv (
  echo Ilk kurulum yapiliyor...
  py -3 -m venv .venv || python -m venv .venv || (echo Python 3 bulunamadi: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip -q
  .venv\Scripts\pip install -r requirements.txt -q || (echo Kurulum basarisiz. & pause & exit /b 1)
)
.venv\Scripts\python run.py
pause

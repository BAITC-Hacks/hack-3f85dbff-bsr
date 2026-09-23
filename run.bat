@echo off
cd /d "%~dp0"
if not exist .venv py -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo ===========================================
echo EKT AI Assistant
echo Open: http://127.0.0.1:8000
echo EKT API credentials are read from .env
echo Add OPENAI_API_KEY to .env to enable AI answers.
echo ===========================================
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

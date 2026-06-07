@echo off
set TOURNAMENT_ADMIN_PW=admin123
set TOURNAMENT_REFEREE_PW=ref123
cd /d D:\code\tennis-tournament
python -m uvicorn app:app --host 0.0.0.0 --port 8000
pause

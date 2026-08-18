@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo 실행하지 못했습니다. Python 설치 상태를 확인해 주세요.
  pause
)

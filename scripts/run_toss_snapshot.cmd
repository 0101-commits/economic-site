@echo off
REM 토스증권 스냅샷 수집 — Windows 작업 스케줄러가 이 파일을 실행한다.
REM 토스 Open API 는 허용 IP 목록 밖 호출을 막아 GitHub Actions 에서는 부를 수 없다.
REM 허용 IP 가 등록된 이 PC 가 대신 받아 toss_snapshot.json 으로 저장·푸시하고,
REM 클라우드의 fetch_data.py 가 그 파일을 읽는다. PC 가 꺼져 있으면 기존 소스로 폴백.
REM
REM 등록:   scripts\register_toss_task.ps1 참고
REM 자격증명: 사용자 환경변수 TOSS_CLIENT_ID / TOSS_CLIENT_SECRET

setlocal
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
python scripts\fetch_toss_snapshot.py --push >> "%TEMP%\toss_snapshot.log" 2>&1
exit /b %ERRORLEVEL%

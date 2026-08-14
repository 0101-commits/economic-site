@echo off
REM Toss Securities snapshot collector - launched by Windows Task Scheduler.
REM
REM ASCII ONLY. cmd.exe parses batch files in the OEM code page, so UTF-8
REM Korean comments get mangled into broken commands (observed: exit 9009,
REM "'DING' is not recognized"). Keep every byte in this file ASCII and put
REM the Korean explanation in register_toss_task.ps1 / fetch_toss_snapshot.py.
REM
REM Register / re-register: scripts\register_toss_task.ps1
REM Credentials: user env vars TOSS_CLIENT_ID / TOSS_CLIENT_SECRET

setlocal
cd /d "%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "LOG=%TEMP%\toss_snapshot.log"

REM trim the log when it passes 1 MB - nobody prunes a background job's log
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 1048576 del "%LOG%"

echo [%DATE% %TIME%] run >> "%LOG%"
python scripts\fetch_toss_snapshot.py --push >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo [%DATE% %TIME%] exit %RC% >> "%LOG%"
exit /b %RC%

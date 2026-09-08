@echo off
REM Post-fix pipeline observation - launched by Windows Task Scheduler.
REM
REM ASCII ONLY. cmd.exe parses batch files in the OEM code page, so UTF-8
REM Korean comments get mangled into broken commands (observed: exit 9009,
REM "'DING' is not recognized"). Keep every byte in this file ASCII and put
REM the Korean explanation in verify_pipeline_fix.py.
REM
REM The task action is run_hidden.vbs (no console window) - see
REM register_verify_task.ps1. Run this .cmd directly to watch it.
REM Register / re-register: scripts\register_verify_task.ps1

setlocal
cd /d "%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "LOG=%TEMP%\verify_pipeline_fix.log"

REM trim the log when it passes 1 MB - nobody prunes a background job's log
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 1048576 del "%LOG%"

echo [%DATE% %TIME%] run >> "%LOG%"
python scripts\verify_pipeline_fix.py >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
echo [%DATE% %TIME%] exit %RC% >> "%LOG%"
exit /b %RC%

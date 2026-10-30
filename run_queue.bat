@echo off
rem Key every job.json found under a folder, one after another:
rem   run_queue.bat "D:\CKShots"
setlocal
if "%~1"=="" (
  echo usage: run_queue.bat folder
  exit /b 64
)
set "FAILED=0"
for /r "%~1" %%J in (job.json) do (
  if exist "%%J" (
    echo.
    echo ===== %%J
    call "%~dp0run_job.bat" "%%J" || set /a FAILED+=1
  )
)
echo.
echo Queue finished, %FAILED% job(s) failed.
exit /b %FAILED%

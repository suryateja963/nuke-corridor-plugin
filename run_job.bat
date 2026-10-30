@echo off
rem Key one shot: run_job.bat "D:\CKShots\myshot\job.json"   (or drag a job.json onto this file)
setlocal
set "PY=D:\CorridorKey2\venv\Scripts\python.exe"
set "PYTHONPATH="
set "PYTHONHOME="
if "%~1"=="" (
  echo usage: run_job.bat path\to\job.json
  exit /b 64
)
pushd "%~dp0"
"%PY%" -m ck_engine.run "%~1"
set "RC=%ERRORLEVEL%"
popd
if "%RC%"=="0" (echo Key finished.) else (echo Key did not finish - see log.txt next to the job file.)
exit /b %RC%

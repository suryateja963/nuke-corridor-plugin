@echo off
rem Key one shot: run_job.bat "D:\CKShots\myshot\job.json"   (or drag a job.json onto this file)
setlocal
rem Engine python from settings.local.json, else settings.json (the installer writes local paths).
set "PY="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$s = Get-Content -Raw '%~dp0settings.json' | ConvertFrom-Json; $l = '%~dp0settings.local.json'; if (Test-Path $l) { $o = Get-Content -Raw $l | ConvertFrom-Json; if ($o.engine_python) { $s.engine_python = $o.engine_python } }; $s.engine_python"`) do set "PY=%%P"
if not defined PY set "PY=D:\CorridorKey2\venv\Scripts\python.exe"
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

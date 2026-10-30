# Starts a second Nuke Non-commercial that runs nuke\tests\nuke_auto_test.py by itself,
# waits for its report (_g2_out\nuke_auto_report.txt, last line DONE), then closes that Nuke.
#   powershell -ExecutionPolicy Bypass -File tests\run_nuke_auto.ps1
param(
    [string]$Nuke = "D:\nuke plugin\nuke software\Nuke17.1.exe",
    [int]$TimeoutMin = 15,
    [string]$Module = "nuke_auto_test",
    [string]$ReportName = "nuke_auto_report.txt"
)
$repo = Split-Path -Parent $PSScriptRoot
$report = Join-Path $repo "_g2_out\$ReportName"
$shots = Join-Path $repo "_nuke_test"
Remove-Item $report -ErrorAction SilentlyContinue
Remove-Item $shots -Recurse -Force -ErrorAction SilentlyContinue

$env:NUKE_PATH = Join-Path $repo "nuke\tests\auto_startup"
$env:CK2_AUTO_MODULE = $Module
$console = Join-Path $repo "_g2_out\nuke_auto_console.txt"
$p = Start-Process -FilePath $Nuke -ArgumentList "--nc" -WorkingDirectory (Split-Path $Nuke) -PassThru -RedirectStandardOutput $console -RedirectStandardError "$console.err"
Write-Output "started Nuke pid $($p.Id)"
$deadline = (Get-Date).AddMinutes($TimeoutMin)
while ((Get-Date) -lt $deadline -and -not $p.HasExited) {
    if ((Test-Path $report) -and ((Get-Content $report -Tail 1) -match "^DONE")) { break }
    Start-Sleep -Seconds 5
}
if (Test-Path $report) { Get-Content $report } else { Write-Output "no report written" }
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force; Write-Output "closed test Nuke" }
else { Write-Output "test Nuke exited by itself (code $($p.ExitCode))" }

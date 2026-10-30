# Installs a bundle made by make_bundle.ps1 on this PC. Run it from inside the bundle folder:
#   powershell -ExecutionPolicy Bypass -File "E:\CK2_bundle\install_bundle.ps1"            # installs to D:\
#   powershell -ExecutionPolicy Bypass -File "E:\CK2_bundle\install_bundle.ps1" -Root "C:\" # another drive
# Copies to <Root>\CorridorKey2 and "<Root>\nuke plugin", points the venv at its new interpreter,
# writes settings.local.json with this PC's paths, adds the Nuke menu hook, and runs the setup check.
param(
    [string]$Root = "D:\",
    [string]$Shots = "",
    [switch]$SkipHook    # testing only: leave this PC's Nuke menu hook alone
)
$ErrorActionPreference = "Stop"
$bundle = $PSScriptRoot
$Root = $Root.TrimEnd("\") + "\"
$engine = Join-Path $Root "CorridorKey2"
$tool = Join-Path $Root "nuke plugin"
if (-not $Shots) { $Shots = Join-Path $Root "CKShots" }
if (-not (Test-Path "$bundle\CorridorKey2\venv") -or -not (Test-Path "$bundle\nuke plugin\ck_engine")) {
    throw "Run this script from inside the bundle folder made by make_bundle.ps1."
}
$free = (Get-PSDrive $Root.Substring(0, 1)).Free / 1GB
if ($free -lt 15) { throw ("Only {0:N0} GB free on {1}; need about 10 GB plus room for shots." -f $free, $Root) }

function Copy-Tree($src, $dst) {
    & robocopy $src $dst /E /NFL /NDL /NJH /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed copying $src (code $LASTEXITCODE)" }
}
Write-Output "Copying the engine to $engine (about 10 GB)..."
Copy-Tree "$bundle\CorridorKey2" $engine
Write-Output "Copying the tool to $tool..."
Copy-Tree "$bundle\nuke plugin" $tool

# The venv records its interpreter's absolute path; point it at the copied one.
$cfg = Join-Path $engine "venv\pyvenv.cfg"
$pyHome = (Get-ChildItem (Join-Path $engine ".uv-python") -Directory | Where-Object Name -like "cpython-3.12*" | Select-Object -First 1).FullName
if (-not $pyHome) { throw "Python 3.12 interpreter missing from $engine\.uv-python" }
(Get-Content $cfg) -replace "^home = .*", "home = $pyHome" | Set-Content $cfg -Encoding ascii

$fw = { param($p) $p -replace "\\", "/" }
$settings = [ordered]@{
    engine_python = & $fw (Join-Path $engine "venv\Scripts\python.exe")
    upstream_root = & $fw (Join-Path $engine "upstream")
    worker_script = & $fw (Join-Path $engine "ComfyUI-CorridorKey2\ck2\worker.py")
    ffmpeg        = & $fw (Join-Path $engine "ffmpeg\ffmpeg.exe")
    ffprobe       = & $fw (Join-Path $engine "ffmpeg\ffprobe.exe")
    shot_root     = & $fw $Shots
}
$json = $settings | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $tool "settings.local.json"), $json)
New-Item -ItemType Directory -Force $Shots | Out-Null

$py = Join-Path $engine "venv\Scripts\python.exe"
if (-not $SkipHook) {
    Write-Output "Adding the CorridorKey 2.0 menu to Nuke..."
    & $py (Join-Path $tool "install_nuke_hook.py")
}
Write-Output ""
& $py (Join-Path $tool "tools\check_setup.py")

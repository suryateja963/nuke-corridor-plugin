# Installs a bundle made by make_bundle.ps1 on this PC. Run it from inside the bundle folder:
#   powershell -ExecutionPolicy Bypass -File "E:\CK2_bundle\install_bundle.ps1"            # copies to D:\
#   powershell -ExecutionPolicy Bypass -File "E:\CK2_bundle\install_bundle.ps1" -Root "C:\" # another drive
#   powershell -ExecutionPolicy Bypass -File "D:\CK2_bundle\install_bundle.ps1" -InPlace -Shots "E:\CKShots"
#       uses the bundle where it is (no copy, no extra space): for a bundle already on a local drive
# Points the venv at its interpreter, writes settings.local.json with this PC's paths, adds the Nuke
# menu hook, and runs the setup check.
param(
    [string]$Root = "D:\",
    [string]$Shots = "",
    [switch]$InPlace,    # use the bundle folder itself as the install
    [switch]$SkipHook    # testing only: leave this PC's Nuke menu hook alone
)
$ErrorActionPreference = "Stop"
$bundle = $PSScriptRoot
if (-not (Test-Path "$bundle\CorridorKey2\venv") -or -not (Test-Path "$bundle\nuke plugin\ck_engine")) {
    throw "Run this script from inside the bundle folder made by make_bundle.ps1."
}

function Free-GB($path) {
    # DriveInfo reads free space reliably (Get-PSDrive can report 0, e.g. in an Administrator window).
    [System.IO.DriveInfo]::new($path.Substring(0, 1) + ":\").AvailableFreeSpace / 1GB
}

if ($InPlace) {
    $engine = Join-Path $bundle "CorridorKey2"
    $tool = Join-Path $bundle "nuke plugin"
    if (-not $Shots) { $Shots = Join-Path $bundle.Substring(0, 3) "CKShots" }
    Write-Output "Using the bundle in place: $bundle (nothing is copied)"
} else {
    $Root = $Root.TrimEnd("\") + "\"
    $engine = Join-Path $Root "CorridorKey2"
    $tool = Join-Path $Root "nuke plugin"
    if (-not $Shots) { $Shots = Join-Path $Root "CKShots" }
    $free = Free-GB $Root
    Write-Output ("{0:N1} GB free on {1}" -f $free, $Root)
    if ($free -lt 15) {
        throw ("Only {0:N1} GB free on {1}; copying needs about 10 GB plus room for shots. Free space, pick another " +
               "drive with -Root, or use the bundle where it is with -InPlace." -f $free, $Root)
    }
    $log = Join-Path $env:TEMP "ck2_install_copy.log"
    Remove-Item $log -ErrorAction SilentlyContinue
    function Copy-Tree($src, $dst) {
        & robocopy $src $dst /E /NFL /NDL /NJH /NP /R:1 /W:1 "/LOG+:$log" | Out-Null
        if ($LASTEXITCODE -ge 8) {
            $why = (Select-String -Path $log -Pattern "ERROR" | Select-Object -Last 3 | ForEach-Object Line) -join "`n"
            throw ("robocopy failed copying {0} (code {1}). Free space on {2}: {3:N1} GB. Last errors:`n{4}`nFull log: {5}" -f
                   $src, $LASTEXITCODE, $Root, (Free-GB $Root), $why, $log)
        }
    }
    Write-Output "Copying the engine to $engine (about 10 GB)..."
    Copy-Tree "$bundle\CorridorKey2" $engine
    Write-Output "Copying the tool to $tool..."
    Copy-Tree "$bundle\nuke plugin" $tool
}

$shotFree = Free-GB $Shots
Write-Output ("Shots folder {0}: {1:N1} GB free" -f $Shots, $shotFree)
if ($shotFree -lt 5) {
    Write-Output "WARNING: under 5 GB free for shots; keys write large EXR files. Use -Shots on a drive with space."
}

# The venv records its interpreter's absolute path; point it at this copy's interpreter.
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

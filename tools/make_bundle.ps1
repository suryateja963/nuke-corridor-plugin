# Packs everything another PC needs into one folder (about 10 GB): the CorridorKey 2.0 engine
# (upstream code + weights + foundation models), its Python venv and interpreter, the CK2 worker,
# ffmpeg/ffprobe, and this tool (with its git history, so `git pull` works there later).
#   powershell -ExecutionPolicy Bypass -File "D:\nuke plugin\tools\make_bundle.ps1" -Dest "E:\CK2_bundle"
# Copy the folder to the other PC (USB drive, network share), then run install_bundle.ps1 inside it.
param(
    [Parameter(Mandatory = $true)][string]$Dest,
    [string]$Engine = "D:\CorridorKey2"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

function Copy-Tree($src, $dst, [string[]]$excludeDirs = @(), [string[]]$excludeFiles = @()) {
    $rcArgs = @($src, $dst, "/E", "/NFL", "/NDL", "/NJH", "/NP", "/R:1", "/W:1")
    if ($excludeDirs.Count) { $rcArgs += "/XD"; $rcArgs += $excludeDirs }
    if ($excludeFiles.Count) { $rcArgs += "/XF"; $rcArgs += $excludeFiles }
    & robocopy @rcArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed copying $src (code $LASTEXITCODE)" }
}

$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobe = (Get-Command ffprobe -ErrorAction Stop).Source
New-Item -ItemType Directory -Force $Dest | Out-Null
$free = [System.IO.DriveInfo]::new((Resolve-Path $Dest).Drive.Name + ":\").AvailableFreeSpace / 1GB
if ($free -lt 11) { throw ("Only {0:N0} GB free on the destination; the bundle needs about 10 GB." -f $free) }

Write-Output "1/5 CorridorKey 2.0 upstream + weights (4.8 GB)..."
Copy-Tree "$Engine\upstream" "$Dest\CorridorKey2\upstream" @("__pycache__")
Write-Output "2/5 Python venv + interpreter (4.9 GB)..."
Copy-Tree "$Engine\venv" "$Dest\CorridorKey2\venv" @("__pycache__")
Copy-Tree "$Engine\.uv-python" "$Dest\CorridorKey2\.uv-python" @("__pycache__")
Write-Output "3/5 CK2 worker..."
New-Item -ItemType Directory -Force "$Dest\CorridorKey2\ComfyUI-CorridorKey2\ck2" | Out-Null
Copy-Item "$Engine\ComfyUI-CorridorKey2\ck2\worker.py" "$Dest\CorridorKey2\ComfyUI-CorridorKey2\ck2\"
Write-Output "4/5 ffmpeg..."
New-Item -ItemType Directory -Force "$Dest\CorridorKey2\ffmpeg" | Out-Null
Copy-Item $ffmpeg, $ffprobe "$Dest\CorridorKey2\ffmpeg\"
Write-Output "5/5 the Nuke tool..."
Copy-Tree $repo "$Dest\nuke plugin" @("nuke software", "_e2e_out", "_g2_out", "_nuke_test", "shots", "__pycache__") @("settings.local.json")
Copy-Item "$PSScriptRoot\install_bundle.ps1" "$Dest\"
Copy-Item "$repo\docs\install_other_pc.md" "$Dest\INSTALL.md"

$size = (Get-ChildItem $Dest -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Write-Output ("Bundle ready: {0} ({1:N1} GB). On the other PC run:" -f $Dest, $size)
Write-Output "  powershell -ExecutionPolicy Bypass -File `"<bundle>\install_bundle.ps1`""

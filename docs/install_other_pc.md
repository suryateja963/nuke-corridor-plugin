# Installing on another PC

The tool needs three things on the other PC: the CorridorKey 2.0 engine (code, weights and
foundation models, about 4.8 GB), its Python environment (about 4.9 GB, with torch for CUDA 12.8),
and this tool. Nothing is downloaded from the internet: you copy one bundle folder over.

## What the other PC needs

| | |
|---|---|
| Windows 10/11, 64-bit | |
| NVIDIA GPU, 8 GB VRAM | RTX 20xx / 30xx / 40xx / 50xx. An RTX 3050 8 GB works; expect slower keys than an RTX 5060 |
| NVIDIA driver **570 or newer** | needed by CUDA 12.8; update from nvidia.com or the NVIDIA App |
| Nuke (Non-commercial or commercial) | tested on 17.1v2 NC; any Nuke with Python 3 should work |
| About 10 GB free, plus room for shots | EXR plates are large: keep 20+ GB free on the shots drive |

## 1. Make the bundle (on this PC)

Plug in a USB drive (or use a network share) with about 11 GB free, then:

```bat
powershell -ExecutionPolicy Bypass -File "D:\nuke plugin\tools\make_bundle.ps1" -Dest "E:\CK2_bundle"
```

It copies:
- the engine (`upstream`, `venv`, `.uv-python`, the CK2 `worker.py`);
- ffmpeg/ffprobe;
- this tool, with its git history;
- `install_bundle.ps1` and this guide.

## 2. Install (on the other PC)

Close Nuke, then run the installer from the bundle:

```bat
powershell -ExecutionPolicy Bypass -File "E:\CK2_bundle\install_bundle.ps1"
```

By default it installs to `D:\CorridorKey2` and `D:\nuke plugin`, and puts shots in `D:\CKShots`.
For another drive (for example a PC with only C:):

```bat
powershell -ExecutionPolicy Bypass -File "E:\CK2_bundle\install_bundle.ps1" -Root "C:\" -Shots "C:\CKShots"
```

**Not enough space to copy, or the copy fails (robocopy code 9)?** If the bundle folder is already on a local
drive of that PC, use it where it is; nothing is copied:

```bat
powershell -ExecutionPolicy Bypass -File "D:\SOFTWEARS\CK2_bundle\install_bundle.ps1" -InPlace -Shots "E:\CKShots"
```

Point `-Shots` at a drive with plenty of free space. Don't move or rename the bundle folder afterwards.

The installer:
1. Copies the engine and the tool.
2. Points the Python venv at its copied interpreter.
3. Writes `settings.local.json` with that PC's paths.
4. Adds the CorridorKey 2.0 menu to Nuke.
5. Runs the setup check.

Every line of the check should say PASS.

## 3. Check it in Nuke

Start Nuke. A **CorridorKey 2.0** menu appears. For an unattended check that keys two real clips,
point the automatic test at that PC's Nuke executable:

```bat
powershell -ExecutionPolicy Bypass -File "D:\nuke plugin\tests\run_nuke_auto.ps1" -Nuke "C:\Program Files\Nuke17.1v2\Nuke17.1.exe" -Module nuke_crop_despill_test -ReportName nuke_crop_despill_report.txt
```

That test uses clips from `D:\CorridorKey2\test_clips`, which are not in the bundle. Without them,
key any green-screen clip of your own from the panel instead.

Re-run the setup check any time:

```bat
D:\CorridorKey2\venv\Scripts\python.exe "D:\nuke plugin\tools\check_setup.py"
```

## Updating later

The tool folder is a git checkout of the private repo, so with GitHub access on that PC:

```bat
cd /d "D:\nuke plugin"
git pull
```

Without GitHub access, re-run `make_bundle.ps1` on the first PC and the installer on the other one.
It overwrites the files but keeps nothing you need: shots live in the shots folder. The engine only
changes if CorridorKey itself is upgraded (`docs/upgrade_checklist.md`).

## If the check fails

| FAIL line | Fix |
|---|---|
| NVIDIA driver / GPU sees no CUDA | Install the latest Game Ready or Studio driver (570+), reboot |
| engine files missing | The bundle copy was incomplete: re-run the installer |
| ffmpeg | `settings.local.json` must point at `<Root>\CorridorKey2\ffmpeg\ffmpeg.exe` |
| Nuke menu hook | `D:\CorridorKey2\venv\Scripts\python.exe "D:\nuke plugin\install_nuke_hook.py"` |
| GPU out of memory while keying | Tick **Low VRAM** and use window 8 or 4; close browsers and other GPU apps |

On an 8 GB card, auto-crop (on by default) lowers the memory needed. 4K shots run with small
windows, so expect them to be slow.

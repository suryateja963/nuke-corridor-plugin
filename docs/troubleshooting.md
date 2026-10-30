# Troubleshooting

Every run writes `log.txt` and `status.json` in the shot folder; start there.

| Message / symptom | Cause | Fix |
|---|---|---|
| *The GPU ran out of memory* | Another app holds VRAM, or the window is too big for the frame size | Close browser/Resolve/games, view a small frame in Nuke, tick **low VRAM** or choose window 8 or 4 |
| *CorridorKey venv python not found* / *weights missing* | Paths in settings.json are wrong | Fix `settings.json` or add `settings.local.json` |
| *ffmpeg not found* | ffmpeg not on PATH | Install the gyan.dev full build (`winget install Gyan.FFmpeg`) or set full paths in settings |
| *camera raw can't be decoded* | BRAW/R3D/ARRIRAW | See [unsupported_formats.md](unsupported_formats.md) |
| *the first-frame hint is empty* | Roto not on the first frame of the range, or inverted | Check the Roto exists on that frame; untick **invert** |
| *hint sequence has N frames but the plate needs M* | Hint rendered over a different range | Render the hint over the same first/last as the key |
| *this shot is already being keyed* | Another key of the same shot is running | Wait or cancel it; if nothing is running, delete `<shot>\.running` |
| *Disk full* | Plates and keys are large (4K: about 25 MB per frame per pass) | Free space; use **Clean up a shot…** |
| Key looks washed out or too contrasty | Wrong colour space or range | Re-check [colour_spaces.md](colour_spaces.md); try the other range |
| Nuke freezes while keying | `nuke_blocking_run` is true in settings | Expected in blocking mode; set false if Gate G2's thread checks passed |
| No menu after install | Hook not loaded | Check `%USERPROFILE%\.nuke\init.py` has the CorridorKey line; restart Nuke |
| The Read shows "colorspace" warnings | Your OCIO config uses other names | Set the Reads to your config's linear Rec.709 by hand; tell Claude the name |

"""Menu: free disk space in a shot folder. Never deletes the newest key version."""

import os
import re
import shutil

import nuke


def _size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _gb(n):
    return "{:.2f} GB".format(n / 1024.0 ** 3)


def clean_shot():
    folder = nuke.getFilename("CorridorKey 2.0: pick a shot folder to clean up")
    if not folder:
        return
    folder = folder if os.path.isdir(folder) else os.path.dirname(folder)
    if not os.path.isfile(os.path.join(folder, "job.json")):
        nuke.message("{} is not a CorridorKey shot folder (no job.json).".format(folder))
        return
    if os.path.exists(os.path.join(folder, ".running")):
        nuke.message("This shot is keying right now; clean it up afterwards.")
        return

    key_dir = os.path.join(folder, "key")
    versions = sorted(d for d in (os.listdir(key_dir) if os.path.isdir(key_dir) else [])
                      if re.fullmatch(r"v\d{3,}", d))
    targets = [os.path.join(folder, "work"), os.path.join(key_dir, "preview"),
               os.path.join(folder, "hint", "nuke_render")]
    targets += [os.path.join(key_dir, v) for v in versions[:-1]]  # keep the newest
    targets = [t for t in targets if os.path.isdir(t)]
    if not targets:
        nuke.message("Nothing to clean up in {}.".format(folder))
        return
    sizes = [(t, _size(t)) for t in targets]
    listing = "\n".join("  {}  ({})".format(os.path.relpath(t, folder), _gb(s)) for t, s in sizes)
    keep = versions[-1] if versions else "none"
    if not nuke.ask("Delete these from {}?\n\n{}\n\nTotal {}. Kept: newest key {} and the plate.".format(
            folder, listing, _gb(sum(s for _, s in sizes)), keep)):
        return
    failed = []
    for t, _ in sizes:
        try:
            shutil.rmtree(t)
        except OSError as exc:
            failed.append("{}: {}".format(t, exc))
    plate = os.path.join(folder, "plate_lin")
    msg = "Cleaned up." if not failed else "Some folders could not be deleted:\n" + "\n".join(failed)
    if os.path.isdir(plate) and nuke.ask(msg + "\n\nAlso delete the linear plate ({})? It is "
                                         "rebuilt automatically on the next key.".format(_gb(_size(plate)))):
        shutil.rmtree(plate, ignore_errors=True)
        try:
            os.remove(os.path.join(folder, "plate.json"))
        except OSError:
            pass
    elif failed:
        nuke.message(msg)

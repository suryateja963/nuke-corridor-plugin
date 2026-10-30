r"""Adds (or removes) the one line that makes Nuke load the CorridorKey 2.0 tool.

    python install_nuke_hook.py            # install
    python install_nuke_hook.py --remove   # uninstall

Writes to %USERPROFILE%\.nuke\init.py. The line points Nuke at this repo's nuke\
folder; nothing else is copied, so updating the repo updates the tool.
Any Python 3 works (no packages needed).
"""

import os
import sys
from pathlib import Path

MARK = "# CorridorKey 2.0 tool"
NUKE_DIR = (Path(__file__).resolve().parent / "nuke").as_posix()
LINE = f'import nuke; nuke.pluginAddPath(r"{NUKE_DIR}")  {MARK}\n'


def main():
    init = Path(os.environ["USERPROFILE"]) / ".nuke" / "init.py"
    init.parent.mkdir(exist_ok=True)
    lines = init.read_text(encoding="utf-8").splitlines(keepends=True) if init.is_file() else []
    lines = [l for l in lines if MARK not in l]
    if "--remove" in sys.argv:
        init.write_text("".join(lines), encoding="utf-8")
        print(f"Removed the CorridorKey 2.0 line from {init}")
        return
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(LINE)
    init.write_text("".join(lines), encoding="utf-8")
    print(f"Added to {init}:\n  {LINE.strip()}\nRestart Nuke: the 'CorridorKey 2.0' menu appears in the menu bar.")


if __name__ == "__main__":
    main()

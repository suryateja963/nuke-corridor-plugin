r"""Test helper: hold N GB of GPU memory for a while, to simulate another program
(a Nuke viewer caching 4K frames, a player) taking memory while a key runs.

    D:\CorridorKey2\venv\Scripts\python.exe tests\gpu_hog.py 2.5 600
"""

import sys
import time

import torch

gb, seconds = float(sys.argv[1]), float(sys.argv[2])
hog = torch.empty(int(gb * 2**30), dtype=torch.uint8, device="cuda")
print(f"holding {gb} GB of GPU memory for {seconds:.0f} s", flush=True)
time.sleep(seconds)

# Only on NUKE_PATH when tests\run_nuke_auto.ps1 starts Nuke: waits for the UI,
# then runs the test module named in CK2_AUTO_MODULE (default nuke_auto_test)
# on the main thread.
import importlib
import os
import sys
import threading

import nuke

sys.path.insert(0, r"D:\nuke plugin\nuke\tests")


def _go():
    importlib.import_module(os.environ.get("CK2_AUTO_MODULE", "nuke_auto_test")).run()


threading.Timer(20.0, lambda: nuke.executeInMainThread(_go)).start()

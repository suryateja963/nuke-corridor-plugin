# Upgrade checklist

## New Nuke Non-commercial version (about every 180 days)

1. Install the new Nuke NC.
2. The hook in `%USERPROFILE%\.nuke\init.py` is shared by all Nuke versions, so nothing to copy. If
   the menu is missing, re-run `install_nuke_hook.py`.
3. Re-run the Gate G2 capability test ([nuke_env.md](nuke_env.md)) and record the new version and its
   expiry date there.
4. Key one known shot and compare with the previous result (tests/e2e_gpu.py, or by eye).

## Updating CorridorKey 2.0 upstream

1. Don't update in place. Clone the new commit to a new folder, e.g. `D:\CorridorKey2\upstream_new`,
   and download weights there.
2. Point `upstream_root` at it in `settings.local.json`.
3. Re-read [worker_api.md](worker_api.md) against the new code. Check in particular: output folder
   names (`*_alpha_exr`), frame naming (`alpha_000000.exr`), and the `window i/N` and `Auto VRAM` log
   lines.
4. Run all tests (unit + `tests\e2e_gpu.py`), then key your reference shots.
5. Keep the old folder until everything passes; switching back is one settings line.

## Updating the CK2 worker (CK2-roto repo)

The Nuke tool relies on the worker's job fields and stdout messages (`CK2_PROGRESS`, `CK2_DONE`,
`CK2_ERROR`) and on the `CANCEL` file. After updating that repo, diff `ck2/worker.py` against commit
`f7053e1` for those parts, then run the tests above.

## Updating this tool

`git pull` in `D:\nuke plugin`, run the unit tests, restart Nuke.

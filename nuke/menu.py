# Run by Nuke at start-up because install_nuke_hook.py added this folder with
# nuke.pluginAddPath(). Builds the CorridorKey 2.0 menu; the tool's code only
# loads when a menu item is used, so start-up stays fast.
import nuke

_m = nuke.menu("Nuke").addMenu("CorridorKey 2.0")
_m.addCommand("Key shot...", "import ck2nuke.panel; ck2nuke.panel.key_shot()")
_m.addCommand("Prepare plate only...", "import ck2nuke.panel; ck2nuke.panel.key_shot(prepare_only=True)")
_m.addSeparator()
_m.addCommand("Load latest key of a shot...", "import ck2nuke.loader; ck2nuke.loader.load_from_folder()")
_m.addCommand("Clean up a shot...", "import ck2nuke.cleanup; ck2nuke.cleanup.clean_shot()")
_m.addSeparator()
_m.addCommand("About", "import ck2nuke; ck2nuke.about()")

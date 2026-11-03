"""Release regressions: child-mode dispatch and frozen autostart commands."""
import os
import sys
import unittest
from unittest.mock import patch

import desktop_app
from winapi import autostart

try:
    import tkinter  # noqa: F401
    HAVE_TK = True
except ImportError:  # 例如没有图形环境的 Linux
    HAVE_TK = False


class PortableCommands(unittest.TestCase):
    def test_frozen_autostart_does_not_pass_source_script(self):
        exe=r"C:\My Apps\WaterInspector\WaterInspector.exe"
        with patch.object(sys,"frozen",True,create=True),patch.object(sys,"executable",exe):
            self.assertEqual(autostart.launch_args("missing-main.py"),[exe])
            self.assertEqual(autostart.command("missing-main.py"),'"'+exe+'"')

    def test_source_autostart_preserves_script(self):
        with patch.object(sys,"frozen",False,create=True),patch.object(autostart,"pythonw",return_value="pythonw.exe"):
            args=autostart.launch_args("main.py")
        self.assertEqual(args[1],os.path.abspath("main.py"))
        self.assertEqual(args[0],"pythonw.exe")

    def test_renderer_child_dispatch_preserves_arguments(self):
        with patch("persona.render.main",return_value=0) as child:
            self.assertEqual(desktop_app.main(["-m","persona.render","--preview","example.png"]),0)
            child.assert_called_once_with(["--preview","example.png"])

    @unittest.skipUnless(HAVE_TK, "需要 tkinter（设置界面）")
    def test_settings_child_dispatch_preserves_arguments(self):
        with patch("settings_ui.app.main",return_value=None) as child:
            self.assertEqual(desktop_app.main(["--settings","--close-after","1"]),0)
            child.assert_called_once_with(["--close-after","1"])

    def test_unknown_child_module_cannot_start(self):
        with self.assertRaises(ValueError):
            desktop_app.main(["-m","unknown.module"])

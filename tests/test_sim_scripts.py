# -*- coding: utf-8 -*-
"""模拟器回放：典型的一天 + 手工测试清单，正常模式与演示模式（×1/60）都要通过。"""

import glob
import io
import os
import unittest

from helpers import ROOT

from sim.run import run_file

SCRIPTS = sorted(glob.glob(os.path.join(ROOT, "sim", "scripts", "*.sim")))


class SimScripts(unittest.TestCase):
    def test_have_scripts(self):
        self.assertGreaterEqual(len(SCRIPTS), 10)

    def test_normal_mode(self):
        for path in SCRIPTS:
            with self.subTest(script=os.path.basename(path)):
                out = io.StringIO()
                sim = run_file(path, verbose=False, out=out)
                self.assertEqual(sim.failures, [], out.getvalue())

    def test_demo_mode(self):
        for path in SCRIPTS:
            with self.subTest(script=os.path.basename(path)):
                out = io.StringIO()
                sim = run_file(path, verbose=False, out=out, compress=True)
                if sim is not None:
                    self.assertEqual(sim.failures, [], out.getvalue())


if __name__ == "__main__":
    unittest.main()

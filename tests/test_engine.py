# SPDX-License-Identifier: GPL-3.0-or-later
"""The speech worker's protocol (without loading a model) and output mode choice."""

import unittest

from heard import worker
from heard.config import Config
from heard.output import resolve_mode


class WorkerProtocolTest(unittest.TestCase):
    def test_ping_and_unload_without_model(self):
        engine = worker.Engine()
        self.assertEqual(worker.handle(engine, {"cmd": "ping"}), {"device": None})
        self.assertEqual(worker.handle(engine, {"cmd": "unload"}), {})

    def test_unknown_command(self):
        with self.assertRaises(ValueError):
            worker.handle(worker.Engine(), {"cmd": "dance"})


class OutputModeTest(unittest.TestCase):
    def test_auto_types_ascii_and_pastes_the_rest(self):
        self.assertEqual(resolve_mode("auto", "Run the tests. "), "type")
        self.assertEqual(resolve_mode("auto", "Naïve café "), "paste")

    def test_explicit_modes(self):
        self.assertEqual(resolve_mode("type", "café"), "type")
        self.assertEqual(resolve_mode("paste", "abc"), "paste")
        self.assertIsNone(resolve_mode("clipboard", "abc"))


class ConfigTest(unittest.TestCase):
    def test_engine_options(self):
        options = Config(model="small.en", device="cpu").engine_options()
        self.assertEqual(options["model"], "small.en")
        self.assertEqual(options["device"], "cpu")
        self.assertTrue(options["models_dir"].endswith("heard/models"))


if __name__ == "__main__":
    unittest.main()

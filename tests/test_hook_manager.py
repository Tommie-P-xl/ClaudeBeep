# -*- coding: utf-8 -*-
"""hook_manager 所有权判定与命令解析单元测试。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hook_manager import (
    _command_argv,
    _is_owned,
    _is_legacy_claude_owned,
    build_hook_command,
)


class TestCommandArgv(unittest.TestCase):
    def test_simple(self):
        argv = _command_argv('"C:/x/notify.py" --from-stdin')
        self.assertEqual(argv, ["C:/x/notify.py", "--from-stdin"])

    def test_empty(self):
        self.assertEqual(_command_argv(""), [])
        self.assertEqual(_command_argv(None), [])

    def test_quoted_python(self):
        argv = _command_argv('"C:/Program Files/Python/python.exe" "C:/x/notify.py" --type stop')
        self.assertEqual(argv, ["C:/Program Files/Python/python.exe", "C:/x/notify.py", "--type", "stop"])


class TestIsOwned(unittest.TestCase):
    def _project_script(self):
        root = os.path.dirname(os.path.abspath(__file__))
        project = os.path.dirname(root)
        return os.path.join(project, "notify.py")

    def test_owned_command(self):
        # 真实 hook 命令格式：<python> <notify.py> --claudebeep-hook --platform ... 
        cmd = f'"python.exe" "{self._project_script()}" --claudebeep-hook --platform claude_code --from-stdin --type ask'
        self.assertTrue(_is_owned(cmd, "claude_code"))
        self.assertFalse(_is_owned(cmd, "codex"))

    def test_not_owned(self):
        cmd = '"python" "some_other_script.py" --from-stdin'
        self.assertFalse(_is_owned(cmd, "claude_code"))

    def test_legacy_claude_owned(self):
        cmd = f'"python.exe" "{self._project_script()}" --from-stdin --type stop'
        self.assertTrue(_is_legacy_claude_owned(cmd))
        cmd2 = f'"python.exe" "{self._project_script()}" --from-stdin --type ask'
        self.assertTrue(_is_legacy_claude_owned(cmd2))
        cmd3 = '"python" "other.py" --from-stdin --type stop'
        self.assertFalse(_is_legacy_claude_owned(cmd3))


class TestBuildHookCommand(unittest.TestCase):
    def test_claude(self):
        entry = build_hook_command("claude_code", "Stop")
        self.assertEqual(entry["type"], "command")
        self.assertIn("--claudebeep-hook", entry["command"])
        self.assertIn("--platform claude_code", entry["command"])
        self.assertIn("--from-stdin", entry["command"])
        self.assertIn("--type stop", entry["command"])

    def test_codex(self):
        entry = build_hook_command("codex", "Stop")
        self.assertIn("--platform codex", entry["command"])
        self.assertIn("timeout", entry)

    def test_invalid_event(self):
        with self.assertRaises(ValueError):
            build_hook_command("claude_code", "NotARealEvent")


if __name__ == "__main__":
    unittest.main()

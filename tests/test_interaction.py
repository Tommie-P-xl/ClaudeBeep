# -*- coding: utf-8 -*-
"""interaction 回复解析单元测试（含 R3 边界）。"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interaction import (
    parse_reply,
    _parse_multi_question_reply,
    _parse_permission_select,
    _parse_single_select,
    _parse_multi_select,
)


class TestApproveDeny(unittest.TestCase):
    def test_keywords(self):
        pending = {"option_type": "approve_deny", "options": []}
        for kw in ("1", "y", "yes", "是", "批准", "approve", "ok", "好", "同意"):
            self.assertEqual(parse_reply(kw, pending), "approve", kw)
        for kw in ("2", "n", "no", "否", "拒绝", "deny", "不", "不同意"):
            self.assertEqual(parse_reply(kw, pending), "deny", kw)

    def test_free_text_passthrough(self):
        pending = {"option_type": "approve_deny", "options": []}
        self.assertEqual(parse_reply("自定义回复内容", pending), "自定义回复内容")


class TestPermissionSelect(unittest.TestCase):
    def test_digits(self):
        pending = {"option_type": "permission_select", "options": []}
        self.assertEqual(parse_reply("1", pending), "approve")
        self.assertEqual(parse_reply("2", pending), "approve_all")
        self.assertEqual(parse_reply("3", pending), "deny")

    def test_keywords(self):
        pending = {"option_type": "permission_select", "options": []}
        self.assertEqual(parse_reply("approve", pending), "approve")
        self.assertEqual(parse_reply("allow all", pending), "approve_all")
        self.assertEqual(parse_reply("拒绝", pending), "deny")

    def test_unknown_passthrough(self):
        pending = {"option_type": "permission_select", "options": []}
        self.assertEqual(parse_reply("自定义", pending), "自定义")


class TestSingleSelect(unittest.TestCase):
    def test_option_by_number(self):
        pending = {"option_type": "single_select", "options": ["甲", "乙", "丙"], "allow_custom": False}
        self.assertEqual(parse_reply("1", pending), "甲")
        self.assertEqual(parse_reply("3", pending), "丙")

    def test_out_of_range_returns_number(self):
        pending = {"option_type": "single_select", "options": ["甲", "乙"], "allow_custom": False}
        self.assertEqual(parse_reply("9", pending), "9")

    def test_text_passthrough(self):
        pending = {"option_type": "single_select", "options": ["甲", "乙"], "allow_custom": True}
        self.assertEqual(parse_reply("自定义文本", pending), "自定义文本")


class TestMultiSelect(unittest.TestCase):
    def test_multiple_options(self):
        pending = {"option_type": "multi_select", "options": ["甲", "乙", "丙"]}
        self.assertEqual(parse_reply("1,3", pending), "甲,丙")

    def test_mixed(self):
        pending = {"option_type": "multi_select", "options": ["甲", "乙"]}
        self.assertEqual(parse_reply("1,自定义", pending), "甲,自定义")


class TestMultiQuestion(unittest.TestCase):
    def _pending(self):
        return {
            "option_type": "single_select",
            "options": [],
            "tool_input": {
                "questions": [
                    {"field": "q1", "options": [{"label": "甲"}, {"label": "乙"}]},
                    {"field": "q2", "options": [{"label": "丙"}, {"label": "丁"}]},
                ]
            },
        }

    def test_pipe_separator(self):
        result = parse_reply("1|2", self._pending())
        data = json.loads(result)
        self.assertEqual(data, {"q1": "甲", "q2": "丁"})

    def test_chinese_period_not_treated_as_separator(self):
        """R3：普通文本含中文句号不应触发多问题解析"""
        result = parse_reply("可以。", self._pending())
        self.assertEqual(result, "可以。")

    def test_decimal_point_not_treated_as_separator(self):
        """R3：含小数点的回复不应被误拆"""
        result = parse_reply("1.5倍", self._pending())
        self.assertEqual(result, "1.5倍")

    def test_multi_question_parse_direct(self):
        questions = [
            {"field": "q1", "options": [{"label": "甲"}, {"label": "乙"}]},
            {"field": "q2", "options": [{"label": "丙"}, {"label": "丁"}]},
        ]
        self.assertEqual(_parse_multi_question_reply("1|2", questions), '{"q1": "甲", "q2": "丁"}')
        self.assertEqual(_parse_multi_question_reply("2", questions), '{"q1": "乙", "q2": ""}')


class TestHelpers(unittest.TestCase):
    def test_parse_single_select(self):
        self.assertEqual(_parse_single_select("2", ["a", "b", "c"], True), "b")
        self.assertEqual(_parse_single_select("x", ["a", "b"], True), "x")

    def test_parse_multi_select(self):
        self.assertEqual(_parse_multi_select("1,3", ["a", "b", "c"]), "a,c")
        self.assertEqual(_parse_multi_select("", ["a"]), "")

    def test_parse_permission_select(self):
        self.assertEqual(_parse_permission_select("1", []), "approve")
        self.assertEqual(_parse_permission_select("3", []), "deny")
        self.assertEqual(_parse_permission_select("yes, allow all", []), "approve_all")


if __name__ == "__main__":
    unittest.main()

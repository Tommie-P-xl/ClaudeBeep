# -*- coding: utf-8 -*-
"""app.py Web API 单元测试（Flask test_client，不监听真实端口）。

覆盖使用路径：
- 配置读取/保存与敏感字段脱敏、空值不覆盖
- 本地访问防护（Host 白名单 / X-Requested-With 校验）
- 集成开关与 hooks 同步、权限模式读写
- 日志查看/清除
- 各渠道注销后集成开关同步关闭（B2 回归）

所有配置/日志/hook 文件均隔离到临时目录，绝不触碰用户真实数据。
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_store
import hook_manager
import app as app_module
import notification_core


class AppApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        cfg_path = self._tmp / "config.json"
        settings_path = self._tmp / "claude_settings.json"

        self.enterContext(mock.patch.object(config_store, "CONFIG_FILE", cfg_path))
        self.enterContext(mock.patch.object(app_module, "CONFIG_FILE", cfg_path))
        self.enterContext(mock.patch.object(app_module, "LOG_FILE", self._tmp / "notify.log"))
        self.enterContext(mock.patch.object(app_module, "CLAUDECODE_SETTINGS", settings_path))
        self.enterContext(mock.patch.object(hook_manager, "CLAUDE_SETTINGS", settings_path))
        # 隔离 secret.key（_load_or_create_secret_key 写入 RUNTIME_DIR）
        self.enterContext(mock.patch.object(app_module, "RUNTIME_DIR", self._tmp))

        # 重置 config_store 的 mtime 缓存，避免跨用例串值
        config_store._config_cache = None
        config_store._config_mtime = 0.0
        config_store._config_path_cached = None

        self._app = app_module.create_app()
        self._app.config["TESTING"] = True
        self._client = self._app.test_client()

    def _json_post(self, url, payload=None, **kwargs):
        headers = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        return self._client.post(url, data=json.dumps(payload or {}), headers=headers, **kwargs)

    def _json_put(self, url, payload=None, **kwargs):
        headers = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        return self._client.put(url, data=json.dumps(payload or {}), headers=headers, **kwargs)


class TestConfigApi(AppApiTestCase):
    def test_get_config_redacts_secrets(self):
        config_store.save_config({"channels": {
            "telegram": {"bot_token": "super-secret-token", "chat_id": "12345"},
        }})
        resp = self._client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        tg = data["channels"]["telegram"]
        self.assertEqual(tg["bot_token"], "")
        self.assertTrue(tg["configured_secrets"]["bot_token"])
        self.assertEqual(tg["chat_id"], "12345")

    def test_update_config_preserves_empty_secret(self):
        # 先写入一个 token
        r1 = self._json_put("/api/config", {"telegram": {"bot_token": "tok-123", "chat_id": "1"}})
        self.assertEqual(r1.status_code, 200)
        # 空值不应覆盖已有 token
        r2 = self._json_put("/api/config", {"telegram": {"bot_token": ""}})
        self.assertEqual(r2.status_code, 200)
        # GET 恒脱敏敏感字段，通过 configured_secrets 标记验证 token 仍存在
        data = self._client.get("/api/config").get_json()
        tg = data["channels"]["telegram"]
        self.assertTrue(tg["configured_secrets"]["bot_token"])
        self.assertEqual(tg["chat_id"], "1")

    def test_update_config_invalid_body_400(self):
        resp = self._client.put(
            "/api/config", data="[1,2,3]",
            headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400)


class TestLocalGuard(AppApiTestCase):
    def test_non_loopback_host_rejected(self):
        resp = self._client.get("/api/status", headers={"Host": "evil.example.com"})
        self.assertEqual(resp.status_code, 403)

    def test_write_method_requires_header(self):
        resp = self._client.post("/api/test")
        self.assertEqual(resp.status_code, 403)

    def test_write_method_with_header_passes(self):
        with mock.patch.object(notification_core, "collect_channels", return_value=[]):
            resp = self._json_post("/api/test")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["results"], [])


class TestIntegrationApi(AppApiTestCase):
    def test_integrations_list(self):
        resp = self._client.get("/api/integrations")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["integrations"]
        self.assertIn("claude_code", data)
        self.assertIn("codex", data)
        self.assertIn("interaction", data["claude_code"])

    def test_update_integration_events_syncs_hooks(self):
        # 关闭 Stop 事件 → 应同步 hooks 文件（写入隔离的 settings 路径）
        resp = self._json_put("/api/integrations/claude_code", {"events": {"Stop": False}})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["integration"]["events"]["Stop"])
        # hooks 文件已生成且不含 Stop
        settings = json.loads(app_module.CLAUDECODE_SETTINGS.read_text(encoding="utf-8"))
        self.assertNotIn("Stop", settings["hooks"])

    def test_update_integration_invalid_event_400(self):
        resp = self._json_put("/api/integrations/claude_code", {"events": {"NotARealEvent": True}})
        self.assertEqual(resp.status_code, 400)


class TestPermissionModeApi(AppApiTestCase):
    def test_put_and_get(self):
        resp = self._json_put("/api/permission-mode", {"mode": "acceptEdits"})
        self.assertEqual(resp.status_code, 200)
        settings = json.loads(app_module.CLAUDECODE_SETTINGS.read_text(encoding="utf-8"))
        self.assertEqual(settings["permissions"]["defaultMode"], "acceptEdits")
        self.assertEqual(self._client.get("/api/permission-mode").get_json()["mode"], "acceptEdits")

    def test_put_invalid_mode_400(self):
        resp = self._json_put("/api/permission-mode", {"mode": "hack"})
        self.assertEqual(resp.status_code, 400)

    def test_put_default_removes_key(self):
        self._json_put("/api/permission-mode", {"mode": "acceptEdits"})
        self._json_put("/api/permission-mode", {"mode": "default"})
        settings = json.loads(app_module.CLAUDECODE_SETTINGS.read_text(encoding="utf-8"))
        self.assertNotIn("defaultMode", settings.get("permissions", {}))


class TestLogsApi(AppApiTestCase):
    def test_logs_roundtrip(self):
        app_module.LOG_FILE.write_text("line1\nline2\n", encoding="utf-8")
        resp = self._client.get("/api/logs?lines=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["lines"], ["line1", "line2"])

    def test_clear_logs(self):
        app_module.LOG_FILE.write_text("junk\n", encoding="utf-8")
        resp = self._json_post("/api/logs/clear")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(app_module.LOG_FILE.read_text(encoding="utf-8"), "")


class TestLogoutSyncsIntegration(AppApiTestCase):
    """B2 回归：注销渠道后，各集成下的渠道开关必须同步关闭，
    否则 runtime_channel_config 仍会选中该渠道空凭据发送。"""

    def _assert_channel_off(self, name):
        data = self._client.get("/api/config").get_json()
        for platform in ("claude_code", "codex"):
            self.assertFalse(
                data["integrations"][platform]["channels"][name],
                f"{name} 在 {platform} 下注销后应关闭",
            )

    def test_weixin_logout(self):
        self.assertEqual(self._json_post("/api/weixin/logout").status_code, 200)
        self._assert_channel_off("weixin")

    def test_qq_logout(self):
        self.assertEqual(self._json_post("/api/qq/logout").status_code, 200)
        self._assert_channel_off("qq")

    def test_telegram_logout(self):
        self.assertEqual(self._json_post("/api/telegram/logout").status_code, 200)
        self._assert_channel_off("telegram")

    def test_feishu_logout(self):
        self.assertEqual(self._json_post("/api/feishu/logout").status_code, 200)
        self._assert_channel_off("feishu")

    def test_dingtalk_logout(self):
        self.assertEqual(self._json_post("/api/dingtalk/logout").status_code, 200)
        self._assert_channel_off("dingtalk")


class TestCredentialValidation(AppApiTestCase):
    def test_qq_validate_empty_credentials_400(self):
        resp = self._json_post("/api/qq/validate", {"app_id": "", "app_secret": ""})
        self.assertEqual(resp.status_code, 400)

    def test_telegram_validate_empty_token_400(self):
        resp = self._json_post("/api/telegram/validate", {"bot_token": ""})
        self.assertEqual(resp.status_code, 400)


class TestEmbeddedUiMode(AppApiTestCase):
    """MEM 回归：托盘内嵌 UI 模式（enable_sse_shutdown=False）必须正常工作。

    托盘内嵌 Flask 后，浏览器关闭不应退出托盘进程，因此禁用 SSE 自杀线程。
    """

    def test_create_app_without_sse_shutdown(self):
        app = app_module.create_app(enable_sse_shutdown=False)
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("hooks_installed", resp.get_json())

    def test_create_app_default_keeps_original_behavior(self):
        # setUp 中 create_app()（默认参数）创建成功，独立 --ui 模式行为不变
        self.assertIsNotNone(self._app)


if __name__ == "__main__":
    unittest.main()

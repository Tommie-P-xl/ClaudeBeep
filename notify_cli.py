"""CLI 参数解析（M3）：从 notify.main() 拆分，保持参数定义单一来源。"""

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude Code 通知管理器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--type", choices=["stop", "ask"], default="stop",
        help="通知类型: stop (执行完毕) / ask (询问问题)"
    )
    parser.add_argument("--message", default="", help="自定义通知消息")
    parser.add_argument("--from-stdin", action="store_true", help="从 stdin 读取 hook 上下文")
    parser.add_argument("--platform", choices=["claude_code", "codex"], default="claude_code")
    parser.add_argument("--claudebeep-hook", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install", action="store_true", help="安装 Claude Code hooks")
    parser.add_argument("--uninstall", action="store_true", help="卸载 Claude Code hooks")
    parser.add_argument("--test", action="store_true", help="测试所有通知渠道")
    parser.add_argument("--ui", action="store_true", help="启动 Web 管理界面")
    return parser

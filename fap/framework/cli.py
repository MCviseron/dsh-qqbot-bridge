"""命令行入口：

    python -m framework.cli --no-gui          # 非 GUI（本项目用法）
    python -m framework.cli --gui             # GUI 版本（额外起本地面板）
    python -m framework.cli --gui                # GUI：原生窗口套壳
    python -m framework.cli --gui --no-connect   # 只开窗口，不连 QQ（本地看界面）
    python -m framework.cli --gui --web-console  # GUI：浏览器控制台（http://127.0.0.1:39080/）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from framework.app import FapApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fap", description="fap framework runner")
    parser.add_argument("--root", default=".", help="项目根目录（含 config.json 与 plugins/）")
    parser.add_argument("--config", default="", help="配置文件路径（默认 <root>/config.json）")
    parser.add_argument("--gui", dest="gui", action="store_true", help="启用 GUI（默认原生窗口套壳）")
    parser.add_argument("--web-console", dest="web", action="store_true", help="GUI 用浏览器控制台而不是原生窗口")
    parser.add_argument("--no-gui", dest="gui", action="store_false", help="纯命令行（默认）")
    parser.add_argument("--no-connect", dest="connect", action="store_false", help="不连 QQ（只跑框架与控制台）")
    parser.add_argument("--gui-selftest", action="store_true", help="建一遍界面并打印自检结果后退出")
    parser.add_argument("--dry-run", action="store_true", help="只加载插件并打印状态")
    parser.add_argument("--list-commands", action="store_true", help="打印命令表后退出")
    parser.set_defaults(gui=None, connect=True)
    return parser


def run_native_gui(args: argparse.Namespace) -> int:
    """原生窗口模式：tkinter 主线程 + 框架工作线程。"""
    from framework.gui.shell import AppShell

    root = Path(args.root).resolve()
    app = FapApp(root, gui=True, config_path=(Path(args.config) if args.config else None))
    connect = bool(args.connect) and not (args.dry_run or args.list_commands)
    AppShell(app, connect=connect).run()
    return 0


async def _run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    gui = bool(args.gui) if args.gui is not None else False
    app = FapApp(
        root,
        gui=gui,
        config_path=(Path(args.config) if args.config else None),
    )
    connect = bool(args.connect) and not (args.dry_run or args.list_commands)
    await app.start(connect=connect)
    if args.list_commands:
        print(app.commands.help_text(scope="both", roles=["owner", "admin"]))
        await app.stop()
        return 0
    if args.dry_run:
        print(json.dumps(app.status(), ensure_ascii=False, indent=2))
        await app.stop()
        return 0
    await asyncio.Event().wait()
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "web", False):
        import os

        os.environ["FAP_GUI_MODE"] = "web"
    if getattr(args, "gui_selftest", False):
        import json

        from framework.gui.shell import AppShell

        root = Path(args.root).resolve()
        app = FapApp(root, gui=True, config_path=(Path(args.config) if args.config else None))
        summary = AppShell(app, connect=False).selftest()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.gui and not getattr(args, "web", False) and not (args.dry_run or args.list_commands):
        try:
            return run_native_gui(args)
        except Exception as error:  # noqa: BLE001 - 没有图形环境就退回命令行
            print("原生窗口启动失败（" + str(error) + "），改用命令行模式")
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("bye")
        return 0


if __name__ == "__main__":
    sys.exit(main())

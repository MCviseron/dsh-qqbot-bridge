"""命令行入口：

    python -m framework.cli --no-gui          # 非 GUI（本项目用法）
    python -m framework.cli --gui             # GUI 版本（额外起本地面板）
    python -m framework.cli --dry-run         # 只加载插件并打印状态，不连 QQ
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
    parser.add_argument("--gui", dest="gui", action="store_true", help="启用 GUI 面板")
    parser.add_argument("--no-gui", dest="gui", action="store_false", help="纯命令行（默认）")
    parser.add_argument("--dry-run", action="store_true", help="只加载插件并打印状态")
    parser.add_argument("--list-commands", action="store_true", help="打印命令表后退出")
    parser.set_defaults(gui=None)
    return parser


async def _run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    gui = bool(args.gui) if args.gui is not None else False
    app = FapApp(
        root,
        gui=gui,
        config_path=(Path(args.config) if args.config else None),
    )
    await app.start(connect=not (args.dry_run or args.list_commands))
    if args.list_commands:
        print(app.commands.help_text(scope="both", is_owner=True))
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
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("bye")
        return 0


if __name__ == "__main__":
    sys.exit(main())

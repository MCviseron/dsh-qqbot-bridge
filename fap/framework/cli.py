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
    parser.add_argument("--web-console", dest="web", action="store_true", help="只起控制台服务并打印地址（不套窗口）")
    parser.add_argument("--gui-mode", default="", choices=["", "app", "web"], help="覆盖 config 的 gui_mode")
    parser.add_argument("--no-gui", dest="gui", action="store_false", help="纯命令行（默认）")
    parser.add_argument("--no-connect", dest="connect", action="store_false", help="不连 QQ（只跑框架与控制台）")
    parser.add_argument("--gui-selftest", action="store_true", help="建一遍界面并打印自检结果后退出")

    parser.add_argument("--dry-run", action="store_true", help="只加载插件并打印状态")
    parser.add_argument("--list-commands", action="store_true", help="打印命令表后退出")
    parser.set_defaults(gui=None, connect=True, gui_mode="")
    return parser


def gui_url(app: Any) -> str:
    host = str(app.config.get("gui_host", "127.0.0.1"))
    port = int(app.config.get("gui_port", 39080))
    return "http://" + host + ":" + str(port) + "/"


def run_window(args: argparse.Namespace) -> int:
    """GUI 应用窗口：后台跑框架，主线程开一个无地址栏的 Chromium 窗口，关窗即退出。"""
    import threading
    import time

    from framework.gui.app_window import AppWindow

    root = Path(args.root).resolve()
    app = FapApp(root, gui=True, config_path=(Path(args.config) if args.config else None))
    connect = bool(args.connect) and not (args.dry_run or args.list_commands)
    ready = threading.Event()

    def boot() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app.loop = loop

        async def main() -> None:
            await app.start(connect=connect)
            ready.set()
            await asyncio.Event().wait()

        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()

    thread = threading.Thread(target=boot, name="fap-app", daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not ready.is_set() and time.time() < deadline:
        time.sleep(0.1)
    if not ready.is_set():
        print("框架启动超时，看看 " + str(root / "session" / "logs" / "fap.log"))
        return 1
    url = gui_url(app)
    mode = AppWindow(root / "session" / "window-profile").open_blocking(url)
    print("窗口关闭（形态：" + mode + "），正在停止框架…")
    try:
        asyncio.run_coroutine_threadsafe(app.stop(), app.loop).result(timeout=15)
    except Exception:  # noqa: BLE001
        pass
    return 0


def selftest(args: argparse.Namespace) -> int:
    """无头自检：起服务端 → 逐个打接口 → 打印摘要 → 停止。"""
    import json
    import threading
    import time
    import urllib.request

    root = Path(args.root).resolve()
    app = FapApp(root, gui=True, config_path=(Path(args.config) if args.config else None))
    ready = threading.Event()

    def boot() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app.loop = loop

        async def main() -> None:
            await app.start(connect=False)
            ready.set()
            await asyncio.Event().wait()

        try:
            loop.run_until_complete(main())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()

    thread = threading.Thread(target=boot, name="fap-app", daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not ready.is_set() and time.time() < deadline:
        time.sleep(0.1)

    url = gui_url(app)

    def fetch(path: str) -> Any:
        with urllib.request.urlopen(url.rstrip("/") + path, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    summary: Dict[str, Any] = {"url": url}
    try:
        status = fetch("/api/status")
        summary["status"] = {
            "version": status.get("version"),
            "connected": status.get("connected"),
            "commands": status.get("commands"),
            "plugins": len(status.get("plugins", [])),
            "issues": len(status.get("issues", [])),
        }
        summary["framework_settings"] = len(fetch("/api/settings")["fields"])
        plugins = fetch("/api/plugins")
        summary["plugins"] = [{"id": row["id"], "commands": row["commands"], "loaded": row["loaded"]} for row in plugins]
        detail = fetch("/api/plugins/" + plugins[0]["id"])["plugin"]
        summary["plugin_detail"] = {
            "id": detail["id"],
            "commands": len(detail["commands"]),
            "settings": len(detail["settings"]),
            "pages": len(detail["pages"]),
        }
        summary["traffic_buckets"] = len(fetch("/api/traffic?minutes=10")["buckets"])
        summary["events"] = len(fetch("/api/events?since=0")["events"])
        summary["logs"] = len(fetch("/api/logs?lines=20")["lines"])
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        try:
            asyncio.run_coroutine_threadsafe(app.stop(), app.loop).result(timeout=15)
        except Exception:  # noqa: BLE001
            pass
    return 0


async def _run(args: argparse.Namespace, *, print_url: bool = False) -> int:
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
    if print_url:
        print("控制台：" + gui_url(app) + "（Ctrl+C 停止）")
    await asyncio.Event().wait()
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "web", False):
        args.gui_mode = "web"
        args.gui = True
    if args.gui_mode:
        import os

        os.environ["FAP_GUI_MODE"] = args.gui_mode
    if getattr(args, "gui_selftest", False):
        return selftest(args)
    if args.gui and not (args.dry_run or args.list_commands):
        if args.gui_mode == "web":
            return asyncio.run(_run(args, print_url=True))
        return run_window(args)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("bye")
        return 0


if __name__ == "__main__":
    sys.exit(main())

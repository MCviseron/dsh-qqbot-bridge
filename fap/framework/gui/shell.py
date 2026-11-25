"""GUI 的「应用套壳」：一个原生窗口（tkinter），把框架装进去。

不是浏览器页面，而是一个桌面窗口：左侧导航、右侧内容，直接读框架进程内状态
（不需要 HTTP，所以也没有 aiohttp 访问日志刷屏）。

    python -m framework.cli --gui                # 原生窗口
    python -m framework.cli --gui --no-connect   # 只看界面，不连 QQ
    python -m framework.cli --gui --web-console  # 换成浏览器控制台

窗口关闭 = 框架停止（会走一遍 stop()，插件 teardown 都会执行）。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Dict, List, Optional

from framework.logging import get

log = get("gui.shell")


class AppShell:
    """tkinter 套壳：主线程跑窗口，工作线程跑 asyncio（框架本体）。"""

    def __init__(self, app: Any, *, connect: bool = True) -> None:
        self.app = app
        self.connect = connect
        self.root: Any = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Any = None
        self._last_seq = 0
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None

    # -- 启动 ---------------------------------------------------------------
    def run(self) -> None:
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("fap 控制台")
        self.root.geometry("1080x720")
        self.root.minsize(880, 560)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._thread = threading.Thread(target=self._run_app, name="fap-app", daemon=True)
        self._thread.start()
        self._tick()
        self.root.mainloop()

    def _run_app(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self.app.loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.app.start(connect=self.connect))
        except BaseException as error:  # noqa: BLE001 - 启动失败要显示在界面上
            self._error = error
            log.exception("framework start failed: %s", error)
        finally:
            self._ready.set()
        loop.run_forever()

    def _submit(self, coro) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # -- 界面 ---------------------------------------------------------------
    def _build(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        header = ttk.Frame(self.root, padding=(12, 8))
        header.pack(fill="x")
        ttk.Label(header, text="fap 控制台", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="启动中…")
        ttk.Label(header, textvariable=self.status_var, foreground="#666").pack(side="left", padx=14)

        body = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill="both", expand=True)

        self._build_overview()
        self._build_plugins()
        self._build_commands()
        self._build_events()
        self._build_pages()
        self._build_logs()

    def _tab(self, title: str) -> Any:
        from tkinter import ttk

        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=title)
        return frame

    def _tree(self, parent: Any, columns: List[str], widths: List[int]) -> Any:
        from tkinter import ttk

        tree = ttk.Treeview(parent, columns=columns, show="headings", height=16)
        for name, width in zip(columns, widths):
            tree.heading(name, text=name)
            tree.column(name, width=width, anchor="w")
        tree.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        return tree

    def _build_overview(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._tab("概览")
        self.kpi_var = tk.StringVar(value="—")
        ttk.Label(frame, textvariable=self.kpi_var, font=("Consolas", 10)).pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="定时任务").pack(anchor="w")
        self.job_tree = self._tree(frame, ["任务", "执行次数", "错误"], [220, 100, 80])

    def _build_plugins(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._tab("插件")
        self.plugin_tree = self._tree(frame, ["id", "名称", "版本", "命令", "状态"], [160, 200, 80, 70, 90])
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=6, side="bottom")
        for label, action in (("重载", "reload"), ("卸载", "disable"), ("加载", "enable")):
            ttk.Button(row, text=label, command=lambda a=action: self._plugin_action(a)).pack(side="left", padx=4)
        ttk.Label(row, text="先选中一行，再点按钮（直接作用于当前进程）", foreground="#666").pack(side="left", padx=8)

    def _build_commands(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._tab("命令")
        self.cmd_filter = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.cmd_filter)
        entry.pack(fill="x", pady=(0, 6))
        entry.bind("<KeyRelease>", lambda _event: self._refresh_commands())
        self.cmd_tree = self._tree(frame, ["命令", "别名", "说明", "范围", "权限", "插件"], [150, 120, 260, 70, 70, 110])

    def _build_events(self) -> None:
        import tkinter as tk

        frame = self._tab("事件")
        self.event_text = tk.Text(frame, height=18, wrap="none")
        self.event_text.pack(fill="both", expand=True)

    def _build_pages(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._tab("插件页面")
        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="页面").pack(side="left")
        self.page_choice = ttk.Combobox(top, values=[], state="readonly", width=32)
        self.page_choice.pack(side="left", padx=6)
        ttk.Button(top, text="刷新", command=self._refresh_pages).pack(side="left")
        self.page_text = tk.Text(frame, height=16, wrap="none")
        self.page_text.pack(fill="both", expand=True)
        self.page_choice.bind("<<ComboboxSelected>>", lambda _event: self._render_page())

    def _build_logs(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._tab("日志")
        self.log_text = tk.Text(frame, height=18, wrap="none")
        self.log_text.pack(fill="both", expand=True)
        ttk.Label(frame, text="显示 session/logs/fap.log 的尾部，2 秒刷新", foreground="#666").pack(anchor="w")

    # -- 刷新 ---------------------------------------------------------------
    def _tick(self) -> None:
        try:
            self._refresh_status()
            self._refresh_events()
            if int(time.time()) % 2 == 0:
                self._refresh_logs()
        finally:
            if self.root is not None:
                self.root.after(1000, self._tick)

    def _refresh_status(self) -> None:
        if self._error is not None:
            self.status_var.set("启动失败：" + str(self._error))
            return
        status = self.app.status()
        connected = status.get("connected")
        self.status_var.set(
            ("QQ 已连接" if connected else "QQ 未连接")
            + " · v" + str(status.get("version"))
            + " · " + str(status.get("uptime_s")) + "s"
            + " · 插件 " + str(len([p for p in status.get("plugins", []) if p.get("loaded")]))
            + "/" + str(len(status.get("plugins", [])))
        )
        stats = status.get("stats", {})
        self.kpi_var.set(
            "收到消息 {in}    发出回复 {out}    命令执行 {commands}    错误 {errors}    命令总数 {total}".format(
                total=status.get("commands"), **{"in": stats.get("in", 0), "out": stats.get("out", 0),
                                                 "commands": stats.get("commands", 0), "errors": stats.get("errors", 0)}
            )
        )
        self._fill(self.job_tree, [[job["name"], job["runs"], job["errors"]] for job in status.get("jobs", [])])
        self._fill(self.plugin_tree, [
            [row["id"], row["name"], row["version"], row["commands"], "已加载" if row["loaded"] else "未加载"]
            for row in status.get("plugins", [])
        ])
        self._refresh_commands()
        self._refresh_pages()

    def _refresh_commands(self) -> None:
        needle = (self.cmd_filter.get() if hasattr(self, "cmd_filter") else "").strip().lower()
        rows = []
        for command in self.app.commands.unique():
            blob = (command.name + " " + command.plugin + " " + command.summary).lower()
            if needle and needle not in blob:
                continue
            rows.append([
                "/" + command.name + (" " + command.usage if command.usage else ""),
                ", ".join(command.aliases) or "-",
                command.summary or "-",
                command.scope,
                command.requires or "-",
                command.plugin or "framework",
            ])
        self._fill(self.cmd_tree, rows)

    def _refresh_events(self) -> None:
        rows = self.app.events.history(since=self._last_seq, limit=80)
        if not rows:
            return
        for row in rows:
            self._last_seq = max(self._last_seq, int(row.get("seq", 0)))
            when = time.strftime("%H:%M:%S", time.localtime(float(row.get("at", 0))))
            extra = ""
            if row.get("convKey"):
                extra = " · " + str(row["convKey"])[-8:] + (("：" + str(row["text"])) if row.get("text") else "")
            self.event_text.insert("end", when + " · " + str(row.get("event")) + extra + "\n")
        self.event_text.see("end")

    def _refresh_pages(self) -> None:
        pages = list((self.app.gui.pages if self.app.gui is not None else {}).items())
        titles = [value["title"] for _key, value in pages]
        if list(self.page_choice["values"]) != titles:
            self.page_choice["values"] = titles
            if titles and not self.page_choice.get():
                self.page_choice.current(0)
                self._render_page()

    def _render_page(self) -> None:
        gui = self.app.gui
        if gui is None:
            return
        title = self.page_choice.get()
        for key, value in gui.pages.items():
            if value["title"] != title:
                continue
            try:
                data = value["render"]()
            except Exception as error:  # noqa: BLE001 - 页面渲染失败要显示原因
                data = {"error": str(error)}
            self.page_text.delete("1.0", "end")
            self.page_text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
            return

    def _refresh_logs(self) -> None:
        from pathlib import Path

        path = Path(self.app.root) / str(self.app.config.get("log_dir", "session/logs")) / "fap.log"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
        except OSError:
            return
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(lines))
        self.log_text.see("end")

    def _fill(self, tree: Any, rows: List[List[Any]]) -> None:
        existing = tree.get_children()
        signature = [tuple(str(cell) for cell in row) for row in rows]
        current = [tuple(str(value) for value in tree.item(item, "values")) for item in existing]
        if signature == current:
            return
        for item in existing:
            tree.delete(item)
        for row in rows:
            tree.insert("", "end", values=row)

    # -- 操作 ---------------------------------------------------------------
    def _plugin_action(self, action: str) -> None:
        selection = self.plugin_tree.selection()
        if not selection:
            self.status_var.set("先在「插件」里选中一行")
            return
        plugin_id = str(self.plugin_tree.item(selection[0], "values")[0])
        registry = self.app.plugins
        if action == "reload":
            self._submit(registry.reload(plugin_id))
        elif action == "disable":
            self._submit(registry.unload(plugin_id))
        elif action == "enable":
            self._submit(registry.load(plugin_id))
        self.status_var.set("已提交：" + action + " " + plugin_id)

    def _on_close(self) -> None:
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop).result(timeout=10)
            except Exception:  # noqa: BLE001 - 关窗失败也要退
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self.root is not None:
            self.root.destroy()

    # -- 自检（无头验证界面能建、能读数据）---------------------------------
    def selftest(self, rounds: int = 6) -> dict:
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()
        self._build()
        self._thread = threading.Thread(target=self._run_app, name="fap-app", daemon=True)
        self._thread.start()
        for _ in range(rounds):
            self.root.update()
            self.root.after(400, lambda: None)
            try:
                self.root.update_idletasks()
            except Exception:  # noqa: BLE001
                pass
            threading.Event().wait(0.4)
            if self._ready.is_set():
                self._refresh_status()
                self._refresh_events()
                self._refresh_logs()
        summary = {
            "status": self.status_var.get(),
            "kpi": self.kpi_var.get(),
            "plugins": len(self.plugin_tree.get_children()),
            "commands": len(self.cmd_tree.get_children()),
            "jobs": len(self.job_tree.get_children()),
            "events_chars": len(self.event_text.get("1.0", "end").strip()),
            "log_chars": len(self.log_text.get("1.0", "end").strip()),
            "page_values": list(self.page_choice["values"]),
            "error": str(self._error) if self._error else "",
        }
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop).result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()
        return summary

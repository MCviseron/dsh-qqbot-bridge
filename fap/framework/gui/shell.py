"""GUI 的「应用套壳」：原生桌面窗口（tkinter），把框架装进去。

设计目标：像一个真正的管理应用——左侧导航、卡片式概览、表单化设置、插件主从视图、
事件流、日志。所有数据都直接读框架进程内状态，不走 HTTP（也就没有访问日志刷屏）。

页面：仪表盘 / 设置 / 插件（含子页：命令、设置、页面）/ 命令 / 事件 / 日志 / 插件页面
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from framework.logging import get

log = get("gui.shell")

# ---- 配色（深色侧栏 + 浅色内容，接近常见桌面应用） ----
C_SIDEBAR = "#171a21"
C_SIDEBAR_ACTIVE = "#242a35"
C_SIDEBAR_TEXT = "#c9d1dc"
C_ACCENT = "#2f6bff"
C_BG = "#f4f6f9"
C_CARD = "#ffffff"
C_LINE = "#e2e6ec"
C_TEXT = "#1b1f27"
C_MUTED = "#6b7280"
C_OK = "#16a34a"
C_BAD = "#dc2626"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_SMALL = ("Segoe UI", 9)
MONO = ("Consolas", 9)


class AppShell:
    def __init__(self, app: Any, *, connect: bool = True) -> None:
        self.app = app
        self.connect = connect
        self.root: Any = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Any = None
        self._last_seq = 0
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._pages: Dict[str, Any] = {}
        self._nav_buttons: Dict[str, Any] = {}
        self.current = "dashboard"
        self._plugin_detail: Dict[str, Any] = {}
        self._forms: Dict[str, Dict[str, Any]] = {}
        self._event_paused = False
        self._event_filter = None
        self._log_follow = True

    # ---------------------------------------------------------------- 启动
    def run(self) -> None:
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("fap 控制台")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self._style()
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
        except BaseException as error:  # noqa: BLE001
            self._error = error
            log.exception("framework start failed: %s", error)
        finally:
            self._ready.set()
        loop.run_forever()

    def _submit(self, coro) -> Any:
        if self._loop is None:
            return None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ---------------------------------------------------------------- 样式
    def _style(self) -> None:
        from tkinter import ttk

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=FONT, background=C_BG, foreground=C_TEXT)
        style.configure("TFrame", background=C_BG)
        style.configure("Card.TFrame", background=C_CARD, relief="flat")
        style.configure("TLabel", background=C_BG, foreground=C_TEXT)
        style.configure("Card.TLabel", background=C_CARD, foreground=C_TEXT)
        style.configure("Muted.TLabel", background=C_CARD, foreground=C_MUTED, font=FONT_SMALL)
        style.configure("Title.TLabel", background=C_CARD, foreground=C_TEXT, font=FONT_TITLE)
        style.configure("Kpi.TLabel", background=C_CARD, foreground=C_TEXT, font=("Segoe UI", 18, "bold"))
        style.configure("Side.TButton", background=C_SIDEBAR, foreground=C_SIDEBAR_TEXT, borderwidth=0,
                        anchor="w", padding=(14, 10), font=FONT)
        style.map("Side.TButton", background=[("active", C_SIDEBAR_ACTIVE)])
        style.configure("Accent.TButton", background=C_ACCENT, foreground="#ffffff", borderwidth=0, padding=(12, 6))
        style.map("Accent.TButton", background=[("active", "#2559d8")])
        style.configure("TButton", padding=(10, 5))
        style.configure("Treeview", background=C_CARD, fieldbackground=C_CARD, rowheight=24, font=MONO)
        style.configure("Treeview.Heading", background="#eef1f5", foreground=C_MUTED, font=FONT_SMALL)
        style.configure("TNotebook", background=C_BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 7))
        style.configure("TEntry", fieldbackground="#ffffff")
        style.configure("TCheckbutton", background=C_CARD)
        self.root.configure(background=C_BG)

    # ---------------------------------------------------------------- 布局
    def _build(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        sidebar = tk.Frame(self.root, bg=C_SIDEBAR, width=196)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=C_SIDEBAR)
        brand.pack(fill="x", padx=16, pady=(18, 6))
        tk.Label(brand, text="fap", bg=C_SIDEBAR, fg="#ffffff", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        import framework

        tk.Label(brand, text="frame + plugin · v" + framework.__version__, bg=C_SIDEBAR, fg="#7f8a99",
                 font=FONT_SMALL).pack(anchor="w")

        nav = tk.Frame(sidebar, bg=C_SIDEBAR)
        nav.pack(fill="both", expand=True, pady=(12, 0))
        for key, label in (
            ("dashboard", "仪表盘"),
            ("settings", "设置"),
            ("plugins", "插件"),
            ("commands", "命令"),
            ("events", "事件"),
            ("logs", "日志"),
            ("pages", "插件页面"),
        ):
            button = tk.Button(nav, text="  " + label, bg=C_SIDEBAR, fg=C_SIDEBAR_TEXT, bd=0, anchor="w",
                               activebackground=C_SIDEBAR_ACTIVE, activeforeground="#ffffff",
                               font=FONT, padx=14, pady=9, highlightthickness=0,
                               command=lambda k=key: self.show(k))
            button.pack(fill="x", padx=8, pady=1)
            self._nav_buttons[key] = button

        self.side_status = tk.Label(sidebar, text="启动中…", bg=C_SIDEBAR, fg="#7f8a99", font=FONT_SMALL,
                                    justify="left", wraplength=170, padx=16, pady=12)
        self.side_status.pack(side="bottom", fill="x")

        right = tk.Frame(self.root, bg=C_BG)
        right.pack(side="left", fill="both", expand=True)
        header = tk.Frame(right, bg=C_BG)
        header.pack(fill="x", padx=18, pady=(16, 4))
        self.title_var = tk.StringVar(value="仪表盘")
        tk.Label(header, textvariable=self.title_var, bg=C_BG, fg=C_TEXT, font=FONT_TITLE).pack(side="left")
        self.subtitle_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.subtitle_var, bg=C_BG, fg=C_MUTED, font=FONT_SMALL).pack(side="left", padx=12)

        self.body = tk.Frame(right, bg=C_BG)
        self.body.pack(fill="both", expand=True, padx=18, pady=(6, 8))

        status_bar = tk.Frame(right, bg="#eceff3")
        status_bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="—")
        tk.Label(status_bar, textvariable=self.status_var, bg="#eceff3", fg=C_MUTED, font=FONT_SMALL,
                 anchor="w", padx=12, pady=5).pack(fill="x")

        self._build_dashboard()
        self._build_settings()
        self._build_plugins()
        self._build_commands()
        self._build_events()
        self._build_logs()
        self._build_pages()
        self.show("dashboard")

    # ------------------------------------------------------------ 通用部件
    def _card(self, parent: Any, title: str = "") -> Any:
        import tkinter as tk

        outer = tk.Frame(parent, bg=C_CARD, highlightbackground=C_LINE, highlightthickness=1)
        outer.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(outer, bg=C_CARD)
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        if title:
            tk.Label(inner, text=title, bg=C_CARD, fg=C_TEXT, font=FONT_BOLD).pack(anchor="w", pady=(0, 8))
        return inner

    def _table(self, parent: Any, columns: List[str], widths: List[int], height: int = 10) -> Any:
        import tkinter as tk
        from tkinter import ttk

        wrap = tk.Frame(parent, bg=C_CARD)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=columns, show="headings", height=height)
        for name, width in zip(columns, widths):
            tree.heading(name, text=name)
            tree.column(name, width=width, anchor="w")
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    def _form(self, parent: Any, owner: str) -> Dict[str, Any]:
        """按设置声明画表单，返回 {key: (spec, var, widget)}。"""
        import tkinter as tk
        from tkinter import ttk

        rows: Dict[str, Any] = {}
        config = self.app.config
        snapshot = config.snapshot(mask_secrets=False)
        section = snapshot.get("plugins", {}).get(owner, {}) if owner else snapshot
        for spec in self.app.settings.specs(owner):
            row = tk.Frame(parent, bg=C_CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=spec.label, bg=C_CARD, fg=C_TEXT, width=18, anchor="w").pack(side="left")
            value = section.get(spec.key, spec.default)
            if spec.kind == "bool":
                var = tk.BooleanVar(value=bool(value))
                widget = ttk.Checkbutton(row, variable=var)
            elif spec.kind == "choice":
                var = tk.StringVar(value=str(value))
                widget = ttk.Combobox(row, textvariable=var, values=spec.choices, state="readonly", width=24)
            else:
                if spec.kind == "list":
                    text = ", ".join(str(item) for item in (value or []))
                else:
                    text = "" if value is None else str(value)
                var = tk.StringVar(value=text)
                widget = ttk.Entry(row, textvariable=var, width=34,
                                   show=("•" if spec.kind == "secret" else ""))
            widget.pack(side="left")
            if spec.help:
                tk.Label(row, text=spec.help, bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(side="left", padx=10)
            rows[spec.key] = (spec, var, widget)
        return rows

    def _fill(self, tree: Any, rows: List[List[Any]]) -> None:
        signature = [tuple(str(cell) for cell in row) for row in rows]
        current = [tuple(str(value) for value in tree.item(item, "values")) for item in tree.get_children()]
        if signature == current:
            return
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tree.insert("", "end", values=row)

    # -------------------------------------------------------------- 仪表盘
    def _build_dashboard(self) -> None:
        import tkinter as tk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["dashboard"] = page

        cards = tk.Frame(page, bg=C_BG)
        cards.pack(fill="x", pady=(0, 12))
        self.kpi_vars: Dict[str, Any] = {}
        for key, label in (("in", "收到消息"), ("out", "发出回复"), ("commands", "命令执行"),
                           ("errors", "错误"), ("total", "命令总数"), ("plugins", "已加载插件")):
            box = tk.Frame(cards, bg=C_CARD, highlightbackground=C_LINE, highlightthickness=1)
            box.pack(side="left", fill="both", expand=True, padx=(0, 10))
            tk.Label(box, text=label, bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(anchor="w", padx=12, pady=(10, 0))
            var = tk.StringVar(value="0")
            tk.Label(box, textvariable=var, bg=C_CARD, fg=C_TEXT, font=("Segoe UI", 17, "bold")).pack(
                anchor="w", padx=12, pady=(0, 10))
            self.kpi_vars[key] = var

        info = self._card(page, "连接信息")
        self.info_var = tk.StringVar(value="—")
        tk.Label(info, textvariable=self.info_var, bg=C_CARD, fg=C_TEXT, font=MONO, justify="left").pack(anchor="w")

        jobs = self._card(page, "定时任务")
        self.job_tree = self._table(jobs, ["任务", "执行次数", "错误"], [260, 110, 90], height=3)

        recent = self._card(page, "最近事件")
        self.dash_event_text = tk.Text(recent, height=7, wrap="none", font=MONO, bg="#fbfcfd", bd=0)
        self.dash_event_text.pack(fill="both", expand=True)

    # -------------------------------------------------------------- 设置
    def _build_settings(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["settings"] = page

        card = self._card(page, "框架设置")
        tk.Label(card, text="保存后写入 config.json 并即时生效；AppSecret 只显示掩码。", bg=C_CARD, fg=C_MUTED,
                 font=FONT_SMALL).pack(anchor="w", pady=(0, 8))
        canvas = tk.Canvas(card, bg=C_CARD, highlightthickness=0, height=380)
        canvas.pack(fill="both", expand=True)
        self.settings_form_area = tk.Frame(canvas, bg=C_CARD)
        canvas.create_window((0, 0), window=self.settings_form_area, anchor="nw")
        self.settings_form_area.bind(
            "<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))

        bar = tk.Frame(card, bg=C_CARD)
        bar.pack(fill="x", pady=(10, 0))
        tk.Button(bar, text="保存", bg=C_ACCENT, fg="#ffffff", bd=0, padx=16, pady=6,
                  activebackground="#2559d8", command=self._save_framework_settings).pack(side="left")
        tk.Button(bar, text="重新读取", bd=1, padx=12, pady=6,
                  command=self._reload_settings_form).pack(side="left", padx=8)
        self.settings_hint = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.settings_hint, bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(side="left", padx=10)

    def _reload_settings_form(self) -> None:
        for child in self.settings_form_area.winfo_children():
            child.destroy()
        self._forms[""] = self._form(self.settings_form_area, "")
        self.settings_hint.set("已重新读取配置文件")

    def _save_framework_settings(self) -> None:
        rows = self._forms.get("") or {}
        values = {key: item[1].get() for key, item in rows.items()}
        self.app.save_settings(values, owner="")
        self.settings_hint.set("已保存 " + time.strftime("%H:%M:%S"))
        self._refresh_status()

    # -------------------------------------------------------------- 插件
    def _build_plugins(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["plugins"] = page

        split = tk.Frame(page, bg=C_BG)
        split.pack(fill="both", expand=True)

        left = tk.Frame(split, bg=C_CARD, highlightbackground=C_LINE, highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 12))
        tk.Label(left, text="插件", bg=C_CARD, fg=C_TEXT, font=FONT_BOLD).pack(anchor="w", padx=12, pady=(10, 6))
        self.plugin_tree = ttk.Treeview(left, columns=["id", "版本", "状态"], show="headings", height=14)
        for name, width in (("id", 130), ("版本", 70), ("状态", 70)):
            self.plugin_tree.heading(name, text=name)
            self.plugin_tree.column(name, width=width, anchor="w")
        self.plugin_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.plugin_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_plugin_detail())

        right = tk.Frame(split, bg=C_CARD, highlightbackground=C_LINE, highlightthickness=1)
        right.pack(side="left", fill="both", expand=True)
        self.plugin_title = tk.StringVar(value="选择左侧插件")
        tk.Label(right, textvariable=self.plugin_title, bg=C_CARD, fg=C_TEXT, font=FONT_TITLE).pack(
            anchor="w", padx=14, pady=(12, 2))
        self.plugin_desc = tk.StringVar(value="")
        tk.Label(right, textvariable=self.plugin_desc, bg=C_CARD, fg=C_MUTED, font=FONT_SMALL,
                 wraplength=620, justify="left").pack(anchor="w", padx=14)

        bar = tk.Frame(right, bg=C_CARD)
        bar.pack(fill="x", padx=14, pady=10)
        for label, action in (("重载", "reload"), ("卸载", "disable"), ("加载", "enable")):
            tk.Button(bar, text=label, bd=1, padx=14, pady=5,
                      command=lambda a=action: self._plugin_action(a)).pack(side="left", padx=(0, 8))

        self.plugin_tabs = ttk.Notebook(right)
        self.plugin_tabs.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.plugin_cmd_frame = tk.Frame(self.plugin_tabs, bg=C_CARD)
        self.plugin_tabs.add(self.plugin_cmd_frame, text="命令")
        self.plugin_setting_frame = tk.Frame(self.plugin_tabs, bg=C_CARD)
        self.plugin_tabs.add(self.plugin_setting_frame, text="设置")
        self.plugin_page_frame = tk.Frame(self.plugin_tabs, bg=C_CARD)
        self.plugin_tabs.add(self.plugin_page_frame, text="页面")

        self.plugin_cmd_tree = self._table(self.plugin_cmd_frame, ["命令", "说明", "权限"], [160, 320, 80], height=8)

        save_bar = tk.Frame(self.plugin_setting_frame, bg=C_CARD)
        self.plugin_setting_area = tk.Frame(self.plugin_setting_frame, bg=C_CARD)
        self.plugin_setting_area.pack(fill="both", expand=True)
        save_bar.pack(fill="x", pady=(8, 0))
        tk.Button(save_bar, text="保存该插件设置", bg=C_ACCENT, fg="#ffffff", bd=0, padx=14, pady=5,
                  command=self._save_plugin_settings).pack(side="left")
        self.plugin_setting_hint = tk.StringVar(value="")
        tk.Label(save_bar, textvariable=self.plugin_setting_hint, bg=C_CARD, fg=C_MUTED,
                 font=FONT_SMALL).pack(side="left", padx=10)

        self.plugin_page_text = tk.Text(self.plugin_page_frame, height=8, wrap="none", font=MONO,
                                        bg=C_CARD, bd=0)
        self.plugin_page_text.pack(fill="both", expand=True)
        tk.Button(self.plugin_page_frame, text="刷新页面数据", bd=1, padx=12, pady=4,
                  command=self._render_plugin_page).pack(anchor="w", pady=6)

    def _selected_plugin(self) -> str:
        selection = self.plugin_tree.selection()
        if not selection:
            return ""
        return str(self.plugin_tree.item(selection[0], "values")[0])

    def _show_plugin_detail(self) -> None:
        plugin_id = self._selected_plugin()
        if not plugin_id:
            return
        manifest = self.app.plugins.manifests.get(plugin_id)
        loaded = plugin_id in self.app.plugins.loaded
        self.plugin_title.set((manifest.name if manifest else plugin_id) + "  ·  v" + (manifest.version if manifest else "?"))
        self.plugin_desc.set(((manifest.description if manifest else "") or "") +
                             ("\n状态：" + ("已加载" if loaded else "未加载") +
                              "　目录：" + str(manifest.path if manifest else "")))
        self._fill(self.plugin_cmd_tree, [
            ["/" + command.name + (" " + command.usage if command.usage else ""), command.summary or "-",
             command.requires or "-"]
            for command in self.app.commands.unique() if command.plugin == plugin_id
        ])
        for child in self.plugin_setting_area.winfo_children():
            child.destroy()
        self._forms[plugin_id] = self._form(self.plugin_setting_area, plugin_id)
        self.plugin_setting_hint.set("")
        self._render_plugin_page()

    def _save_plugin_settings(self) -> None:
        plugin_id = self._selected_plugin()
        if not plugin_id:
            return
        rows = self._forms.get(plugin_id) or {}
        values = {key: item[1].get() for key, item in rows.items()}
        self.app.save_settings(values, owner=plugin_id)
        self.plugin_setting_hint.set("已保存 " + time.strftime("%H:%M:%S"))

    def _render_plugin_page(self) -> None:
        plugin_id = self._selected_plugin()
        gui = self.app.gui
        self.plugin_page_text.delete("1.0", "end")
        if gui is None or not plugin_id:
            return
        matched = [(key, value) for key, value in gui.pages.items() if value.get("plugin") == plugin_id]
        if not matched:
            self.plugin_page_text.insert("1.0", "（这个插件没有注册页面；可在 setup 里 ctx.page(...)）")
            return
        chunks = []
        for key, value in matched:
            try:
                data = value["render"]()
            except Exception as error:  # noqa: BLE001
                data = {"error": str(error)}
            chunks.append("# " + value["title"] + "（" + key + "）\n" + json.dumps(data, ensure_ascii=False, indent=2))
        self.plugin_page_text.insert("1.0", "\n\n".join(chunks))

    def _plugin_action(self, action: str) -> None:
        plugin_id = self._selected_plugin()
        if not plugin_id:
            return
        registry = self.app.plugins
        if action == "reload":
            self._submit(registry.reload(plugin_id))
        elif action == "disable":
            self._submit(registry.unload(plugin_id))
        elif action == "enable":
            self._submit(registry.load(plugin_id))
        self.plugin_setting_hint.set("已提交：" + action + " " + plugin_id)

    # -------------------------------------------------------------- 命令
    def _build_commands(self) -> None:
        import tkinter as tk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["commands"] = page
        card = self._card(page, "命令表")
        self.cmd_filter = tk.StringVar()
        entry = tk.Entry(card, textvariable=self.cmd_filter, bd=1, relief="solid")
        entry.pack(fill="x", pady=(0, 8))
        entry.bind("<KeyRelease>", lambda _event: self._refresh_commands())
        self.cmd_tree = self._table(card, ["命令", "别名", "说明", "范围", "权限", "插件"],
                                    [170, 130, 330, 70, 70, 120], height=16)

    # -------------------------------------------------------------- 事件
    def _build_events(self) -> None:
        import tkinter as tk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["events"] = page
        card = self._card(page, "事件流")
        bar = tk.Frame(card, bg=C_CARD)
        bar.pack(fill="x", pady=(0, 8))
        tk.Label(bar, text="过滤", bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(side="left")
        self._event_filter = tk.StringVar()
        tk.Entry(bar, textvariable=self._event_filter, width=26, bd=1, relief="solid").pack(side="left", padx=6)
        tk.Button(bar, text="暂停/继续", bd=1, padx=10, pady=3,
                  command=self._toggle_event_pause).pack(side="left", padx=4)
        tk.Button(bar, text="清空", bd=1, padx=10, pady=3,
                  command=lambda: self.event_text.delete("1.0", "end")).pack(side="left")
        self.event_hint = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.event_hint, bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(side="left", padx=8)
        self.event_text = tk.Text(card, height=20, wrap="none", font=MONO, bg="#fbfcfd", bd=0)
        self.event_text.pack(fill="both", expand=True)

    def _toggle_event_pause(self) -> None:
        self._event_paused = not self._event_paused
        self.event_hint.set("已暂停" if self._event_paused else "实时")

    # -------------------------------------------------------------- 日志
    def _build_logs(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["logs"] = page
        card = self._card(page, "运行日志")
        bar = tk.Frame(card, bg=C_CARD)
        bar.pack(fill="x", pady=(0, 8))
        tk.Label(bar, text="行数", bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(side="left")
        self.log_lines = tk.StringVar(value="200")
        ttk.Combobox(bar, textvariable=self.log_lines, values=["100", "200", "500"], width=6,
                     state="readonly").pack(side="left", padx=6)
        self.log_follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="自动滚到底部", variable=self.log_follow).pack(side="left", padx=8)
        tk.Button(bar, text="刷新", bd=1, padx=10, pady=3,
                  command=self._refresh_logs).pack(side="left")
        tk.Label(bar, text="session/logs/fap.log", bg=C_CARD, fg=C_MUTED, font=FONT_SMALL).pack(side="left", padx=8)
        self.log_text = tk.Text(card, height=20, wrap="none", font=MONO, bg="#fbfcfd", bd=0)
        self.log_text.pack(fill="both", expand=True)

    # -------------------------------------------------------------- 页面
    def _build_pages(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        page = tk.Frame(self.body, bg=C_BG)
        self._pages["pages"] = page
        card = self._card(page, "插件注册的页面")
        bar = tk.Frame(card, bg=C_CARD)
        bar.pack(fill="x", pady=(0, 8))
        self.page_choice = ttk.Combobox(bar, values=[], state="readonly", width=36)
        self.page_choice.pack(side="left")
        tk.Button(bar, text="渲染", bd=1, padx=12, pady=3, command=self._render_page).pack(side="left", padx=6)
        tk.Label(bar, text="插件在 setup 里用 ctx.page(key, 标题, 渲染函数) 注册", bg=C_CARD, fg=C_MUTED,
                 font=FONT_SMALL).pack(side="left", padx=8)
        self.page_text = tk.Text(card, height=20, wrap="none", font=MONO, bg="#fbfcfd", bd=0)
        self.page_text.pack(fill="both", expand=True)

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
            except Exception as error:  # noqa: BLE001
                data = {"error": str(error)}
            self.page_text.delete("1.0", "end")
            self.page_text.insert("1.0", "# " + key + "\n" + json.dumps(data, ensure_ascii=False, indent=2))
            return

    # -------------------------------------------------------------- 切换
    def show(self, key: str) -> None:
        if key not in self._pages:
            return
        self.current = key
        for page_key, frame in self._pages.items():
            frame.pack_forget()
        self._pages[key].pack(fill="both", expand=True)
        for nav_key, button in self._nav_buttons.items():
            button.configure(bg=(C_SIDEBAR_ACTIVE if nav_key == key else C_SIDEBAR),
                             fg=("#ffffff" if nav_key == key else C_SIDEBAR_TEXT))
        titles = {
            "dashboard": "仪表盘", "settings": "设置", "plugins": "插件", "commands": "命令",
            "events": "事件", "logs": "日志", "pages": "插件页面",
        }
        self.title_var.set(titles.get(key, key))
        extras = {
            "dashboard": "机器人状态、计数、定时任务",
            "settings": "AppID / AppSecret / 别名 / 白名单 …（写 config.json）",
            "plugins": "选中插件 → 右侧是它的命令、设置、页面",
            "commands": "全部命令，可搜索",
            "events": "框架内部事件流",
            "logs": "fap.log 尾部",
            "pages": "插件自己画的页面",
        }
        self.subtitle_var.set(extras.get(key, ""))
        if key == "settings" and not (self._forms.get("") or {}):
            self._reload_settings_form()
        if key == "commands":
            self._refresh_commands()
        if key == "plugins":
            self._refresh_plugins()

    # -------------------------------------------------------------- 刷新
    def _tick(self) -> None:
        try:
            self._refresh_status()
            if self.current == "events":
                self._refresh_events()
            elif self.current == "logs":
                self._refresh_logs()
            elif self.current == "pages":
                self._refresh_pages()
        finally:
            if self.root is not None:
                self.root.after(1000, self._tick)

    def _refresh_status(self) -> None:
        if self._error is not None:
            self.status_var.set("启动失败：" + str(self._error))
            self.side_status.configure(text="启动失败", fg="#ff8a8a")
            return
        status = self.app.status()
        connected = bool(status.get("connected"))
        plugins = status.get("plugins", [])
        loaded = len([row for row in plugins if row.get("loaded")])
        stats = status.get("stats", {})
        self.status_var.set(
            ("● QQ 已连接" if connected else "○ QQ 未连接")
            + "　运行 " + str(status.get("uptime_s", 0)) + "s"
            + "　消息 in/out " + str(stats.get("in", 0)) + "/" + str(stats.get("out", 0))
            + "　命令 " + str(stats.get("commands", 0))
            + "　错误 " + str(stats.get("errors", 0))
            + "　插件 " + str(loaded) + "/" + str(len(plugins))
        )
        self.side_status.configure(
            text=("● 已连接" if connected else "○ 未连接") + chr(10)
            + "运行 " + str(status.get("uptime_s", 0)) + "s" + chr(10)
            + "插件 " + str(loaded) + "/" + str(len(plugins)),
            fg=(C_OK if connected else "#7f8a99"),
        )
        if self.current == "dashboard":
            for key in ("in", "out", "commands", "errors"):
                self.kpi_vars[key].set(str(stats.get(key, 0)))
            self.kpi_vars["total"].set(str(status.get("commands", 0)))
            self.kpi_vars["plugins"].set(str(loaded))
            self.info_var.set(
                "状态　　：" + ("已连接 QQ" if connected else "未连接 QQ") + chr(10)
                + "版本　　：" + str(status.get("version")) + chr(10)
                + "控制台　：" + ("原生窗口" if not status.get("gui_mode") == "web" else "浏览器") + chr(10)
                + "配置　　：" + str(Path(self.app.root) / "config.json") + chr(10)
                + "权限角色：" + (", ".join(status.get("roles") or []) or "（无插件声明）")
            )
            self._fill(self.job_tree, [[job["name"], job["runs"], job["errors"]] for job in status.get("jobs", [])])
            rows = self.app.events.history(limit=12)
            self.dash_event_text.delete("1.0", "end")
            if not rows:
                self.dash_event_text.insert("1.0", "（还没有事件：发条消息、或点一下插件按钮就会有）")
            for row in rows:
                when = time.strftime("%H:%M:%S", time.localtime(float(row.get("at", 0))))
                extra = ("  " + str(row["convKey"])[-8:]) if row.get("convKey") else ""
                self.dash_event_text.insert("end", when + "  " + str(row.get("event")) + extra + chr(10))
        if self.current == "settings" and not (self._forms.get("") or {}):
            self._reload_settings_form()
        if self.current == "plugins":
            self._refresh_plugins()

    def _refresh_plugins(self) -> None:
        self._fill(self.plugin_tree, [
            [row["id"], row["version"], "已加载" if row["loaded"] else "未加载"]
            for row in self.app.plugins.status()
        ])

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
        if self._event_paused:
            return
        rows = self.app.events.history(since=self._last_seq, limit=80)
        if not rows:
            return
        needle = (self._event_filter.get() if self._event_filter is not None else "").strip().lower()
        for row in rows:
            self._last_seq = max(self._last_seq, int(row.get("seq", 0)))
            name = str(row.get("event"))
            if needle and needle not in (name + " " + str(row.get("convKey", ""))).lower():
                continue
            when = time.strftime("%H:%M:%S", time.localtime(float(row.get("at", 0))))
            extra = ""
            if row.get("convKey"):
                extra = "  " + str(row["convKey"])[-8:] + (("：" + str(row["text"])) if row.get("text") else "")
            self.event_text.insert("end", when + "  " + name + extra + "\n")
        self.event_text.see("end")

    def _refresh_logs(self) -> None:
        from pathlib import Path as _Path

        try:
            limit = int(self.log_lines.get())
        except (TypeError, ValueError):
            limit = 200
        path = _Path(self.app.root) / str(self.app.config.get("log_dir", "session/logs")) / "fap.log"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        except OSError:
            lines = ["（还没有日志）"]
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(lines))
        if self.log_follow.get():
            self.log_text.see("end")

    def _refresh_pages(self) -> None:
        gui = self.app.gui
        sections = []
        if gui is not None:
            for key, value in gui.pages.items():
                sections.append([key, value["title"], value.get("plugin", "")])
        titles = [row[1] for row in sections]
        if list(self.page_choice["values"]) != titles:
            self.page_choice["values"] = titles
            if titles and not self.page_choice.get():
                self.page_choice.current(0)
                self._render_page()

    # -------------------------------------------------------------- 关闭
    def _on_close(self) -> None:
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop).result(timeout=10)
            except Exception:  # noqa: BLE001
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self.root is not None:
            self.root.destroy()

    # -------------------------------------------------------------- 自检
    def selftest(self, rounds: int = 6) -> dict:
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()
        self._style()
        self._build()
        self._thread = threading.Thread(target=self._run_app, name="fap-app", daemon=True)
        self._thread.start()
        for _ in range(rounds):
            self.root.update()
            self.root.update_idletasks()
            threading.Event().wait(0.4)
            if self._ready.is_set():
                self._refresh_status()
                self._refresh_events()
                self._refresh_logs()
        self.show("settings")
        self.root.update()
        self.show("plugins")
        self.root.update()
        for item in self.plugin_tree.get_children()[:1]:
            self.plugin_tree.selection_set(item)
            self._show_plugin_detail()
        self.root.update()
        summary = {
            "pages": list(self._pages.keys()),
            "status": self.status_var.get(),
            "kpi": {key: var.get() for key, var in self.kpi_vars.items()},
            "framework_settings": len((self._forms.get("") or {})),
            "plugins": len(self.plugin_tree.get_children()),
            "plugin_settings": len(self._forms.get(self._selected_plugin()) or {}),
            "plugin_commands": len(self.plugin_cmd_tree.get_children()),
            "commands": len(self.cmd_tree.get_children()),
            "jobs": len(self.job_tree.get_children()),
            "error": str(self._error) if self._error else "",
        }
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop).result(timeout=10)
            except Exception:  # noqa: BLE001
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()
        return summary

    # ------------------------------------------------------------ 截图模式
    def shot(self, path: str, page: str = "dashboard", delay: float = 2.5) -> str:
        """打开窗口 → 切到指定页 → 停一会儿 → 截屏保存（用于验收/文档）。"""
        import tkinter as tk

        self.root = tk.Tk()
        self.root.title("fap 控制台")
        self.root.geometry("1180x760")
        self._style()
        self._build()
        self.show(page)
        self.root.update()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self._thread = threading.Thread(target=self._run_app, name="fap-app", daemon=True)
        self._thread.start()
        deadline = time.time() + delay
        while time.time() < deadline:
            self.root.update()
            self.root.update_idletasks()
            self._refresh_status()
            if page == "events":
                self._refresh_events()
            if page == "logs":
                self._refresh_logs()
            if page == "plugins":
                self._refresh_plugins()
                for item in self.plugin_tree.get_children()[:1]:
                    self.plugin_tree.selection_set(item)
                    self._show_plugin_detail()
                    break
            if page == "commands":
                self._refresh_commands()
            if page == "pages":
                self._refresh_pages()
                self._render_page()
            threading.Event().wait(0.12)
        self.root.attributes("-topmost", False)
        self.root.update()
        from PIL import ImageGrab

        image = ImageGrab.grab()
        # 只截窗口本身（避免把桌面其它内容带进文档）
        try:
            scale = image.width / max(1, self.root.winfo_screenwidth())
            left = int(self.root.winfo_rootx() * scale)
            top = int(self.root.winfo_rooty() * scale)
            right = left + int(self.root.winfo_width() * scale)
            bottom = top + int(self.root.winfo_height() * scale)
            image = image.crop((max(0, left), max(0, top), min(image.width, right), min(image.height, bottom)))
        except Exception:  # noqa: BLE001 - 裁切失败就整屏
            pass
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self.app.stop(), self._loop).result(timeout=10)
            except Exception:  # noqa: BLE001
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()
        return path

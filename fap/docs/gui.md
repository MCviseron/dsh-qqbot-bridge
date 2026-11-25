# GUI 版本：应用套壳（原生窗口）

GUI 不是「一个网页」，而是一个**桌面窗口套壳**：tkinter 原生窗口把框架装进去，
左边导航、右边内容，直接读框架进程内状态（不走 HTTP，所以也没有 aiohttp 访问日志刷屏）。

## 启动方式

| 方式 | 入口 | 说明 |
|---|---|---|
| 双击 | start-gui.bat | 原生窗口（连 QQ） |
| 双击 | start-console-only.bat | 原生窗口，不连 QQ（调界面/插件） |
| 双击 | start-web-console.bat | 浏览器控制台 http://127.0.0.1:39080/ |
| 双击 | start-nogui.bat | 无界面常驻 |
| 命令行 | python -m framework.cli --gui | 原生窗口 |
| 命令行 | python -m framework.cli --gui --web-console | 浏览器控制台 |

配置项 `gui_mode` 决定 `--gui` 用哪种：`app`（默认，原生窗口）/ `web`（浏览器控制台）。
关窗 = 停止框架（会执行 stop()，插件的 teardown 都会跑）。

## 窗口里有 6 个页签

| 页签 | 内容 |
|---|---|
| **概览** | 状态条（QQ 已连接/未连接 · 版本 · 运行时长 · 插件 3/3）+ KPI（收到消息/发出回复/命令执行/错误/命令总数）+ 定时任务表 |
| **插件** | id/名称/版本/命令数/状态；选中一行后点 **重载 / 卸载 / 加载**，立即作用于当前进程 |
| **命令** | 整张命令表（32 条）：命令、别名、说明、范围、所需角色、所属插件；顶部实时搜索 |
| **事件** | 框架 EventBus 的实时事件流（每秒增量追加） |
| **插件页面** | 插件通过 ctx.page() 注册的页面，下拉选择后渲染 JSON —— 插件可以在框架中注册页面 |
| **日志** | fap.log 尾部，2 秒刷新 |

## 实现要点

- 主线程跑 tkinter，工作线程跑 asyncio（框架本体）；界面操作通过
  `asyncio.run_coroutine_threadsafe` 投递到框架事件循环；
- 界面每秒轮询一次进程内状态（成本可忽略），不产生 HTTP 访问日志；
- 没有图形环境时 `--gui` 自动回退命令行，不会崩；
- 自检：`python -m framework.cli --gui-selftest` —— 建一遍窗口、读一遍数据后退出并打印摘要，
  可用于远程排障或 CI。

## 插件接入

```python
ctx.page("pets", "养成游戏", self.render_page)   # → 「插件页面」页签里出现
ctx.card("pets-top", self.render_card)           # 预留卡片位
```

`dsh_bridge` 的页面就是这样一个例子（进程状态 + 日志尾部）。

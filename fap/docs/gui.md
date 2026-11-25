# GUI：应用套壳（Chromium app 窗口 + Web 控制台）

GUI 分两层，各管一件事：

| 层 | 文件 | 职责 |
|---|---|---|
| **壳** | framework/gui/app_window.py | 用系统自带 Edge/Chrome 以 @@B@@--app=@@B@@ 模式开一个**没有地址栏/标签页**的窗口，独立 user-data-dir；关窗即执行 app.stop() |
| **界面** | framework/gui/index.html | 控制台本体（深色侧栏 + 卡片 + 表格 + 表单），长在下面的 HTTP API 上 |

如果系统没有 Edge/Chrome，会自动退回默认浏览器（带地址栏，功能一致）。

## 启动

| 入口 | 说明 |
|---|---|
| start-gui.bat | 应用窗口 + 连 QQ |
| start-console-only.bat | 应用窗口，不连 QQ（调界面/插件） |
| start-web-console.bat | 只起服务，用浏览器打开 http://127.0.0.1:39080/ |
| start-nogui.bat | 无界面常驻 |
| python -m framework.cli --gui | 同 start-gui.bat |
| python -m framework.cli --gui --web-console | 同 start-web-console.bat |
| python -m framework.cli --gui-selftest | 无头自检：起服务、逐个打接口、打印摘要 |

配置 @@B@@gui_mode@@B@@（app / web）决定 @@B@@--gui@@B@@ 的形态。

## 七个页面

![仪表盘](shots/fap-dashboard.png)

| 页面 | 功能 |
|---|---|
| **仪表盘** | 6 张 KPI 卡、最近 30 分钟收发柱状图、检查项（缺 AppID / 插件未加载 / 无插件页面…）、定时任务、运行信息 |
| **设置** | 按 SettingSpec 自动生成的表单：AppID、AppSecret（写入后仅存文件，界面留空表示不修改）、机器人名字、别名、命令前缀、群/私聊开关、白名单、单条上限、静默时段、限流、连接 QQ、控制台形态 |
| **插件** | 左侧插件列表，右侧详情 + 三个子页：**命令** / **设置** / **页面**，以及重载 / 卸载 / 加载 |
| **命令** | 32 条命令全表：命令、别名、说明、范围、权限、插件，实时搜索 |
| **事件** | EventBus 实时流，可过滤、暂停、清空 |
| **日志** | fap.log 尾部，行数可选、自动滚底 |
| **插件页面** | 插件 @ ctx.page() 注册的页面，选中渲染 JSON |

![设置页](shots/fap-settings.png)
![插件页](shots/fap-plugins.png)

## 后端接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | / | 控制台页面（no-store，改完刷新即最新） |
| GET | /api/status | 状态 + 统计 + 插件 + 页面 + 检查项 |
| GET | /api/plugins | 插件列表 |
| GET | /api/plugins/{id} | 插件详情（命令 / 设置 / 页面） |
| POST | /api/plugins/{id}/{reload\|disable\|enable} | 热操作 |
| GET | /api/commands | 命令表 |
| GET | /api/events?since= | 增量事件 |
| GET | /api/traffic?minutes= | 按分钟分桶的收发量 |
| GET | /api/settings?owner= | 设置项声明 + 当前值（secret 打码） |
| POST | /api/settings | 保存设置（框架项写顶层，插件项写 plugins.&lt;id&gt;） |
| GET | /api/logs?lines= | 日志尾部 |
| GET | /api/config | 配置快照 |
| GET | /api/pages / /api/pages/{key} | 插件页面 |

## 布局要点

- 侧栏与顶栏固定，只有内容区滚动（@@B@@body overflow:hidden@@B@@ + @@B@@.content{flex:1;min-height:0;overflow-y:auto}@@B@@）；
- 深色/浅色跟随系统（@@B@@prefers-color-scheme@@B@@）；
- 单个 index.html，无前端构建，无 CDN 依赖。

## 插件接入

```python
ctx.page("pets", "养成游戏", self.render_page)   # 出现在「插件页面」与插件详情「页面」子页
ctx.declare_settings([SettingSpec("feed_cooldown_s", "喂食冷却（秒）", "int", 30)])
```

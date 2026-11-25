# GUI 版本：应用套壳（原生窗口）

GUI 不是网页，而是一个**桌面应用窗口**：tkinter 原生窗口把框架装进去，左侧导航、
右侧内容，直接读框架进程内状态（不走 HTTP，因此没有 aiohttp 访问日志刷屏）。

![仪表盘](shots/fap-dashboard.png)

## 启动

| 入口 | 说明 |
|---|---|
| start-gui.bat | 原生窗口（连 QQ） |
| start-console-only.bat | 原生窗口，不连 QQ（调界面/插件） |
| start-web-console.bat | 浏览器控制台 http://127.0.0.1:39080/ |
| start-nogui.bat | 无界面常驻 |
| python -m framework.cli --gui | 同 start-gui.bat |
| python -m framework.cli --gui --web-console | 浏览器形态 |

配置项 `gui_mode`（app / web）决定 `--gui` 的形态；关窗 = 停止框架（插件 teardown 都会跑）。

## 七个页面

| 页面 | 功能 |
|---|---|
| **仪表盘** | 状态条 + 6 张 KPI 卡（收到消息/发出回复/命令执行/错误/命令总数/已加载插件）+ 连接信息（状态、版本、配置路径、权限角色）+ 定时任务表 + 最近事件 |
| **设置** | 按设置声明自动生成的表单：AppID、AppSecret（掩码显示）、机器人名字、别名、命令前缀、群/私聊开关、白名单、单条上限、静默时段、限流、连接 QQ、控制台形态；保存即写 `config.json` 并生效 |
| **插件** | 左侧插件列表，右侧详情 + 三个子页：**命令**（该插件的命令表）、**设置**（该插件声明的配置项，单独保存）、**页面**（该插件注册的页面数据） |
| **命令** | 全量命令表（32 条）：命令、别名、说明、范围、所需角色、所属插件，顶部实时搜索 |
| **事件** | 框架 EventBus 实时流，可按事件名/会话过滤、暂停/继续、清空 |
| **日志** | `session/logs/fap.log` 尾部，行数可选、自动滚底 |
| **插件页面** | 插件用 `ctx.page()` 注册的页面，选中后渲染 JSON |

![设置页](shots/fap-settings.png)
![插件页](shots/fap-plugins.png)

## 设置是怎么来的（框架能力）

框架和插件都**不写死界面**，只声明「有哪些配置项」：

```python
from framework.settings import SettingSpec

ctx.declare_settings([
    SettingSpec("feed_cooldown_s", "喂食冷却（秒）", "int", 30),
    SettingSpec("secret_key", "密钥", "secret", ""),
])
```

- 框架自带 14 项（AppID / AppSecret / 别名 / 白名单 …），见 `app._register_core_settings()`；
- 插件各自声明自己的项，GUI 自动出表单，保存走 `app.save_settings(values, owner=plugin_id)`；
- `secret` 类型的输入框用掩码显示，`config.snapshot()` 里一律 `***`。

## 实现要点

- 主线程跑 tkinter，工作线程跑 asyncio（框架本体），界面操作经
  `asyncio.run_coroutine_threadsafe` 投递到框架循环；
- 每秒刷新一次状态（进程内读取），只有切到对应页才拉对应数据；
- 没有图形环境时 `--gui` 自动回退命令行；
- `--gui-selftest`：建全部页面、读一遍数据、打印摘要后退出（远程排障/CI 用）；
- `--gui-shot shots/x.png --gui-page settings`：截取窗口保存图片（做文档/验收）。

## 插件页面接入

```python
ctx.page("pets", "养成游戏", self.render_page)   # → 「插件页面」与插件详情「页面」子页
ctx.card("pets-top", self.render_card)           # 预留卡片位
```

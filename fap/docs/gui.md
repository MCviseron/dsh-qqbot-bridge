# GUI 版本（控制台）

框架的意义是**便捷管理机器人、插件、事件**，所以 GUI 版本做成一个像应用的控制台：
左边导航、右边内容、数据自动刷新，全部走同一套框架 API。

```bash
python -m framework.cli --gui                 # 起控制台并连 QQ
python -m framework.cli --gui --no-connect    # 只起控制台（本地看界面 / 调试插件）
# 浏览器打开 http://127.0.0.1:39080/
```

非 GUI 版本（`--no-gui`，本项目用法）不会 import 本模块，没装 aiohttp 也能跑机器人。

## 界面结构

| 页面 | 内容 |
|---|---|
| **概览** | 机器人连接状态、版本、运行时长、主人、插件数；KPI（收到消息 / 发出回复 / 命令执行 / 错误 / 命令总数 / 定时任务数）；定时任务表；插件注册的页面入口 |
| **插件** | id、名称、版本、命令数、加载状态；每行带 **重载 / 卸载 / 加载** 按钮，点一下立即生效 |
| **命令** | 整张命令表（29 条）：命令、别名、说明、范围、所属插件；可搜索 |
| **事件** | 框架内部 EventBus 的实时事件流（最近 120 条，2 秒轮询增量） |
| **设置 / 日志** | 配置快照（appsecret/token 自动剔除）+ 日志尾部自动刷新 |

## 后端接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 控制台页面 |
| GET | `/api/status` | 运行状态快照（含 connected、stats、jobs、pages） |
| GET | `/api/plugins` | 插件列表（含 loaded / commands） |
| POST | `/api/plugins/{id}/{reload|disable|enable}` | 热操作，返回最新插件列表 |
| GET | `/api/commands` | 命令表快照 |
| GET | `/api/events?since=<seq>` | 增量事件（轮询用） |
| GET | `/api/logs?lines=120` | 日志尾部 |
| GET | `/api/config` | 配置快照（密钥打码） |
| GET | `/api/pages/{key}` | 插件注册的自定义页面数据 |

## 鉴权

gui_host 默认 127.0.0.1（只绑回环）。若设了 gui_token，所有 /api/* 都要求 ?token=xxx 或请求头 x-fap-token；
控制台页面带 ?token=xxx 打开即可，前端会自动续用。

## 插件接入

插件通过 PluginContext 往控制台加内容，非 GUI 下是空操作：

```python
ctx.page("pets", "养成游戏", self.render_page)    # → /api/pages/pets
ctx.card("pets-top", self.render_card)            # 预留卡片式布局
```

dsh_bridge 的 /api/pages/dsh 就是这样一个页面（进程状态 + 日志尾部）。

## 设计取舍

- **没有前端构建**：单个 index.html，原生 JS + CSS 变量（跟随系统深浅色），复制即可用；
- **轮询而非 WebSocket**：控制台是本机排障工具，2–3 秒轮询足够，省掉一条长连接；
- **操作即生效**：插件启停/重载直接操作当前进程，不需要重启框架；
- **只读配置**：界面不写 config.json（改配置仍走文件 + mtime 热加载），避免误操作改坏凭据。

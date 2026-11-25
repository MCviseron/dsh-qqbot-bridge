# 框架使用文档

## 1. 生命周期

```text
FapApp(root, gui=False)
   ├─ Config(root/config.json)          # mtime 热加载
   ├─ EventBus / CommandTable / Scheduler / PluginManager / QQBot
   └─ start(connect=True)
        ├─ 注册框架核心命令（/help /ping /plugins /version /reload）
        ├─ emit("app.starting")
        ├─ PluginManager.load_all()     # 逐插件 setup
        ├─ Scheduler.start()            # 启动所有周期任务
        ├─ （gui=True）Panel.start()     # 起本地面板
        ├─ emit("app.ready")
        └─ （connect 且 connect_qq）QQBot.start_background()
```

停止：`stop()` → emit("app.stopping") → 停面板 → 卸载插件（teardown + 摘命令/订阅/定时器）→ 停定时器。

## 2. 配置

优先级：**代码默认值 → config.json → 环境变量 `FAP_*`**。
文件改动按 mtime 自动生效，不用重启。

```json
{
  "appid": "1906xxxx",
  "appsecret": "xxxx",
  "botname": "蓝色大肥鱼",
  "aliases": ["大肥鱼", "机器人"],
  "owners": ["主人 openid"],
  "claim_owner": true,
  "command_prefix": "/",
  "group_enabled": true,
  "c2c_enabled": true,
  "max_chars": 1500,
  "connect_qq": true,
  "gui": false,
  "gui_port": 39080,
  "plugins": {
    "dsh_bridge": { "legacy_dir": "legacy/bot", "autostart": false },
    "pet_game":   { "feed_cooldown_s": 30 }
  }
}
```

插件配置用 `ctx.config("key", default)` 读，读写统一走 `plugins.<插件id>` 段。

## 3. 命令表

```python
@ctx.command("喂食", aliases=("feed",), summary="喂一次", scope="both", owner_only=False)
async def _feed(context):
    await context.say("吃掉了")
```

派发顺序：`CommandTable.dispatch()` → 解析前缀/命令名/参数 → 校验 scope 与 owner → 调用处理函数。
处理函数里可以：

| 能力 | 写法 |
|---|---|
| 回话 | `await context.say("...")` |
| 取参数 | `context.args`（列表） / `context.raw_args`（原串） |
| 判断主人 | `context.is_owner` |
| 插件配置 | `context.plugin_config()` |
| 存储目录 | `context.storage_dir` |
| 主动报错（回给用户） | `context.fail("用法：...")` |

## 4. 事件

```python
ctx.on("message", handler)              # 每条入站消息
ctx.on("message.unhandled", handler)    # 没有命令处理时
ctx.on("outbound", handler)             # 每次发送
ctx.on("bot.ready", handler)            # 连上 QQ
ctx.on("app.starting" / "app.ready" / "app.stopping", handler)
ctx.on("interaction", handler)          # 按钮点击（SDK interaction）
```

事件按 `priority` 升序执行；单个处理器异常只记日志，不影响其它订阅者。

## 5. 存储

```python
store = ctx.store("pets")                 # session/state/pet_game/pets.json
store.update(lambda data: data.setdefault("n", 0) + 1)
store.set("last", 1)

log = ctx.log_store("events")             # session/state/pet_game/events/YYYY-MM-DD.jsonl
log.append({"kind": "feed"})
log.tail(20)
```

JSON 采用「写 .tmp 再 replace」的原子写；文件损坏时回落到默认值，不会把插件带崩。

## 6. 定时任务

```python
ctx.every("decay", 3600, self.decay)          # 每 3600s
ctx.every("boot", 60, self.warm, run_immediately=True)
```

任务名会被加上插件前缀（`pet_game:decay`），卸载插件时自动取消。

## 7. GUI 版本

```python
python -m framework.cli --gui
```

- 面板：`http://127.0.0.1:39080/`（可用 `gui_host/gui_port/gui_token` 配置）
- 插件注册页面：`ctx.page("pets", "养成游戏", self.render_page)` → `/api/pages/pets`
- 接口：`/api/status`（状态）、`/api/pages`（页面列表）、`/api/pages/<key>`（页面数据）
- 非 GUI 版本**不会 import aiohttp**，没装依赖也能跑机器人

## 8. 错误与安全

- 命令异常：回「命令执行出错：类型名」并记日志，不打断进程
- 插件加载失败：跳过该插件，其它插件继续
- 出站发送失败：记 warning，不抛给调用方
- 密钥：`appsecret` / `token` 只在发送时使用，`config.snapshot()` 默认打码

## 9. 与旧项目的关系

`legacy/` 是现有 QQ⇄DSH 项目的**原样副本**（去掉了 state/logs/config）。
`dsh_bridge` 插件以子进程方式托管它，等框架能力补齐后逐块迁移，详见 `plugins/dsh_bridge/README.md`。

## 10. 已知缺口（框架 v0.1 尚未迁移的能力）

框架是「够用且可扩展」的骨架，不是老机器人的等价重写。下面这些**明确没有**实现，
避免以后误以为“框架已经支持”：

| 能力 | 现状 | 归属 |
|---|---|---|
| 群聊插话判断（judge） | 未迁移 | 应做成独立插件 |
| C2C 流式输出（stream_messages） | 未迁移 | 框架 sender 能力 |
| 引用消息解析 / 引用回显 | 未迁移 | 框架（Message.raw 已留位） |
| 图片下载与转交模型 | 只收集 URL，未下载 | 框架 |
| 文件发送（send_file） | 未迁移 | 框架 |
| 审批卡片 / 按钮回调 | 只回执 + 抛 interaction 事件 | 插件 |
| 群管理（禁言/踢人/二次确认） | 未迁移 | 独立插件 |
| 表情包库 | 未迁移 | 独立插件 |
| 消息池 / 冷场判定 / 冷却 | 未迁移 | 插件 |
| 指标与仪表盘 | 只有 /api/status | 插件或 GUI |
| 进程托管 | 由 dsh_bridge 以子进程方式提供 | 插件 |

**已经补齐的框架级能力**（这些曾经是缺口）：

- 入站去重：同一 message.id 5 分钟内只处理一次（平台会重投）
- 被动回复：回复自动带最近一条入站消息的 msg_id，避免“主动消息无权限”
- Markdown 自动判定：msg_type=2（列表/表格/代码块/粗体才走）
- 交互回执：按钮点击先 on_interaction_result(code=0) 再抛事件
- 主人落盘：认领后写 session/state/framework.json，重启不丢
- 静默时段：quiet_hours 只拦闲聊，命令照常
- 限流：rate_limit_per_hour 按会话计，超出丢弃并记 warning

# 插件开发指南

## 1. 一个插件就是一个目录

```text
plugins/hello/
├── manifest.json
├── plugin.py
└── README.md
```

`manifest.json`：

```json
{
  "id": "hello",
  "name": "打招呼",
  "version": "0.1.0",
  "description": "最小插件示例",
  "entry": "plugin.py",
  "class_name": "HelloPlugin",
  "requires_gui": false,
  "default_enabled": true
}
```

`plugin.py`：

```python
from framework.plugin import Plugin, PluginContext


class HelloPlugin(Plugin):
    id = "hello"
    name = "打招呼"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        store = ctx.store("counters")

        @ctx.command("hello", aliases=("你好",), summary="打个招呼", usage="[名字]")
        async def _hello(context) -> None:
            who = context.raw_args.strip() or context.sender.display
            total = store.update(lambda data: data.setdefault(who, 0) + 1)[who]
            await context.say("你好，" + who + "（第 " + str(total) + " 次）")

        ctx.on("message", self.on_message)
        ctx.every("tick", 300, self.tick)
        ctx.page("hello", "打招呼统计", lambda: {"counters": store.read()})

    async def on_message(self, event: str = "", **payload) -> None:
        message = payload.get("message")
        if message is not None and message.text == "在吗":
            await self.ctx.app.send(message.target, "在")

    async def tick(self) -> None:
        self.ctx.log.info("hello tick")
```

放进 `plugins/hello/` 就会在下次启动时被自动发现（也可 `/reload hello` 热重载）。

## 2. PluginContext 能力一览

| 成员 | 用途 |
|---|---|
| `ctx.config(key, default)` | 读 `config.json` 的 `plugins.<id>` 段 |
| `ctx.store(name)` | 拿到一个 JSON 存储（原子写） |
| `ctx.log_store(name)` | 按天切分的 JSONL 追加日志 |
| `ctx.command(...)` | 注册命令（自动带插件 id，卸载时整批摘除） |
| `ctx.on(event, handler)` | 订阅事件（自动清理） |
| `ctx.every(name, seconds, handler)` | 周期任务（自动取消） |
| `ctx.page(key, title, render)` | GUI 页面（非 GUI 下是空操作） |
| `ctx.card(key, render)` | GUI 卡片片段 |
| `ctx.state_dir` | 插件私有目录 `session/state/<id>/` |
| `ctx.log` | 带插件前缀的 logger |

## 3. 命令写法的约定

1. 名字用用户真正会打的那几个字（比如 `领养`），英文名放 `aliases`；
2. `summary` 一定要写——它会出现在 `/help` 里；
3. 参数解析交给 `context.args`（空格分隔）或 `context.raw_args`（保留整串）；
4. 出错别抛裸异常，用 `context.fail("用法：...")`，它会回给用户且不算崩溃；
5. 破坏性/管理类命令标 `owner_only=True`；只在某类会话可用的标 `scope="group"` 或 `"c2c"`。

## 4. 事件一览

| 事件 | 何时 |
|---|---|
| `message` | 每条入站消息（已归一化为 `Message`） |
| `message.unhandled` | 没有命令匹配时（闲聊交给插件处理） |
| `message.done` | 单条消息处理结束（带 `elapsed`） |
| `outbound` | 框架每次发送前 |
| `bot.ready` | 连上 QQ |
| `app.starting` / `app.ready` / `app.stopping` | 框架生命周期 |
| `interaction` | 按钮点击等 SDK 交互 |

## 5. 存储与并发

`JsonStore.update()` 是「锁内读-改-写」，并发安全；写入走临时文件替换，进程被杀也不会留下半个 JSON。

## 6. 热重载

`python
/reload pet_game      # 主人命令
```

等价于 `await app.plugins.reload("pet_game")`：先 `teardown()` 再摘除命令/订阅/定时器，然后重新 `setup()`。

## 7. 测试建议

- 插件里把「业务计算」抽成纯函数（例如 `level_of(exp)`），单测直接调；
- 需要完整消息流时，用 `FapApp(root=tmp, log_to_file=False)` + 手工构造 `Message`；
- 参考 `tests/test_plugins.py` 的写法。

## 8. 检查清单

- [ ] `manifest.json` 的 `id` 与目录名一致
- [ ] 至少一条 `ctx.command`，且写了 `summary`
- [ ] `setup()` 里注册的东西都可通过框架清理（不要自己起线程/除非在 `teardown()` 停掉）
- [ ] 有 `README.md` 说明命令与配置
- [ ] `python tests/run_tests.py` 通过

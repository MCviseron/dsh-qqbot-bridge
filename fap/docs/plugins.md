# 内置插件说明

## dsh_bridge — QQ ⇄ DSH 桥接

| 项 | 内容 |
|---|---|
| id / 版本 | `dsh_bridge` / 0.3.0 |
| 命令 | `/dsh [status|start|stop|restart|logs|panel]`、`/dsh-log [行数]` |
| 配置 | `legacy_dir`、`autostart`、`python`、`panel_url`、`log_tail` |
| 依赖 | 无（子进程方式运行 `legacy/bot/main.py`） |

工作方式：把现有机器人作为受管子进程拉起，框架负责命令、状态、日志与面板页。
**此时应设 `connect_qq=false`**，否则框架与旧机器人会抢同一个 AppID。
迁移路线见 `plugins/dsh_bridge/README.md`。

## pet_game — 群内养成游戏

| 项 | 内容 |
|---|---|
| id / 版本 | `pet_game` / 1.0.0 |
| 命令 | `/领养`、`/宠物`、`/喂食`、`/摸摸`、`/改名`、`/排行` |
| 配置 | 冷却、衰减、经验门槛等 8 项 |
| 数据 | `session/state/pet_game/pets.json` |

完全用框架能力实现（命令表 + 事件 + 定时器 + 存储 + 面板页），可作为插件模板参考。

## 命令总表（13 条）

```text
框架     /help /ping /plugins /version /reload
桥接     /dsh /dsh-log
养成     /领养 /宠物 /喂食 /摸摸 /改名 /排行
```

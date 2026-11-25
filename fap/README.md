# fap — frame & plugin（QQ 机器人框架）

一个把「QQ 机器人」拆成**框架 + 插件**的工程：框架只提供通用能力，业务全在插件里。
新增功能 = 新建一个插件目录；改功能 = 只动那个插件；命令一律走**命令表**，不写 if/elif 森林。

> 本项目（QQ ⇄ DSH 桥接）是本框架的**第一个插件**，外加一个示例业务插件「群内养成游戏」。

## 两个版本

| 版本 | 启动方式 | 适用 |
|---|---|---|
| **非 GUI（本项目用法）** | `python -m framework.cli --no-gui` | 服务器 / 后台常驻，不装 aiohttp 也能跑 |
| **GUI** | `python -m framework.cli --gui` | 本地调试，多一个 Web 面板看状态、插件页 |

两个版本共用同一份 `framework/` 与同一批插件；GUI 只是额外加载 `framework/gui/`。

## 目录

```
fap/
├── framework/            框架核心（与业务无关）
│   ├── app.py            FapApp：装配 + 生命周期 + 入站总入口
│   ├── bot.py            QQBot：SDK 封装，事件归一化与发送
│   ├── commands.py       命令表（Command / CommandTable / 派发）
│   ├── events.py         事件总线（插件间解耦）
│   ├── plugin.py         插件契约 + 管理器（发现/加载/热重载）
│   ├── config.py         分层配置（默认值 ← 文件 ← 环境变量，mtime 热加载）
│   ├── storage.py        JSON / JSONL 持久化（原子写）
│   ├── scheduler.py      周期任务
│   ├── types.py          Message / Target / Sender / Outgoing
│   ├── cli.py            命令行入口（--gui / --no-gui / --dry-run）
│   └── gui/panel.py      可选 Web 面板（插件可注册页面）
├── plugins/
│   ├── dsh_bridge/       QQ ⇄ DSH 桥接（托管已有机器人进程）
│   └── pet_game/         群内养成游戏（纯框架实现）
├── docs/                 框架文档
├── examples/             最小可运行示例
├── tests/                自测（不依赖网络/pytest）
└── legacy/               现有项目原样副本（供 dsh_bridge 托管）
```

## 快速开始

```bash
cd fap
python -m framework.cli --dry-run        # 只看插件与命令表，不连 QQ
python -m framework.cli --list-commands  # 打印命令表
python -m framework.cli --no-gui         # 真的连 QQ（需要 config.json 里的 appid/secret）
python tests/run_tests.py                # 自测
```

配置文件默认 `fap/config.json`（参考 `config.example.json`），也可用 `--config` 指定；
任意键都能被环境变量 `FAP_<KEY>` 覆盖，例如 `FAP_GUI_PORT=39090`。

## 命令表（框架 + 两个插件，共 29 条）

```
/help  /ping  /plugins  /version  /reload <插件id>            ← 框架自带（5）
/状态  /日志 [行数]  /面板  /dsh [status|start|stop|...]      ← dsh_bridge 框架侧（4）
/绑定 /重置 /分组 /菜单 /pr /链接 /截图 /窗口 /会话 /切会话
/切回 /花费 /撤回 /消息池                                    ← dsh_bridge 旧机器人专有（14）
/领养 <名字>  /宠物  /喂食  /摸摸  /改名 <名字>  /排行         ← pet_game（6）
```

## 文档

- [框架使用文档](docs/framework.md)
- [插件开发指南](docs/plugin-dev.md)
- [内置插件说明](docs/plugins.md)

## 设计要点

1. **命令是数据**：每条命令是一个 `Command`（名字/别名/用法/权限/适用范围/所属插件），
   注册进 `CommandTable`；卸载插件时按 plugin id 整批摘除。
2. **插件只认 PluginContext**：要用的能力（配置、存储、命令、事件、定时器、面板页）全部由它给，
   插件之间不互相 import。
3. **框架不写业务**：`app.py` 里只有流程，没有一条业务规则。
4. **失败隔离**：命令抛错只回一句话并记日志；事件订阅者、定时任务、插件加载都有独立 try。
5. **可测**：SDK 与 aiohttp 都是延迟 import，`python -m framework.cli --dry-run` 与自测无需网络。

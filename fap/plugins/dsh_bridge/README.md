# dsh_bridge — QQ ⇄ DSH 桥接

把 QQ 会话接到 DeepSeek Harness。当前以**进程托管**方式工作：框架负责命令、状态、
日志、面板与生命周期，实际连 QQ 的工作由已验证的旧机器人（`legacy/bot`）承担。

## 命令

| 命令 | 说明 |
|---|---|
| `/dsh` | 桥接状态（进程、目录、面板地址） |
| `/dsh start` / `stop` / `restart` | 启停旧机器人 |
| `/dsh logs` | 日志尾部 |
| `/dsh panel` | DSH 面板地址 |
| `/dsh-log [行数]` | 只看日志（主人） |

## 配置（config.json → plugins.dsh_bridge）

```json
{
  "legacy_dir": "legacy/bot",
  "autostart": false,
  "python": "",
  "panel_url": "http://127.0.0.1:39062",
  "log_tail": 12
}
```

## 两种运行形态

1. **托管模式（默认）**：本插件拉起 `legacy/bot/main.py`，框架自己**不要**连 QQ
   （`config.connect_qq = false`），否则两条网关抢同一个 AppID。
2. **纯框架模式**：`connect_qq = true`，框架自己连 QQ；本插件只提供 DSH 面板类命令。

## 迁移路线（为什么先托管）

旧机器人里有大量已验证的平台细节：流式分帧、被动回复窗口、审批卡片、文件发送、
群管理二次确认。框架先把外围（命令表、状态、日志、面板）接过来，逐块迁移，
避免一次性重写把线上行为弄坏。下一步计划依次迁移：

1. 消息归一化与去重（已有雏形：`framework/bot.py`）
2. 池化上下文 + 插话判断 → 变成 `judge` 插件
3. 流式发送 → 变成框架的 `sender` 能力
4. 群管理（禁言/踢人/二次确认）→ 独立插件

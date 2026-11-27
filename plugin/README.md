# dsh-qq-bridge

DeepSeek Harness Host 插件：把 QQ 会话映射成 DSH Session。

- 每条 QQ 消息 → `ctx.sessionController.prompt()`（每个会话一个 Session，首次自动 `create()`）
- `ctx.on('session/event')` 捕获 `assistant/message`，`turn/end` 时把整轮文字推给机器人
- `ctx.on('approval/request')` 把审批转给主人，返回 `allowed-once` / `rejected` / `cancelled`
- 只监听已绑定的 Session，其它会话（例如 GUI 里自己开的）不会外泄到 QQ

## 配置（profile 条目 `qq-bridge` 的 config）

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 关掉即整插件不启动 |
| `host` / `port` | 127.0.0.1 / 39061 | 回环监听地址 |
| `token` | '' | `x-bridge-token` 校验；须与 `bot/.env` 的 `BRIDGE_TOKEN` 一致 |
| `cwd` | `$DSH_HOME/qq-bridge/workspace` | 新 Session 的工作目录 |
| `statePath` | `$DSH_HOME/qq-bridge/state.json` | 会话映射持久化 |
| `approvalTimeoutMs` | 180000 | 审批等待上限，超时按 `approvalDefault` |
| `approvalDefault` | reject | 超时结果 |

## 一键装机器人环境

设置页「机器人环境」里的 **下载 / 配置机器人** 会在 `<DSH_HOME>/qq-bridge/` 下把机器人装好：
找系统 Python（3.10+）→ 建 `venv` → pip 装 aiohttp / Pillow / viseron-qqbotpy（直连失败自动换清华镜像）
→ 复制随包的 `bot/` 源码（跳过 state/logs/`.env`/config.json）→ 写 `bot/config.json` 的
AppID / AppSecret / 分组根目录 → 拉起 `main.py --supervise`。
装完落 `install.json`，之后自动启动优先用里面的 venv 解释器；重复点会复用已有 venv。

## HTTP 路由（全部要求 `x-bridge-token`，且只接受回环来源）

| 方法与路径 | 请求 | 响应 |
|---|---|---|
| `GET /health` | — | `{ok, service: ready/waiting, conversations, pendingApprovals}` |
| `GET /status` | — | `{cwd, statePath, conversations, pendingApprovals, cursor}` |
| `POST /inbound` | `{convKey, text, senderName?, isOwner?, approvalTarget?}` | `{ok, sessionId, accepted}` |
| `GET /pull?since=<seq>&wait=<ms>` | — | `{ok, cursor, events: [{type: reply\|approval\|notice, ...}]}` |
| `POST /approval` | `{approvalId, decision: allow\|reject\|cancel}` | `{ok, approvalId, decision}` |
| `POST /reset` | `{convKey}` | `{ok, convKey}`（下次消息开新 Session） |

`convKey` 约定：`group:<group_openid>` / `c2c:<user_openid>`。

## 离线自测

```bash
node test/smoke.mjs        # HTTP 载波 + 映射存储
node test/plugin.test.mjs  # 假 Context：会话创建/提示/回合捕获/审批回传
```

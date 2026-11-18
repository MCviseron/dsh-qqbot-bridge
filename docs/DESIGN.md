# 设计与验证记录

## 1. 为什么是「插件 + 独立机器人进程」

| 方案 | 结论 |
|---|---|
| 每次 QQ 消息起一个 `dsh --profile headless` 进程 | 无上下文、每消息一次冷启动，且完全不可见 → 否 |
| 机器人直接调 DSH 的 Web API / RPC | 依赖 GUI 鉴权与 Typert 帧格式，非公开契约，升级即坏 → 否 |
| **Host 插件 + Python 机器人进程** | 插件只用公开的 `ctx.sessionController` 与 cordis 事件面；机器人复用手上能跑的 SDK → 是 |

插件里只用了官方声明过的能力：

- `ctx.sessionController.create()` / `.prompt()`
- `ctx.on('session/event')`（`turn/start` / `assistant/message` / `tool/call` / `turn/end`）
- `ctx.on('approval/request', handler, { prepend: true })` → `allowed-once` / `rejected` / `cancelled`
- `ctx.effect` / `ctx.inject`，与 `dsh-email-notify` 同款写法（结构化类型，不硬依赖内部包）

QQ 侧只 import SDK，一个字节都没改；运行环境沿用现成的 conda `ChatClone-BotPy`。

## 2. 落地清单（本机实际改动）

DSH `desktop` profile（`C:\Users\25639\.dsh\profiles\desktop`）：

1. `node_modules\dsh-qq-bridge` → junction 指向 `D:\Program\QQ-Bot-Class\dsh-bot\plugin`
   （手工 junction：PATH 里的 pnpm 10.6.3 会把 `link:D:/...` 解析成 profile 内相对路径，
   而该 profile 是 pnpm 11.28.5 装的，不要用旧 pnpm 动它）
2. `package.json`：`dependencies` + `dsh.profile.bundles` 各加一项
3. `cordis.patch.yml`：末尾 `qq-bridge` 条目（port / token / cwd / statePath / 审批超时 / contextLines）

备份：`*.bak-20260213-qqbridge`。**改配置即时热加载**，不需要重启 DSH（实测）。

## 3. 验证记录（都是真跑出来的）

| 检查 | 结果 |
|---|---|
| `node plugin/test/smoke.mjs` | 12/12（token、长轮询唤醒、映射持久化） |
| `node plugin/test/plugin.test.mjs` | 19/19（建会话、提示注入、回合捕获、审批回传、外部会话不外泄） |
| `GET /health` / `GET /status` | `service: ready`，会话映射可见 |
| 注入 → 回合捕获 | 新建 `session-…`，agent 跑工具后回复文本回到 outbox |
| 会话在 cwd 跑工具 | 读 `bot/main.py` 答出 495 行与桥接地址 |
| **审批走 QQ 而不是 GUI** | prepend 后，越权写 `D:\Program\QQ-Bot-Class\outside-probe.txt` 触发 `approval:write`，`/approval allow` → 文件落盘、回复返回；GUI 不再拦这道 |
| **Markdown 发送** | 日志 `sent markdown (85 chars, proactive) to c2c:…`，平台无报错（msg_type=2） |
| Python 机器人 | 网关连上、token 刷新、`bot online`、owner 已认领 |

修过的环境问题：DSH 沙箱无法给 `workspace` 授写权限（`SetNamedSecurityInfoW Win32 5`），
按 skill `diagnose-windows-sandbox-acl` 一键脚本补 full-control ACE（`GRANTED=2`，已验证）。
报告留在 `.acl-recovery\`。

## 4. v2 修正（2026-10-29）

| 你的反馈 | 处理 |
|---|---|
| 审批没进 QQ，只在电脑上点了 | 之前监听被 GUI 的 answerer 抢先；改为 `{ prepend: true }` 抢在瀑布最前，非桥接会话照旧 `next()` |
| 审批「无理由」 | 审批消息现在带 **工具名 + 参数预览**（从 `tool/call` 抓 `arguments`）+ 模型给的理由 + 来源会话 |
| 群里是群主也认不出 | 先查 `get_group_member().member_role == owner`（内邀能力，未开通会记一条 info 并退回），仍可 `/绑定` |
| 发图没解析 | 机器人下载附件（png/jpeg/webp/gif，≤8MB，最多 4 张）→ base64 → `content: [{type:'image'}]` |
| 能不能发表情 | 文本表情（Unicode emoji）本来就能发，提示词里已告诉模型可用；图片表情包要走富媒体上传，暂未接 |
| 群全量消息 + 不必每条都回 | 新增 `on_group_message_create`：非 @ 消息只进插件滚动上下文（零 token），攒够 `GROUP_CHIME_MIN` 条且过了冷却才问一次模型，模型可回 `[NO_REPLY]` 保持沉默 |
| 连续几条描述一件事 | 机器人做 debounce：安静 1.8s 或最长 6s 合并成一条 prompt |
| 文字没法直接发 MD | 回复里出现标题/列表/代码块/表格/粗体 → `msg_type=2 + markdown={"content":…}`，失败自动降级纯文本 |

## 5. 回滚

```powershell
$p = 'C:\Users\25639\.dsh\profiles\desktop'
Copy-Item "$p\package.json.bak-20260213-qqbridge"     "$p\package.json" -Force
Copy-Item "$p\cordis.patch.yml.bak-20260213-qqbridge" "$p\cordis.patch.yml" -Force
Copy-Item "$p\pnpm-lock.yaml.bak-20260213-qqbridge"   "$p\pnpm-lock.yaml" -Force
Remove-Item "$p\node_modules\dsh-qq-bridge" -Force   # 只是 junction
```

只想停用：把 `qq-bridge` 条目的 `enabled` 改成 `false`（插件自己不启动）。

## 6. 去敏

- 凭证只在 `bot/.env`（gitignored）与本机 profile，代码里无硬编码。
- 提交前清理：`bot/state.json`（主人 openid）、`bot/logs/`、`bot/groups.json`、
  `plugin/state/`（会话 ID + bridge.log）、`.acl-recovery/`。

## 7. 待办

- 图片表情包/语音的双向传输（`post_group_file` + 富媒体上传）
- `ask_user_question` 也转发到 QQ（目前只转发审批）
- 群白名单、限速、每群独立 agent preset
- 机器人头像/昵称/简介只能在 QQ 开放平台控制台改

# dsh-bot — 把 DeepSeek Harness 接到 QQ

用 QQ 直接和 DSH 里的 agent 对话：群里 @机器人 聊天，私聊里远程办公。
QQ 侧只做搬运，真正干活的是 DSH 里的 Session（有工具、有工作目录、有审批）。

你的点歌机器人（`EX-ChatClone-Reloader`）和 SDK（`viseron-botpy`）全程只读，没有改动。

## 架构

```
QQ 群 / 私聊
   │  WebSocket 网关（viseron_qqbotpy，AppID <你的AppID>）
   ▼
bot/  Python 机器人         ──POST /inbound──▶  plugin/  dsh-qq-bridge
      只 import SDK，不改它                        │  ctx.sessionController.create / prompt
      长轮询 GET /pull ◀──── 回复/审批 ◀────────────┤  ctx.on('session/event') 抓最终答复
                                                  │  ctx.on('approval/request') 接管审批
                                                  ▼
                                     DSH Session（GUI 侧边栏可见）
```

- 一个 QQ 群 / 一个私聊 = 一个固定 DSH Session，上下文连续；多群互不串。
- 插件自己起 `127.0.0.1:39061`，带 `x-bridge-token`；只接受回环连接。
- 审批只发主人单聊，按钮「允许 / 拒绝」+ 文字双通道，超时按拒绝。

## 快速开始（别人拿到仓库怎么用）

这条链路有**两半，都要装**：

1. **插件**（`plugin/`）——装进 DSH（profile 里 `link:` 或 npm），起本地桥 `127.0.0.1:39061`；
2. **机器人**（`bot/`）——Python 进程，连 QQ 网关，把消息推给桥、把回复发回 QQ。

```bash
# 机器人
conda create -n ChatClone-BotPy python=3.12 -y && conda activate ChatClone-BotPy
pip install -r bot/requirements.txt
cp bot/.env.example bot/.env    # 填 APPID / APPSECRET / BRIDGE_TOKEN
bot/run-bot.bat                 # 守护模式 + 设置页 127.0.0.1:39062
```

完整步骤（含 profile 怎么写、第一次验收清单、常见故障）见 **[docs/INSTALL.md](docs/INSTALL.md)**；
所有环境变量与运行时开关见 **[docs/CONFIG.md](docs/CONFIG.md)**；设计取舍见 [docs/DESIGN.md](docs/DESIGN.md)。

> 只装插件不装机器人：桥没人推消息，功能等于空转。

## 功能

- **私聊**：远程办公，能读写工作目录、跑命令、查资料；回答**流式**输出（平台仅单聊支持）
- **群聊**：`@机器人` 进工作模式；非全量模式下只响应 @ 与 `/命令`；全量模式下能看每条群消息，按节奏决定要不要插一句（会自己判断 `[NO_REPLY]`）
- **引用消息**：识别 QQ 引用，区分「机器人自己 / 主人 / 群友」，把被引用原文一并给模型；图片、文件引用按种类标注
- **审批**：工具的越权操作推送到主人单聊，按钮「允许 / 拒绝」+ 文字双通道，只有主人能批准
- **图片**：能看群友/主人发的图（自动纠正截断的 JPEG、归一化到 RGB）
- **表情包**：`[[sticker: 名字]]` 发本地表情包；`/帮助` 有完整命令表
- **设置**：网页面板（`39062`）与 DSH 内设置页（设置 → 「QQ 机器人」）并存

## 目录

```
dsh-bot/
├─ bot/               QQ 侧（Python，复用 conda 环境 ChatClone-BotPy 里已装的 SDK）
│  ├─ main.py         事件处理、分段发送、审批路由
│  ├─ bridge.py       与插件通信的回环 HTTP 客户端
│  ├─ .env            本机私有配置（已 gitignore）
│  ├─ .env.example    模板
│  └─ run-bot.bat     启动脚本
├─ plugin/            DSH Host 插件（纯 ESM JS，零第三方依赖）
│  ├─ lib/index.js    cordis 插件：会话映射 + 注入 + 事件捕获 + 审批
│  ├─ lib/server.js   回环 HTTP 与长轮询事件队列
│  ├─ lib/store.js    会话映射持久化
│  └─ test/*.mjs      离线自测（不需要 DSH）
├─ workspace/         （备用）隔离沙盒目录
└─ docs/DESIGN.md     设计决策、验证记录、回滚
```

## 运行

1) DSH 侧：插件已装进 `desktop` profile（`package.json` 依赖 + `dsh.profile.bundles` + `cordis.patch.yml` 的 `qq-bridge` 条目）。
   健康检查：

       curl -H "x-bridge-token: <token>" http://127.0.0.1:39061/health

2) QQ 侧：双击 `bot\run-bot.bat`（或 `python bot/main.py`），看到 `bot online` 即可。

3) 在 QQ 里私聊机器人任意一句 → 自动认领主人（写入 `bot/state.json`）；
   把机器人拉进群后 @它 即可聊天；群里发 `/绑定` 把你自己绑成该群主人。

## 机器人命令

| 输入 | 作用 |
|---|---|
| 直接说话 / @机器人 | 转给 DSH，答复回到原会话 |
| `/新会话` `/reset` | 清空绑定，下次消息开新 Session |
| `/绑定` | （群内）把你绑定为本群主人 |
| `允许` / `拒绝` 或按钮 | 审批（仅主人单聊有效） |
| `/帮助` | 说明 |

## 安全边界

- 审批请求只发到主人单聊；群友点按钮会被拒（`code=4 没有权限`）。
- 群里默认按「普通群友」喂给模型：闲聊为主，要改文件/跑命令需主人审批。
- 桥接会话默认落在 `D:\Program\QQ-Bot-Class\dsh-bot`，仍在 DSH 沙箱内。
- `BRIDGE_TOKEN` 同时写在 `bot/.env` 与 profile 的 `qq-bridge` 条目里，两者必须一致。

## 发仓库前的去敏

- `bot/.env`（APPID/APPSECRET/BRIDGE_TOKEN）已在 `.gitignore`，仓库里只有 `.env.example`。
- profile 的 `cordis.patch.yml` 属于本机 DSH 配置，不进本仓库。
- 清理后再提交：`bot/state.json`、`bot/logs/`、`bot/groups.json`、`plugin/state/`、`.acl-recovery/`。

## 已知限制

- 目前只处理纯文本（图片/文件/语音后续接）。
- QQ 被动回复窗口 5 分钟、同一条消息最多回 5 次；更久的结果会尝试主动消息，可能被额度拦。
- 按钮渲染依赖客户端版本，文字「允许 / 拒绝」始终可用。
- 同一个 AppID 只能跑一个网关进程（别再让点歌机器人用同一个 AppID）。

回滚与排查见 `docs/DESIGN.md`。
## v2 行为（2026-10-29，按你的反馈调整）

| 能力 | 行为 |
|---|---|
| 审批 | 走 **QQ 主人单聊**：工具名 + 参数预览 + 模型理由 + 来源会话，附「允许 / 拒绝」按钮，也可直接回文字；超时按拒绝。桥接会话的审批不再进 GUI 弹窗（`prepend` 抢在瀑布最前，其它会话不受影响） |
| 群主识别 | 先查平台 `get_group_member` 的 `member_role`（内邀能力，未开通时日志记一条 info），失败仍可 `/绑定` |
| 发图 | 机器人下载附件（png/jpeg/webp/gif，≤8MB，最多 4 张）→ base64 → DSH 多模态输入 |
| 表情 | 文本 emoji 直接可用；图片表情包（富媒体）暂未接 |
| 群全量消息 | `GROUP_FULL_MODE=1` 时能看到每条群消息，但**不逐条回**：非 @ 消息只进滚动上下文（不耗 token）；攒够 `GROUP_CHIME_MIN` 条且过了 `GROUP_CHIME_COOLDOWN` 才自己插话一次，模型可回 `[NO_REPLY]` 保持沉默 |
| 连续消息 | debounce：安静 `DEBOUNCE_MS`(1.8s) 或最长 `DEBOUNCE_MAX_MS`(6s) 后合并成一条 prompt |
| Markdown | 回复含标题/列表/代码块/表格/粗体 → `msg_type=2 + markdown.content`；失败自动降级纯文本 |
| 发送日志 | 每条成功发送记一行 `sent markdown|text (n chars, passive|proactive) to …`；失败记 WARNING 并自动降级重试 |

### 需要在 QQ 开放平台做一件事

群里的「全量消息」要在机器人管理后台开启（消息 → 群消息 → 全量/全量接收）。没开也没关系，
只是收不到非 @ 消息，其余功能照常。

### .env 新增开关

`GROUP_FULL_MODE`(1) `GROUP_CHIME_MIN`(8) `GROUP_CHIME_COOLDOWN`(240)
`OWNER_ROLE_CHECK`(1) `DEBOUNCE_MS`(1800) `DEBOUNCE_MAX_MS`(6000)
`MD_AUTO`(1) `IMAGE_MAX_MB`(8)
## v3：图片与文件（2026-10-29 晚）

**收图（已验证）**：QQ 附件 → 机器人下载（png/jpeg/webp/gif，≤8MB，最多 4 张）→ base64 →
DSH 多模态输入。验证方式：发一张 64×64 纯红 PNG 问「什么颜色」，answer = `红色`。

**发图/发文件（已验证）**：模型在回复里单独一行写 `[[send_file: 绝对路径]]`，机器人把该文件
走 QQ 富媒体上传（`upload_group_media` / `upload_c2c_media`，`srv_send_msg=True`）直接发到聊天，
然后发剩下的文字。文件类型按扩展名判定：图片→1、视频→2、语音→3（需 silk/amr）、其它→4。
安全边界：只允许 `SEND_FILE_ROOTS`（默认本仓库根 `D:\Program\QQ-Bot-Class\dsh-bot`）内的文件，
越界只记一条 `refusing to send ...` 警告。

日志对照：`sent file blue.png (type=1) to c2c:…`。

**表情包**：等同图片，模型生成/找到 png/gif 用同一个 marker 发即可；纯文本 emoji 一直可用。

**按钮**：群/单聊的 `keyboard` 只在 Markdown 消息（`msg_type=2`）下渲染——审批卡片已强制走 MD，
点按钮等价于发「允许/拒绝 <审批id>」，两条路都能被 `parse_decision` 认出。
### 运行方式（重要）

机器人**不要**挂在 DSH 的后台任务里跑：DSH 的「自动重启」会等所有后台任务结束，
挂在里面就永远等下去（提示「后台任务未结束，等待重启」）。

- 日常：双击 `bot\run-bot.bat`（前台窗口，Ctrl+C 退出）
- 想后台常驻且不阻塞 DSH 重启：
  `Start-Process 'C:\Users\25639\.conda\envs\ChatClone-BotPy\python.exe' -ArgumentList '-u','main.py' -WorkingDirectory 'D:\Program\QQ-Bot-Class\dsh-bot\bot' -WindowStyle Hidden`
- 验证：`logs\viseron_qqbotpy.log` 里出现 `[DSH] bot online` 与 `bridge ready`
### 运行方式（三种，2026-10-29 定版）

| 命令 | 行为 |
|---|---|
| `python main.py` | 只跑一个进程，退出就退出 |
| `python main.py --supervise` | **受监督**：崩溃/被杀/异常退出后自动重启（2s→5s→15s→30s 退避，稳定 5 分钟后重置）。可以挂在 DSH 后台任务里 |
| `python main.py --stop` | **有意识地停**：先写 `state/stop.flag`，再只杀子进程，监督进程看到标记后自己退出（不会重启），5 秒不退则强杀 |

- 双击 `bot\run-bot.bat` = `--supervise`；双击 `bot\stop-bot.bat` = `--stop`。
- 崩溃与主动停止的区别只有 `state/stop.flag`：存在就不重启，监督进程启动时会清掉它。
- ⚠️ 挂在 DSH 后台任务里时，DSH 的「自动重启」会等这个任务结束；**先 --stop 再重启 DSH**。
## 窗口截屏（2026-10-29 新增）

工具：`tools/window-capture.ps1`（PowerShell 5.1，无需额外依赖）

| 用法 | 说明 |
|---|---|
| `-List` | 列出所有可见顶层窗口：pid / 标题 / 尺寸 / 位置 |
| `-Title "QQ"` | 标题包含关键字的窗口（多个取最宽的） |
| `-ProcessId 37096` | 按 pid 截 |
| `-Foreground` | 当前前台窗口 |
| `-FullScreen` | 整个虚拟桌面（多显示器） |
| `-Out D:\path\shot.png` | 必填，PNG 输出路径 |

实现要点：`PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` 能抓到被遮挡/后台窗口的内容，
失败才回退到 `CopyFromScreen`；调用前会把窗口从最小化恢复并置前，进程声明 per-monitor DPI aware 避免坐标错位。

机器人命令（群里 @ 或私聊）：

- `/窗口` → 回当前可见窗口清单
- `/截图` → 全屏截图并作为图片消息发回来
- `/截图 QQ` → 标题含「QQ」的窗口
- `/截图 前台` → 当前前台窗口

截图落盘在 `shots/`（在 `SEND_FILE_ROOTS` 内，所以能直接发出去）。
限制：截的是**当前登录会话的桌面**——锁屏或无人登录时抓不到内容；UWP 加密视频/受保护内容会是黑块。
## 设置页（2026-10-29 新增）

由 supervisor 进程提供，**机器人停了页面也还能开**（所以能点「启动」）：

    DSH 左侧导航栏 →「QQ 机器人」

设置页已经并入 DSH 左侧导航栏；机器人没启动时那里会提示“设置服务没有运行”。

设置存在 `bot/config.json`，**改完立即生效**（机器人每 2 秒内重读，无需重启）；凭据除外，改完按「重启」。

| 分组 | 配置项 |
|---|---|
| 总开关 | `enabled` / `c2c_enabled` / `group_enabled` / `group_full_mode` |
| 群聊节奏 | `chatter_batch` / `chatter_max_s` / `chatter_cooldown_s` / `bot_say_memory_s` / `stuck_turn_s` |
| 发送 | `md_auto` / `ack_delay_s` / `debounce_ms` / `debounce_max_ms` / `max_chars` |
| 过滤与边界 | `group_allowlist` / `c2c_allowlist`（逗号分隔 openid，空=全部）、`bot_aliases`、`quiet_hours`（如 `23:30-07:00`，该时段不主动插话，@ 照回）、`rate_limit_per_hour`（每会话每小时上限，0=不限） |
| 图片/文件 | `image_max_mb` / `image_cache_s` / `capture_enabled`（`/截图`、`/窗口` 是否可用） |
| 凭据 | `appid` / `appsecret` / `bridge_url` / `bridge_token`（覆盖 .env，需重启） |
| 进程 | 启动 / 重启 / 关闭（不拉起） |
| 面板 | `panel_host` / `panel_port` |

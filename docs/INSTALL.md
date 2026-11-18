# 安装与使用（别人拿到这个仓库怎么跑起来）

整条链路有两半，**都必须装**：

| 一半 | 是什么 | 跑在哪 |
|---|---|---|
| `plugin/` | DSH 插件 `dsh-qq-bridge`：把 DSH Session 接到本地 HTTP 桥 | DSH 进程里（Node） |
| `bot/` | QQ 机器人：收 QQ 消息、转发给桥、把回复发回 QQ | 独立 Python 进程 |

桥是回环 HTTP（默认 `127.0.0.1:39061`，带 `x-bridge-token`），只接受本机连接。

---

## 0. 前置

- Windows（其他平台可跑，脚本是 .bat，需要自己改）
- DSH（DeepSeek Harness）已安装并能打开 Web GUI
- Python 3.12（推荐 conda 环境，示例：`ChatClone-BotPy`）
- 一个 QQ 机器人应用：AppID / AppSecret（QQ 开放平台 → 机器人 → 开发设置）
  - 需要的权限：群聊/@（`GROUP_AT_MESSAGE_CREATE`）、单聊（`C2C_MESSAGE_CREATE`）、按钮交互（`INTERACTION_CREATE`）
  - 想“看到群里每条消息”还要在全量消息（`GROUP_MESSAGE_CREATE`）里勾上并等待审核

---

## 1. 装插件（plugin/）

### 方式 A：从源码 link（推荐自用）

1. 把仓库放到例如 `D:\Program\QQ-Bot-Class\dsh-bot`。
2. 编辑 DSH 的 profile `%USERPROFILE%\.dsh\profiles\desktop\package.json`：
   ```json
   {
     "dependencies": { "dsh-qq-bridge": "link:D:/Program/QQ-Bot-Class/dsh-bot/plugin" },
     "dsh": { "profile": { "bundles": ["dsh-qq-bridge"] } }
   }
   ```
3. 在 profile 的 `cordis.patch.yml` 里加一条：
   ```yaml
   - id: qq-bridge
     config:
       host: 127.0.0.1
       port: 39061
       token: <自己生成一串随机>        # 必须和 bot/.env 的 BRIDGE_TOKEN 一致
       cwd: D:/Program/QQ-Bot-Class/dsh-bot
       statePath: D:/Program/QQ-Bot-Class/dsh-bot/plugin/state/state.json
       approvalTimeoutMs: 300000
   ```
4. 重启 DSH。日志里应出现 `dsh-qq-bridge: listening on http://127.0.0.1:39061`。

> 插件默认 **set 了 `token: ''`**（`plugin/cordis.patch.yml`），生产请务必填一个非空值，否则任何本机进程都能驱动你的 DSH。

### 方式 B：npm

插件 `package.json` 已带 `dsh.bundle.patch` / `exports` / `dsh.client`，可以直接发布安装：

```bash
cd plugin && npm publish        # 需要 npm 凭据
```
然后在 profile 里 `npm i dsh-qq-bridge`（或 `plugin_manager install_bundle`），并在 `cordis.patch.yml` 加同样的条目，重启 DSH。

> 只有插件、不装 bot 时：插件会一直等待没有人推消息，功能等于空转。

---

## 2. 装机器人（bot/）

```bash
conda create -n ChatClone-BotPy python=3.12 -y    # 已有环境可跳过
conda activate ChatClone-BotPy
pip install -r bot/requirements.txt
```

`requirements.txt` 里 `viseron-qqbotpy` 来自 Git 仓库（该项目只读依赖，不需要改它）。

复制 `bot/.env.example` 为 `bot/.env`，至少填三项：

```ini
APPID=你的AppID
APPSECRET=你的AppSecret
BRIDGE_TOKEN=和 profile 里 qq-bridge.config.token 完全一致
```

启动（**二选一**）：

```bat
bot\run-bot.bat      # 守护模式：崩了自动拉起 + 开设置页 127.0.0.1:39062
```
或手动：
```bash
cd bot && python -u main.py --supervise
```

停止（保持停止、不自动拉起）：`bot\stop-bot.bat` 或 `python -u main.py --stop`。

---

## 3. 第一次跑通的验收清单

1. 设置页 `http://127.0.0.1:39062/`：开关「接收消息（总）」为开；
2. QQ 里给机器人发一条私聊。第一条私聊会**自动认领主人**（写入 `bot/state.json`），并回一句；
3. 群里 `@机器人 /状态` → 有回复；
4. 让它干活（例如“把 xxx 写到工作目录”），越权操作时**主人单聊应收到审批卡片**（允许 / 拒绝按钮 + 文字「允许」/「拒绝」）；
5. 私聊里回答应当是**流式**出现的（同一气泡逐段变长，平台只支持单聊流式）。

---

## 4. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 私聊流式返回 `50015001 系统繁忙` | `stream_messages` 只在 `https://api.sgroup.qq.com` 上可用；本项目已强制该域名，若你改过 `SG_GROUP_BASE_URL` 请改回 |
| 机器人起来又自己停 | 有两个 supervisor 在抢 `bot/config.json`；现在有单实例守卫，检查 `bot/state/supervisor.pid` 是否残留 |
| 审批只在 GUI 弹、QQ 没收到 | 机器人没在轮询（进程挂了 / 未启动）；插件检测到 45 秒无轮询会把审批交还 GUI |
| 图片发过去 DSH 报 `INVALID_IMAGE` | QQ CDN 偶发截断；机器人会重试 3 次并做 Pillow 归一化，仍失败会在日志里标 `bad-*.bin` |
| 群里 @ 它没反应 | 确认「群聊响应」和「群全量消息」开关；全量模式下只有 @ 或 `/命令` 才会走工作模式 |
| `get_group_member` 报 `40012010 应用无接口访问权限` | 内邀能力未开通；把 `OWNER_ROLE_CHECK=0`，用群里 `/绑定` 认主 |
| 设置页打不开 | 别用 `file://` 打开 `panel.html`；用 `http://127.0.0.1:39062/?t=<BRIDGE_TOKEN>` |

---

## 5. 安全要点

- `bot/.env`、`bot/config.json`、`bot/state.json`、`bot/panels/`、`plugin/state/` **都不进仓库**（已在 `.gitignore`）；
- 桥令牌、AppSecret 只在本地文件里，别贴到聊天/Issue；
- 插件只监听回环地址；如果要跨机用，请自己加 TLS 反向代理，不要把 39061 直接暴露到公网。

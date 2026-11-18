# 配置参考

配置分三层，优先级：**运行时配置（config.json / 设置页） > 环境变量（bot/.env） > 代码默认值**。

---

## 1. 环境变量（bot/.env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `BOTNAME` | `DSH` | 机器人显示名（日志/消息池里用它标识“机器人自己”） |
| `APPID` / `APPSECRET` | 必填 | QQ 开放平台凭据 |
| `OWNER_OPENID` | 空 | 主人 openid；留空则**第一条私聊自动认领** |
| `BRIDGE_URL` | `http://127.0.0.1:39061` | 插件桥地址 |
| `BRIDGE_TOKEN` | 空 | 必须与 profile 里 `qq-bridge.config.token` 一致 |
| `QQ_SANDBOX` | `0` | 1 = 走沙箱域名（需要沙箱环境） |
| `GROUP_ENABLED` / `C2C_ENABLED` | `1` | 群 / 单聊总开关（会被运行时配置覆盖） |
| `GROUP_FULL_MODE` | `1` | 群全量消息模式：能看到每条群消息（只作上下文） |
| `GROUP_CHIME_MIN` / `GROUP_CHIME_COOLDOWN` | `8` / `240` | 群里主动插话的门槛与冷却 |
| `OWNER_ROLE_CHECK` | `1` | 用平台接口校验群主身份；内邀能力未开通时置 0，改用群里 `/绑定` |
| `HTTP_TIMEOUT` | `60` | SDK HTTP 超时（秒） |
| `MAX_CHARS` | `1600` | 单条消息最大字数，超出分段 |
| `PULL_WAIT_MS` | `25000` | 长轮询等待时间（毫秒） |
| `ACK_DELAY_S` / `ACK_TEXT` | `12` / `（还在处理，请稍等…）` | 慢回合的“正在处理”提示 |
| `DEBOUNCE_MS` / `DEBOUNCE_MAX_MS` | `1800` / `6000` | 连发合并：安静 1.8s 或最长 6s |
| `PANEL_HOST` / `PANEL_PORT` | `127.0.0.1` / `39062` | 设置页监听地址 |

---

## 2. 运行时配置（`bot/config.json`，可在设置页里改，改完即时生效）

### 总开关与通道
| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关，关掉后私聊/群聊都不响应 |
| `c2c_enabled` / `group_enabled` | `true` | 单聊 / 群聊单独的开关 |
| `group_full_mode` | `true` | 群全量消息（需平台审核通过） |
| `md_auto` | `true` | 回复像 Markdown 时用 `msg_type=2` 发送 |
| `capture_enabled` | `true` | 允许 `/截图`、`/窗口` |
| `desired_running` | `true` | 守护进程是否应保持机器人运行（`--stop` 会置 false） |

### 群聊节奏
| 键 | 默认 | 说明 |
|---|---|---|
| `chatter_batch` | `5` | 攒够几条群消息触发一次“要不要插话”的判断 |
| `chatter_max_s` | `60` | 最长等待多久强制判断一次 |
| `chatter_cooldown_s` | `90` | 判断后冷却，避免刷屏 |
| `bot_say_memory_s` | `300` | “我刚说过什么”的记忆窗口 |
| `quiet_hours` | `23:30-07:00` | 静默时段（@ 仍会回） |
| `stuck_turn_s` | `180` | 回合卡死判定，超过就把队列放开 |

### 流式（平台仅在单聊支持）
| 键 | 默认 | 说明 |
|---|---|---|
| `stream_enabled` | `true` | 私聊流式输出 |
| `stream_mode` | `api` | `api`=`stream_messages`（官方契约，需 `api.sgroup.qq.com`）；`messages` 已废弃 |
| `stream_interval_ms` | `500` | 帧间隔，官方建议 ≥400ms |

### 引用消息
| 键 | 默认 | 说明 |
|---|---|---|
| `quote_enabled` | `true` | 识别引用，把被引用原文/来源带给模型 |
| `quote_context_chars` | `300` | 被引用原文带给模型时的截断长度 |
| `quote_probe` | `false` | 排查用：把平台原始引用字段打进日志 |

### 其他
| 键 | 默认 | 说明 |
|---|---|---|
| `max_chars` | `1600` | 单条最大字数 |
| `image_max_mb` / `image_cache_s` | `10` / `120` | 图片大小上限 / 复用窗口 |
| `rate_limit_per_hour` | `60` | 每会话每小时消息上限（0=不限） |
| `group_allowlist` / `c2c_allowlist` | 空 | 白名单 openid，逗号分隔，空=全部 |
| `bot_aliases` | `蓝色大肥鱼,大肥鱼,机器人,DSH,dsh` | 群里被叫到的别名 |
| `bridge_url` / `bridge_token` | 空 | 覆盖 `.env` 里的桥地址/令牌 |
| `appid` / `appsecret` | 空 | 覆盖 `.env` 凭据（改完需重启） |
| `panel_host` / `panel_port` | `127.0.0.1` / `39062` | 设置页 |

---

## 3. 插件侧配置（profile 的 `cordis.patch.yml`）

| 键 | 默认 | 说明 |
|---|---|---|
| `host` / `port` | `127.0.0.1` / `39061` | 桥监听地址 |
| `token` | `''` | 请求头 `x-bridge-token`，**生产必须设置** |
| `cwd` | `process.cwd()` | 新建 Session 的工作目录 |
| `statePath` | 系统临时目录 | 会话映射持久化 |
| `approvalTimeoutMs` | `300000` | 审批超时（超时按拒绝） |
| `contextLines` | `12` | 群聊滚动上下文行数 |
| `modelProvider` / `model` / `reasoningEffort` | 空 | 固定桥接会话使用的模型 |
| `autoStartBot` | `true` | 插件启动时顺带拉起 `bot/main.py --supervise` |
| `streamEnabled` / `streamIntervalMs` | `true` / `250` | 插件侧把 token 增量推给机器人 |
| `quoteContextChars` | `300` | 提示词里被引用原文的长度上限 |

---

## 4. 设置页

- `http://127.0.0.1:39062/?t=<BRIDGE_TOKEN>` —— 开关、数字、凭据、启停按钮、实时日志（最近 600 行）；
- DSH 内：设置 → 「QQ 机器人」——同一批开关（官方样式、官方 token），与网页设置**并存**，改哪个都生效。

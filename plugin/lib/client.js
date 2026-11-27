/**
 * dsh-qq-bridge 的浏览器半身：左侧导航栏「QQ 机器人」+ 整页设置/日志。
 * 全部改用内联样式：宿主 main 槽位不在同一个样式作用域，注入 <style> 不可靠。
 */
window.__ModuleLoader__.load({
  id: "@mcviseron/dsh-qq-bridge",
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" })

    const React = require("react")
    const h = React.createElement
    const PANEL = "http://127.0.0.1:39062"
    // 安装器在宿主插件里（Node 侧），不在机器人面板
    const BRIDGE = "http://127.0.0.1:39061"

    const T = {
      page: { width: "100%", height: "100%", minHeight: 0, overflow: "auto", boxSizing: "border-box", padding: "24px clamp(16px,4vw,48px) 32px", color: "var(--dsw-alias-label-primary)", fontFamily: "var(--dsw-font-family, inherit)" },
      inner: {
        width: "100%", maxWidth: 720, margin: "0 auto", display: "grid", gap: 14,
        // 磨砂玻璃底：页面浮在背景图之上时保证文字可读
        padding: "20px 22px", borderRadius: 16,
        border: "1px solid var(--dsw-alias-border-l2, rgba(255,255,255,0.14))",
        backgroundColor: "rgba(22, 24, 30, 0.62)",
        // 94% 而不是 72%：卡片半透明太强时，滚动内容会从悬浮栏上下的内边距里透出来
        background: "color-mix(in srgb, var(--dsw-alias-bg-base, #14161c) 94%, transparent)",
        backdropFilter: "blur(18px) saturate(130%)",
        WebkitBackdropFilter: "blur(18px) saturate(130%)",
        boxShadow: "0 10px 30px rgba(0,0,0,0.24)",
      },
      row: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, padding: "9px 0", borderTop: "1px solid var(--dsw-alias-border-l2)" },
      labelBox: { display: "grid", gap: 2, minWidth: 0 },
      title: { fontSize: 13, color: "var(--dsw-alias-label-primary)" },
      hint: { fontSize: 12, color: "var(--dsw-alias-label-tertiary)" },
      tabs: { display: "flex", gap: 8, marginBottom: 4 },
      tab: { padding: "6px 14px", borderRadius: 999, border: "1px solid var(--dsw-alias-border-l2)", background: "transparent", color: "var(--dsw-alias-label-secondary)", fontSize: 13, cursor: "pointer" },
      tabActive: { background: "var(--dsw-alias-label-primary)", borderColor: "var(--dsw-alias-label-primary)", color: "var(--dsw-alias-bg-layer-3)" },
      grid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 },
      kpiRow: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 },
      kpi: { display: "grid", gap: 4, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--dsw-alias-border-l2)", background: "var(--dsw-alias-bg-layer-1, rgba(255,255,255,0.04))" },
      kpiLabel: { fontSize: 12, color: "var(--dsw-alias-label-tertiary)" },
      kpiValue: { fontSize: 26, fontWeight: 650, letterSpacing: "-0.02em", color: "var(--dsw-alias-label-primary)", fontVariantNumeric: "tabular-nums" },
      cardHead: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 6 },
      legend: { display: "flex", gap: 10, flexWrap: "wrap" },
      legendItem: { display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--dsw-alias-label-tertiary)" },
      legendDot: { width: 8, height: 8, borderRadius: 999, display: "inline-block" },
      ringBox: { display: "grid", justifyItems: "center", gap: 4 },
      ringLabel: { fontSize: 13, fontWeight: 600, color: "var(--dsw-alias-label-primary)" },
      barRow: { display: "grid", gridTemplateColumns: "minmax(64px,auto) 1fr 34px", alignItems: "center", gap: 8, fontSize: 12, whiteSpace: "nowrap" },
      barLabel: { color: "var(--dsw-alias-label-tertiary)" },
      barTrack: { height: 8, borderRadius: 999, background: "var(--dsw-alias-border-l2, rgba(255,255,255,0.12))", overflow: "hidden" },
      barFill: { height: "100%", borderRadius: 999 },
      barValue: { textAlign: "right", color: "var(--dsw-alias-label-secondary)", fontVariantNumeric: "tabular-nums" },
      eventRow: { display: "grid", gridTemplateColumns: "42px 62px 1fr", gap: 8, fontSize: 12, lineHeight: 1.5 },
      eventTime: { color: "var(--dsw-alias-label-tertiary)", fontVariantNumeric: "tabular-nums" },
      eventKind: { color: "var(--dsw-alias-state-business-primary, #2f6bff)" },
      eventText: { color: "var(--dsw-alias-label-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
      footNote: { fontSize: 11, color: "var(--dsw-alias-label-tertiary)" },
      memberRow: { display: "grid", gridTemplateColumns: "24px 1fr auto", alignItems: "center", gap: 8, fontSize: 12 },
      memberAvatar: { width: 24, height: 24, borderRadius: 999, objectFit: "cover", display: "inline-block" },
      memberName: { color: "var(--dsw-alias-label-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
      memberTail: { color: "var(--dsw-alias-label-tertiary)", fontVariantNumeric: "tabular-nums" },
      memberList: { maxHeight: 172, overflowY: "scroll", display: "flex", flexDirection: "column", gap: 6, paddingRight: 4 },
      eventList: { maxHeight: 200, overflowY: "scroll", display: "flex", flexDirection: "column", gap: 4, paddingRight: 4 },
      chipRow: { display: "flex", flexWrap: "wrap", gap: 6 },
      chip: { padding: "2px 8px", borderRadius: 999, border: "1px solid var(--dsw-alias-border-l2)", fontSize: 11, color: "var(--dsw-alias-label-secondary)" },
      card: { display: "grid", gap: 8, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--dsw-alias-border-l2)", background: "var(--dsw-alias-bg-layer-1, rgba(255,255,255,0.04))" },
      cardTitle: { fontSize: 13, fontWeight: 600, color: "var(--dsw-alias-label-primary)" },
      cardRow: { display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12 },
      cardKey: { color: "var(--dsw-alias-label-tertiary)" },
      cardValue: { color: "var(--dsw-alias-label-secondary)", fontVariantNumeric: "tabular-nums" },
      sectionTitle: { fontSize: 12, letterSpacing: "0.04em", color: "var(--dsw-alias-label-tertiary)", margin: "10px 0 2px" },
      // 顶/底悬浮栏：跟随主题的表面色（写死深色在浅色主题里就是一块黑板），圆角+描边看着像工具条
      stickyBar: { position: "sticky", zIndex: 6, display: "grid", gap: 10, padding: "10px 12px", borderRadius: 12,
        background: "color-mix(in srgb, var(--dsw-alias-bg-base, #ffffff) 96%, transparent)",
        backdropFilter: "blur(14px) saturate(140%)", WebkitBackdropFilter: "blur(14px) saturate(140%)",
        border: "1px solid var(--dsw-alias-border-l2, rgba(0,0,0,0.12))", boxShadow: "0 6px 18px rgba(0,0,0,0.10)" },
      stickyTop: { top: 0 },
      stickyBottom: { bottom: 0, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" },
      // 设置页去掉外层上下内边距，悬浮栏才能贴到视口边缘，不留一条会透出内容的缝
      pageTight: { paddingTop: 0, paddingBottom: 0 },
      input: { width: 132, padding: "5px 8px", border: "1px solid var(--dsw-alias-border-l2)", borderRadius: 6, background: "var(--dsw-alias-bg-layer-3)", color: "var(--dsw-alias-label-primary)", font: "inherit", textAlign: "right" },
      inputWide: { width: 260, textAlign: "left" },
      textarea: { width: "100%", minHeight: 120, padding: "8px 10px", border: "1px solid var(--dsw-alias-border-l2)", borderRadius: 6, background: "var(--dsw-alias-bg-layer-3)", color: "var(--dsw-alias-label-primary)", font: "inherit", lineHeight: 1.6, resize: "vertical", boxSizing: "border-box", textAlign: "left" },
      btn: { padding: "6px 14px", border: "1px solid var(--dsw-alias-border-l2)", borderRadius: 6, background: "transparent", color: "var(--dsw-alias-label-primary)", font: "inherit", cursor: "pointer" },
      btnPrimary: { background: "var(--dsw-alias-label-primary)", borderColor: "var(--dsw-alias-label-primary)", color: "var(--dsw-alias-bg-layer-3)" },
      actions: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" },
      badge: { display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 9px", border: "1px solid var(--dsw-alias-border-l2)", borderRadius: 999, fontSize: 12, color: "var(--dsw-alias-label-secondary)" },
      dot: { width: 7, height: 7, borderRadius: "50%" },
      log: { margin: 0, maxHeight: 300, overflow: "auto", padding: 10, border: "1px solid var(--dsw-alias-border-l2)", borderRadius: 6, background: "var(--dsw-alias-bg-layer-3)", color: "var(--dsw-alias-label-secondary)", font: "12px/1.5 ui-monospace, Consolas, monospace", whiteSpace: "pre-wrap" },
    }

    function Switch(props) {
      return h("button", {
        type: "button", role: "switch", "aria-checked": props.checked ? "true" : "false",
        "aria-label": props.label, disabled: props.disabled,
        onClick: function () { props.onChange(!props.checked) },
        style: {
          position: "relative", flex: "0 0 auto", width: 38, height: 22, padding: 2, border: 0,
          borderRadius: 999, cursor: props.disabled ? "default" : "pointer", boxSizing: "border-box",
          // 用官方语义色：开启=业务主色，关闭=边框 L3（不再用不存在的 brand-primary 导致发白）
          background: props.checked
            ? "var(--dsw-alias-state-business-primary, #2f6bff)"
            : "var(--dsw-alias-border-l3, #5a6270)",
          boxShadow: props.checked ? "inset 0 0 0 1px rgba(255,255,255,0.12)" : "none",
          opacity: props.disabled ? 0.5 : 1,
        },
      }, h("span", {
        "aria-hidden": "true",
        style: {
          display: "block", width: 18, height: 18, borderRadius: "50%",
          background: props.checked ? "#fff" : "var(--dsw-alias-switch-thumb, #c9ccd6)",
          transform: props.checked ? "translateX(16px)" : "none", transition: "transform 120ms ease",
        },
      }))
    }

    function Row(props) {
      return h("div", { style: T.row },
        h("div", { style: T.labelBox },
          h("span", { style: T.title }, props.title),
          props.hint ? h("span", { style: T.hint }, props.hint) : null),
        props.children)
    }

    const LABELS = {
      enabled: ["接收消息（总）", "关掉后私聊与群聊都不响应"],
      c2c_enabled: ["私聊响应", ""],
      group_enabled: ["群聊响应", ""],
      group_full_mode: ["群全量消息", "需在开放平台开启全量接收"],
      group_at_only: ["群聊只处理 @ 我的消息", "开启后群里的普通发言一律丢弃（仅在拿到全量消息时才需要）"],
      md_auto: ["Markdown 自动发送", "回复像 Markdown 时用 msg_type=2"],
      stream_enabled: ["流式输出（仅私聊）", "平台只在单聊支持流式"],
      ack_enabled: ["“还在处理”占位提示", "会打断流式输出，默认关"],
      quote_enabled: ["识别引用消息", "引用时把被引用原文和来源一起带给模型"],
      capture_enabled: ["允许截屏", "/截图、/窗口 是否可用"],
      auto_group: ["自动分组（每个会话独立工作区）", "关闭则所有会话共用同一个工作目录"],
      approval_inline_redraw: ["审批按钮就地重绘为“已允许”", "关闭后退回旧行为：额外发一条结论文字 + “已处理”卡片"],
      kick_confirm: ["踢人二次审批", "开启后踢人前先在你的私聊弹一张确认卡片，点了才执行"],
      interject_hook_only: ["插话只要命中钩子才判断", "开启后只有被点名/带问号/提到别名/长时间冷场才花一次判断；关闭则每攒够几条就判一次"],
      judge_score_output: ["判断用打分制", "让模型先给 0~3 分的开口意愿，再按阈值决定发不发"],
      persona_enabled: ["启用人设", "只在新会话的第一条消息里发一次；会话已有历史就不再重复"],
    }

    const SWITCHES = ["enabled","c2c_enabled","group_enabled","group_full_mode","group_at_only","md_auto","stream_enabled","ack_enabled","quote_enabled","capture_enabled","auto_group","approval_inline_redraw","kick_confirm","interject_hook_only","judge_score_output","persona_enabled"]
      .map(function (key) { return [key, LABELS[key][0], LABELS[key][1]] })

    // 静默时段：开始/结束时间 + 最右侧开关，并实时显示"当前是否静默、下次切换"
    function parseQuiet(value) {
      const text = String(value || "23:30-07:00")
      const parts = text.split("-")
      const ok = parts.length === 2 && /^\d{1,2}:\d{2}$/.test(parts[0].trim()) && /^\d{1,2}:\d{2}$/.test(parts[1].trim())
      return ok ? [parts[0].trim(), parts[1].trim()] : ["23:30", "07:00"]
    }
    function minutesOf(text) { const p = text.split(":"); return Number(p[0]) * 60 + Number(p[1]) }
    function quietStatus(value) {
      const pair = parseQuiet(value)
      const start = minutesOf(pair[0])
      const end = minutesOf(pair[1])
      const now = new Date()
      const mins = now.getHours() * 60 + now.getMinutes()
      const inQuiet = start <= end ? (mins >= start && mins < end) : (mins >= start || mins < end)
      const next = inQuiet ? end : start
      const label = String(Math.floor(next / 60)).padStart(2, "0") + ":" + String(next % 60).padStart(2, "0")
      return { inQuiet, label }
    }

    const NUMBERS = [
      ["chatter_batch","攒够几条触发判断",1,30], ["chatter_max_s","最长等待（秒）",5,600],
      ["chatter_cooldown_s","判断后冷却（秒）",0,1800], ["bot_say_memory_s","「最近说过」记忆（秒）",30,3600],
      ["stuck_turn_s","回合卡死判定（秒）",30,1800], ["ack_delay_s","迟到提示延迟（秒）",0,120],
      ["debounce_ms","连发合并（毫秒）",0,5000], ["max_chars","单条最大字数",200,4000],
      ["image_max_mb","图片上限（MB）",1,20], ["rate_limit_per_hour","每会话每小时上限（0=不限）",0,240],
      ["stream_interval_ms","流式节流（毫秒）",50,2000], ["quote_context_chars","引用原文上限（字）",50,2000],
      ["pool_ttl_s","消息池保留（秒）",60,86400], ["pool_max","消息池上限（条）",10,1000],
      ["metrics_keep_days","仪表盘数据保留（天）",1,365], ["interject_cold_s","冷场判定（秒，超过则有钩子）",60,7200],
      ["send_file_timeout_s","发文件超时（秒）",10,300], ["stream_retry_s","流式降级后暂停（秒）",10,3600],
      ["judge_join_threshold","开口阈值（0~3，越大越安静）",0,3],
      ["judge_silent_streak","连续沉默几次后自动降一档",0,20],
      ["judge_force_per_hour","每小时最多几次降档补开口",0,5],
    ]

    // 凭据放最前面：装机器人、改 AppID 都在第一屏
    const CREDENTIALS = [
      ["appid", "APPID（开放平台的机器人 AppID）"],
      ["appsecret", "APPSECRET（留空=不变；打码值不会被写入）"],
    ]

    const TEXTS = [
      ["group_allowlist","群白名单（openid，逗号分隔）"],
      ["c2c_allowlist","私聊白名单（同上）"], ["bot_aliases","群内别名（逗号分隔）"],
      ["auto_group_root","自动分组根目录（如 D:\\dsh-qqbot-temp）"],
    ]

    function QQBridgePage() {
      const [state, setState] = React.useState(null)
      const [draft, setDraft] = React.useState({})
      const [message, setMessage] = React.useState("")
      const [busy, setBusy] = React.useState(false)
      const [logs, setLogs] = React.useState([])
      const [paused, setPaused] = React.useState(false)
      const [follow, setFollow] = React.useState(true)
      const [tab, setTab] = React.useState("settings")
      const [dash, setDash] = React.useState(null)
      const [dashRange, setDashRange] = React.useState("hour")
      const [install, setInstall] = React.useState(null)
      const [installNote, setInstallNote] = React.useState("")
      const [stickers, setStickers] = React.useState([])
      const [stickerNote, setStickerNote] = React.useState("")
      const [stickerDir, setStickerDir] = React.useState("")
      const [renameFile, setRenameFile] = React.useState("")
      const [renameValue, setRenameValue] = React.useState("")
      const [deleteFile, setDeleteFile] = React.useState("")
      const logRef = React.useRef(null)
      React.useEffect(function () {
        const node = logRef.current
        if (node && follow) node.scrollTop = node.scrollHeight
      }, [logs, follow])

      const call = React.useCallback(async function (path, options) {
        const response = await fetch(PANEL + path, Object.assign({ headers: { "content-type": "application/json" } }, options || {}))
        return await response.json()
      }, [])

      const load = React.useCallback(async function () {
        try { setState(await call("/api/state")) } catch (error) { setState({ offline: true }) }
      }, [call])

      React.useEffect(function () { load() }, [load])

      // 装环境的状态轮询必须和其它 hook 一样在提前 return 之前声明，否则 hook 数量会变
      const installCall = async function (body) {
        const response = await fetch(BRIDGE + "/install", {
          method: "POST",
          headers: { "content-type": "application/json", "x-qqbridge-install": "1" },
          body: JSON.stringify(body || {}),
        })
        return await response.json()
      }
      // 挂载时读一次；running 翻成 true 后持续轮询（首次挂载 running=false，旧写法会直接停掉不再更新）
      const installRunning = install !== null && install.running === true
      React.useEffect(function () {
        let stop = false
        const tick = async function () {
          try {
            const state = await installCall({ action: "status" })
            if (stop) return
            setInstall(state)
            if (state.running === true) setTimeout(tick, 1000)
          } catch (error) {
            if (!stop) setInstallNote("连不上宿主插件（39061），确认插件已加载")
          }
        }
        void tick()
        return function () { stop = true }
      }, [installRunning])
      React.useEffect(function () {
        if (tab !== "stickers") return undefined
        let stop = false
        call("/api/stickers").then(function (data) {
          if (stop) return
          setStickers(Array.isArray(data.stickers) ? data.stickers : [])
          setStickerDir(String(data.dir || ""))
        }).catch(function () { if (!stop) setStickerNote("表情包目录不可达") })
        return function () { stop = true }
      }, [tab, call])
      React.useEffect(function () {
        if (tab !== "dashboard") return undefined
        let stop = false
        const tick = async function () {
          try {
            const data = await call("/api/dashboard?range=" + dashRange)
            if (!stop) setDash(data)
          } catch (error) {
            if (!stop) setDash({ offline: true })
          }
        }
        tick()
        const timer = setInterval(tick, 5000)
        return function () { stop = true; clearInterval(timer) }
      }, [tab, call, dashRange])
      React.useEffect(function () {
        const timer = setInterval(load, 8000)
        return function () { clearInterval(timer) }
      }, [load])
      React.useEffect(function () {
        if (paused) return undefined
        let stop = false
        const tick = async function () {
          try {
            const data = await call("/api/logs?lines=200")
            if (!stop) setLogs(Array.isArray(data.lines) ? data.lines : [])
          } catch (error) {
            if (!stop) setLogs(["(日志服务不可达)"])
          }
        }
        tick()
        const timer = setInterval(tick, 3000)
        return function () { stop = true; clearInterval(timer) }
      }, [call, paused])

      if (state !== null && state.offline) {
        return h("div", { style: T.page },
          h("div", { style: T.inner },
          h("div", { style: T.title }, "机器人的设置服务没有运行"),
          h("div", { style: T.hint }, "用 bot\\run-bot.bat 启动一次（或 python -u main.py --supervise），再点重试。"),
          h("div", { style: T.actions }, h("button", { style: T.btn, onClick: load }, "重试"))))
      }
      if (state === null) return h("div", { style: T.page }, h("div", { style: T.inner }, h("div", { style: T.hint }, "读取中…")))

      const config = state.config || {}
      const bot = state.bot || {}
      const value = function (key) { return key in draft ? draft[key] : config[key] }
      const setValue = function (key, next) { const copy = Object.assign({}, draft); copy[key] = next; setDraft(copy) }
      const save = async function () {
        setBusy(true)
        try {
          const result = await call("/api/config", { method: "POST", body: JSON.stringify(draft) })
          const unknown = Array.isArray(result.unknown) ? result.unknown : []
          setDraft({})
          setMessage(unknown.length === 0 ? "已保存" : "部分未生效（键不在运行进程里）：" + unknown.join(", ") + " —— 需要重启机器人进程")
          await load()
        }
        catch (error) { setMessage("保存失败") }
        setBusy(false)
      }
      // 装环境：POST 给宿主插件的 /install，再轮询进度
      const startInstall = async function () {
        setInstallNote("")
        try {
          // 面板回传的 AppSecret 是打码值（ab12****yz），别把它当真的传下去
          const rawSecret = String(value("appsecret") === undefined ? "" : value("appsecret"))
          const started = await installCall({
            action: "start",
            appid: value("appid"),
            appsecret: rawSecret.indexOf("****") >= 0 ? "" : rawSecret,
            autoGroupRoot: value("auto_group_root"),
          })
          if (started.ok !== true) { setInstallNote("启动安装失败：" + (started.error || "未知错误")); return }
          setInstall(started.state || null)
        } catch (error) {
          setInstallNote("连不上宿主插件（39061），确认插件已加载")
        }
      }

      const manage = async function (action) {
        setBusy(true)
        try { const result = await call("/api/manage", { method: "POST", body: JSON.stringify({ action: action }) }); setMessage(result.message || action); await load() }
        catch (error) { setMessage("操作失败") }
        setBusy(false)
      }

      const SCROLLBAR_CSS = [
        '[data-qq-scroll]::-webkit-scrollbar{width:9px;height:9px}',
        '[data-qq-scroll]::-webkit-scrollbar-track{background:rgba(0,0,0,0.04);border-radius:999px}',
        '[data-qq-scroll]::-webkit-scrollbar-thumb{background:rgba(120,130,145,0.55);border-radius:999px;border:2px solid transparent;background-clip:padding-box}',
        '[data-qq-scroll]::-webkit-scrollbar-thumb:hover{background:rgba(120,130,145,0.8);background-clip:padding-box}',
      ].join('')

      function bucketPlan(range) {
        const now = Math.floor(Date.now() / 1000)
        if (range === "today") {
          const midnight = new Date(now * 1000)
          midnight.setHours(0, 0, 0, 0)
          const start = Math.floor(midnight.getTime() / 1000)
          return { start: start, step: 60, count: Math.min(1440, Math.ceil((now - start) / 60) + 1) }
        }
        if (range === "7d") {
          const step = 30 * 60
          const start = Math.floor((now - 7 * 86400) / step) * step
          return { start: start, step: step, count: Math.ceil((now - start) / step) + 1 }
        }
        const start = Math.floor((now - 60 * 60) / 60) * 60
        return { start: start, step: 60, count: 60 }
      }

      function buildSeries(raw, keys, range) {
        const plan = bucketPlan(range)
        const byTime = new Map()
        ;(raw || []).forEach(function (row) {
          const bucket = Math.floor(Number(row.t) / plan.step) * plan.step
          const cell = byTime.get(bucket) || {}
          keys.forEach(function (key) { cell[key] = (cell[key] || 0) + Number(row[key] || 0) })
          byTime.set(bucket, cell)
        })
        return Array.from({ length: plan.count }, function (_, index) {
          const t = plan.start + index * plan.step
          const cell = byTime.get(t) || {}
          const point = { t: t }
          keys.forEach(function (key) { point[key] = Number(cell[key] || 0) })
          return point
        })
      }

      function chartTick(tSec, spanSec) {
        const d = new Date(Number(tSec) * 1000)
        const pad = function (n) { return ("0" + n).slice(-2) }
        if (spanSec > 86400) return (d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + "h"
        return pad(d.getHours()) + ":" + pad(d.getMinutes())
      }

      function areaChart(rawPoints, keys, colors) {
        // 7 天区间会产生上万条分钟点：抽稀到 ≤1000 条，形状不变，重绘不卡
        let points = rawPoints
        if (points.length > 1000) {
          const stride = Math.ceil(points.length / 1000)
          points = points.filter(function (_point, index) { return index % stride === 0 || index === points.length - 1 })
        }
        const width = 560
        const height = 150
        const left = 30
        const right = 8
        const top = 8
        const bottom = 20
        const plotW = width - left - right
        const plotH = height - top - bottom
        let max = 1
        points.forEach(function (point) {
          keys.forEach(function (key) { if (point[key] > max) max = point[key] })
        })
        const nice = Math.max(1, Math.ceil(max / 2) * 2)
        const stamp = function (point) { return Number(point.t) || 0 }
        let tMin = points.length ? Math.min.apply(null, points.map(stamp)) : 0
        let tMax = points.length ? Math.max.apply(null, points.map(stamp)) : 60
        if (tMax - tMin < 60) tMax = tMin + 60
        const xAt = function (point) { return left + ((stamp(point) - tMin) / (tMax - tMin)) * plotW }
        const yAt = function (value) { return top + plotH - ((Number(value) || 0) / nice) * plotH }
        const children = [
          h("rect", { key: "bg", x: 0, y: 0, width: width, height: height, fill: "transparent" }),
        ]
        ;[nice, Math.round(nice / 2), 0].forEach(function (value, index) {
          const y = yAt(value)
          children.push(h("line", {
            key: "gy" + index, x1: left, y1: y, x2: left + plotW, y2: y,
            stroke: "var(--dsw-alias-border-l2, #e3e6ea)", strokeWidth: 0.5,
          }))
          children.push(h("text", {
            key: "gyt" + index, x: left - 5, y: y + 3, textAnchor: "end", fontSize: 9,
            fill: "var(--dsw-alias-label-tertiary, #8b929c)",
          }, String(value)))
        })
        const spanSec = tMax - tMin
        for (let i = 0; i <= 4; i += 1) {
          const x = left + (plotW / 4) * i
          const tickTime = tMin + (spanSec / 4) * i
          children.push(h("line", {
            key: "gx" + i, x1: x, y1: top + plotH, x2: x, y2: top + plotH + 3,
            stroke: "var(--dsw-alias-border-l3, #cfd4da)", strokeWidth: 0.5,
          }))
          children.push(h("text", {
            key: "gxt" + i, x: x, y: height - 6,
            textAnchor: i === 0 ? "start" : (i === 4 ? "end" : "middle"), fontSize: 9,
            fill: "var(--dsw-alias-label-tertiary, #8b929c)",
          }, chartTick(tickTime, spanSec)))
        }
        keys.forEach(function (key) {
          const coords = points.map(function (point) {
            return [xAt(point).toFixed(1), yAt(point[key]).toFixed(1)]
          })
          if (!coords.length) return
          if (coords.length === 1) {
            children.push(h("circle", { key: "p" + key, cx: coords[0][0], cy: coords[0][1], r: 2.5, fill: colors[key] }))
            return
          }
          const d = coords.map(function (pair, index) {
            return (index === 0 ? "M" : "L") + pair[0] + " " + pair[1]
          }).join(" ")
          const baseline = (top + plotH).toFixed(1)
          children.push(h("path", {
            key: "a" + key,
            d: d + " L" + coords[coords.length - 1][0] + " " + baseline + " L" + coords[0][0] + " " + baseline + " Z",
            fill: colors[key], opacity: 0.14,
          }))
          children.push(h("path", {
            key: "l" + key, d: d, fill: "none", stroke: colors[key], strokeWidth: 2,
            strokeLinejoin: "round", strokeLinecap: "round",
          }))
        })
        return h("svg", { viewBox: "0 0 " + width + " " + height, style: { width: "100%", height: 150, display: "block" } }, children)
      }

      function ring(ratio, label, detail, color) {
        const value = Math.max(0, Math.min(1, Number(ratio) || 0))
        const radius = 26
        const circumference = 2 * Math.PI * radius
        const filled = circumference * value
        return h("div", { style: T.ringBox },
          h("svg", { viewBox: "0 0 72 72", style: { width: 72, height: 72 } },
            h("circle", { cx: 36, cy: 36, r: radius, fill: "none", stroke: "var(--dsw-alias-border-l2, rgba(255,255,255,0.16))", strokeWidth: 7 }),
            h("circle", {
              cx: 36, cy: 36, r: radius, fill: "none", stroke: color, strokeWidth: 7, strokeLinecap: "round",
              strokeDasharray: filled.toFixed(1) + " " + circumference.toFixed(1),
              transform: "rotate(-90 36 36)",
            }),
            h("text", { x: 36, y: 41, textAnchor: "middle", fontSize: 15, fill: "var(--dsw-alias-label-primary)", fontWeight: 600 }, Math.round(value * 100) + "%")),
          h("div", { style: T.ringLabel }, label),
          h("div", { style: T.hint }, detail))
      }

      function kpi(label, value, sub) {
        return h("div", { style: T.kpi },
          h("div", { style: T.kpiLabel }, label),
          h("div", { style: T.kpiValue }, value),
          sub ? h("div", { style: T.hint }, sub) : null)
      }

      function barRow(label, value, max, color) {
        const width = max > 0 ? Math.round((value / max) * 100) : 0
        return h("div", { key: label, style: T.barRow },
          h("span", { style: T.barLabel }, label),
          h("div", { style: T.barTrack },
            h("div", { style: Object.assign({}, T.barFill, { width: width + "%", background: color }) })),
          h("span", { style: T.barValue }, String(value)))
      }

      function chartCard(title, legend, body) {
        return h("div", { style: T.card },
          h("div", { style: T.cardHead },
            h("span", { style: T.cardTitle }, title),
            h("span", { style: T.legend }, (legend || []).map(function (item) {
              return h("span", { key: item.label, style: T.legendItem },
                h("span", { style: Object.assign({}, T.legendDot, { background: item.color }) }),
                item.label)
            }))),
          body)
      }

      const reloadStickers = async function () {
        try {
          const data = await call("/api/stickers")
          setStickers(Array.isArray(data.stickers) ? data.stickers : [])
          setStickerDir(String(data.dir || ""))
        } catch (error) { setStickerNote("表情包目录不可达") }
      }

      const uploadSticker = function (event) {
        const file = event.target.files && event.target.files[0]
        if (!file) return
        if (file.size > 4 * 1024 * 1024) { setStickerNote("图片超过 4MB"); return }
        const reader = new FileReader()
        reader.onload = async function () {
          const name = String(file.name || "sticker").replace(/\.[^.]+$/, "")
          try {
            const result = await call("/api/stickers", { method: "POST", body: JSON.stringify({ action: "upload", name: name, data: String(reader.result) }) })
            setStickerNote(result.ok ? "已上传：" + name : "上传失败：" + (result.error || ""))
            await reloadStickers()
          } catch (error) { setStickerNote("上传失败") }
        }
        reader.readAsDataURL(file)
        event.target.value = ""
      }

      const stickerAction = async function (action, name, extra) {
        try {
          const result = await call("/api/stickers", { method: "POST", body: JSON.stringify(Object.assign({ action: action, name: name }, extra || {})) })
          setStickerNote(result.ok ? (action === "delete" ? "已删除：" + name : "已改名") : "操作失败：" + (result.error || ""))
          await reloadStickers()
        } catch (error) { setStickerNote("操作失败") }
      }

      function stickersView() {
        return h("div", { style: { display: "grid", gap: 14 } },
          h("div", { style: T.actions },
            h("label", { style: Object.assign({}, T.btn, T.btnPrimary, { cursor: "pointer" }) },
              "上传表情包",
              h("input", { type: "file", accept: "image/*", style: { display: "none" }, onChange: uploadSticker })),
            h("button", { style: T.btn, onClick: reloadStickers }, "刷新"),
            h("span", { style: T.hint }, stickers.length + " 个 · " + (stickerDir || "assets/stickers"))),
          stickerNote ? h("div", { style: T.hint }, stickerNote) : null,
          h("div", { style: T.grid },
            ...(stickers.length === 0
              ? [h("div", { style: T.card }, h("div", { style: T.hint }, "还没有表情包，点「上传表情包」加一个"))]
              : stickers.map(function (item) {
                  return h("div", { key: item.file, style: Object.assign({}, T.card, { justifyItems: "center" }) },
                    h("img", {
                      src: PANEL + "/api/stickers?file=" + encodeURIComponent(item.file),
                      alt: item.name,
                      style: { width: "100%", maxHeight: 120, objectFit: "contain", borderRadius: 8 },
                    }),
                    renameFile === item.file
                      ? h("div", { style: { display: "grid", gap: 6, width: "100%" } },
                          h("input", {
                            style: Object.assign({}, T.input, { width: "100%", textAlign: "center" }),
                            value: renameValue,
                            autoFocus: true,
                            onChange: function (event) { setRenameValue(event.target.value) },
                            onKeyDown: function (event) {
                              if (event.key === "Enter" && renameValue.trim() && renameValue.trim() !== item.name) {
                                stickerAction("rename", item.name, { to: renameValue.trim() })
                                setRenameFile("")
                              }
                              if (event.key === "Escape") setRenameFile("")
                            },
                          }),
                          h("div", { style: T.actions },
                            h("button", {
                              style: Object.assign({}, T.btn, T.btnPrimary),
                              onClick: function () {
                                const next = renameValue.trim()
                                if (!next || next === item.name) { setRenameFile(""); return }
                                stickerAction("rename", item.name, { to: next })
                                setRenameFile("")
                              },
                            }, "保存"),
                            h("button", { style: T.btn, onClick: function () { setRenameFile("") } }, "取消")))
                      : h("div", { style: T.cardTitle }, item.name),
                    h("div", { style: T.hint }, Math.round(item.bytes / 1024) + " KB"),
                    h("div", { style: T.actions },
                      h("button", {
                        style: T.btn,
                        onClick: function () {
                          const syntax = "[[sticker: " + item.name + "]]"
                          try { navigator.clipboard.writeText(syntax) ; setStickerNote("已复制 " + syntax) } catch (error) { setStickerNote(syntax) }
                        },
                      }, "复制语法"),
                      h("button", {
                        style: T.btn,
                        onClick: function () {
                          setRenameFile(item.file)
                          setRenameValue(item.name)
                          setStickerNote("")
                        },
                      }, "改名"),
                      h("button", {
                        style: deleteFile === item.file ? Object.assign({}, T.btn, { color: "#ef4444", borderColor: "#ef4444" }) : T.btn,
                        onClick: function () {
                          if (deleteFile === item.file) {
                            setDeleteFile("")
                            stickerAction("delete", item.name)
                          } else {
                            setDeleteFile(item.file)
                            setStickerNote("再点一次「确认删除」移除 " + item.name)
                          }
                        },
                      }, deleteFile === item.file ? "确认删除" : "删除"))
                  )
                }))),
          h("div", { style: T.hint }, "模型在回复里写 " + "[[sticker: 名字]]" + " 就会发出对应的图；名字就是文件名去掉扩展名。"))
      }
      function dashboardView() {
        if (!dash) return h("div", { style: T.card }, h("div", { style: T.hint }, "正在读取…"))
        if (dash.offline) return h("div", { style: T.card }, h("div", { style: T.hint }, "面板不可达（守护进程没在跑）"))
        const c = dash.counters || {}
        const botInfo = dash.bot || {}
        const queues = dash.queues || {}
        const logs = dash.logs || {}
        const uptime = Number(dash.uptime_s || 0)
        const human = uptime > 0 ? Math.floor(uptime / 3600) + "h " + Math.floor((uptime % 3600) / 60) + "m" : "—"
        const points = buildSeries(dash.series, ["c2c_msgs", "group_msgs", "judge_spoke", "streams"], dashRange)
        const sumKey = function (key) {
          return (points || []).reduce(function (acc, point) { return acc + Number(point[key] || 0) }, 0)
        }
        const rangeC2c = sumKey("c2c_msgs")
        const rangeGroup = sumKey("group_msgs")
        const rangeSpoke = sumKey("judge_spoke")
        const rangeStreams = sumKey("streams")
        const totalMsgs = (c.c2c_msgs || 0) + (c.group_msgs || 0)
        const judged = c.judge_calls || 0
        const spoke = c.judge_spoke || 0
        const speakRate = judged > 0 ? spoke / judged : 0
        const streamed = c.streams || 0
        const fallbacks = c.stream_fallbacks || 0
        const streamOk = streamed > 0 ? 1 - fallbacks / streamed : 1
        const runtime = dash.runtime || {}
        const actions = [
          ["图片文件", c.files_image || 0, "var(--dsw-alias-state-business-primary, #2f6bff)"],
          ["文档文件", c.files_doc || 0, "#0ea5e9"],
          ["审批通过", c.approvals_allow || 0, "#22c55e"],
          ["审批拒绝", c.approvals_deny || 0, "#ef4444"],
          ["提问回答", c.questions_answered || 0, "#8b5cf6"],
          ["提问超时", c.question_timeouts || 0, "#f97316"],
          ["禁言", c.mutes || 0, "#f59e0b"],
          ["解禁", c.unmutes || 0, "#14b8a6"],
          ["踢人", c.kicks || 0, "#dc2626"],
        ]
        const actionMax = actions.reduce(function (acc, item) { return Math.max(acc, item[1]) }, 1)
        const logText = Object.keys(logs).map(function (name) { return name.replace(".log", "") + " " + Math.round(logs[name] / 1024) + "KB" }).join(" · ") || "—"
        return h("div", { style: { display: "grid", gap: 14 } },
          h("div", { style: T.kpiRow },
            kpi("运行时长", human, (botInfo.online ? "在线" : "离线") + " · pid " + (botInfo.pid || "—")),
            kpi("消息（本区间）", rangeC2c + rangeGroup, "私聊 " + rangeC2c + " · 群 " + rangeGroup),
            kpi("开口（本区间）", rangeSpoke, "累计 " + spoke + " 次 · 判断 " + judged),
            kpi("流式（本区间）", rangeStreams, "累计 " + streamed + " 次 · 降级 " + fallbacks)),
          h("div", { style: T.kpiRow },
            kpi("累计消息", totalMsgs, "自首次运行起，重启不清零"),
            kpi("累计开口", spoke, "共判断 " + judged + " 次"),
            kpi("省下的调用", c.hook_skips || 0, "钩子预筛直接跳过"),
            kpi("内存/错误", (dash.memory_mb ? dash.memory_mb + " MB" : "—") + " / " + (dash.errors || 0), "工作集 / 日志 ERROR 数")),
          h("div", { style: T.actions },
            [["hour", "近 60 分钟"], ["today", "今天"], ["7d", "近 7 天"]].map(function (item) {
              return h("button", {
                key: item[0],
                style: dashRange === item[0] ? Object.assign({}, T.tab, T.tabActive) : T.tab,
                onClick: function () { setDashRange(item[0]) },
              }, item[1])
            }),
            h("span", { style: T.hint }, dashRange === "hour" ? "近 60 分钟，按分钟聚合" : "读取 state/metrics/*.jsonl，停机也留档")),          chartCard(dashRange === "hour" ? "近 60 分钟活动" : dashRange === "today" ? "今天每分钟活动" : "近 7 天每 30 分钟活动", [
            { label: "私聊", color: "#2f6bff" },
            { label: "群聊", color: "#22c55e" },
            { label: "开口", color: "#f59e0b" },
            { label: "流式", color: "#a855f7" },
          ], areaChart(points, ["c2c_msgs", "group_msgs", "judge_spoke", "streams"], {
            c2c_msgs: "#2f6bff", group_msgs: "#22c55e", judge_spoke: "#f59e0b", streams: "#a855f7",
          })),
          h("div", { style: T.kpiRow },
            h("div", { style: T.card }, ring(speakRate, "开口率", spoke + " / " + judged + " 次判断", "#f59e0b")),
            h("div", { style: T.card }, ring(streamed > 0 ? streamOk : 0, streamed > 0 ? "流式成功率" : "流式（暂无数据）", streamed + " 次 · 降级 " + fallbacks, "#a855f7")),
            h("div", { style: Object.assign({}, T.card, { gridColumn: "span 2" }) },
              h("div", { style: T.cardTitle }, "动作分布"),
              ...actions.map(function (item) { return barRow(item[0], item[1], actionMax, item[2]) }))),
          h("div", { style: T.kpiRow },
            kpi("队列残留", (queues.questions || 0) + (queues.admin || 0), "提问 " + (queues.questions || 0) + " · 管理 " + (queues.admin || 0)),
            kpi("成员索引", dash.members || 0, "本群发过言的成员"),
            kpi("日志体积", Math.round(Object.keys(logs).reduce(function (acc, k) { return acc + logs[k] }, 0) / 1024) + " KB", logText)),
          h("div", { style: T.kpiRow },
            kpi("内存占用", (dash.memory_mb ? dash.memory_mb + " MB" : "—"), "bot 进程工作集"),
            kpi("日志错误", dash.errors || 0, "最近 300KB 内 [ERROR] 行"),
            kpi("待处理", (runtime.inflight || 0) + (runtime.queued || 0) + (runtime.chatter || 0),
              "在跑 " + (runtime.inflight || 0) + " · 排队 " + (runtime.queued || 0) + " · 待判 " + (runtime.chatter || 0)),
            kpi("群图片/引用", (c.group_images || 0) + " / " + (c.quotes || 0), "含附件的群消息与引用次数")),
          h("div", { style: T.kpiRow },
            h("div", { style: T.card },
              h("div", { style: T.cardTitle }, "最近事件"),
              h("div", { style: T.eventList, "data-qq-scroll": "1" },
                ...(dash.events && dash.events.length
                  ? dash.events.map(function (item, index) {
                      const when = new Date(Number(item.at) * 1000)
                      const hhmm = ("0" + when.getHours()).slice(-2) + ":" + ("0" + when.getMinutes()).slice(-2)
                      return h("div", { key: "ev" + index, style: T.eventRow },
                        h("span", { style: T.eventTime }, hhmm),
                        h("span", { style: T.eventKind }, String(item.kind || "")),
                        h("span", { style: T.eventText }, String(item.text || "")))
                    })
                  : [h("div", { style: T.hint }, "还没有事件")]))),
            h("div", { style: T.card },
              h("div", { style: T.cardTitle }, "群资料"),
              ...(dash.groups_detail && dash.groups_detail.length
                ? dash.groups_detail.flatMap(function (group) {
                    const rows = [
                      h("div", { key: group.openid + "-name", style: T.cardRow },
                        h("span", { style: T.cardKey }, "群名"),
                        h("span", { style: T.cardValue }, group.name || "—")),
                      h("div", { key: group.openid + "-members", style: T.cardRow },
                        h("span", { style: T.cardKey }, "成员数"),
                        h("span", { style: T.cardValue }, String(group.members || 0))),
                    ]
                    if (group.memo) {
                      rows.push(h("div", { key: group.openid + "-memo", style: T.hint }, group.memo))
                    }
                    if (group.class || (group.tags || []).length) {
                      rows.push(h("div", { key: group.openid + "-tags", style: T.chipRow },
                        ...[group.class].concat(group.tags || []).filter(Boolean).map(function (tag) {
                          return h("span", { key: group.openid + tag, style: T.chip }, tag)
                        })))
                    }
                    return rows
                  })
                : [h("div", { style: T.hint }, "还没取到群资料（机器人收到群消息后会自动缓存）")])),
            h("div", { style: T.card },
              h("div", { style: T.cardTitle }, "群成员 · " + Object.keys(dash.members_detail || {}).reduce(function (sum, key) { return sum + ((dash.members_detail[key] || []).length) }, 0)),
              ...Object.keys(dash.members_detail || {}).length
                ? Object.keys(dash.members_detail || {}).flatMap(function (key) {
                    const groupName = (dash.group_names || {})[key.replace("group:", "")] || ""
                    const list = dash.members_detail[key] || []
                    const rows = [h("div", { key: key, style: T.footNote }, groupName ? groupName + " · " + key.replace("group:", "").slice(-8) : key.replace("group:", "").slice(-8))]
                    rows.push(h("div", { key: key + "-list", style: T.memberList, "data-qq-scroll": "1" },
                      ...(list.length
                        ? list.map(function (item) {
                            return h("div", { key: key + item.tail, style: T.memberRow },
                              item.avatar
                                ? h("img", { src: item.avatar, alt: item.tail, style: T.memberAvatar })
                                : h("span", { style: Object.assign({}, T.memberAvatar, { background: "var(--dsw-alias-border-l2)" }) }),
                              h("span", { style: T.memberName }, item.name || item.tail),
                              h("span", { style: T.memberTail }, item.name ? item.tail : ""))
                          })
                        : [h("div", { key: key + "-empty", style: T.hint }, "暂无")])))
                    if (list.length > 5) {
                      rows.push(h("div", { key: key + "-more", style: T.footNote }, "共 " + list.length + " 人 · 上下滚动查看全部"))
                    }
                    return rows
                  })
                : [h("div", { style: T.hint }, "暂无")])),
          h("div", { style: T.card },
            h("div", { style: T.cardTitle }, "历史留档（state/metrics）"),
            ...(dash.history && dash.history.length
              ? dash.history.slice(-7).reverse().map(function (item) {
                  return h("div", { key: item.day, style: T.cardRow },
                    h("span", { style: T.cardKey }, item.day),
                    h("span", { style: T.cardValue }, item.minutes + " 分钟 · " + item.total + " 次事件"))
                })
              : [h("div", { style: T.hint }, "还没有归档文件（每分钟结束后自动写一行 JSONL）")])),
          h("div", { style: T.footNote }, "计数与曲线跨重启保留（读 state/metrics），只有运行时长按本次启动计算。"))
      }
      const dot = function (ok) {
        return h("span", { style: Object.assign({}, T.dot, { background: ok === true ? "var(--dsw-alias-state-success-primary, #35c759)" : ok === false ? "var(--dsw-alias-label-error, #e5534b)" : "var(--dsw-alias-label-tertiary, #888)" }) })
      }

      const tabBar = h("div", { style: T.tabs },
        h("button", { style: tab === "settings" ? Object.assign({}, T.tab, T.tabActive) : T.tab, onClick: function () { setTab("settings") } }, "设置"),
        h("button", { style: tab === "dashboard" ? Object.assign({}, T.tab, T.tabActive) : T.tab, onClick: function () { setTab("dashboard") } }, "数据仪表盘"),
        h("button", { style: tab === "stickers" ? Object.assign({}, T.tab, T.tabActive) : T.tab, onClick: function () { setTab("stickers") } }, "表情包"))

      // 人设：一个大输入框一份，群聊与私聊分开
      const personaBox = function (key, title, hint) {
        return h("div", { key: key, style: T.card },
          h("div", { style: T.cardHead },
            h("span", { style: T.cardTitle }, title),
            h("span", { style: T.hint }, hint)),
          h("textarea", {
            style: T.textarea,
            rows: 8,
            placeholder: "写这里，例如：你是一条叫「蓝色大肥鱼」的群宠，话短、带口癖「喵」，不主动聊政治和带节奏。",
            value: value(key) === undefined ? "" : value(key),
            onChange: function (event) { setValue(key, event.target.value) },
          }))
      }

      if (tab === "dashboard") {
        return h("div", { style: T.page }, h("style", { key: "qq-scroll-css" }, SCROLLBAR_CSS), h("div", { style: T.inner }, tabBar, dashboardView()))
      }
      if (tab === "stickers") {
        return h("div", { style: T.page }, h("style", { key: "qq-scroll-css" }, SCROLLBAR_CSS), h("div", { style: T.inner }, tabBar, stickersView()))
      }

      return h("div", { style: Object.assign({}, T.page, T.pageTight) },
        h("style", { key: "qq-scroll-css" }, SCROLLBAR_CSS),
        h("div", { style: T.inner },
          h("div", { style: { paddingTop: 24 } }, tabBar),
          h("div", { style: Object.assign({}, T.stickyBar, T.stickyTop) },
            h("div", { style: T.actions },
              h("span", { style: T.badge }, dot(!!bot.running), "进程 · " + (bot.running ? "运行中" : "已停止")),
              h("span", { style: T.badge }, dot(!!bot.online), "在线 · " + (bot.online ? "是" : "否")),
              h("span", { style: T.badge }, dot(state.bridge === "ready"), "桥接 · " + (state.bridge || "?")),
              bot.pid ? h("span", { style: T.hint }, "pid " + bot.pid) : null),
            message ? h("div", { style: T.hint }, message) : null,
            h("div", { style: T.actions },
              h("button", { style: Object.assign({}, T.btn, T.btnPrimary), disabled: busy, onClick: function () { manage("start") } }, "启动"),
            h("button", { style: T.btn, disabled: busy, onClick: function () { manage("restart") } }, "重启"),
            h("button", { style: T.btn, disabled: busy, onClick: function () { manage("stop") } }, "关闭（不拉起）"),
            h("button", { style: T.btn, onClick: function () { window.open("https://q.qq.com/qqbot/", "_blank", "noopener") } }, "QQ 开放平台"),
            h("button", {
              style: T.btn,
              onClick: async function () {
                const target = String(config.auto_group_root || "D:\\dsh-qqbot-temp")
                try {
                  const result = await call("/api/open-folder", { method: "POST", body: JSON.stringify({ path: target }) })
                  setMessage(result.ok ? "已打开 " + target : "打不开：" + (result.error || target))
                } catch (error) {
                  setMessage("打不开：" + target)
                }
              },
              }, "打开分组文件夹"))),
          h("div", { style: T.sectionTitle }, "凭据"),
          CREDENTIALS.map(function (item) {
            return h(Row, { key: item[0], title: item[1] },
              h("input", {
                type: item[0].indexOf("secret") >= 0 ? "password" : "text",
                placeholder: item[0].indexOf("secret") >= 0 ? "不改" : "留空=用 config.json",
                style: Object.assign({}, T.input, T.inputWide),
                value: value(item[0]) === undefined ? "" : value(item[0]),
                onChange: function (event) { setValue(item[0], event.target.value) },
              }))
          }),
          h("div", { style: T.sectionTitle }, "机器人环境（把 Python / SDK / 机器人代码一次配好）"),
          h("div", { style: T.card },
            h("div", { style: T.cardRow },
              h("span", { style: T.cardKey }, "状态"),
              h("span", { style: T.cardValue },
                install === null ? "读取中…"
                  : install.running ? "正在配置…"
                    : (install.done && install.succeeded) ? "配置完成"
                      : install.installed ? "已配置" : "未用一键安装（按插件里的 pythonPath 启动）")),
            install && install.installed
              ? h("div", { style: T.hint }, "目录 " + install.installed.botDir + " · Python " + (install.installed.pythonVersion || "?"))
              : h("div", { style: T.hint }, "点按钮：找系统 Python（3.10+）→ 建 venv → pip 装 aiohttp / Pillow / viseron-qqbotpy → 复制机器人代码 → 写配置 → 拉起守护进程"),
            install && install.running && Array.isArray(install.steps)
              ? h("div", { style: T.hint }, "第 " + (install.step + 1) + "/" + install.steps.length + " 步：" + install.steps[install.step])
              : null,
            install && install.error ? h("div", { style: T.hint }, "失败：" + install.error) : null,
            installNote ? h("div", { style: T.hint }, installNote) : null,
            h("div", { style: T.actions },
              h("button", {
                style: Object.assign({}, T.btn, T.btnPrimary),
                disabled: busy || (install !== null && install.running === true),
                onClick: function () { void startInstall() },
              }, install && install.running ? "正在配置…" : "下载 / 配置机器人")),
            install && Array.isArray(install.lines) && install.lines.length
              ? h("pre", { style: T.log }, install.lines.slice(-60).join("\n"))
              : null),
          h("div", { style: T.sectionTitle }, "开关"),
          SWITCHES.map(function (item) {
            return h(Row, { key: item[0], title: item[1], hint: item[2] },
              h(Switch, { checked: !!value(item[0]), label: item[1], disabled: busy, onChange: function (next) { setValue(item[0], next) } }))
          }),
          h("div", { style: T.sectionTitle }, "人设（只在新会话的第一条消息里发一次）"),
          personaBox("persona_group", "群聊人设", "群聊里带的人设；留空=不启用"),
          personaBox("persona_c2c", "私聊人设", "单聊里带的人设；留空=不启用"),
          h("div", { style: T.sectionTitle }, "群聊节奏与发送"),
          h(QuietRow, {
            key: "quiet-hours",
            value: value("quiet_hours"),
            checked: !!value("quiet_enabled"),
            disabled: busy,
            onChange: function (next) { setValue("quiet_hours", next) },
            onChange2: function (next) { setValue("quiet_enabled", next) },
          }),
          NUMBERS.map(function (item) {
            return h(Row, { key: item[0], title: item[1] },
              h("input", {
                type: "number", min: item[2], max: item[3], style: T.input,
                value: value(item[0]) === undefined ? "" : value(item[0]),
                onChange: function (event) { setValue(item[0], Number(event.target.value)) },
              }))
          }),
          h(ModeRow, {
            key: "group-mode",
            value: value("group_mode"),
            disabled: busy,
            onChange: function (next) { setValue("group_mode", next) },
          }),          h("div", { style: T.sectionTitle }, "过滤与目录"),
          TEXTS.map(function (item) {
            return h(Row, { key: item[0], title: item[1] },
              h("input", {
                type: item[0].indexOf("secret") >= 0 ? "password" : "text",
                placeholder: "不改", style: Object.assign({}, T.input, T.inputWide),
                value: value(item[0]) === undefined ? "" : value(item[0]),
                onChange: function (event) { setValue(item[0], event.target.value) },
              }))
          }),
          h("div", { style: Object.assign({}, T.stickyBar, T.stickyBottom, { marginBottom: 24 }) },
            h("button", { style: Object.assign({}, T.btn, T.btnPrimary), disabled: busy, onClick: save }, "保存设置"),
            h("button", { style: T.btn, disabled: busy, onClick: function () { setDraft({}); load() } }, "重新读取"),
            h("span", { style: T.hint }, Object.keys(draft).length === 0 ? "（没有改动）" : "（有 " + Object.keys(draft).length + " 项未保存）")),
          h("div", { style: T.sectionTitle }, "运行日志（最近 200 行）"),
          h("div", { style: T.actions },
            h("button", { style: T.btn, onClick: function () { setPaused(!paused) } }, paused ? "继续刷新" : "暂停刷新"),
            h("button", {
              style: Object.assign({}, T.btn, follow ? { borderColor: "var(--dsw-alias-state-business-primary, #2f6bff)", color: "var(--dsw-alias-state-business-primary, #2f6bff)" } : {}),
              onClick: function () { setFollow(!follow) },
            }, follow ? "跟随中" : "已暂停跟随"),
            h("button", { style: T.btn, onClick: function () { setLogs([]) } }, "清屏")),
          h("pre", {
            style: T.log,
            ref: logRef,
            onScroll: function (event) {
              const node = event.target
              // 手动往上翻就暂停跟随；回到底部自动恢复
              setFollow(node.scrollHeight - node.scrollTop - node.clientHeight < 24)
            },
          }, logs.join("\n") || "(暂无日志)")
        ))
    }

    function QuietRow(props) {
      const value = String(props.value || "23:30-07:00")
      const pair = parseQuiet(value)
      const status = quietStatus(value)
      const setRange = function (index, next) {
        const parts = parseQuiet(value).slice()
        parts[index] = next || parts[index]
        props.onChange(parts[0] + "-" + parts[1])
      }
      const timeInput = function (index, label) {
        return h("span", { style: { display: "inline-flex", alignItems: "center", gap: 6 } },
          h("span", { style: T.hint }, label),
          h("input", {
            type: "time", value: pair[index], style: Object.assign({}, T.input, { width: 108, textAlign: "center" }),
            onChange: function (event) { setRange(index, event.target.value) },
          }))
      }
      return h("div", { style: Object.assign({}, T.row, { alignItems: "flex-start" }) },
        h("div", { style: T.labelBox },
          h("span", { style: T.title }, "静默时段（晚间群聊闲聊不回）"),
          h("span", { style: T.hint }, "按本机时间：静默时段内群里不主动插话，@ 与私聊照常回复"),
          h("span", { style: T.hint }, (status.inQuiet ? "当前为静默" : "当前不在静默") + " · 下次切换 " + status.label),
          h("div", { style: Object.assign({}, T.actions, { marginTop: 8 }) },
            timeInput(0, "开始"), h("span", { style: T.hint }, "至"), timeInput(1, "结束"))),
        h(Switch, { checked: !!props.checked, label: "静默时段生效", disabled: props.disabled, onChange: props.onChange2 }))
    }

    // 群聊主动消息模式：下拉式二选一（方案 A / 方案 B）
    function ModeRow(props) {
      const current = String(props.value || "A").toUpperCase() === "B" ? "B" : "A"
      const options = [
        ["A", "方案 A", "群里先攒几条消息，再由主会话判断要不要说话；跟它已有的对话上下文连着，插话会更自然。"],
        ["B", "方案 B", "用一个独立的判断会话先决定“说 / 不说”；决定要说时，把群聊记录原样交给主模型。判断与主对话隔离。"],
      ]
      const pill = function (key, label, hint) {
        const active = current === key
        return h("button", {
          key: key,
          type: "button",
          disabled: props.disabled,
          onClick: function () { props.onChange(key) },
          style: {
            padding: "6px 16px", borderRadius: 999, cursor: props.disabled ? "default" : "pointer", font: "inherit",
            border: "1px solid " + (active ? "var(--dsw-alias-label-primary, #fff)" : "var(--dsw-alias-border-l2)"),
            background: active ? "var(--dsw-alias-label-primary, #fff)" : "transparent",
            color: active ? "var(--dsw-alias-bg-layer-3, #1b1d23)" : "var(--dsw-alias-label-secondary)",
          },
        }, label)
      }
      const pick = options.filter(function (item) { return item[0] === current })[0]
      return h("div", { style: Object.assign({}, T.row, { alignItems: "flex-start" }) },
        h("div", { style: T.labelBox },
          h("span", { style: T.title }, "群聊主动消息模式"),
          h("span", { style: T.hint }, pick[2])),
        h("div", { style: Object.assign({}, T.actions, { flex: "0 0 auto" }) },
          options.map(function (item) { return pill(item[0], item[1], item[2]) })))
    }

    function SidebarIcon() {
      return h("span", { "aria-hidden": "true", style: { fontSize: 15, lineHeight: 1 } }, "🐟")
    }

    exports.inject = ["slots"]
    exports.apply = function apply(ctx) {
      ctx.slots.inject("sidebar.panellist", function () {
        const unregister = ctx.slots.register({ name: "sidebar.panellist", id: "qq-bridge", order: 120, label: function () { return "QQ 机器人" } }, SidebarIcon)
        return function () { unregister() }
      })
      ctx.slots.inject("main", function () {
        const unregister = ctx.slots.register({ name: "main", key: "qq-bridge", order: 120, label: function () { return "QQ 机器人" } }, QQBridgePage)
        return function () { unregister() }
      })
    }
    return module.exports
  },
})

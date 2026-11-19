/**
 * dsh-qq-bridge 的浏览器半身：左侧导航栏「QQ 机器人」+ 整页设置/日志。
 * 全部改用内联样式：宿主 main 槽位不在同一个样式作用域，注入 <style> 不可靠。
 */
window.__ModuleLoader__.load({
  id: "dsh-qq-bridge",
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" })

    const React = require("react")
    const h = React.createElement
    const PANEL = "http://127.0.0.1:39062"

    const T = {
      page: { width: "100%", height: "100%", minHeight: 0, overflow: "auto", boxSizing: "border-box", padding: "24px clamp(16px,4vw,48px) 32px", color: "var(--dsw-alias-label-primary)", fontFamily: "var(--dsw-font-family, inherit)" },
      inner: { width: "100%", maxWidth: 720, margin: "0 auto", display: "grid", gap: 14 },
      row: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, padding: "9px 0", borderTop: "1px solid var(--dsw-alias-border-l2)" },
      labelBox: { display: "grid", gap: 2, minWidth: 0 },
      title: { fontSize: 13, color: "var(--dsw-alias-label-primary)" },
      hint: { fontSize: 12, color: "var(--dsw-alias-label-tertiary)" },
      sectionTitle: { fontSize: 12, letterSpacing: "0.04em", color: "var(--dsw-alias-label-tertiary)", margin: "10px 0 2px" },
      input: { width: 132, padding: "5px 8px", border: "1px solid var(--dsw-alias-border-l2)", borderRadius: 6, background: "var(--dsw-alias-bg-layer-3)", color: "var(--dsw-alias-label-primary)", font: "inherit", textAlign: "right" },
      inputWide: { width: 260, textAlign: "left" },
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
          background: props.checked ? "var(--dsw-alias-brand-primary, #4c8dff)" : "var(--dsw-alias-border-l3, #4a4f5c)",
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
      md_auto: ["Markdown 自动发送", "回复像 Markdown 时用 msg_type=2"],
      stream_enabled: ["流式输出（仅私聊）", "平台只在单聊支持流式"],
      ack_enabled: ["“还在处理”占位提示", "会打断流式输出，默认关"],
      quote_enabled: ["识别引用消息", "引用时把被引用原文和来源一起带给模型"],
      capture_enabled: ["允许截屏", "/截图、/窗口 是否可用"],
      auto_group: ["自动分组（每个会话独立工作区）", "关闭则所有会话共用同一个工作目录"],
    }

    const SWITCHES = ["enabled","c2c_enabled","group_enabled","group_full_mode","md_auto","stream_enabled","ack_enabled","quote_enabled","capture_enabled","auto_group"]
      .map(function (key) { return [key, LABELS[key][0], LABELS[key][1]] })

    const NUMBERS = [
      ["chatter_batch","攒够几条触发判断",1,30], ["chatter_max_s","最长等待（秒）",5,600],
      ["chatter_cooldown_s","判断后冷却（秒）",0,1800], ["bot_say_memory_s","「最近说过」记忆（秒）",30,3600],
      ["stuck_turn_s","回合卡死判定（秒）",30,1800], ["ack_delay_s","迟到提示延迟（秒）",0,120],
      ["debounce_ms","连发合并（毫秒）",0,5000], ["max_chars","单条最大字数",200,4000],
      ["image_max_mb","图片上限（MB）",1,20], ["rate_limit_per_hour","每会话每小时上限（0=不限）",0,240],
      ["stream_interval_ms","流式节流（毫秒）",50,2000], ["quote_context_chars","引用原文上限（字）",50,2000],
      ["pool_ttl_s","消息池保留（秒）",60,86400], ["pool_max","消息池上限（条）",10,1000],
    ]

    const TEXTS = [
      ["group_mode","群聊主动消息模式（A / B）"], ["group_allowlist","群白名单（openid，逗号分隔）"],
      ["c2c_allowlist","私聊白名单（同上）"], ["bot_aliases","群内别名（逗号分隔）"],
      ["quiet_hours","静默时段（如 23:30-07:00）"], ["appid","APPID（留空=用 config.json）"],
      ["appsecret","APPSECRET（留空=不变，需重启）"],
      ["auto_group_root","自动分组根目录（如 D:\\dsh-qqbot-temp）"],
      ,
    ]

    function QQBridgePage() {
      const [state, setState] = React.useState(null)
      const [draft, setDraft] = React.useState({})
      const [message, setMessage] = React.useState("")
      const [busy, setBusy] = React.useState(false)
      const [logs, setLogs] = React.useState([])
      const [paused, setPaused] = React.useState(false)

      const call = React.useCallback(async function (path, options) {
        const response = await fetch(PANEL + path, Object.assign({ headers: { "content-type": "application/json" } }, options || {}))
        return await response.json()
      }, [])

      const load = React.useCallback(async function () {
        try { setState(await call("/api/state")) } catch (error) { setState({ offline: true }) }
      }, [call])

      React.useEffect(function () { load() }, [load])
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
        return h("div", { style: T.page }, h("div", { style: T.inner },
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
        try { await call("/api/config", { method: "POST", body: JSON.stringify(draft) }); setDraft({}); setMessage("已保存"); await load() }
        catch (error) { setMessage("保存失败") }
        setBusy(false)
      }
      const manage = async function (action) {
        setBusy(true)
        try { const result = await call("/api/manage", { method: "POST", body: JSON.stringify({ action: action }) }); setMessage(result.message || action); await load() }
        catch (error) { setMessage("操作失败") }
        setBusy(false)
      }
      const dot = function (ok) {
        return h("span", { style: Object.assign({}, T.dot, { background: ok === true ? "var(--dsw-alias-state-success-primary, #35c759)" : ok === false ? "var(--dsw-alias-label-error, #e5534b)" : "var(--dsw-alias-label-tertiary, #888)" }) })
      }

      return h("div", { style: T.page },
        h("div", { style: T.inner },
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
            }, "打开分组文件夹")),
          h("div", { style: T.sectionTitle }, "开关"),
          SWITCHES.map(function (item) {
            return h(Row, { key: item[0], title: item[1], hint: item[2] },
              h(Switch, { checked: !!value(item[0]), label: item[1], disabled: busy, onChange: function (next) { setValue(item[0], next) } }))
          }),
          h("div", { style: T.sectionTitle }, "群聊节奏与发送"),
          NUMBERS.map(function (item) {
            return h(Row, { key: item[0], title: item[1] },
              h("input", {
                type: "number", min: item[2], max: item[3], style: T.input,
                value: value(item[0]) === undefined ? "" : value(item[0]),
                onChange: function (event) { setValue(item[0], Number(event.target.value)) },
              }))
          }),
          h("div", { style: T.sectionTitle }, "过滤与凭据"),
          TEXTS.map(function (item) {
            return h(Row, { key: item[0], title: item[1] },
              h("input", {
                type: item[0].indexOf("secret") >= 0 ? "password" : "text",
                placeholder: "不改", style: Object.assign({}, T.input, T.inputWide),
                value: value(item[0]) === undefined ? "" : value(item[0]),
                onChange: function (event) { setValue(item[0], event.target.value) },
              }))
          }),
          h("div", { style: T.actions },
            h("button", { style: Object.assign({}, T.btn, T.btnPrimary), disabled: busy, onClick: save }, "保存设置"),
            h("button", { style: T.btn, disabled: busy, onClick: function () { setDraft({}); load() } }, "重新读取")),
          h("div", { style: T.sectionTitle }, "运行日志（最近 200 行）"),
          h("div", { style: T.actions },
            h("button", { style: T.btn, onClick: function () { setPaused(!paused) } }, paused ? "继续刷新" : "暂停刷新"),
            h("button", { style: T.btn, onClick: function () { setLogs([]) } }, "清屏")),
          h("pre", { style: T.log }, logs.join("\n") || "(暂无日志)")
        ))
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

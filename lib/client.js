/**
 * Browser half of dsh-qq-bridge: a settings section inside the DSH Web GUI.
 * Styling follows the official settings tokens (--dsw-*) and the official
 * role="switch" markup, so it matches the native settings pages.
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
    const CSS = "\n.dsh-qq-bridge { display: grid; gap: 12px; color: var(--dsw-alias-label-primary); }\n.dsh-qq-bridge__status { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; font-size: 13px; color: var(--dsw-alias-label-secondary); }\n.dsh-qq-bridge__badge { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 999px; font-size: 12px; }\n.dsh-qq-bridge__dot { width: 7px; height: 7px; border-radius: 50%; background: var(--dsw-alias-label-tertiary); }\n.dsh-qq-bridge__dot--ok { background: var(--dsw-alias-state-success-primary); }\n.dsh-qq-bridge__dot--bad { background: var(--dsw-alias-label-error); }\n.dsh-qq-bridge__section { display: grid; gap: 2px; }\n.dsh-qq-bridge__sectionTitle { font-size: 12px; letter-spacing: .04em; color: var(--dsw-alias-label-tertiary); margin: 8px 0 2px; }\n.dsh-qq-bridge__row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 7px 0; border-top: 1px solid var(--dsw-alias-border-l2); }\n.dsh-qq-bridge__row:first-of-type { border-top: 0; }\n.dsh-qq-bridge__label { display: grid; gap: 2px; min-width: 0; }\n.dsh-qq-bridge__title { font-size: 13px; color: var(--dsw-alias-label-primary); }\n.dsh-qq-bridge__hint { font-size: 12px; color: var(--dsw-alias-label-tertiary); }\n.dsh-qq-bridge__input { width: 120px; padding: 4px 8px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; background: var(--dsw-alias-bg-layer-3); color: var(--dsw-alias-label-primary); font: inherit; text-align: right; }\n.dsh-qq-bridge__input--wide { width: 240px; text-align: left; }\n.dsh-qq-bridge__actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }\n.dsh-qq-bridge__btn { padding: 5px 12px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px; background: transparent; color: var(--dsw-alias-label-primary); font: inherit; cursor: pointer; }\n.dsh-qq-bridge__btn:hover { border-color: var(--dsw-alias-border-l3); }\n.dsh-qq-bridge__btn--primary { background: var(--dsw-alias-label-primary); border-color: var(--dsw-alias-label-primary); color: var(--dsw-alias-bg-layer-3); }\n.dsh-qq-bridge__btn:disabled { opacity: .5; cursor: default; }\n.dsh-qq-bridge__switch { box-sizing: border-box; position: relative; flex: 0 0 auto; width: 36px; height: 20px; padding: 2px; border: 0; border-radius: 999px; background: var(--dsw-alias-border-l3); cursor: pointer; }\n.dsh-qq-bridge__switch[aria-checked='true'] { background: var(--dsw-alias-brand-primary); }\n.dsh-qq-bridge__switch:disabled { cursor: default; opacity: .5; }\n.dsh-qq-bridge__switch:focus-visible { outline: var(--dsw-focus-ring-width) solid var(--dsw-focus-ring-color, var(--dsw-alias-state-business-primary)); outline-offset: 2px; }\n.dsh-qq-bridge__thumb { display: block; width: 16px; height: 16px; border-radius: 50%; background: var(--dsw-alias-label-primary-foreground); transition: transform 120ms ease; }\n.dsh-qq-bridge__switch[aria-checked='false'] .dsh-qq-bridge__thumb { background: var(--dsw-alias-switch-thumb); }\n.dsh-qq-bridge__switch[aria-checked='true'] .dsh-qq-bridge__thumb { transform: translateX(16px); }\n"

    const SWITCHES = [["enabled","接收消息（总）","关掉后私聊与群聊都不响应"],["c2c_enabled","私聊响应",""],["group_enabled","群聊响应",""],["group_full_mode","群全量消息","需在开放平台开启全量接收"],["md_auto","Markdown 自动发送","回复像 Markdown 时用 msg_type=2"],["stream_enabled","流式输出（仅私聊）","平台只在单聊支持流式，群里整段发"],["capture_enabled","允许截屏","/截图、/窗口 是否可用"]]
    const NUMBERS = [["chatter_batch","攒够几条触发判断",1,30],["chatter_max_s","最长等待（秒）",5,600],["chatter_cooldown_s","判断后冷却（秒）",0,1800],["bot_say_memory_s","「最近说过」记忆（秒）",30,3600],["stuck_turn_s","回合卡死判定（秒）",30,1800],["ack_delay_s","迟到提示延迟（秒）",0,120],["debounce_ms","连发合并（毫秒）",0,5000],["max_chars","单条最大字数",200,4000],["image_max_mb","图片上限（MB）",1,20],["rate_limit_per_hour","每会话每小时上限（0=不限）",0,240],["stream_interval_ms","流式节流（毫秒）",50,2000]]
    const TEXTS = [["group_allowlist","群白名单（openid，逗号分隔，空=全部）"],["c2c_allowlist","私聊白名单（同上）"],["bot_aliases","群内别名（逗号分隔）"],["quiet_hours","静默时段（如 23:30-07:00，@ 仍回复）"],["appid","APPID（留空=用 .env）"],["appsecret","APPSECRET（留空=用 .env，需重启）"]]

    function useStyle() {
      React.useEffect(function () {
        if (document.getElementById("dsh-qq-bridge-style")) return
        const style = document.createElement("style")
        style.id = "dsh-qq-bridge-style"
        style.textContent = CSS
        document.head.appendChild(style)
      }, [])
    }

    function Row(props) {
      return h("div", { className: "dsh-qq-bridge__row" },
        h("div", { className: "dsh-qq-bridge__label" },
          h("span", { className: "dsh-qq-bridge__title" }, props.title),
          props.hint ? h("span", { className: "dsh-qq-bridge__hint" }, props.hint) : null),
        props.children)
    }

    function Switch(props) {
      return h("button", {
        type: "button", role: "switch",
        "aria-checked": props.checked ? "true" : "false",
        "aria-label": props.label, disabled: props.disabled,
        className: "dsh-qq-bridge__switch",
        onClick: function () { props.onChange(!props.checked) }
      }, h("span", { "aria-hidden": "true", className: "dsh-qq-bridge__thumb" }))
    }

    function QQBridgeSettings() {
      useStyle()
      const [state, setState] = React.useState(null)
      const [draft, setDraft] = React.useState({})
      const [message, setMessage] = React.useState("")
      const [busy, setBusy] = React.useState(false)
      const call = React.useCallback(async function (path, options) {
        const response = await fetch(PANEL + path, Object.assign({ headers: { "content-type": "application/json" } }, options || {}))
        return await response.json()
      }, [])
      const load = React.useCallback(async function () {
        try { setState(await call("/api/state")) } catch (error) { setState({ offline: true }) }
      }, [call])
      React.useEffect(function () { load() }, [load])
      React.useEffect(function () { const timer = setInterval(load, 6000); return function () { clearInterval(timer) } }, [load])
      if (state !== null && state.offline) {
        return h("div", { className: "dsh-qq-bridge" },
          h("div", { className: "dsh-qq-bridge__title" }, "机器人的设置服务没有运行"),
          h("div", { className: "dsh-qq-bridge__hint" }, "在 DSH 里启动一次 python -u main.py --supervise，或双击 bot\\run-bot.bat，然后刷新。"),
          h("div", { className: "dsh-qq-bridge__actions" }, h("button", { className: "dsh-qq-bridge__btn", onClick: load }, "重试")))
      }
      if (state === null) return h("div", { className: "dsh-qq-bridge__hint" }, "读取中…")
      const config = state.config || {}
      const bot = state.bot || {}
      const value = function (key) { return key in draft ? draft[key] : config[key] }
      const setValue = function (key, next) { const copy = Object.assign({}, draft); copy[key] = next; setDraft(copy) }
      const save = async function () {
        setBusy(true)
        try { await call("/api/config", { method: "POST", body: JSON.stringify(draft) }); setDraft({}); setMessage("已保存，立即生效（凭据需重启）"); await load() }
        catch (error) { setMessage("保存失败：设置服务不可达") }
        setBusy(false)
      }
      const manage = async function (action) {
        setBusy(true)
        try { const result = await call("/api/manage", { method: "POST", body: JSON.stringify({ action: action }) }); setMessage(result.message || action); await load() }
        catch (error) { setMessage("操作失败：设置服务不可达") }
        setBusy(false)
      }
      const badge = function (text, ok) {
        return h("span", { className: "dsh-qq-bridge__badge" },
          h("span", { className: "dsh-qq-bridge__dot" + (ok === true ? " dsh-qq-bridge__dot--ok" : ok === false ? " dsh-qq-bridge__dot--bad" : "") }), text)
      }
      const sw = function (item) {
        return h(Row, { key: item[0], title: item[1], hint: item[2] },
          h(Switch, { checked: !!value(item[0]), label: item[1], disabled: busy, onChange: function (next) { setValue(item[0], next) } }))
      }
      const num = function (item) {
        return h(Row, { key: item[0], title: item[1] },
          h("input", { className: "dsh-qq-bridge__input", type: "number", min: item[2], max: item[3],
            value: value(item[0]) === undefined ? "" : value(item[0]),
            onChange: function (event) { setValue(item[0], Number(event.target.value)) } }))
      }
      const text = function (item) {
        return h(Row, { key: item[0], title: item[1] },
          h("input", { className: "dsh-qq-bridge__input dsh-qq-bridge__input--wide",
            type: item[0].indexOf("secret") >= 0 ? "password" : "text", placeholder: "不改",
            value: value(item[0]) === undefined ? "" : value(item[0]),
            onChange: function (event) { setValue(item[0], event.target.value) } }))
      }
      return h("div", { className: "dsh-qq-bridge" },
        h("div", { className: "dsh-qq-bridge__status" },
          badge("进程 · " + (bot.running ? "运行中" : "已停止"), !!bot.running),
          badge("在线 · " + (bot.online ? "是" : "否"), !!bot.online),
          badge("桥接 · " + (state.bridge || "?"), state.bridge === "ready"),
          bot.pid ? h("span", { className: "dsh-qq-bridge__hint" }, "pid " + bot.pid) : null),
        message ? h("div", { className: "dsh-qq-bridge__hint" }, message) : null,
        h("div", { className: "dsh-qq-bridge__actions" },
          h("button", { className: "dsh-qq-bridge__btn dsh-qq-bridge__btn--primary", disabled: busy, onClick: function () { manage("start") } }, "启动"),
          h("button", { className: "dsh-qq-bridge__btn", disabled: busy, onClick: function () { manage("restart") } }, "重启"),
          h("button", { className: "dsh-qq-bridge__btn", disabled: busy, onClick: function () { manage("stop") } }, "关闭（不拉起）")),
        h("div", { className: "dsh-qq-bridge__actions" },
          h("button", { className: "dsh-qq-bridge__btn", onClick: function () { window.open(PANEL + "/", "_blank", "noopener") } }, "打开网页版设置页"),
          h("button", { className: "dsh-qq-bridge__btn", onClick: function () { window.open("https://q.qq.com/qqbot/", "_blank", "noopener") } }, "打开 QQ 网页端设置")),
        h("div", { className: "dsh-qq-bridge__section" },
          h("div", { className: "dsh-qq-bridge__sectionTitle" }, "开关"), SWITCHES.map(sw)),
        h("div", { className: "dsh-qq-bridge__section" },
          h("div", { className: "dsh-qq-bridge__sectionTitle" }, "群聊节奏与发送"), NUMBERS.map(num)),
        h("div", { className: "dsh-qq-bridge__section" },
          h("div", { className: "dsh-qq-bridge__sectionTitle" }, "过滤与凭据"), TEXTS.map(text)),
        h("div", { className: "dsh-qq-bridge__actions" },
          h("button", { className: "dsh-qq-bridge__btn dsh-qq-bridge__btn--primary", disabled: busy, onClick: save }, "保存设置"),
          h("button", { className: "dsh-qq-bridge__btn", disabled: busy, onClick: function () { setDraft({}); load() } }, "重新读取")))
    }

    exports.inject = ["slots"]
    exports.apply = function apply(ctx) {
      ctx.slots.inject("settings.section", function () {
        return ctx.slots.register({ name: "settings.section", id: "qq-bridge", order: 150, label: function () { return "QQ 机器人" } }, QQBridgeSettings)
      })
    }
    return module.exports
  },
})

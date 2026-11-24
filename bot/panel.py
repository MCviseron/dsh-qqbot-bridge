"""Local settings page for the QQ bot.

Served by the supervisor process, so the page keeps answering while the bot
itself is stopped (that is what makes the 启动/关闭 buttons possible).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid

import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("dsh-qq-bot.panel")
STICKER_DIR = Path(__file__).resolve().parent.parent / "assets" / "stickers"

from aiohttp import web

from runtime_config import RuntimeConfig



def build_app(control: Any, runtime: RuntimeConfig, token: str) -> web.Application:
    """Create the aiohttp app; `control` owns the process lifecycle."""

    app = web.Application(middlewares=[])

    def authorised(request: web.Request) -> bool:
        # The server binds loopback only, so the DSH GUI (another local port)
        # may call it without a token; a supplied token is still verified.
        supplied = request.headers.get("x-panel-token") or request.query.get("t") or ""
        if supplied == "":
            return True
        return token == "" or supplied == token

    @web.middleware
    async def cors(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.method == "OPTIONS":
            response: web.StreamResponse = web.Response(status=204)
        else:
            response = await handler(request)
        response.headers["access-control-allow-origin"] = "*"
        response.headers["access-control-allow-headers"] = "content-type,x-panel-token"
        response.headers["access-control-allow-methods"] = "GET,POST,OPTIONS"
        return response

    async def state(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        return web.json_response({
            "ok": True,
            "bot": control.status(),
            "config": runtime.snapshot(),
            "bridge": control.bridge_state(),
        })

    async def update_config(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            patch = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        if not isinstance(patch, dict):
            return web.json_response({"ok": False, "error": "body must be an object"}, status=400)
        known = set(runtime.snapshot().keys())
        unknown = sorted(k for k in patch.keys() if k not in known)
        if unknown:
            # 新增设置项只在重启守护进程后才进 DEFAULTS；这里明确报出来，避免"保存了却没生效"。
            log.warning("config keys ignored (not in this process's DEFAULTS): %s", ",".join(unknown))
        config = runtime.update(patch)
        return web.json_response({
            "ok": True,
            "config": runtime.snapshot(),
            "saved": len(config),
            "unknown": unknown,
        })

    async def manage(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = str((body or {}).get("action") or "")
        if action not in {"start", "stop", "restart"}:
            return web.json_response({"ok": False, "error": "unknown action"}, status=400)
        message = await control.perform(action)
        return web.json_response({"ok": True, "action": action, "message": message, "bot": control.status()})

    async def question(request: web.Request) -> web.Response:
        """Called by the plugin: render a dsh question as an inline keyboard."""
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        conv_key = str((body or {}).get("convKey") or "")
        question_id = str((body or {}).get("id") or "")
        text = str((body or {}).get("question") or "")
        options = [str(item) for item in ((body or {}).get("options") or [])]
        if conv_key == "" or question_id == "" or not options:
            return web.json_response({"ok": False, "error": "convKey/id/options required"}, status=400)
        # 面板跑在守护进程里，QQ 客户端在子进程里：用文件队列交给子进程发卡片
        outbox = Path("state") / "questions"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / f"{question_id}.json").write_text(
            json.dumps({"convKey": conv_key, "id": question_id, "question": text, "options": options}, ensure_ascii=False),
            encoding="utf-8",
        )
        return web.json_response({"ok": True})
    async def admin(request: web.Request) -> web.Response:
        """Queue a group-admin action for the bot process and wait for its result."""
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        action = str((body or {}).get("action") or "")
        if action == "members":
            # 成员索引由机器人进程维护，面板直接读同一份文件
            try:
                known = json.loads((Path("state") / "members.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                known = {}
            return web.json_response({"ok": True, "members": known})
        if action == "groups":
            try:
                profiles = json.loads((Path("state") / "groups.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                profiles = {}
            return web.json_response({"ok": True, "groups": profiles})
        if action not in ("mute", "kick", "members", "mute_state", "group", "muted", "member", "stats"):
            return web.json_response(
                {"ok": False, "error": "action must be one of mute/kick/members/mute_state/group/muted/member/stats"},
                status=400,
            )
        request_id = str((body or {}).get("id") or uuid.uuid4())
        outbox = Path("state") / "admin"
        outbox.mkdir(parents=True, exist_ok=True)
        target = outbox / f"{request_id}.json"
        target.write_text(json.dumps({**body, "id": request_id, "status": "pending"}, ensure_ascii=False), encoding="utf-8")
        deadline = time.time() + 15
        while time.time() < deadline:
            await asyncio.sleep(0.4)
            try:
                done = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if done.get("status") == "waiting":
                # 踢人需要主人在私聊里二次确认：立刻回话，不等 15 秒
                return web.json_response(
                    {"ok": True, "pending": True, "error": None, "hint": "已发送私聊二次确认，等你点头才执行"}
                )
            if done.get("status") == "done":
                target.unlink(missing_ok=True)
                payload = {key: value for key, value in done.items() if key not in ("status", "_path")}
                payload["ok"] = bool(done.get("ok"))
                return web.json_response(payload)
        return web.json_response({"ok": False, "error": "机器人没响应（可能没在运行）"}, status=504)
    async def open_folder(request: web.Request) -> web.Response:
        """Open a workspace folder in Explorer (local convenience only)."""
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            body = await request.json()
        except Exception:
            body = {}
        path = str((body or {}).get("path") or "")
        target = Path(path).expanduser().resolve()
        allowed = Path(str(runtime.get("auto_group_root") or "")).expanduser().resolve()
        if path.strip() == "" or not target.exists():
            return web.json_response({"ok": False, "error": "no such folder"}, status=400)
        if str(allowed) not in ("", ".", str(Path("."))):
            try:
                target.relative_to(allowed)
            except ValueError:
                return web.json_response({"ok": False, "error": "outside auto_group_root"}, status=403)
        try:
            if os.name == "nt":
                os.startfile(str(target))  # noqa: S606 - user-invoked
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as error:
            return web.json_response({"ok": False, "error": str(error)}, status=500)
        return web.json_response({"ok": True})

    async def logs(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"ok": False, "error": "bad token"}, status=401)
        try:
            limit = int(request.query.get("lines", "300"))
        except ValueError:
            limit = 300
        getter = getattr(control, "logs", None)
        lines = getter(limit) if callable(getter) else []
        return web.json_response({"ok": True, "lines": lines})

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "panel": "dsh-qq-bot", "bot": control.status()})

    app.middlewares.append(cors)
    async def stickers(request: web.Request) -> web.Response:
        """List, upload, rename and delete the bot sticker pack."""
        folder = Path(STICKER_DIR)
        folder.mkdir(parents=True, exist_ok=True)

        if request.method == "GET":
            wanted = request.query.get("file")
            if wanted:
                try:
                    target = (folder / wanted).resolve(strict=True)
                    target.relative_to(folder.resolve())
                except (OSError, ValueError):
                    return web.Response(status=404)
                if not target.is_file():
                    return web.Response(status=404)
                return web.FileResponse(target)
            items = []
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    stat = path.stat()
                    items.append({"name": path.stem, "file": path.name, "bytes": stat.st_size, "mtime": int(stat.st_mtime)})
            return web.json_response({"ok": True, "stickers": items, "dir": str(folder)})

        body = await request.json()
        action = str((body or {}).get("action") or "upload")

        def safe_stem(raw: str) -> str:
            cleaned = "".join(ch for ch in str(raw) if ch.isalnum() or ch in "-_ ").strip()
            return cleaned[:40]

        if action == "delete":
            stem = safe_stem((body or {}).get("name") or "")
            removed = 0
            for path in folder.iterdir():
                if path.is_file() and path.stem == stem:
                    path.unlink(missing_ok=True)
                    removed += 1
            return web.json_response({"ok": removed > 0, "removed": removed})

        if action == "rename":
            old = safe_stem((body or {}).get("name") or "")
            new = safe_stem((body or {}).get("to") or "")
            if not old or not new:
                return web.json_response({"ok": False, "error": "name/to required"}, status=400)
            for path in folder.iterdir():
                if path.is_file() and path.stem == old:
                    path.rename(folder / (new + path.suffix.lower()))
                    return web.json_response({"ok": True, "name": new})
            return web.json_response({"ok": False, "error": "not found"}, status=404)

        raw = str((body or {}).get("data") or "")
        name = safe_stem((body or {}).get("name") or "")
        if not raw or not name:
            return web.json_response({"ok": False, "error": "name/data required"}, status=400)
        if raw.startswith("data:"):
            header, _, encoded = raw.partition(",")
            ext = header.split("image/", 1)[1].split(";", 1)[0].strip().lower() if "image/" in header else "png"
            suffix = ".jpg" if ext in ("jpeg", "jpg") else "." + (ext or "png")
        else:
            encoded, suffix = raw, ".png"
        try:
            payload = base64.b64decode(encoded, validate=False)
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "error": "bad base64"}, status=400)
        if len(payload) > 4 * 1024 * 1024:
            return web.json_response({"ok": False, "error": "图片超过 4MB"}, status=400)
        target = folder / (name + suffix)
        target.write_bytes(payload)
        return web.json_response({"ok": True, "name": name, "file": target.name, "bytes": len(payload)})
    async def dashboard(request: web.Request) -> web.Response:
        """Aggregated counters for the panel dashboard (read-only)."""
        def read_json(path: Path, default):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return default

        metrics = read_json(Path("state") / "metrics.json", {})
        members = read_json(Path("state") / "members.json", {})
        groups_raw = read_json(Path("state") / "groups.json", {})
        group_names = {}
        groups_detail = []
        for key, value in (groups_raw or {}).items():
            if not isinstance(value, dict):
                continue
            group_names[key] = str(value.get("name") or "")
            groups_detail.append({
                "openid": key,
                "name": str(value.get("name") or ""),
                "memo": str(value.get("memo") or ""),
                "class": str(value.get("class") or ""),
                "tags": list(value.get("tags") or []),
                "members": int(value.get("members") or 0),
                "fetched_at": int(value.get("fetched_at") or 0),
            })
        member_count = sum(len(items) for items in members.values()) if isinstance(members, dict) else 0
        queue_counts = {}
        for name in ("questions", "admin"):
            folder = Path("state") / name
            queue_counts[name] = len(list(folder.glob("*.json"))) if folder.is_dir() else 0
        log_sizes = {}
        log_dir = Path("logs")
        if log_dir.is_dir():
            for path in sorted(log_dir.glob("*.log")):
                try:
                    log_sizes[path.name] = path.stat().st_size
                except OSError:
                    pass
        range_key = str(request.query.get("range") or "hour")
        metrics_dir = Path("state") / "metrics"
        history_days = []
        try:
            if metrics_dir.is_dir():
                for path in sorted(metrics_dir.glob("*.jsonl")):
                    total = 0
                    minutes = 0
                    try:
                        for line in path.read_text(encoding="utf-8").splitlines():
                            if not line.strip():
                                continue
                            row = json.loads(line)
                            minutes += 1
                            for key, value in row.items():
                                if key != "minute":
                                    total += int(value)
                    except (OSError, ValueError):
                        continue
                    history_days.append({"day": path.stem, "minutes": minutes, "total": total})
        except OSError:
            history_days = []
        file_series = []
        if range_key in ("today", "7d") and metrics_dir.is_dir():
            wanted = sorted(metrics_dir.glob("*.jsonl"))[-7:] if range_key == "7d" else sorted(metrics_dir.glob("*.jsonl"))[-1:]
            for path in wanted:
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            row = json.loads(line)
                            file_series.append({"t": int(row.pop("minute")), **{k: int(v) for k, v in row.items()}})
                except (OSError, ValueError):
                    continue
            file_series.sort(key=lambda row: row["t"])
        raw_series = metrics.get("series") or {}
        series = []
        try:
            for bucket in sorted(raw_series, key=lambda key: int(key))[-90:]:
                cell = raw_series[bucket]
                series.append({"t": int(bucket), **{k: int(v) for k, v in cell.items()}})
        except (TypeError, ValueError):
            series = []
        error_count = 0
        try:
            log_path = Path("logs") / "viseron_qqbotpy.log"
            if log_path.exists():
                with log_path.open("rb") as handle:
                    handle.seek(max(0, log_path.stat().st_size - 300_000))
                    error_count = handle.read().count(b"[ERROR]")
        except OSError:
            pass
        memory_mb = None
        try:
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pid = None
            try:
                pid = int((Path("state") / "child.pid").read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = None
            if pid:
                counters = _Counters()
                counters.cb = ctypes.sizeof(_Counters)
                handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
                if handle:
                    if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                        memory_mb = round(counters.WorkingSetSize / 1024 / 1024, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001 - metrics must never break the endpoint
            memory_mb = None
        started = float(metrics.get("started_at") or 0.0)
        # 运行时长属于进程寿命：优先用监督进程记的子进程启动时间，文件里的 started_at 只作兜底
        live_uptime = (state_doc.get("bot") or {}).get("uptime_s")
        state_doc = {}
        try:
            state_doc = await state(request)
            state_doc = json.loads(state_doc.body.decode("utf-8"))
        except Exception:  # noqa: BLE001 - dashboard must render even if state fails
            state_doc = {}
        return web.json_response({
            "ok": True,
            "bot": state_doc.get("bot", {}),
            "counters": {key: value for key, value in metrics.items() if key not in ("started_at", "series")},
            "uptime_s": int(live_uptime) if isinstance(live_uptime, (int, float)) and live_uptime >= 0
            else (int(time.time() - started) if started else None),
            "queues": queue_counts,
            "logs": log_sizes,
            "members": member_count,
            "group_names": group_names,
            "groups_detail": groups_detail,
            "series": series if range_key == "hour" else file_series[-1440:],
            "range": range_key,
            "history": history_days,
            "events": list(reversed((metrics.get("events") or [])[-12:])),
            "runtime": metrics.get("runtime") or {},
            "memory_mb": memory_mb,
            "errors": error_count,
            "members_detail": {
                key: [
                    {"tail": tail, "name": (info or {}).get("name", ""), "avatar": (info or {}).get("avatar", "")}
                    for tail, info in list(value.items())[:30]
                ]
                for key, value in (members or {}).items()
                if isinstance(value, dict)
            } if isinstance(members, dict) else {},
            "config": state_doc.get("config", {}),
        })
    app.router.add_get("/health", health)
    app.router.add_get("/api/state", state)
    app.router.add_get("/api/dashboard", dashboard)
    app.router.add_get("/api/stickers", stickers)
    app.router.add_post("/api/stickers", stickers)
    app.router.add_get("/api/logs", logs)
    app.router.add_post("/api/config", update_config)
    app.router.add_post("/api/manage", manage)
    app.router.add_post("/api/open-folder", open_folder)
    app.router.add_post("/api/question", question)
    app.router.add_post("/api/admin", admin)
    return app


def start_panel(control: Any, runtime: RuntimeConfig, host: str, port: int, token: str) -> threading.Thread:
    """Run the page in a background thread with its own event loop."""

    def runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = build_app(control, runtime, token)
        app_runner = web.AppRunner(app)
        loop.run_until_complete(app_runner.setup())
        site = web.TCPSite(app_runner, host, port)
        try:
            loop.run_until_complete(site.start())
            print(f"[panel] settings page on http://{host}:{port}/?t=<token>", flush=True)
            loop.run_forever()
        except OSError as error:
            print(f"[panel] could not bind {host}:{port}: {error}", flush=True)

    thread = threading.Thread(target=runner, name="qq-bot-panel", daemon=True)
    thread.start()
    return thread

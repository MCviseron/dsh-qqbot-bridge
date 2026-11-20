"""Loopback HTTP client for the dsh-qq-bridge DSH plugin.

The plugin owns the DSH Sessions; this module is only the transport between
the QQ gateway and that plugin, so nothing here knows about agents or tools.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

# QQ 侧只认这几种图片类型
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

log = logging.getLogger("dsh.bot.bridge")


class BridgeError(RuntimeError):
    """The bridge plugin is unreachable or answered with an error."""


class BridgeClient:
    """Thin async client for the plugin's loopback routes."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def _session_or_create(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = await self._session_or_create()
        headers = {"x-bridge-token": self.token} if self.token else {}
        url = f"{self.base_url}{path}"
        try:
            async with session.request(method, url, params=params, json=payload, headers=headers) as response:
                body = await response.text()
                if response.status != 200:
                    raise BridgeError(f"{method} {path} -> {response.status}: {body[:300]}")
                return json.loads(body) if body.strip() else {}
        except aiohttp.ClientError as error:
            raise BridgeError(f"{method} {path} failed: {error}") from error

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def status(self) -> Dict[str, Any]:
        return await self._request("GET", "/status")

    async def inbound(
        self,
        *,
        conv_key: str,
        text: str,
        sender_name: str = "",
        is_owner: bool = False,
        approval_target: str = "",
        images: Optional[List[Dict[str, str]]] = None,
        context_only: bool = False,
        chime: bool = False,
        quote: Optional[Dict[str, Any]] = None,
        auto_group: Optional[bool] = None,
        auto_group_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Hand one QQ message to DSH; the answer arrives through :meth:`pull`.

        `context_only` only feeds the plugin's rolling group transcript, so
        background chatter costs no agent turn.
        """
        return await self._request(
            "POST",
            "/inbound",
            payload={
                "convKey": conv_key,
                "text": text,
                "senderName": sender_name,
                "isOwner": bool(is_owner),
                "approvalTarget": approval_target,
                "images": images or [],
                "contextOnly": bool(context_only),
                "chime": bool(chime),
                "quote": quote,
                "autoGroup": auto_group,
                "autoGroupRoot": auto_group_root,
            },
        )

    async def judge(self, conv_key: str, transcript: str) -> Dict[str, Any]:
        """Ask the plugin's independent judge session whether to answer."""
        return await self._request(
            "POST",
            "/judge",
            payload={"convKey": conv_key, "transcript": transcript},
        )

    async def answer_question(self, question_id: str, index: int) -> Dict[str, Any]:
        """Deliver a picked option back to the plugin's pending user-questions/request."""
        return await self._request("POST", "/answer", payload={"id": question_id, "index": int(index)})

    async def commands(self, conv_key: str) -> Dict[str, Any]:
        """List the DSH slash commands available to this conversation's session."""
        return await self._request("POST", "/commands", payload={"convKey": conv_key})

    async def run_command(self, conv_key: str, line: str) -> Dict[str, Any]:
        """Execute one DSH slash command through the official command runtime."""
        return await self._request("POST", "/command", payload={"convKey": conv_key, "line": line})

    async def rebind(self, conv_key: str) -> Dict[str, Any]:
        """Re-create the DSH session for one conversation (used by /分组)."""
        return await self._request("POST", "/rebind", payload={"convKey": conv_key})

    async def permission(self, conv_key: str, preset: Optional[str] = None) -> Dict[str, Any]:
        """Read or switch the DSH permission preset for one conversation."""
        return await self._request(
            "POST",
            "/permission",
            payload={"convKey": conv_key, "preset": preset or ""},
        )

    async def pull(self, cursor: Optional[int], wait_ms: int) -> Dict[str, Any]:
        """Long-poll the outbox; cursor=None starts from the current tail."""
        params: Dict[str, Any] = {"wait": max(0, int(wait_ms))}
        if cursor is not None:
            params["since"] = int(cursor)
        return await self._request("GET", "/pull", params=params)

    async def approve(self, approval_id: str, decision: str) -> Dict[str, Any]:
        """Answer one pending approval: allow / reject / cancel."""
        return await self._request(
            "POST",
            "/approval",
            payload={"approvalId": approval_id, "decision": decision},
        )

    async def switch_session(self, conv_key: str, session_id: str) -> Dict[str, Any]:
        """Rebind one QQ conversation onto another existing Session ("" = go back)."""
        return await self._request(
            "POST",
            "/switch",
            payload={"convKey": conv_key, "sessionId": session_id},
        )

    async def sessions(self) -> Dict[str, Any]:
        """Bindings this plugin knows plus the Host's own Session list."""
        return await self._request("GET", "/sessions")

    async def reset(self, conv_key: str) -> Dict[str, Any]:
        """Forget the conversation's Session binding so the next message starts fresh."""
        return await self._request("POST", "/reset", payload={"convKey": conv_key})


def normalize_image(data: bytes, *, max_side: int = 1280, budget: int = 400_000) -> Optional[Tuple[bytes, str]]:
    """Re-encode any decodable image into a clean PNG/JPEG for DSH.

    DSH decodes image bytes with sharp and rejects anything it cannot parse, so
    the payload is normalized here instead of trusting the source format: this
    also drops odd EXIF/ICC profiles and shrinks screenshots before upload.
    """
    try:
        from PIL import Image, ImageFile
        # QQ's CDN regularly cuts the tail of a transfer (measured: exactly 64 KiB
        # dumps missing the JPEG EOI); Pillow refuses those unless truncation is
        # tolerated. The re-encode below always emits a complete file.
        ImageFile.LOAD_TRUNCATED_IMAGES = True
    except ImportError:
        log.warning("Pillow is not installed; keeping the original image bytes")
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = image.convert("RGB")
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            png = buffer.getvalue()
            if len(png) <= budget:
                return png, "image/png"
            # The bridge caps its JSON body at 1 MiB, so keep the encoded image
            # small enough that base64 (+33%) always fits.
            for quality in (85, 75, 65, 55):
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                jpeg = buffer.getvalue()
                if len(jpeg) <= budget:
                    return jpeg, "image/jpeg"
            return jpeg, "image/jpeg"
    except Exception as error:  # noqa: BLE001 - retry once with truncated input allowed
        try:
            from PIL import Image, ImageFile
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                image = image.convert("RGB")
                if max(image.size) > max_side:
                    image.thumbnail((max_side, max_side))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=80, optimize=True)
                return buffer.getvalue(), "image/jpeg"
        except Exception:  # noqa: BLE001 - really not decodable
            print(f"[image] re-encode failed: {error}", flush=True)
            return None


def sniff_media_type(data: bytes) -> str:
    """Detect the real image type from magic bytes (QQ often lies in Content-Type)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def normalize_media_type(content_type: str) -> str:
    """Map the platform's MIME spelling onto the types DSH accepts."""
    value = (content_type or "").split(";")[0].strip().lower()
    if value in {"image/jpg", "image/pjpeg"}:
        return "image/jpeg"
    return value if value in IMAGE_TYPES else ""


async def download_image(
    url: str,
    *,
    max_bytes: int,
    dump_dir: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Fetch one QQ attachment URL and return a base64 image part for DSH.

    DSH decodes image bytes with sharp and rejects anything that is not a real
    png/jpeg/webp/gif, so the type is sniffed from magic bytes here; a body that
    is not a supported image is optionally dumped for diagnosis and skipped.
    """
    if not url:
        return None

    # QQ's CDN occasionally closes the connection early; a partial JPEG then
    # decodes as garbage. Read the whole body, check it against Content-Length,
    # and retry a couple of times before giving up.
    timeout = aiohttp.ClientTimeout(total=60, sock_read=45)
    header_type = ""
    status = 0
    expected = -1
    raw = b""
    for attempt in range(1, 4):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers={"Accept": "image/*,*/*"}) as response:
                    status = response.status
                    header_type = response.headers.get("content-type", "")
                    expected = response.content_length if response.content_length is not None else -1
                    if response.status != 200:
                        raw = b""
                        break
                    raw = await response.read()
        except (aiohttp.ClientError, TimeoutError) as error:
            print(f"[image] download attempt {attempt} failed: {error}", flush=True)
            await asyncio.sleep(0.4 * attempt)
            continue
        if expected < 0 or len(raw) >= expected:
            break
        print(
            f"[image] truncated download attempt {attempt}: {len(raw)}/{expected} bytes",
            flush=True,
        )
        await asyncio.sleep(0.4 * attempt)

    if not raw:
        return None
    if len(raw) > max_bytes:
        print(f"[image] refusing {len(raw)} bytes (limit {max_bytes})", flush=True)
        return None
    sniffed = sniff_media_type(raw)
    normalized = normalize_image(raw) if raw else None
    if normalized is not None:
        media_type, data = normalized[1], normalized[0]
    elif sniffed and len(raw) <= max_bytes:
        # Pillow missing or unable to decode: the magic bytes still describe a
        # real png/jpeg/webp/gif, which DSH's sharp decoder accepts as-is.
        media_type, data = sniffed, raw
    else:
        media_type = ""

    if dump_dir and raw:
        try:
            import os as _os
            import time as _time
            _os.makedirs(dump_dir, exist_ok=True)
            tag = "ok" if media_type else "bad"
            path = _os.path.join(dump_dir, f"{tag}-{_time.strftime('%Y%m%d-%H%M%S')}.bin")
            with open(path, "wb") as handle:
                handle.write(raw[: 4 * 1024 * 1024])
            log.info(
                "[image] %s: status=%s header=%r sniffed=%s raw=%d normalized=%d head=%r dump=%s",
                tag,
                status,
                header_type,
                sniffed or "unknown",
                len(raw),
                len(data) if media_type else 0,
                raw[:16],
                path,
            )
        except OSError:
            pass

    if not media_type or len(data) > max_bytes:
        return None
    return {"mediaType": media_type, "data": base64.b64encode(data).decode("ascii")}

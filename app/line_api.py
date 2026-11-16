"""Minimal LINE Messaging API client (reply is free; push counts against the monthly quota)."""
import base64
import hashlib
import hmac
import logging

import httpx

from . import config

log = logging.getLogger(__name__)
API = "https://api.line.me/v2/bot"
DATA_API = "https://api-data.line.me/v2/bot"
MAX_TEXT = 5000


def verify_signature(body: bytes, signature: str, secret: str | None = None) -> bool:
    secret = secret if secret is not None else config.LINE_CHANNEL_SECRET
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"}


def _messages(text: str) -> list[dict]:
    # LINE caps a text message at 5000 chars and a reply at 5 messages.
    chunks = [text[i : i + MAX_TEXT] for i in range(0, len(text), MAX_TEXT)] or [""]
    return [{"type": "text", "text": c} for c in chunks[:5]]


async def reply(reply_token: str, text: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{API}/message/reply",
            headers=_headers(),
            json={"replyToken": reply_token, "messages": _messages(text)},
        )
    if r.status_code != 200:
        log.warning("reply failed %s: %s", r.status_code, r.text)
    return r.status_code == 200


async def push(user_id: str, text: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{API}/message/push",
            headers=_headers(),
            json={"to": user_id, "messages": _messages(text)},
        )
    if r.status_code != 200:
        log.warning("push failed %s: %s", r.status_code, r.text)
    return r.status_code == 200


async def respond(user_id: str, reply_token: str | None, text: str) -> None:
    """Reply if the token is still valid, otherwise fall back to push."""
    if reply_token and await reply(reply_token, text):
        return
    await push(user_id, text)


async def show_loading(user_id: str, seconds: int = 60) -> None:
    """The '...' typing animation in the chat while Claude works. Free, best effort."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{API}/chat/loading/start",
                headers=_headers(),
                json={"chatId": user_id, "loadingSeconds": seconds},
            )
    except httpx.HTTPError:
        pass


async def get_content(message_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{DATA_API}/message/{message_id}/content", headers=_headers())
        r.raise_for_status()
        return r.content

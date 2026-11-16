"""FastAPI app: LINE webhook + monthly scheduler."""
import json
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from . import config, db, handlers, line_api
from .claude_cli import ClaudeError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("expense-bot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = [k for k in ("LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN") if not getattr(config, k)]
    if missing:
        raise RuntimeError(f"missing env: {', '.join(missing)}")
    os.makedirs(config.SLIP_DIR, exist_ok=True)
    db.init()
    if not config.ALLOWED_USER_IDS:
        log.warning("ALLOWED_USER_IDS is empty: setup mode, bot only replies with the sender's userId")

    scheduler = AsyncIOScheduler(timezone=config.TZ)
    scheduler.add_job(
        handlers.send_monthly_summaries,
        CronTrigger(day=config.MONTHLY_SUMMARY_DAY, hour=config.MONTHLY_SUMMARY_HOUR, timezone=config.TZ),
        id="monthly",
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not line_api.verify_signature(body, request.headers.get("x-line-signature", "")):
        raise HTTPException(status_code=400, detail="bad signature")
    # Answer LINE right away; the slow work (Claude) runs after the response.
    for event in json.loads(body).get("events", []):
        background.add_task(process_event, event)
    return {"ok": True}


async def process_event(event: dict) -> None:
    source = event.get("source", {})
    user_id = source.get("userId")
    reply_token = event.get("replyToken")
    if source.get("type") != "user" or not user_id:
        return  # ignore groups/rooms

    if not config.ALLOWED_USER_IDS:
        if reply_token:
            await line_api.reply(
                reply_token,
                f"โหมดตั้งค่า: userId ของคุณคือ\n{user_id}\n\nใส่ค่านี้ใน ALLOWED_USER_IDS ในไฟล์ .env แล้วรีสตาร์ทบอท",
            )
        return
    if user_id not in config.ALLOWED_USER_IDS:
        log.info("ignored message from unknown user %s", user_id)
        return

    etype = event.get("type")
    msg = event.get("message", {})
    try:
        if etype == "follow":
            await line_api.reply(reply_token, handlers.HELP)
        elif etype == "message" and msg.get("type") == "text":
            await handlers.handle_text(user_id, reply_token, msg["text"])
        elif etype == "message" and msg.get("type") == "image":
            await handlers.handle_image(user_id, reply_token, msg["id"])
        elif etype == "message":
            await line_api.respond(user_id, reply_token, "รับได้แค่ข้อความกับรูปสลิปครับ พิมพ์ \"วิธีใช้\" เพื่อดูคำสั่ง")
    except ClaudeError as e:
        log.warning("claude error: %s", e)
        await line_api.respond(user_id, reply_token, f"ขอโทษครับ เรียก Claude ไม่สำเร็จ\n{e}")
    except Exception:
        log.exception("failed to handle event")
        await line_api.respond(user_id, reply_token, "ขอโทษครับ เกิดข้อผิดพลาด ลองใหม่อีกครั้ง")

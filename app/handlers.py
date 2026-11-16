"""What the bot does with each LINE message."""
import logging
import os
import re
from datetime import datetime, timedelta

from . import claude_cli, config, db, line_api, prompts, summary
from .claude_cli import ClaudeError
from .summary import money

log = logging.getLogger(__name__)

HELP = f"""วิธีใช้บอทบันทึกรายจ่าย

📸 ส่งรูปสลิป → อ่านยอดและบันทึกให้
✏️ พิมพ์ "ข้าวมันไก่ 50" หรือ "เมื่อวาน grab 120 กาแฟ 65"
❓ ถามได้เลย เช่น "เดือนนี้กินกาแฟไปเท่าไหร่"

คำสั่ง
• สรุป / สรุปเดือนที่แล้ว
• วิเคราะห์ → ให้ Claude วิเคราะห์เดือนนี้
• ล่าสุด → 10 รายการล่าสุด
• ลบ → ลบรายการล่าสุด, ลบ 12 → ลบรายการ #12
• แก้ 12 อาหาร → เปลี่ยนหมวดรายการ #12
• หมวด → ดูรายชื่อหมวด

ทุกวันที่ {config.MONTHLY_SUMMARY_DAY} ของเดือน บอทจะส่งสรุปเดือนที่แล้วมาให้อัตโนมัติ"""


# ---------- helpers ----------

def _parse_dt(value: str | None, *, date_only: bool = False) -> datetime:
    """Parse Claude's date; fall back to now if missing or implausible."""
    now = summary.now()
    if not value:
        return now
    try:
        dt = datetime.fromisoformat(str(value).strip()[:16])
    except ValueError:
        return now
    if date_only:
        dt = now if dt.date() == now.date() else dt.replace(hour=12, minute=0)
    if dt > now + timedelta(days=1) or dt < now - timedelta(days=400):
        return now
    return dt


def _valid_amount(x) -> float | None:
    try:
        v = float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 10_000_000 else None


def _today_month_totals(user_id: str) -> str:
    now = summary.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t = sum(r["amount"] for r in db.between(user_id, today, today + timedelta(days=1)))
    m = sum(r["amount"] for r in db.between(user_id, summary.month_start(now), summary.month_start(now, 1)))
    return f"วันนี้รวม {money(t)} ฿ · เดือนนี้รวม {money(m)} ฿"


def _fmt_row(r) -> str:
    when = r["spent_at"][5:16].replace("T", " ")  # MM-DD HH:MM
    return f"#{r['id']} {when} {r['description']} {money(r['amount'])} ฿ ({r['category']})"


# ---------- images (slips) ----------

async def handle_image(user_id: str, reply_token: str, message_id: str) -> None:
    await line_api.show_loading(user_id)
    os.makedirs(config.SLIP_DIR, exist_ok=True)
    path = os.path.join(config.SLIP_DIR, f"{message_id}.jpg")
    with open(path, "wb") as f:
        f.write(await line_api.get_content(message_id))

    try:
        raw = await claude_cli.ask(
            prompts.slip(path),
            model=config.CLAUDE_MODEL_FAST,
            allowed_tools=["Read"],
            cwd=config.SLIP_DIR,
        )
        data = claude_cli.extract_json(raw)
    finally:
        if not config.KEEP_SLIPS:
            os.remove(path)

    amount = _valid_amount(data.get("amount"))
    if not data.get("is_slip") or amount is None:
        await line_api.respond(user_id, reply_token, "อ่านรูปนี้เป็นสลิปไม่ได้ ลองพิมพ์เองแทน เช่น \"ข้าว 50\"")
        return
    if data.get("direction") == "in":
        await line_api.respond(
            user_id, reply_token, f"สลิปนี้เป็นเงินเข้า {money(amount)} ฿ เลยไม่ได้บันทึกเป็นรายจ่าย"
        )
        return

    description = data.get("description") or data.get("receiver") or "จ่ายตามสลิป"
    try:
        new_id = db.add_expense(
            user_id,
            amount,
            description,
            data.get("category") or "อื่นๆ",
            _parse_dt(data.get("datetime")),
            source="slip",
            merchant=data.get("receiver"),
            slip_ref=(str(data["ref"]).strip() or None) if data.get("ref") else None,
            raw=raw,
        )
    except db.DuplicateSlip as e:
        await line_api.respond(user_id, reply_token, f"สลิปนี้บันทึกไปแล้วครับ\n{_fmt_row(e.existing)}")
        return

    row = db.get_many(user_id, [new_id])[0]
    await line_api.respond(
        user_id, reply_token, f"✅ บันทึกจากสลิปแล้ว\n{_fmt_row(row)}\n{_today_month_totals(user_id)}"
    )


# ---------- text ----------

async def handle_text(user_id: str, reply_token: str, text: str) -> None:
    t = text.strip()
    cmd = t.lower()
    respond = lambda msg: line_api.respond(user_id, reply_token, msg)  # noqa: E731

    if cmd in ("help", "/help", "วิธีใช้", "ช่วย", "?"):
        return await respond(HELP)
    if cmd in ("สรุป", "/summary", "สรุปเดือนนี้"):
        return await respond(summary.month_report(user_id, 0)[0])
    if cmd in ("สรุปเดือนที่แล้ว", "สรุปเดือนก่อน", "/lastmonth"):
        return await respond(summary.month_report(user_id, -1)[0])
    if cmd in ("ล่าสุด", "รายการ", "/list"):
        rows = db.recent(user_id)
        return await respond("\n".join(map(_fmt_row, rows)) if rows else "ยังไม่มีรายการ")
    if cmd in ("หมวด", "/categories"):
        return await respond("หมวดที่มี:\n" + "\n".join(f"• {c}" for c in config.CATEGORIES))
    if cmd in ("ลบ", "ลบล่าสุด", "/undo", "undo"):
        row = db.delete_last(user_id)
        return await respond(f"🗑 ลบแล้ว\n{_fmt_row(row)}" if row else "ไม่มีรายการให้ลบ")
    if m := re.fullmatch(r"(?:ลบ|/del)\s*#?(\d+)", t):
        row = db.delete(user_id, int(m.group(1)))
        return await respond(f"🗑 ลบแล้ว\n{_fmt_row(row)}" if row else f"ไม่พบรายการ #{m.group(1)}")
    if m := re.fullmatch(r"(?:แก้|/cat)\s*#?(\d+)\s+(.+)", t):
        cat = m.group(2).strip()
        if cat not in config.CATEGORIES:
            return await respond(f"ไม่มีหมวด \"{cat}\"\nพิมพ์ \"หมวด\" เพื่อดูรายชื่อ")
        ok = db.set_category(user_id, int(m.group(1)), cat)
        return await respond(f"✏️ เปลี่ยน #{m.group(1)} เป็น {cat} แล้ว" if ok else f"ไม่พบรายการ #{m.group(1)}")
    if cmd in ("วิเคราะห์", "/analyze"):
        await line_api.show_loading(user_id)
        return await respond(await monthly_text(user_id, 0))

    await line_api.show_loading(user_id)
    # Has a number → probably an expense entry. Claude returns no items if it's really a question.
    if re.search(r"\d", t) and await _try_record(user_id, reply_token, t):
        return
    await _answer_question(user_id, reply_token, t)


async def _try_record(user_id: str, reply_token: str, text: str) -> bool:
    raw = await claude_cli.ask(
        prompts.text_expense(text, summary.now().strftime("%Y-%m-%d (%A)")),
        model=config.CLAUDE_MODEL_FAST,
        max_turns=1,
    )
    items = claude_cli.extract_json(raw).get("items") or []
    saved = []
    for it in items:
        amount = _valid_amount(it.get("amount"))
        if amount is None:
            continue
        new_id = db.add_expense(
            user_id,
            amount,
            str(it.get("description") or "ไม่ระบุ"),
            it.get("category") or "อื่นๆ",
            _parse_dt(it.get("date"), date_only=True),
            source="text",
            raw=text,
        )
        saved.append(new_id)
    if not saved:
        return False
    body = "\n".join(_fmt_row(r) for r in db.get_many(user_id, saved))
    await line_api.respond(user_id, reply_token, f"✅ บันทึกแล้ว\n{body}\n{_today_month_totals(user_id)}")
    return True


async def _answer_question(user_id: str, reply_token: str, question: str) -> None:
    now = summary.now()
    months = 3
    rows = db.between(user_id, summary.month_start(now, -(months - 1)), summary.month_start(now, 1))
    answer = await claude_cli.ask(
        prompts.qa(question, summary.to_csv(rows, with_id=True), now.strftime("%Y-%m-%d"), months),
        model=config.CLAUDE_MODEL_SMART,
        max_turns=1,
    )
    await line_api.respond(user_id, reply_token, answer.strip() or "ขอโทษครับ ตอบไม่ได้")


# ---------- monthly ----------

async def monthly_text(user_id: str, offset: int) -> str:
    text, rows, cur, prev = summary.month_report(user_id, offset)
    if not rows:
        return text
    try:
        start = summary.month_start(summary.now(), offset)
        insight = await claude_cli.ask(
            prompts.monthly(summary.month_name(start), summary.totals_for_prompt(cur, prev), summary.to_csv(rows)),
            model=config.CLAUDE_MODEL_SMART,
            max_turns=1,
        )
        return f"{text}\n\n💡 {insight.strip()}"
    except ClaudeError as e:
        log.warning("monthly insight failed: %s", e)
        return text


async def send_monthly_summaries() -> None:
    for uid in config.ALLOWED_USER_IDS:
        try:
            await line_api.push(uid, await monthly_text(uid, -1))
        except Exception:
            log.exception("monthly summary failed for %s", uid)

"""Month maths and plain-text summaries (no Claude needed)."""
import csv
import io
from collections import defaultdict
from datetime import datetime

from . import config, db

THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def now() -> datetime:
    return datetime.now(config.TZ).replace(tzinfo=None)


def month_start(d: datetime, offset: int = 0) -> datetime:
    """First day of d's month, shifted by `offset` months."""
    idx = d.year * 12 + (d.month - 1) + offset
    return datetime(idx // 12, idx % 12 + 1, 1)


def month_name(start: datetime) -> str:
    return f"{THAI_MONTHS[start.month - 1]} {start.year + 543}"


def money(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".") if x % 1 else f"{x:,.0f}"


def totals(rows) -> dict[str, float]:
    t: dict[str, float] = defaultdict(float)
    for r in rows:
        t[r["category"]] += r["amount"]
    return dict(sorted(t.items(), key=lambda kv: -kv[1]))


def to_csv(rows, with_id: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        cols = [r["spent_at"].replace("T", " "), r["amount"], r["category"], r["description"]]
        w.writerow([r["id"], *cols] if with_id else cols)
    return buf.getvalue().strip()


def month_report(user_id: str, offset: int = 0) -> tuple[str, list, dict, dict]:
    """Text report for a month (offset 0 = this month, -1 = last month).

    Returns (text, rows, totals, previous-month totals)."""
    start = month_start(now(), offset)
    end = month_start(start, 1)
    rows = db.between(user_id, start, end)
    cur = totals(rows)
    prev = totals(db.between(user_id, month_start(start, -1), start))

    title = f"สรุปรายจ่าย {month_name(start)}"
    if not rows:
        return f"{title}\nยังไม่มีรายการ", rows, cur, prev

    lines = [title, ""]
    for cat, amt in cur.items():
        diff = ""
        if cat in prev and prev[cat] > 0:
            pct = (amt - prev[cat]) / prev[cat] * 100
            diff = f"  ({'+' if pct >= 0 else ''}{pct:.0f}%)"
        lines.append(f"• {cat}: {money(amt)} ฿{diff}")
    total, prev_total = sum(cur.values()), sum(prev.values())
    lines.append("")
    lines.append(f"รวม {money(total)} ฿ จาก {len(rows)} รายการ")
    if prev_total:
        lines.append(f"เดือนก่อน {money(prev_total)} ฿")
    if offset == 0:
        days = (now() - start).days + 1
        lines.append(f"เฉลี่ยวันละ {money(total / days)} ฿")
    return "\n".join(lines), rows, cur, prev


def totals_for_prompt(cur: dict, prev: dict) -> str:
    cats = list(cur) + [c for c in prev if c not in cur]
    return "\n".join(
        f"{c}: {money(cur.get(c, 0))} (เดือนก่อน {money(prev.get(c, 0))})" for c in cats
    )

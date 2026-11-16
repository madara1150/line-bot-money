import base64
import hashlib
import hmac
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import claude_cli, config, db, handlers, line_api, main, summary


# ---------- fakes ----------

class FakeLine:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def reply(self, token, text):
        self.sent.append(("reply", text))
        return True

    async def push(self, user_id, text):
        self.sent.append(("push", text))
        return True

    async def show_loading(self, user_id, seconds=60):
        pass

    async def get_content(self, message_id):
        return b"\xff\xd8fakejpeg"

    @property
    def last(self) -> str:
        return self.sent[-1][1]


class FakeClaude:
    """Returns canned replies in order and records the prompts it got."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    import os
    if os.path.exists(config.DB_PATH):
        os.remove(config.DB_PATH)
    os.makedirs(config.SLIP_DIR, exist_ok=True)
    db.init()
    fake = FakeLine()
    for name in ("reply", "push", "show_loading", "get_content"):
        monkeypatch.setattr(line_api, name, getattr(fake, name))
    return fake


def use_claude(monkeypatch, *replies) -> FakeClaude:
    fake = FakeClaude(*replies)
    monkeypatch.setattr(claude_cli, "ask", fake)
    return fake


def sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(b"test-secret", body, hashlib.sha256).digest()).decode()


def text_event(text, user="Uowner"):
    return {"type": "message", "replyToken": "rt", "source": {"type": "user", "userId": user},
            "message": {"type": "text", "id": "1", "text": text}}


def post(client, *events):
    body = json.dumps({"events": list(events)}).encode()
    return client.post("/webhook", content=body, headers={"x-line-signature": sign(body)})


# ---------- unit ----------

def test_signature():
    body = b'{"events":[]}'
    assert line_api.verify_signature(body, sign(body))
    assert not line_api.verify_signature(body, "nope")


def test_extract_json_variants():
    assert claude_cli.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert claude_cli.extract_json('นี่คือผล {"a": {"b": 2}} จบ') == {"a": {"b": 2}}
    with pytest.raises(claude_cli.ClaudeError):
        claude_cli.extract_json("ไม่มี json")


def test_month_start_wraps_year():
    d = datetime(2026, 1, 15)
    assert summary.month_start(d, -1) == datetime(2025, 12, 1)
    assert summary.month_start(d, 12) == datetime(2027, 1, 1)
    assert summary.month_name(datetime(2026, 11, 1)) == "พฤศจิกายน 2569"


def test_money():
    assert summary.money(1500) == "1,500"
    assert summary.money(65.5) == "65.5"


def test_unknown_category_becomes_other():
    i = db.add_expense("Uowner", 10, "x", "หมวดมั่ว", summary.now(), "text")
    assert db.get_many("Uowner", [i])[0]["category"] == "อื่นๆ"


# ---------- webhook flows ----------

def test_bad_signature_rejected():
    with TestClient(main.app) as c:
        r = c.post("/webhook", content=b"{}", headers={"x-line-signature": "x"})
    assert r.status_code == 400


def test_text_expense_recorded(monkeypatch, fresh):
    today = summary.now().strftime("%Y-%m-%d")
    use_claude(monkeypatch, json.dumps({"items": [
        {"amount": 50, "description": "ข้าวมันไก่", "category": "อาหาร", "date": today},
        {"amount": "65", "description": "กาแฟ", "category": "เครื่องดื่ม/กาแฟ", "date": None},
    ]}))
    with TestClient(main.app) as c:
        post(c, text_event("ข้าวมันไก่ 50 กาแฟ 65"))
    assert "บันทึกแล้ว" in fresh.last
    assert "วันนี้รวม 115 ฿" in fresh.last
    assert len(db.recent("Uowner")) == 2


def test_number_question_falls_through_to_qa(monkeypatch, fresh):
    claude = use_claude(monkeypatch, '{"items": []}', "เดือนนี้ใช้ไป 0 บาทครับ")
    with TestClient(main.app) as c:
        post(c, text_event("เดือน 11 ใช้ไปเท่าไหร่"))
    assert fresh.last == "เดือนนี้ใช้ไป 0 บาทครับ"
    assert "<question>" in claude.prompts[1]


def test_slip_recorded_and_duplicate_blocked(monkeypatch, fresh):
    slip = json.dumps({"is_slip": True, "amount": "1,250.00", "receiver": "ร้านสมใจ",
                       "description": "ค่าอาหาร ร้านสมใจ", "category": "อาหาร",
                       "datetime": summary.now().strftime("%Y-%m-%dT%H:%M"),
                       "ref": "ABC123", "direction": "out"})
    claude = use_claude(monkeypatch, slip, slip)
    ev = {"type": "message", "replyToken": "rt", "source": {"type": "user", "userId": "Uowner"},
          "message": {"type": "image", "id": "m42"}}
    with TestClient(main.app) as c:
        post(c, ev)
        assert "บันทึกจากสลิปแล้ว" in fresh.last and "1,250" in fresh.last
        post(c, ev)
        assert "บันทึกไปแล้ว" in fresh.last
    assert len(db.recent("Uowner")) == 1
    assert "m42.jpg" in claude.prompts[0]


def test_incoming_slip_not_recorded(monkeypatch, fresh):
    use_claude(monkeypatch, '{"is_slip": true, "amount": 500, "direction": "in"}')
    ev = {"type": "message", "replyToken": "rt", "source": {"type": "user", "userId": "Uowner"},
          "message": {"type": "image", "id": "m1"}}
    with TestClient(main.app) as c:
        post(c, ev)
    assert "เงินเข้า" in fresh.last
    assert db.recent("Uowner") == []


def test_commands(monkeypatch, fresh):
    a = db.add_expense("Uowner", 100, "แท็กซี่", "เดินทาง", summary.now(), "text")
    db.add_expense("Uowner", 40, "น้ำ", "เครื่องดื่ม/กาแฟ", summary.now(), "text")
    with TestClient(main.app) as c:
        post(c, text_event("สรุป"))
        assert "เดินทาง: 100 ฿" in fresh.last and "รวม 140 ฿" in fresh.last
        post(c, text_event(f"แก้ {a} อาหาร"))
        assert db.get_many("Uowner", [a])[0]["category"] == "อาหาร"
        post(c, text_event("ลบ"))
        assert "น้ำ" in fresh.last
        post(c, text_event(f"ลบ {a}"))
        assert db.recent("Uowner") == []


def test_stranger_ignored(monkeypatch, fresh):
    use_claude(monkeypatch)  # any call would fail: no replies queued
    with TestClient(main.app) as c:
        post(c, text_event("ข้าว 50", user="Ustranger"))
    assert fresh.sent == []


def test_setup_mode_replies_user_id(monkeypatch, fresh):
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", [])
    with TestClient(main.app) as c:
        post(c, text_event("hi", user="Unew"))
    assert "Unew" in fresh.last


def test_claude_error_reported(monkeypatch, fresh):
    async def boom(*a, **k):
        raise claude_cli.ClaudeError("token หมดอายุ")
    monkeypatch.setattr(claude_cli, "ask", boom)
    with TestClient(main.app) as c:
        post(c, text_event("ข้าว 50"))
    assert "token หมดอายุ" in fresh.last


def test_monthly_push(monkeypatch, fresh):
    last_month = summary.month_start(summary.now(), -1).replace(day=5, hour=12)
    db.add_expense("Uowner", 300, "ข้าว", "อาหาร", last_month, "text")
    use_claude(monkeypatch, "ค่าอาหารเยอะ ลองทำกับข้าวเอง")
    import asyncio
    asyncio.run(handlers.send_monthly_summaries())
    kind, text = fresh.sent[-1]
    assert kind == "push" and "อาหาร: 300 ฿" in text and "💡 ค่าอาหารเยอะ" in text

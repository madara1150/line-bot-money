# Expense Bot — บอท LINE บันทึกรายจ่าย

ส่งสลิปหรือพิมพ์รายจ่ายใน LINE → บอทบันทึกลง SQLite บนเซิร์ฟเวอร์ของคุณ
Claude Code (บนเซิร์ฟเวอร์) ช่วยอ่านสลิป จัดหมวด ตอบคำถาม และสรุปรายเดือน

```
LINE ──webhook──► Cloudflare Tunnel ──► bot (FastAPI) ──► SQLite
                                           └──► claude -p (อ่านสลิป / วิเคราะห์)
```

## ใช้งาน

| ส่งอะไร | บอททำอะไร |
|---|---|
| รูปสลิป | อ่านยอด ผู้รับ วันเวลา เลขอ้างอิง แล้วบันทึก (สลิปซ้ำจะไม่บันทึกซ้ำ) |
| `ข้าวมันไก่ 50` / `เมื่อวาน grab 120 กาแฟ 65` | บันทึก 1 รายการหรือหลายรายการ พร้อมเดาหมวด |
| `เดือนนี้กินกาแฟไปเท่าไหร่` | Claude ตอบจากข้อมูล 3 เดือนล่าสุด |
| `สรุป` / `สรุปเดือนที่แล้ว` | ยอดรวมตามหมวด เทียบกับเดือนก่อน |
| `วิเคราะห์` | สรุปเดือนนี้ + ข้อสังเกตและคำแนะนำจาก Claude |
| `ล่าสุด` | 10 รายการล่าสุด |
| `ลบ` / `ลบ 12` | ลบรายการล่าสุด / ลบรายการ #12 |
| `แก้ 12 อาหาร` | เปลี่ยนหมวดของรายการ #12 |
| `หมวด`, `วิธีใช้` | ดูรายชื่อหมวด / ดูคำสั่งทั้งหมด |

ทุกวันที่ 1 เวลา 09:00 บอทจะส่งสรุปเดือนที่แล้วพร้อมคำแนะนำมาให้เอง (ใช้ push 1 ข้อความต่อเดือน
ส่วนการตอบกลับปกติเป็น reply ซึ่งฟรีและไม่นับโควตา)

## ติดตั้ง

### 1. สร้าง LINE bot

**ใน LINE Official Account Manager** (<https://manager.line.biz>, เมนูภาษาไทย)

1. เลือกบัญชี LINE OA ที่จะใช้ หรือกด **สร้างบัญชีใหม่**
2. กด **ตั้งค่า** (มุมขวาบน) → เมนูซ้าย **Messaging API** → กด **เปิดใช้ Messaging API**
   → เลือกหรือสร้าง Provider → ตกลง
3. หน้าเดียวกันจะแสดง **Channel secret** ให้คัดลอกไว้
4. เมนูซ้าย **การตอบกลับ** แล้วตั้งค่าดังนี้
   - **ข้อความทักทาย**: ปิด (บอทส่งวิธีใช้ให้เองตอนเพิ่มเพื่อน)
   - **ข้อความตอบกลับอัตโนมัติ**: ปิด (ไม่อย่างนั้น LINE จะตอบซ้อนกับบอท)
   - **Webhook**: เปิด
   - **แชท**: แนะนำให้ปิด เพราะบอทตอบเองทั้งหมด

ชื่อเมนูอาจต่างกันเล็กน้อยตามเวอร์ชันของ LINE ให้มองหาหัวข้อที่ความหมายใกล้เคียงกัน

**ใน LINE Developers Console** (<https://developers.line.biz/console/>, ใช้บัญชี LINE เดียวกัน
หน้านี้ส่วนใหญ่เป็นภาษาอังกฤษ)

5. เลือก Provider จากข้อ 2 → เลือก channel ที่ชื่อเดียวกับบัญชี LINE OA
6. แท็บ **Messaging API** → เลื่อนลงล่างสุดถึง **Channel access token (long-lived)** → กด **Issue** แล้วคัดลอกไว้
7. สแกน QR code ในแท็บเดียวกัน เพื่อเพิ่มบอทเป็นเพื่อน

### 2. สร้าง token ของ Claude Code บนเซิร์ฟเวอร์

```bash
claude setup-token
```

ระบบจะให้ token อายุยาวสำหรับใช้แบบ headless (ใช้โควตาจากบัญชี Claude ของคุณ) คัดลอกไว้ใส่ใน `.env`

### 3. ตั้งค่าและรัน

```bash
cp .env.example .env
nano .env    # ใส่ LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, CLAUDE_CODE_OAUTH_TOKEN
```

**แบบ A: ให้ compose เปิด Cloudflare Tunnel ให้**
1. Cloudflare dashboard → Zero Trust → Networks → Tunnels → Create tunnel (cloudflared)
2. คัดลอก token มาใส่ `CLOUDFLARE_TUNNEL_TOKEN`
3. เพิ่ม Public hostname เช่น `expense.yourdomain.com` → Service `http://bot:8000`

```bash
docker compose --profile tunnel up -d --build
```

**แบบ B: เซิร์ฟเวอร์มี cloudflared หรือ reverse proxy อยู่แล้ว**
ให้ชี้ hostname ไปที่ `http://localhost:8000` (ถ้าพอร์ต 8000 ถูกใช้แล้ว ให้ตั้ง `BOT_PORT` ใน `.env` เป็นพอร์ตอื่น
แล้วชี้ไปที่พอร์ตนั้นแทน)

```bash
docker compose up -d --build
```

### 4. ตั้ง webhook

ใส่ URL `https://expense.yourdomain.com/webhook` ได้ 2 ที่ เลือกที่ใดที่หนึ่ง:

- **LINE OA Manager:** ตั้งค่า → Messaging API → **Webhook URL** → บันทึก
- **LINE Developers Console:** แท็บ Messaging API → Webhook settings → กด **Verify** (ต้องขึ้น Success)
  แล้วเปิด **Use webhook**

แนะนำให้กด Verify ใน Developers Console อย่างน้อยหนึ่งครั้ง เพื่อเช็กว่า tunnel กับบอทเชื่อมกันแล้ว

### 5. ล็อกให้ใช้ได้เฉพาะคุณ

ตอนที่ `ALLOWED_USER_IDS` ยังว่าง บอทจะอยู่ในโหมดตั้งค่า ส่งข้อความอะไรก็ได้ไปหาบอท
บอทจะตอบกลับด้วย userId ของคุณ (ขึ้นต้นด้วย `U...`) ให้ใส่ค่านั้นใน `.env` แล้วรีสตาร์ท:

```bash
docker compose up -d
```

หลังจากนี้ข้อความจากคนอื่นจะถูกเพิกเฉยทั้งหมด จึงไม่มีใครมาใช้โควตา Claude ของคุณได้

## ดูแลระบบ

```bash
docker compose logs -f bot                                   # ดู log
docker compose exec bot claude -p "ตอบว่า ok" --model haiku  # ทดสอบว่า Claude ใช้ได้
docker compose cp bot:/data/expenses.db ./backup.db          # สำรองข้อมูล
```

ไฟล์ข้อมูลอยู่ใน Docker volume `bot-data` (`expenses.db` และรูปสลิปใน `slips/`)
ถ้าไม่อยากเก็บรูปสลิป ให้ตั้ง `KEEP_SLIPS=false`

เปลี่ยนโมเดลได้ที่ `CLAUDE_MODEL_FAST` (อ่านสลิปและจัดหมวด ค่าเริ่มต้น `haiku`)
และ `CLAUDE_MODEL_SMART` (ตอบคำถามและวิเคราะห์ ค่าเริ่มต้น `sonnet`)

## ทดสอบในเครื่อง

```bash
pip install -r requirements.txt pytest
python -m pytest tests
```

ชุดทดสอบใช้ `claude` ปลอมและ LINE API ปลอม จึงไม่เรียกบริการจริง

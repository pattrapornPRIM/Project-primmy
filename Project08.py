import base64
import hashlib
import io
import math
import os
import pathlib
import re
import secrets
import smtplib          
import sqlite3
import ssl              
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import datetime
from email.message import EmailMessage        
from email.utils import formataddr           
from html import escape as html_escape
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

# ฐานข้อมูลอยู่ในโฟลเดอร์เดียวกับไฟล์โปรแกรมเสมอ ไม่ว่าจะสั่งรันจากโฟลเดอร์ไหนก็ตาม
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "moo_yor_shop_gui.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
PAYMENT_METHODS = ["โอนเงินผ่านพร้อมเพย์ (สแกน QR)", "เก็บเงินปลายทาง"]

# ---------- ค่าส่งตามยอดสินค้า (ยอดสินค้านี้คือราคารวม VAT แล้ว ไม่รวมค่าส่ง) ----------
MIN_ORDER = 100            # สั่งขั้นต่ำต่อออเดอร์ (บาท)
MAX_ORDER = 20000          # สั่งได้ไม่เกินต่อออเดอร์ (บาท)
# (ยอดสินค้าสูงสุดของช่วง, ค่าส่ง)  ถ้าจะเปลี่ยนเรท แก้ตารางนี้ที่เดียว
SHIPPING_TIERS = [
    (5000, 80),            # 100 - 5,000      ค่าส่ง 80
    (10000, 160),          # 5,001 - 10,000   ค่าส่ง 160
    (20000, 200),          # 10,001 - 20,000  ค่าส่ง 200
]

def calc_shipping_fee(goods):
    """คืนค่าส่งตามยอดสินค้า; ถ้ายอดน้อยกว่าขั้นต่ำหรือเกินกำหนด คืน None"""
    if goods < MIN_ORDER or goods > MAX_ORDER:
        return None
    for limit, fee in SHIPPING_TIERS:
        if goods <= limit:
            return fee
    return None

def order_limit_error(goods):
    """ข้อความเตือนถ้ายอดสินค้าไม่อยู่ในช่วงที่สั่งได้ (ถ้าปกติคืน None)"""
    if goods < MIN_ORDER:
        return f"สั่งซื้อขั้นต่ำ {MIN_ORDER:,} บาทต่อออเดอร์ (ตอนนี้ {goods:,.2f} บาท)"
    if goods > MAX_ORDER:
        return f"สั่งซื้อได้ไม่เกิน {MAX_ORDER:,} บาทต่อออเดอร์ (ตอนนี้ {goods:,.2f} บาท) กรุณาลดจำนวนสินค้า"
    return None

VAT_RATE = 0.07            # ภาษีมูลค่าเพิ่ม 7% ราคาสินค้าที่ตั้งไว้ "รวม VAT แล้ว"

def calc_vat(goods):
    """ส่วนที่เป็น VAT ซึ่งรวมอยู่ในราคาสินค้า (goods = ราคาสินค้ารวม VAT แล้ว)"""
    return round(goods * VAT_RATE / (1 + VAT_RATE), 2)
PROVINCES = [
    "กระบี่", "กรุงเทพมหานคร", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร", "ขอนแก่น", "จันทบุรี",
    "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชัยภูมิ", "ชุมพร", "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด",
    "ตาก", "นครนายก", "นครปฐม", "นครพนม", "นครราชสีมา", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี",
    "นราธิวาส", "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี", "ปัตตานี",
    "พระนครศรีอยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร", "พิษณุโลก", "เพชรบุรี", "เพชรบูรณ์",
    "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร", "แม่ฮ่องสอน", "ยโสธร", "ยะลา", "ร้อยเอ็ด", "ระนอง",
    "ระยอง", "ราชบุรี", "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา", "สตูล",
    "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี", "สิงห์บุรี", "สุโขทัย",
    "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์", "หนองคาย", "หนองบัวลำภู", "อ่างทอง", "อำนาจเจริญ",
    "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี", "อุบลราชธานี",
]
THUMB = (56, 56)

# ----- ธีมสี (โทนอุ่น ส้ม-ครีม) -----
BG = "#FFF8F0"
CARD = "#FFFFFF"
PRIMARY = "#C2410C"
PRIMARY_DARK = "#9A3412"
TEXT = "#292524"
MUTED = "#78716C"
BORDER = "#E7DDD3"
SUCCESS = "#15803D"
WARN = "#B45309"
DANGER = "#B91C1C"
IMG_BG = "#F5EFE8"
FONT_FAMILY = "Helvetica"      
CARD_W = 224                   
CARD_IMG = (200, 150)          
DETAIL_IMG = (340, 340)        

# =====================================================================
#  ฐานข้อมูล
# =====================================================================
def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def backup_db(manual=False, keep_days=14):
    
    if not os.path.exists(DB_NAME) or os.path.getsize(DB_NAME) == 0:
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    now = datetime.now()
    if manual:
        name = now.strftime("manual_%Y%m%d_%H%M%S.db")
    else:
        name = now.strftime("auto_%Y%m%d.db")
        if os.path.exists(os.path.join(BACKUP_DIR, name)):
            return None                      
    dest = os.path.join(BACKUP_DIR, name)
    src = sqlite3.connect(DB_NAME)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)                  
        finally:
            dst.close()
    finally:
        src.close()
    if not manual:
        autos = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("auto_") and f.endswith(".db"))
        for old in autos[:-keep_days]:
            os.remove(os.path.join(BACKUP_DIR, old))
    return dest

def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return digest.hex(), salt.hex()

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            phone         TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'customer'
        );
        CREATE TABLE IF NOT EXISTS products (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL UNIQUE,
            price REAL NOT NULL CHECK (price >= 0),
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            image BLOB,
            active INTEGER NOT NULL DEFAULT 1,
            description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value
        );
        CREATE TABLE IF NOT EXISTS orders (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at     TEXT NOT NULL,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            total          REAL NOT NULL,
            payment_method TEXT NOT NULL,
            address        TEXT NOT NULL,
            status         TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   INTEGER NOT NULL REFERENCES orders(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            qty        INTEGER NOT NULL,
            unit_price REAL NOT NULL
        );
        """)

        cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)")]
        if "image" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN image BLOB")
        if "active" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "description" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN description TEXT NOT NULL DEFAULT ''")

        ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)")]
        for col, ddl in (("gender", "TEXT"), ("birthdate", "TEXT"),
                         ("email", "TEXT"), ("avatar", "BLOB")):
            if col not in ucols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

        # ค่าส่ง / ที่อยู่แยกช่อง / สลิปโอนเงิน (ออเดอร์เก่าจะได้ค่าส่ง 0 และไม่มีสลิป)
        ocols = [r["name"] for r in conn.execute("PRAGMA table_info(orders)")]
        for col, ddl in (("shipping_fee", "REAL NOT NULL DEFAULT 0"),
                         ("addr_no", "TEXT"), ("addr_road", "TEXT"),
                         ("addr_subdistrict", "TEXT"), ("addr_district", "TEXT"),
                         ("addr_province", "TEXT"), ("addr_postcode", "TEXT"),
                         ("slip", "BLOB")):
            if col not in ocols:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {ddl}")
               
        conn.execute("UPDATE orders SET payment_method = ? WHERE payment_method = ?",
                     ("เก็บเงินปลายทาง", "เก็บเงินปลายทาง (COD)"))

        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            conn.executemany("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
                             [("หมูยอเส้นเล็ก", 60, 50),
                              ("หมูยอเส้นใหญ่", 120, 30),
                              ("หมูยอพริกไทยดำ", 70, 20)])

        if not conn.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone():
            h, s = hash_password("admin1234")
            conn.execute("INSERT INTO users (username, password_hash, salt, full_name, phone, role) "
                         "VALUES ('admin', ?, ?, 'เจ้าของร้าน', '0000000000', 'admin')", (h, s))

def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(key, value):
    with get_conn() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

def authenticate(username, password):
    with get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not u:
        return None
    h, _ = hash_password(password, u["salt"])
    return u if secrets.compare_digest(h, u["password_hash"]) else None

def register_user(username, password, full_name, phone):
    h, s = hash_password(password)
    with get_conn() as conn:
        conn.execute("INSERT INTO users (username, password_hash, salt, full_name, phone) "
                     "VALUES (?, ?, ?, ?, ?)", (username, h, s, full_name, phone))

def reset_password(username, phone, new_password):
    """เปลี่ยนรหัสผ่านเมื่อ username และเบอร์โทรตรงกัน คืน True/False"""
    with get_conn() as conn:
        u = conn.execute("SELECT id FROM users WHERE username = ? AND phone = ?",
                         (username, phone)).fetchone()
        if not u:
            return False
        h, s = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (h, s, u["id"]))
    return True

def get_user(user_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

def update_profile(user_id, full_name, phone, gender, birthdate, email, avatar):
    with get_conn() as conn:
        conn.execute("UPDATE users SET full_name = ?, phone = ?, gender = ?, "
                     "birthdate = ?, email = ?, avatar = ? WHERE id = ?",
                     (full_name, phone, gender, birthdate, email or None, avatar, user_id))

def _junk(text):
    """ข้อความที่พิมพ์ตัวเดิมซ้ำหลายครั้ง เช่น 'กกกกก' ถือว่ากรอกมั่ว"""
    return re.search(r"(.)\1{3,}", text) is not None

def _thai_letters(text):
    return sum(1 for c in text if "ก" <= c <= "ฮ")

def validate_address(no, road, subdistrict, district, province, postcode):
    """ตรวจที่อยู่ที่กรอกเป็นช่อง คืน (dict ที่อยู่ที่จัดรูปแล้ว, None) หรือ (None, ข้อความผิดพลาด)"""
    no, road, subdistrict, district, province, postcode = (
        " ".join(str(x).split()) for x in (no, road, subdistrict, district, province, postcode))
    # ตัดคำนำหน้าที่ลูกค้าอาจพิมพ์ซ้ำ (ระบบเติมคำนำหน้าให้เองตอนแสดงผล)
    road = re.sub(r"^ถนน\s*", "", road)
    subdistrict = re.sub(r"^(ตำบล|แขวง|ต\.)\s*", "", subdistrict)
    district = re.sub(r"^(อำเภอ|เขต|อ\.)\s*", "", district)

    if (not re.fullmatch(r"[0-9ก-๙/\-. ]{1,30}", no) or not any(c.isdigit() for c in no)
            or _junk(no)):
        return None, "บ้านเลขที่ไม่ถูกต้อง ต้องมีตัวเลข เช่น 123 หรือ 45/6 หรือ 12 หมู่ 3"
    if road and (not re.fullmatch(r"[0-9ก-๙/\-. ]{2,60}", road)
                 or _thai_letters(road) < 2 or _junk(road)):
        return None, "ชื่อถนนไม่ถูกต้อง (ถ้าไม่มีถนน ให้เว้นว่างไว้ได้)"
    if (not re.fullmatch(r"[ก-๙. \-]{2,40}", subdistrict) or _thai_letters(subdistrict) < 2
            or _junk(subdistrict)):
        return None, "ตำบล / แขวง ต้องเป็นตัวอักษรภาษาไทยเท่านั้น"
    if (not re.fullmatch(r"[ก-๙. \-]{2,40}", district) or _thai_letters(district) < 2
            or _junk(district)):
        return None, "อำเภอ / เขต ต้องเป็นตัวอักษรภาษาไทยเท่านั้น"
    if province not in PROVINCES:
        return None, "กรุณาเลือกจังหวัดจากรายการ"
    if not re.fullmatch(r"[0-9]{5}", postcode) or not 10000 <= int(postcode) <= 96999:
        return None, "รหัสไปรษณีย์ต้องเป็นตัวเลข 5 หลัก"
    return {"no": no, "road": road, "subdistrict": subdistrict, "district": district,
            "province": province, "postcode": postcode}, None

def format_address(a):
    """รวมที่อยู่ที่แยกช่องเป็นข้อความบรรทัดเดียว (กรุงเทพฯ ใช้ แขวง/เขต ส่วนจังหวัดอื่นใช้ ตำบล/อำเภอ)"""
    bkk = a["province"] == "กรุงเทพมหานคร"
    sub_label, dist_label = ("แขวง", "เขต") if bkk else ("ตำบล", "อำเภอ")
    parts = [f"บ้านเลขที่ {a['no']}"]
    if a["road"]:
        parts.append(f"ถนน{a['road']}")
    parts += [f"{sub_label}{a['subdistrict']}", f"{dist_label}{a['district']}",
              a["province"] if bkk else f"จังหวัด{a['province']}", a["postcode"]]
    return " ".join(parts)

def clean_name(name):
    """สินค้าที่ถูกลบจะมีต่อท้าย [ลบแล้ว #n] ตัดทิ้งก่อนแสดงให้ลูกค้าเห็น"""
    return re.sub(r"\s*\[ลบแล้ว #\d+\]$", "", name or "")

def place_order(user_id, cart, method, addr, shipping_fee=None, slip=None):
    """บันทึกออเดอร์ + ตัดสต็อก ในธุรกรรมเดียว; total = ค่าสินค้า + ค่าส่ง; addr คือ dict จาก validate_address"""
    status = "รอชำระเงิน" if method == PAYMENT_METHODS[0] else "รอจัดส่ง"
    with get_conn() as conn:
        lines, goods = [], 0.0
        for pid, item in cart.items():
            row = conn.execute("SELECT price FROM products WHERE id = ?", (pid,)).fetchone()
            cur = conn.execute("UPDATE products SET stock = stock - ? "
                               "WHERE id = ? AND stock >= ? AND active = 1",
                               (item["qty"], pid, item["qty"]))
            if row is None or cur.rowcount == 0:
                raise ValueError(f"สินค้า '{item['name']}' มีสต็อกไม่พอ หรือถูกถอดออกจากร้านแล้ว")
            lines.append((pid, item["qty"], row["price"]))
            goods += item["qty"] * row["price"]
            err = order_limit_error(goods)# ตรวจซ้ำด้วยราคาจริงใน DB (ถ้าไม่ผ่านจะ rollback สต็อกให้)
            if err:
                raise ValueError(err)
            shipping_fee = calc_shipping_fee(goods)
            total = goods + shipping_fee
            cur = conn.execute(
            "INSERT INTO orders (created_at, user_id, total, payment_method, address, status, "
            "shipping_fee, addr_no, addr_road, addr_subdistrict, addr_district, addr_province, "
            "addr_postcode, slip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), user_id, total, method,
             format_address(addr), status, shipping_fee, addr["no"], addr["road"],
             addr["subdistrict"], addr["district"], addr["province"], addr["postcode"], slip))
        order_id = cur.lastrowid
        conn.executemany("INSERT INTO order_items (order_id, product_id, qty, unit_price) "
                         "VALUES (?, ?, ?, ?)", [(order_id, *ln) for ln in lines])
    return order_id, total

def get_order_detail(order_id, user_id=None):
    """ดึงออเดอร์ + รายการสินค้า (ไม่โหลดรูปสลิป); ถ้าระบุ user_id จะดูได้เฉพาะออเดอร์ของคนนั้น"""
    sql = ("SELECT o.id, o.created_at, o.total, o.payment_method, o.address, o.status, "
           "o.shipping_fee, (o.slip IS NOT NULL) AS has_slip, u.full_name, u.phone "
           "FROM orders o JOIN users u ON u.id = o.user_id WHERE o.id = ?")
    args = [order_id]
    if user_id is not None:
        sql += " AND o.user_id = ?"
        args.append(user_id)
    with get_conn() as conn:
        o = conn.execute(sql, args).fetchone()
        if o is None:
            return None, []
        items = conn.execute("SELECT p.name, oi.qty, oi.unit_price FROM order_items oi "
                             "JOIN products p ON p.id = oi.product_id "
                             "WHERE oi.order_id = ? ORDER BY oi.id", (order_id,)).fetchall()
    return o, items

def get_order_slip(order_id, user_id=None):
    sql, args = "SELECT slip FROM orders WHERE id = ?", [order_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        args.append(user_id)
    with get_conn() as conn:
        row = conn.execute(sql, args).fetchone()
    return row["slip"] if row else None

def set_order_slip(order_id, user_id, blob):
    """แนบ/เปลี่ยนสลิปได้เฉพาะออเดอร์ของตัวเองที่เลือกโอนเงินและยัง 'รอชำระเงิน' คืน True/False"""
    with get_conn() as conn:
        cur = conn.execute("UPDATE orders SET slip = ? WHERE id = ? AND user_id = ? "
                           "AND payment_method = ? AND status = 'รอชำระเงิน'",
                           (blob, order_id, user_id, PAYMENT_METHODS[0]))
    return cur.rowcount > 0

def receipt_html(o, items):
    """สร้างไฟล์ใบเสร็จ (HTML) ให้ลูกค้าบันทึก/พิมพ์/ Save as PDF จากเบราว์เซอร์"""
    e = html_escape
    goods = sum(i["qty"] * i["unit_price"] for i in items)
    rows = "".join(
        f"<tr><td>{e(clean_name(i['name']))}</td><td class='r'>{i['unit_price']:,.2f}</td>"
        f"<td class='r'>{i['qty']}</td><td class='r'>{i['qty'] * i['unit_price']:,.2f}</td></tr>"
        for i in items)
    return f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="utf-8"><title>ใบเสร็จ ออเดอร์ #{o['id']}</title>
<style>
body{{font-family:'Noto Sans Thai',Tahoma,sans-serif;color:#292524;max-width:640px;margin:24px auto;padding:0 16px}}
h1{{color:#9A3412;margin:0 0 2px}} .m{{color:#78716C;font-size:14px}}
table{{border-collapse:collapse;width:100%;margin:14px 0}}
th,td{{border-bottom:1px solid #E7DDD3;padding:7px 6px;text-align:left}} .r{{text-align:right}}
th{{background:#FFF3C4}} .tot td{{border:0;font-weight:bold}} .grand td{{font-size:18px;color:#9A3412}}
@media print{{body{{margin:0}}}}
</style></head><body>
<h1>ใบเสร็จคำสั่งซื้อ</h1>
<div class="m">ร้านหมูยออุบล (UBON MOOYOR SHOP)</div>
<p><b>เลขที่ออเดอร์:</b> #{o['id']}<br>
<b>วันเวลา:</b> {e(o['created_at'].replace('T', ' '))}<br>
<b>ผู้สั่งซื้อ:</b> {e(o['full_name'])} โทร {e(o['phone'])}<br>
<b>ที่อยู่จัดส่ง:</b> {e(o['address'])}<br>
<b>วิธีชำระเงิน:</b> {e(o['payment_method'])}<br>
<b>สถานะ:</b> {e(o['status'])}</p>
<table><tr><th>สินค้า</th><th class="r">ราคา/ชิ้น</th><th class="r">จำนวน</th><th class="r">รวม</th></tr>
{rows}
<tr class="tot"><td colspan="3" class="r">ค่าสินค้า (รวม VAT แล้ว)</td><td class="r">{goods:,.2f}</td></tr>
<tr class="tot"><td colspan="3" class="r">&nbsp;&nbsp;ในนี้เป็น VAT 7%</td><td class="r">{calc_vat(goods):,.2f}</td></tr>
<tr class="tot"><td colspan="3" class="r">ค่าส่ง</td><td class="r">{o['shipping_fee']:,.2f}</td></tr>
<tr class="tot grand"><td colspan="3" class="r">ยอดสุทธิ (บาท)</td><td class="r">{o['total']:,.2f}</td></tr>
</table>
<p class="m">ขอบคุณที่อุดหนุนครับ/ค่ะ</p>
</body></html>"""

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def send_receipt_email(to_addr, o, items):
    """ส่งใบเสร็จทาง Gmail (SMTP) คืน (True, "") หรือ (False, ข้อความผิดพลาด)"""
    gmail = get_setting("gmail_user")
    app_pw = (get_setting("gmail_app_password") or "").replace(" ", "")
    if not gmail or not app_pw:
        return False, "ร้านยังไม่ได้ตั้งค่า Gmail สำหรับส่งอีเมล (เจ้าของร้านตั้งค่าได้ในหน้าแอดมิน)"
    goods = sum(i["qty"] * i["unit_price"] for i in items)
    lines = [f"ใบเสร็จคำสั่งซื้อ #{o['id']} - ร้านหมูยออุบล", ""]
    lines += [f"{clean_name(i['name'])} x{i['qty']} = {i['qty'] * i['unit_price']:,.2f} บาท" for i in items]
    lines += ["", f"ค่าสินค้า (รวม VAT แล้ว): {goods:,.2f} บาท",
              f"  ในนี้เป็น VAT 7%: {calc_vat(goods):,.2f} บาท",
              f"ค่าส่ง: {o['shipping_fee']:,.2f} บาท", f"ยอดสุทธิ: {o['total']:,.2f} บาท",
              "", "ขอบคุณที่อุดหนุนครับ/ค่ะ"]
    msg = EmailMessage()
    msg["Subject"] = f"ใบเสร็จคำสั่งซื้อ #{o['id']} - ร้านหมูยออุบล"
    msg["From"] = formataddr(("ร้านหมูยออุบล", gmail))
    msg["To"] = to_addr
    msg.set_content("\n".join(lines))                       # ข้อความธรรมดา (สำรอง)
    msg.add_alternative(receipt_html(o, items), subtype="html")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(),
                              timeout=20) as server:
            server.login(gmail, app_pw)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return False, ("Gmail ปฏิเสธการเข้าสู่ระบบ ต้องใช้ App Password 16 หลัก "
                       "(ไม่ใช่รหัสผ่าน Gmail ปกติ) และต้องเปิดยืนยัน 2 ขั้นตอนไว้")
    except (smtplib.SMTPException, OSError) as e:
        return False, f"ส่งอีเมลไม่สำเร็จ: {e}"
    return True, ""

def db_reduce_stock(pid, qty):
    with get_conn() as conn:
        cur = conn.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                           (qty, pid, qty))
    return cur.rowcount > 0

def db_delete_product(pid):
    with get_conn() as conn:
        used = conn.execute("SELECT 1 FROM order_items WHERE product_id = ? LIMIT 1", (pid,)).fetchone()
        if used:
            name = conn.execute("SELECT name FROM products WHERE id = ?", (pid,)).fetchone()["name"]
            # เปลี่ยนชื่อด้วย เพื่อให้ใช้ชื่อเดิมตั้งสินค้าใหม่ได้
            conn.execute("UPDATE products SET active = 0, name = ? WHERE id = ?",
                         (f"{name} [ลบแล้ว #{pid}]", pid))
            return "hidden"
        conn.execute("DELETE FROM products WHERE id = ?", (pid,))
        return "deleted"

# =====================================================================
#  PromptPay QR 
# =====================================================================
def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"

def crc16_ccitt(text):
    crc = 0xFFFF
    for b in text.encode("ascii"):
        crc ^= b << 8
        for _ in range(8):
            crc = (crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"

def promptpay_payload(target, amount=None):
    """สร้างข้อความสำหรับทำ QR พร้อมเพย์
    target: เบอร์มือถือ 10 หลัก / เลขบัตรประชาชน-ภาษี 13 หลัก / e-Wallet 15 หลัก
    amount: ยอดเงิน (บาท) หรือ None ถ้าไม่ระบุยอด"""
    digits = "".join(ch for ch in str(target) if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        sub_tag, value = "01", "0066" + digits[1:]
    elif len(digits) == 13:
        sub_tag, value = "02", digits
    elif len(digits) == 15:
        sub_tag, value = "03", digits
    else:
        raise ValueError("ต้องเป็นเบอร์มือถือ 10 หลัก, เลขบัตรประชาชน/เลขผู้เสียภาษี 13 หลัก "
                         "หรือเลข e-Wallet 15 หลัก")
    merchant = _tlv("00", "A000000677010111") + _tlv(sub_tag, value)
    payload = (_tlv("00", "01")
               + _tlv("01", "12" if amount else "11")
               + _tlv("29", merchant)
               + _tlv("58", "TH")
               + _tlv("53", "764"))
    if amount:
        payload += _tlv("54", f"{float(amount):.2f}")
    payload += "6304"
    return payload + crc16_ccitt(payload)

def make_qr_canvas(parent, payload, size=220):
    """วาด QR ลงบน Canvas โดยตรง (ไม่ต้องพึ่ง Pillow)"""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    cell = max(1, size // n)
    px = cell * n
    cv = tk.Canvas(parent, width=px, height=px, bg="white", highlightthickness=0)
    for y, row in enumerate(matrix):
        for x, filled in enumerate(row):
            if filled:
                cv.create_rectangle(x * cell, y * cell, (x + 1) * cell, (y + 1) * cell,
                                    fill="black", outline="")
    return cv

# =====================================================================
#  จัดการรูปภาพ (เก็บเป็น BLOB ใน SQLite)
# =====================================================================
def load_image_file(path, max_px=600, jpeg=False):
    """อ่านไฟล์รูปจากเครื่อง -> bytes ที่พร้อมเก็บลงฐานข้อมูล (jpeg=True ใช้กับสลิป เพื่อให้ไฟล์เล็ก)"""
    if HAS_PIL:
        img = Image.open(path)
        img = img.convert("RGB")
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        if jpeg:
            img.save(buf, "JPEG", quality=85)
        else:
            img.save(buf, "PNG")
        return buf.getvalue()
    if path.lower().endswith((".png", ".gif")):
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > 2_000_000:
            raise ValueError("ไฟล์รูปใหญ่เกิน 2 MB (ติดตั้ง Pillow เพื่อให้ย่อรูปอัตโนมัติ)")
        return data
    raise ValueError("ยังไม่ได้ติดตั้ง Pillow จึงใช้ได้เฉพาะไฟล์ PNG/GIF\n"
                     "ติดตั้งด้วยคำสั่ง:  pip install pillow")

def ask_image_blob(parent, title="เลือกรูปภาพ", max_px=600, jpeg=False):
    path = filedialog.askopenfilename(
        parent=parent, title=title,
        filetypes=[("ไฟล์รูปภาพ", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("ทุกไฟล์", "*.*")])
    if not path:
        return None
    try:
        return load_image_file(path, max_px, jpeg)
    except Exception as e:  
        messagebox.showerror("เปิดรูปไม่สำเร็จ", str(e), parent=parent)
        return None

def blob_to_photo(blob, size, upscale=False):
    """แปลง BLOB เป็น PhotoImage ขนาดไม่เกิน size; คืน None ถ้าอ่านไม่ได้
    upscale=True จะขยายรูปเล็กให้เต็มกรอบด้วย (ต้องมี Pillow)"""
    if not blob:
        return None
    try:
        if HAS_PIL:
            img = Image.open(io.BytesIO(blob))
            img.load()
            img = img.convert("RGBA")
            if upscale and img.width < size[0] and img.height < size[1]:
                ratio = min(size[0] / img.width, size[1] / img.height)
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), resample)
            img.thumbnail(size)
            return ImageTk.PhotoImage(img)
        photo = tk.PhotoImage(data=base64.b64encode(blob))
        factor = max(1, math.ceil(photo.width() / size[0]), math.ceil(photo.height() / size[1]))
        return photo.subsample(factor) if factor > 1 else photo
    except Exception:  # noqa: BLE001
        return None

_placeholders = {}
_thumb_cache = {}     

def placeholder_photo(size):
    if size not in _placeholders:
        img = tk.PhotoImage(width=size[0], height=size[1])
        img.put("#e3e3e3", to=(0, 0, size[0], size[1]))
        _placeholders[size] = img
    return _placeholders[size]

def thumb_for(pid, blob, size=THUMB):
    if not blob:
        return placeholder_photo(size)
    key = (pid, size, hash(blob))
    if key not in _thumb_cache:
        _thumb_cache[key] = blob_to_photo(blob, size) or placeholder_photo(size)
    return _thumb_cache[key]

# =====================================================================
#  ตัวช่วย UI
# =====================================================================
MAIN_WINDOW = None      # หน้าต่างหลัก (App) ใช้เป็นต้นแบบขนาดของทุกหน้าต่างย่อย

def center(win, w, h):
    """หน้าต่างย่อยทุกหน้าใช้ขนาดและตำแหน่งเดียวกับหน้าต่างหลัก (เท่ากับหน้าล็อกอิน)
    w, h ใช้เฉพาะตอนที่ยังไม่มีหน้าต่างหลัก"""
    win.update_idletasks()
    main = MAIN_WINDOW
    if main is not None:
        main.update_idletasks()
        w, h = main.winfo_width(), main.winfo_height()
        x, y = main.winfo_x(), main.winfo_y()
    else:
        w = min(w, win.winfo_screenwidth() - 40)
        h = min(h, win.winfo_screenheight() - 90)
        x = max(0, (win.winfo_screenwidth() - w) // 2)
        y = max(0, (win.winfo_screenheight() - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")

def make_tree(parent, columns, height=12, thumbs=False):
    """columns = [(key, หัวข้อ, ความกว้าง, anchor)]; thumbs=True แสดงรูปย่อในคอลัมน์แรก"""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns],
                        show="tree headings" if thumbs else "headings",
                        height=height, selectmode="browse",
                        style="Thumb.Treeview" if thumbs else "Treeview")
    if thumbs:
        tree.heading("#0", text="รูป")
        tree.column("#0", width=80, stretch=False, anchor="center")
    for key, title, width, anchor in columns:
        tree.heading(key, text=title, anchor=anchor)
        tree.column(key, width=width, anchor=anchor)
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame, tree

def clear_tree(tree):
    tree.delete(*tree.get_children())

def selected_iid(tree):
    sel = tree.selection()
    return int(sel[0]) if sel else None

def insert_product_rows(tree, rows):
    for r in rows:
        desc = " ".join((r["description"] or "").split())
        if len(desc) > 70:
            desc = desc[:70].rstrip() + "…"
        tree.insert("", "end", iid=str(r["id"]), image=thumb_for(r["id"], r["image"]),
                    values=(r["name"], f"{r['price']:,.2f}", r["stock"], desc))

# =====================================================================
#  ธีม / สไตล์ 
# =====================================================================
def font(size=11, bold=False):
    return (FONT_FAMILY, size, "bold" if bold else "normal")

def pick_font_family(root):
    available = set(tkfont.families(root))
    for name in ("Leelawadee UI", "Sarabun", "Noto Sans Thai", "Prompt", "Kanit",
                 "Tahoma", "Segoe UI", "Helvetica Neue"):
        if name in available:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")

def apply_theme(root):
    global FONT_FAMILY
    FONT_FAMILY = pick_font_family(root)
    for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
              "TkCaptionFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(n).configure(family=FONT_FAMILY, size=11)
        except tk.TclError:
            pass
    root.configure(bg=BG)
    root.option_add("*Toplevel.background", BG)

    s = ttk.Style(root)
    s.theme_use("clam")      
    s.configure(".", background=BG, foreground=TEXT, bordercolor=BORDER,
                focuscolor=BG, troughcolor="#EFE7DF")

    # --- กรอบและข้อความ ---
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=CARD)
    s.configure("Header.TFrame", background=PRIMARY)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Card.TLabel", background=CARD)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    s.configure("CardTitle.TLabel", background=CARD, font=font(22, True), foreground=PRIMARY)
    s.configure("Heading.TLabel", font=font(15, True))
    s.configure("Price.TLabel", font=font(22, True), foreground=PRIMARY)
    s.configure("Success.TLabel", font=font(11, True), foreground=SUCCESS)
    s.configure("Warn.TLabel", font=font(11, True), foreground=WARN)
    s.configure("Danger.TLabel", font=font(11, True), foreground=DANGER)
    s.configure("HeaderTitle.TLabel", background=PRIMARY, foreground="#FFFFFF", font=font(17, True))
    s.configure("HeaderSub.TLabel", background=PRIMARY, foreground="#FED7AA")
    s.configure("TSeparator", background=BORDER)

    # --- ปุ่ม ---
    def button(name, bg, fg, hover, press, pad=(14, 7), bold=False, disabled_bg="#F5F5F4", disabled_fg="#A8A29E"):
        s.configure(name, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg,
                    darkcolor=bg, padding=pad, relief="flat", focusthickness=0,
                    font=font(11, bold))
        s.map(name, background=[("pressed", press), ("active", hover), ("disabled", disabled_bg)],
              foreground=[("disabled", disabled_fg)],
              bordercolor=[("pressed", press), ("active", hover), ("disabled", disabled_bg)],
              lightcolor=[("pressed", press), ("active", hover), ("disabled", disabled_bg)],
              darkcolor=[("pressed", press), ("active", hover), ("disabled", disabled_bg)])

    button("TButton", "#F1E8DF", TEXT, "#EADFD3", "#E2D6CA")
    button("Small.TButton", "#F1E8DF", TEXT, "#EADFD3", "#E2D6CA", pad=(10, 5))
    button("Accent.TButton", PRIMARY, "#FFFFFF", "#DB5416", PRIMARY_DARK, bold=True,
           disabled_bg="#D6D3D1", disabled_fg="#FFFFFF")
    button("SmallAccent.TButton", PRIMARY, "#FFFFFF", "#DB5416", PRIMARY_DARK, pad=(10, 5), bold=True,
           disabled_bg="#D6D3D1", disabled_fg="#FFFFFF")
    button("Danger.TButton", "#FEE2E2", DANGER, "#FECACA", "#FCA5A5")
    button("Header.TButton", PRIMARY_DARK, "#FFFFFF", "#B8441A", "#7C2D12", pad=(12, 6))
    button("Cart.TButton", "#FFFFFF", PRIMARY, "#FFF1E6", "#FFE4CC", pad=(14, 6), bold=True)

    # --- ช่องกรอก ---
    for name in ("TEntry", "TCombobox"):
        s.configure(name, fieldbackground="#FFFFFF", bordercolor="#D6CCC2", lightcolor="#D6CCC2",
                    darkcolor="#D6CCC2", padding=7, insertcolor=TEXT)
        s.map(name, bordercolor=[("focus", PRIMARY)], lightcolor=[("focus", PRIMARY)],
              darkcolor=[("focus", PRIMARY)])
    
    # --- ตัวเลือก ---
    for name, bg in (("TRadiobutton", BG), ("TCheckbutton", BG), ("Card.TCheckbutton", CARD)):
        s.configure(name, background=bg)
        s.map(name, background=[("active", bg)])

    # --- ตาราง ---
    s.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=TEXT,
                rowheight=32, borderwidth=0, relief="flat")
    s.map("Treeview", background=[("selected", PRIMARY)], foreground=[("selected", "#FFFFFF")])
    s.configure("Treeview.Heading", background="#F8E4D0", foreground=TEXT, relief="flat",
                padding=(8, 8), font=font(11, True))
    s.map("Treeview.Heading", background=[("active", "#F3D5B8")])
    s.configure("Thumb.Treeview", rowheight=THUMB[1] + 8)

    # --- แท็บ / แถบเลื่อน ---
    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background="#F1E8DF", foreground=MUTED, padding=(18, 9),
                borderwidth=0, font=font(11, True))
    s.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", PRIMARY)])
    s.configure("Vertical.TScrollbar", background="#E2D6CA", troughcolor=BG, bordercolor=BG,
                arrowcolor=MUTED, relief="flat")

def card_frame(parent, padding=16):
    outer = tk.Frame(parent, bg=BORDER)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return outer, inner

class RoundedFrame(tk.Canvas):
    """กรอบโค้งมน (Rounded Frame) สำหรับใช้แทน tk.Frame ปกติ"""
    def __init__(self, parent, bg_color="#FFFFFF", border_color="#E7DDD3", radius=16, **kwargs):
        super().__init__(parent, bg=BG, highlightthickness=0, **kwargs)
        self.bg_color = bg_color
        self.border_color = border_color
        self.radius = radius
        
        self.bind("<Configure>", self._draw)
        
        # สร้าง Frame ภายในสำหรับใส่ Widget ลูกๆ
        self.inner = ttk.Frame(self, style="Card.TFrame")
        self.inner_window = self.create_window(radius, radius, window=self.inner, anchor="nw")

    def _draw(self, event=None):
        self.delete("rounded_rect")
        w = self.winfo_width()
        h = self.winfo_height()
        r = self.radius
        
        # วาดรูปสี่เหลี่ยมโค้งมน
        self.create_rounded_rect(2, 2, w - 2, h - 2, r, 
                                   fill=self.bg_color, 
                                   outline=self.border_color, 
                                   width=1, 
                                   tags="rounded_rect")
        # สั่งให้ Frame ด้านในขยายตามขนาด Canvas
        self.coords(self.inner_window, r, r)
        self.itemconfig(self.inner_window, width=w - (r * 2), height=h - (r * 2))

    def create_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1,
            x1 + r, y1,
            x2 - r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1 + r,
            x1, y1
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

def safe_grab(win):
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass

def fmt_price(value):
    value = float(value)
    return f"฿{value:,.0f}" if value.is_integer() else f"฿{value:,.2f}"

def product_image(parent, p, size, bg="#FFFFFF"):
    """กรอบรูปสินค้าขนาดคงที่ (พื้นหลังสีขาว 1:1) วางรูปไว้กึ่งกลาง"""
    box = tk.Frame(parent, width=size[0], height=size[1], bg=bg)
    box.pack_propagate(False)
    lbl = tk.Label(box, bg=bg)
    if p["image"]:
        photo = thumb_for(p["id"], p["image"], size)
        lbl.configure(image=photo)
        lbl.image = photo
    else:
        lbl.configure(text="🍖\nยังไม่มีรูปสินค้า", fg=MUTED, font=font(11), justify="center")
    lbl.place(relx=0.5, rely=0.5, anchor="center")
    return box

# =====================================================================
#  หน้าต่างเข้าสู่ระบบ + หน้าต่างย่อย สมัครสมาชิก / ลืมรหัสผ่าน
# =====================================================================
RES = getattr(Image, "Resampling", Image) if HAS_PIL else None

BTN_STYLES = {
    "TButton": ("#F1E8DF", TEXT, "#EADFD3", "#E2D6CA", "#F5F5F4", "#A8A29E", False, 14, 7),
    "Small.TButton": ("#F1E8DF", TEXT, "#EADFD3", "#E2D6CA", "#F5F5F4", "#A8A29E", False, 10, 5),
    "Accent.TButton": (PRIMARY, "#FFFFFF", "#DB5416", PRIMARY_DARK, "#D6D3D1", "#FFFFFF", True, 14, 7),
    "SmallAccent.TButton": (PRIMARY, "#FFFFFF", "#DB5416", PRIMARY_DARK, "#D6D3D1", "#FFFFFF", True, 10, 5),
    "Danger.TButton": ("#FEE2E2", DANGER, "#FECACA", "#FCA5A5", "#F5F5F4", "#A8A29E", False, 14, 7),
    "Header.TButton": (PRIMARY_DARK, "#FFFFFF", "#B8441A", "#7C2D12", "#7C2D12", "#D6B8A8", False, 12, 6),
    "Cart.TButton": ("#FFFFFF", PRIMARY, "#FFF1E6", "#FFE4CC", "#F5F5F4", "#A8A29E", True, 14, 6),
}

def _parent_bg(w):
    try:
        return w.cget("bg")
    except tk.TclError:
        pass
    try:
        style = w.cget("style") or w.winfo_class()
        return ttk.Style().lookup(style, "background") or BG
    except tk.TclError:
        return BG

class RoundButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, style="TButton", width=None,
                 state="normal", **kw):
        (self._bg, self._fg, self._hover_bg, self._press_bg,
         self._dis_bg, self._dis_fg, bold, px, py) = BTN_STYLES.get(style, BTN_STYLES["TButton"])
        super().__init__(parent, bg=_parent_bg(parent), highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self._text = text
        self._command = command
        self._chars = width
        self._font = tkfont.Font(font=font(11, bold))
        self._scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self._px = int(px * self._scale * 1.5)
        self._py = int(py * self._scale * 1.3)
        self._disabled = False
        self._hover = False
        self._pressed = False
        self._focus = False
        self._nat = (10, 10)
        self._resize()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Return>", lambda e: self.invoke())
        self.bind("<space>", lambda e: self.invoke())
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        if state == "disabled":
            self.state(["disabled"])

    # ----- วาดปุ่ม -----
    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _resize(self):
        text_w = self._chars * self._font.measure("0") if self._chars else self._font.measure(self._text)
        w = text_w + 2 * self._px
        h = self._font.metrics("linespace") + 2 * self._py
        self._nat = (w, h)
        tk.Canvas.configure(self, width=w, height=h)
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() if self.winfo_width() > 1 else self._nat[0]
        h = self.winfo_height() if self.winfo_height() > 1 else self._nat[1]
        if self._disabled:
            fill, fg = self._dis_bg, self._dis_fg
        elif self._pressed:
            fill, fg = self._press_bg, self._fg
        elif self._hover:
            fill, fg = self._hover_bg, self._fg
        else:
            fill, fg = self._bg, self._fg
        r = max(2, h // 2)
        self._round_rect(1, 1, w - 1, h - 1, r, fill=fill, outline=fill)
        if self._focus and not self._disabled:
            self._round_rect(4, 4, w - 4, h - 4, max(2, r - 3), fill="", outline=fg, dash=(2, 3))
        self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

    # ----- เหตุการณ์เมาส์/คีย์บอร์ด -----
    def _on_enter(self, e):
        self._hover = True
        self._draw()

    def _on_leave(self, e):
        self._hover = self._pressed = False
        self._draw()

    def _on_press(self, e):
        if self._disabled:
            return
        self._pressed = True
        self.focus_set()
        self._draw()

    def _on_release(self, e):
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        if was_pressed and inside:
            self.invoke()

    def _on_focus_in(self, e):
        self._focus = True
        self._draw()

    def _on_focus_out(self, e):
        self._focus = False
        self._draw()

    # ----- เมธอดให้ใช้เหมือน ttk.Button -----
    def invoke(self):
        if not self._disabled and self._command:
            return self._command()

    def state(self, spec=None):
        if spec is None:
            return ("disabled",) if self._disabled else ()
        if isinstance(spec, str):
            spec = [spec]
        for s in spec:
            if s == "disabled":
                self._disabled = True
            elif s == "!disabled":
                self._disabled = False
        tk.Canvas.configure(self, cursor="arrow" if self._disabled else "hand2")
        self._draw()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        if "text" in kw:
            self._text = kw.pop("text")
        if "command" in kw:
            self._command = kw.pop("command")
        if "state" in kw:
            self.state(["disabled" if kw.pop("state") == "disabled" else "!disabled"])
        if kw:
            tk.Canvas.configure(self, **kw)
        self._resize()

    config = configure

def circle_image(blob, d):
    try:
        img = Image.open(io.BytesIO(blob)).convert("RGB")
        side = min(img.size)
        left, top = (img.width - side) // 2, (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((d, d), RES.LANCZOS)
        mask = Image.new("L", (d * 4, d * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
        mask = mask.resize((d, d), RES.LANCZOS)
        out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        return out
    except Exception:  # noqa: BLE001
        return None

class AvatarCanvas(tk.Canvas):

    def __init__(self, parent, size=112, bg=CARD):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.size = size
        self._photo = None

    def set(self, blob, name):
        self.delete("all")
        s = self.size
        photo = None
        if blob and HAS_PIL:
            img = circle_image(blob, s - 10)
            if img:
                photo = ImageTk.PhotoImage(img)
        if photo:
            self._photo = photo
            self.create_image(s / 2, s / 2, image=photo)
        else:
            self.create_oval(5, 5, s - 5, s - 5, fill="#FB923C", outline="#FB923C")
            self.create_text(s / 2, s / 2, text=(name or "?")[:1].upper(), fill="#FFFFFF",
                             font=font(int(s * 0.36), True))
        self.create_oval(3, 3, s - 3, s - 3, outline="#FFFFFF", width=4)     

DEFAULT_ABOUT = (
    "UBON MOOYOR SHOP คือร้านหมูยอจากจังหวัดอุบลราชธานี ที่เกิดจากความรักในรสชาติหมูยอ"
    "แบบดั้งเดิมของบ้านเรา เราคัดเลือกวัตถุดิบสดใหม่ ปรุงรสให้กลมกล่อม และห่อใบตองให้หอม"
    "ตามแบบฉบับท้องถิ่น เพื่อให้ทุกชิ้นนุ่ม อร่อย และมีคุณภาพ\n\n"
    "วันนี้เรานำหมูยอและของฝากจากอุบลมาให้คุณสั่งได้ง่าย ๆ ผ่านโปรแกรมนี้ เลือกสินค้า "
    "ชำระเงินผ่านพร้อมเพย์ แล้วรอรับของอร่อยได้เลย\n\n"
    "(ผู้ดูแลร้านแก้ไขข้อความนี้ให้ตรงกับเรื่องราวของร้านจริงได้ ที่ปุ่ม 'ประวัติร้าน' ในหน้าแอดมิน)"
)

class AboutWindow(tk.Toplevel):
    """หน้าประวัติร้าน (ลูกค้าดูได้ ข้อความแก้ไขได้จากหน้าแอดมิน)"""

    def __init__(self, app):
        super().__init__(app)
        self.title("ประวัติร้าน")
        self.transient(app)
        center(self, 780, 700)
        self.grab_set()
        self.configure(bg=BG)

        banner = tk.Frame(self, bg=PRIMARY)
        banner.pack(fill="x")
        tk.Label(banner, text="🍖 UBON MOOYOR SHOP", bg=PRIMARY, fg="#FFFFFF",
                 font=font(22, True)).pack(padx=32, pady=(24, 2), anchor="w")
        tk.Label(banner, text="ประวัติและเรื่องราวของร้าน UBON MOOYOR SHOP", bg=PRIMARY, fg="#FED7AA",
                 font=font(12)).pack(padx=32, pady=(0, 22), anchor="w")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=32, pady=22)

        outer, card = card_frame(body, padding=(26, 22))
        outer.pack(fill="x")
        tk.Label(card, text="ความเป็นมาของร้าน", bg=CARD, fg=PRIMARY,
                 font=font(15, True)).pack(anchor="w", pady=(0, 8))
        tk.Label(card, text=get_setting("shop_about") or DEFAULT_ABOUT, bg=CARD, fg=TEXT,
                 font=font(12), justify="left", wraplength=600).pack(anchor="w")

        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        row.columnconfigure((0, 1, 2), weight=1, uniform="h")
        highlights = [("🍖", "วัตถุดิบคัดสรร", "คัดเนื้อหมูสดใหม่ ปรุงรสกลมกล่อม"),
                      ("🍃", "ห่อใบตองหอม", "ห่อแบบดั้งเดิม ได้กลิ่นหอมธรรมชาติของใบตองสด"),
                      ("🚚", "สั่งง่าย ส่งถึงบ้าน", "สั่งผ่านโปรแกรม ชำระด้วยพร้อมเพย์หรือเก็บเงินปลายทาง")]
        for i, (icon, title, desc) in enumerate(highlights):
            o, c = card_frame(row, padding=(14, 14))
            o.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            tk.Label(c, text=icon, bg=CARD, font=font(24)).pack()
            tk.Label(c, text=title, bg=CARD, fg=TEXT, font=font(12, True)).pack(pady=(4, 2))
            tk.Label(c, text=desc, bg=CARD, fg=MUTED, font=font(10), wraplength=170,
                     justify="center").pack()

        RoundButton(body, text="ปิด", style="Accent.TButton", command=self.destroy).pack(
            side="bottom", fill="x", pady=(16, 0))

class AboutEditWindow(tk.Toplevel):
    """หน้าต่างให้แอดมินแก้ข้อความประวัติร้าน"""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("แก้ไขประวัติร้าน")
        self.transient(parent.winfo_toplevel())
        center(self, 680, 540)
        self.grab_set()
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="ข้อความประวัติร้าน (ลูกค้าจะเห็นในหน้า 'ประวัติร้าน')").pack(anchor="w")
        self.text = tk.Text(body, wrap="word", font=font(12), height=14, relief="flat",
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=PRIMARY, padx=10, pady=8)
        self.text.pack(fill="both", expand=True, pady=(6, 12))
        self.text.insert("1.0", get_setting("shop_about") or DEFAULT_ABOUT)
        row = ttk.Frame(body)
        row.pack(fill="x")
        RoundButton(row, text="บันทึก", style="Accent.TButton", command=self.save).pack(side="right")
        RoundButton(row, text="ยกเลิก", command=self.destroy).pack(side="right", padx=8)

    def save(self):
        set_setting("shop_about", self.text.get("1.0", "end").strip() or None)
        messagebox.showinfo("บันทึกแล้ว", "บันทึกประวัติร้านเรียบร้อย", parent=self)
        self.destroy()

class LoginFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(28, 20))
        self.app = app
       
        outer, card = card_frame(self, padding=(32, 28))
        outer.place(relx=0.5, rely=0.5, anchor="center", width=420)

        ttk.Label(card, text="🍖", font=font(38), style="CardTitle.TLabel").pack()
        ttk.Label(card, text="UBON MOOYOR SHOP", style="CardTitle.TLabel").pack(pady=(2, 0))
        ttk.Label(card, text="₊˚⊹สั่งหมูยอแสนอร่อยจากอุบลได้ง่าย ๆ⊹˚₊",
                  style="CardMuted.TLabel").pack(pady=(0, 20))
    
        ttk.Label(card, text="ชื่อผู้ใช้", style="Card.TLabel").pack(anchor="w", pady=(0, 3))
        self.username = ttk.Entry(card)
        self.username.pack(fill="x", pady=(0, 12))
        ttk.Label(card, text="รหัสผ่าน", style="Card.TLabel").pack(anchor="w", pady=(0, 3))
        self.password = ttk.Entry(card, show="•")
        self.password.pack(fill="x", pady=(0, 6))
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(card, text="แสดงรหัสผ่าน", variable=self.show_var, style="Card.TCheckbutton",
                        command=self._toggle_pw).pack(anchor="w", pady=(0, 16))

        RoundButton(card, text="เข้าสู่ระบบ", style="Accent.TButton", command=self.login).pack(fill="x")
        ttk.Separator(card).pack(fill="x", pady=16)
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill="x")
        RoundButton(row, text="สมัครสมาชิก", command=lambda: RegisterWindow(app)).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        RoundButton(row, text="ลืมรหัสผ่าน", command=lambda: ForgotWindow(app)).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.username.focus()
        self.password.bind("<Return>", lambda e: self.login())
        self.username.bind("<Return>", lambda e: self.password.focus())

    def _toggle_pw(self):
        self.password.config(show="" if self.show_var.get() else "•")

    def login(self):
        user = authenticate(self.username.get().strip(), self.password.get())
        if not user:
            messagebox.showerror("เข้าสู่ระบบไม่สำเร็จ", "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
            self.password.delete(0, "end")
            return
        self.app.user = dict(user)
        self.app.show_home()

class RegisterWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.title("สมัครสมาชิก")
        self.transient(app)
        center(self, 400, 500)
        self.grab_set()
        body = ttk.Frame(self, padding=(20, 25, 20, 20))
        body.pack(fill="both", expand=True)

        self.entries = {}
        fields = [("username", "ชื่อผู้ใช้ (อย่างน้อย 4 ตัวอักษร)", False),
                  ("password", "รหัสผ่าน (อย่างน้อย 6 ตัวอักษร)", True),
                  ("confirm", "ยืนยันรหัสผ่าน", True),
                  ("full_name", "ชื่อ-นามสกุล", False),
                  ("phone", "เบอร์โทรศัพท์", False)]
        for key, label, secret in fields:
            ttk.Label(body, text=label).pack(anchor="w")
            e = ttk.Entry(body, show="•" if secret else "")
            e.pack(fill="x", pady=(2, 8))
            self.entries[key] = e
        RoundButton(body, text="สมัครสมาชิก", style="Accent.TButton", command=self.submit).pack(fill="x", pady=(14, 0))
        self.entries["username"].focus()

    def submit(self):
        v = {k: e.get().strip() for k, e in self.entries.items()}
        v["password"] = self.entries["password"].get()
        v["confirm"] = self.entries["confirm"].get()
        if len(v["username"]) < 4:
            return messagebox.showwarning("ข้อมูลไม่ครบ", "ชื่อผู้ใช้ต้องมีอย่างน้อย 4 ตัวอักษร", parent=self)
        if len(v["password"]) < 6:
            return messagebox.showwarning("ข้อมูลไม่ครบ", "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร", parent=self)
        if v["password"] != v["confirm"]:
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "รหัสผ่านและการยืนยันไม่ตรงกัน", parent=self)
        if not v["full_name"]:
            return messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกชื่อ-นามสกุล", parent=self)
        if not (v["phone"].isdigit() and 9 <= len(v["phone"]) <= 10):
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "เบอร์โทรต้องเป็นตัวเลข 9-10 หลัก", parent=self)
        try:
            register_user(v["username"], v["password"], v["full_name"], v["phone"])
        except sqlite3.IntegrityError:
            return messagebox.showerror("สมัครไม่สำเร็จ", "ชื่อผู้ใช้นี้ถูกใช้แล้ว", parent=self)
        messagebox.showinfo("สำเร็จ", "สมัครสมาชิกเรียบร้อย เข้าสู่ระบบได้เลย", parent=self)
        self.destroy()

class ForgotWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.title("ลืมรหัสผ่าน")
        self.transient(app)
        center(self, 400, 480)
        self.grab_set()
        body = ttk.Frame(self, padding=(20, 25, 20, 20))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="ยืนยันตัวตนด้วยชื่อผู้ใช้และเบอร์โทรที่ใช้สมัคร",
                  wraplength=350).pack(anchor="w", pady=(0, 12))

        self.entries = {}
        for key, label, secret in [("username", "ชื่อผู้ใช้", False),
                                   ("phone", "เบอร์โทรศัพท์", False),
                                   ("password", "รหัสผ่านใหม่ (อย่างน้อย 6 ตัวอักษร)", True),
                                   ("confirm", "ยืนยันรหัสผ่านใหม่", True)]:
            ttk.Label(body, text=label).pack(anchor="w")
            e = ttk.Entry(body, show="•" if secret else "")
            e.pack(fill="x", pady=(2, 8))
            self.entries[key] = e
        RoundButton(body, text="ตั้งรหัสผ่านใหม่", style="Accent.TButton", command=self.submit).pack(fill="x", pady=(14, 0))

    def submit(self):
        username = self.entries["username"].get().strip()
        phone = self.entries["phone"].get().strip()
        pw = self.entries["password"].get()
        if len(pw) < 6:
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "รหัสผ่านใหม่ต้องมีอย่างน้อย 6 ตัวอักษร", parent=self)
        if pw != self.entries["confirm"].get():
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "รหัสผ่านและการยืนยันไม่ตรงกัน", parent=self)
        if not reset_password(username, phone, pw):
            return messagebox.showerror("ไม่สำเร็จ", "ชื่อผู้ใช้หรือเบอร์โทรไม่ตรงกับในระบบ", parent=self)
        messagebox.showinfo("สำเร็จ", "เปลี่ยนรหัสผ่านเรียบร้อย", parent=self)
        self.destroy()

# =====================================================================
#  หน้าร้านสำหรับลูกค้า: ดูสินค้า (พร้อมรูป) / สั่งซื้อ
# =====================================================================
class ShopFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._cards = []
        self._cols = 0
        self._search_job = None
        self._flash_job = None

        # --- แถบหัวเว็บ ---
        header = ttk.Frame(self, style="Header.TFrame", padding=(22, 14))
        header.pack(side="top", fill="x")
        left = ttk.Frame(header, style="Header.TFrame")
        left.pack(side="left")
        ttk.Label(left, text="🍖 UBON MOOYOR SHOP", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(left, text=f"♡ สวัสดี คุณ{app.user['username']} ♡", style="HeaderSub.TLabel").pack(anchor="w")
        RoundButton(header, text="ออกจากระบบ", style="Header.TButton",
                   command=app.show_login).pack(side="right")
        RoundButton(header, text="ประวัติการสั่งซื้อ", style="Header.TButton",
                   command=lambda: HistoryWindow(app)).pack(side="right", padx=8)
        RoundButton(header, text="👤 โปรไฟล์", style="Header.TButton",
                   command=lambda: ProfileWindow(app)).pack(side="right", padx=(0, 8))
        RoundButton(header, text="ℹ", style="Header.TButton",
                    command=lambda: AboutWindow(app)).pack(side="right", padx=(0, 8))
        
        # --- แถบค้นหา ---
        bar = ttk.Frame(self, padding=(22, 16, 22, 8))
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text="🔍").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search_var, width=34).pack(side="left", padx=(6, 0))
        self.search_var.trace_add("write", self._on_search)
        self.count_lbl = ttk.Label(bar, style="Muted.TLabel")
        self.count_lbl.pack(side="left", padx=14)

        self.cart_btn = RoundButton(bar, style="Cart.TButton", command=self.open_cart)   
        self.cart_btn.pack(side="right")                                                 

        self.flash_lbl = ttk.Label(bar, style="Success.TLabel")
        self.flash_lbl.pack(side="right")

        # --- พื้นที่การ์ดสินค้า (เลื่อนขึ้นลงได้) ---
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=(22, 10), pady=(0, 14))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, self._on_wheel)

        self.refresh()

    def destroy(self):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(seq)
        for job in (self._search_job, self._flash_job):
            if job:
                self.after_cancel(job)
        super().destroy()

    # ----- การเลื่อน / จัดวางการ์ด -----
    def _on_wheel(self, e):
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        if w is None or not str(w).startswith(str(self.canvas)):
            return                     
        if e.num == 4:
            step = -1
        elif e.num == 5:
            step = 1
        elif abs(e.delta) >= 120:
            step = -int(e.delta / 120)
        else:
            step = -1 if e.delta > 0 else 1
        try:
            self.canvas.yview_scroll(step * 2, "units")
        except tk.TclError:
            pass

    def _on_canvas_resize(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        cols = max(1, e.width // (CARD_W + 16))
        if cols != self._cols:
            self._cols = cols
            self._layout()

    def _layout(self):
        cols = max(1, self._cols)
        for c in range(20):
            self.grid_frame.columnconfigure(c, weight=1 if c < cols else 0)
        for i, card in enumerate(self._cards):
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="n")

    # ----- รายการสินค้า -----
    def _on_search(self, *_):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, self._do_search)

    def _do_search(self):
        self._search_job = None
        self.refresh()
        self.canvas.yview_moveto(0)

    def refresh_sum_table(self):
        fmt = {"วัน": "%Y-%m-%d", "เดือน": "%Y-%m", "ปี": "%Y"}[self.sum_mode.get()]
        with get_conn() as conn:
            # ค่าสินค้า = total - ค่าส่ง (รวม VAT แล้ว); VAT = ค่าสินค้า x 7/107 ปัดเศษต่อออเดอร์
            rows = conn.execute("""SELECT strftime(?, created_at) AS period, COUNT(*) AS n,
                                          SUM(total - shipping_fee) AS goods,
                                          SUM(ROUND((total - shipping_fee) * ? / (1 + ?), 2)) AS vat,
                                          SUM(shipping_fee) AS ship, SUM(total) AS total
                                   FROM orders WHERE status != ?
                                   GROUP BY period ORDER BY period DESC""",
                                (fmt, VAT_RATE, VAT_RATE, "ยกเลิก")).fetchall()
        clear_tree(self.sum_tree)
        for r in rows:
            self.sum_tree.insert("", "end", values=(r["period"], r["n"], f"{r['goods']:,.2f}",
                                                    f"{r['vat']:,.2f}", f"{r['goods'] - r['vat']:,.2f}",
                                                    f"{r['ship']:,.2f}", f"{r['total']:,.2f}"))
        self.sum_grand.set(f"รวมทั้งหมด {sum(r['n'] for r in rows)} ออเดอร์   "
                           f"ยอดสุทธิ {sum(r['total'] for r in rows):,.2f} บาท   "
                           f"VAT 7% รวมทั้งหมด {sum(r['vat'] for r in rows):,.2f} บาท")   

    def refresh(self):
        like = f"%{self.search_var.get().strip()}%"
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM products WHERE active = 1 "
                                "AND (name LIKE ? OR description LIKE ?) ORDER BY id",
                                (like, like)).fetchall()
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self._cards = [self._make_card(p) for p in rows]
        self.count_lbl.config(text=f"พบสินค้า {len(rows)} รายการ")
        if rows:
            self._layout()
        else:
            ttk.Label(self.grid_frame, text="ไม่พบสินค้าที่ค้นหา",
                      style="Muted.TLabel").grid(row=0, column=0, padx=20, pady=40)
        self.update_cart_label()

    def _make_card(self, p):
        pid, stock = p["id"], p["stock"]
        card = tk.Frame(self.grid_frame, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        product_image(card, p, CARD_IMG).pack(padx=12, pady=(12, 8))

        tk.Label(card, text=p["name"], bg=CARD, fg=TEXT, font=font(12, True), height=2,
                 wraplength=CARD_W - 28, justify="left", anchor="w").pack(fill="x", padx=14)
        desc = " ".join((p["description"] or "").split())
        if len(desc) > 52:
            desc = desc[:52].rstrip() + "…"
        tk.Label(card, text=desc or "ยังไม่มีคำบรรยาย", bg=CARD, fg=MUTED, font=font(10), height=2,
                 wraplength=CARD_W - 28, justify="left", anchor="nw").pack(fill="x", padx=14, pady=(2, 6))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=14)
        tk.Label(row, text=fmt_price(p["price"]), bg=CARD, fg=PRIMARY,
                 font=font(15, True)).pack(side="left")
        if stock <= 0:
            txt, col = "สินค้าหมด", DANGER
        elif stock <= 5:
            txt, col = f"เหลือ {stock} ชิ้น", WARN
        else:
            txt, col = f"คงเหลือ {stock}", SUCCESS
        tk.Label(row, text=txt, bg=CARD, fg=col, font=font(10, True)).pack(side="right")

        btns = tk.Frame(card, bg=CARD)
        btns.pack(fill="x", padx=14, pady=(8, 14))
        btns.columnconfigure((0, 1), weight=1, uniform="b")
        RoundButton(btns, text="ดูรายละเอียด", style="Small.TButton",
                   command=lambda: self.open_detail(pid)).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        add = RoundButton(btns, text="🛒 เพิ่ม", style="SmallAccent.TButton",
                         command=lambda: self.add_to_cart(pid, 1))
        add.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        if stock <= 0:
            add.state(["disabled"])

        self._wire_card(card, pid)
        return card

    def _wire_card(self, card, pid):
        """คลิกที่ไหนก็ได้บนการ์ด = เปิดรายละเอียด / เอาเมาส์ชี้แล้วขอบเปลี่ยนสี"""
        def walk(w):
            yield w
            for c in w.winfo_children():
                yield from walk(c)

        for w in walk(card):
            w.bind("<Enter>", lambda e, c=card: self._hover(c, True), add="+")
            w.bind("<Leave>", lambda e, c=card: c.after(30, self._leave_check, c), add="+")
            if not isinstance(w, (ttk.Button, RoundButton)):
                w.bind("<Button-1>", lambda e, p=pid: self.open_detail(p), add="+")
                try:
                    w.configure(cursor="hand2")
                except tk.TclError:
                    pass

    @staticmethod
    def _hover(card, on):
        try:
            card.configure(highlightbackground=PRIMARY if on else BORDER)
        except tk.TclError:
            pass

    def _leave_check(self, card):
        try:
            x, y = card.winfo_pointerxy()
            w = card.winfo_containing(x, y)
            inside = w is not None and str(w).startswith(str(card))
        except (KeyError, tk.TclError):
            inside = False
        self._hover(card, inside)

    # ----- รถเข็น -----
    def open_detail(self, pid):
        ProductDetailWindow(self, pid)

    def update_cart_label(self):
        n = sum(i["qty"] for i in self.app.cart.values())
        self.cart_btn.config(text=f"🛒 รถเข็น ({n})")

    def flash(self, text):
        self.flash_lbl.config(text=text)
        if self._flash_job:
            self.after_cancel(self._flash_job)
        self._flash_job = self.after(2500, self._clear_flash)

    def _clear_flash(self):
        self._flash_job = None
        try:
            self.flash_lbl.config(text="")
        except tk.TclError:
            pass

    def add_to_cart(self, pid, qty, parent=None):
        """ใส่สินค้าลงรถเข็น คืน True ถ้าสำเร็จ"""
        parent = parent or self.app
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (pid,)).fetchone()
        if p is None:
            messagebox.showerror("ไม่พบสินค้า", "สินค้านี้ถูกถอดออกจากร้านแล้ว", parent=parent)
            self.refresh()
            return False
        already = self.app.cart.get(pid, {}).get("qty", 0)
        if qty + already > p["stock"]:
            messagebox.showwarning("สต็อกไม่พอ",
                                   f"'{p['name']}' เหลือ {p['stock']} (ในรถเข็นแล้ว {already})",
                                   parent=parent)
            return False
        self.app.cart.setdefault(pid, {"name": p["name"], "price": p["price"], "qty": 0})["qty"] += qty
        self.update_cart_label()
        self.flash(f"✓ เพิ่ม {p['name']} x{qty} ลงรถเข็นแล้ว")
        return True

    def open_cart(self):
        CartWindow(self.app, on_change=self.refresh)


class ProductDetailWindow(tk.Toplevel):
    """หน้ารายละเอียดสินค้า: รูปใหญ่ (คลิกเพื่อขยาย) ราคา สต็อก คำบรรยาย และปุ่มสั่งซื้อ"""

    def __init__(self, shop, pid):
        super().__init__(shop.app)
        self.shop, self.pid = shop, pid
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (pid,)).fetchone()
        if p is None:
            self.destroy()
            messagebox.showinfo("ไม่พบสินค้า", "สินค้านี้ถูกถอดออกจากร้านแล้ว", parent=shop.app)
            shop.refresh()
            return
        self.p = p
        self.stock = p["stock"]
        self.title(p["name"])
        self.transient(shop.app)
        self.resizable(False, False)
        center(self, 800, 520)
        safe_grab(self)

        body = ttk.Frame(self, padding=(26, 30, 26, 26))
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 20))

        # ปรับให้ Label จัดรูปให้อยู่ตรงกลางพอดี ไม่ยืดเต็มช่องสูงๆ
        self.img_lbl = ttk.Label(left, background="#FFFFFF", relief="solid", borderwidth=1, anchor="center")
        self.img_lbl.pack(fill="x")
        self.img_lbl.bind("<Button-1>", lambda e: ImageViewer(self, self.p["image"]))
        self.load_image()

        # ขวา: รายละเอียด
        right = ttk.Frame(body, padding=(28, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)

        # ส่วนปุ่มสั่งซื้อ (pack ก่อนเพื่อให้อยู่ล่างสุดเสมอ)
        act = ttk.Frame(right)
        act.pack(side="bottom", fill="x", pady=(14, 0))
        qty_row = ttk.Frame(act)
        qty_row.pack(fill="x")
        ttk.Label(qty_row, text="จำนวน").pack(side="left")
        self.qty = tk.IntVar(value=1)
        self.minus = RoundButton(qty_row, text="−", width=3, style="Small.TButton",
                                command=lambda: self._step(-1))
        self.minus.pack(side="left", padx=(12, 4))
        vcmd = (self.register(self._validate_qty), "%P")
        self.spin = ttk.Entry(qty_row, textvariable=self.qty, width=5, justify="center",
                      validate="key", validatecommand=vcmd)
        self.spin.pack(side="left")
        self.plus = RoundButton(qty_row, text="+", width=3, style="Small.TButton",
                               command=lambda: self._step(1))
        self.plus.pack(side="left", padx=(4, 0))
        self.msg = ttk.Label(qty_row, style="Success.TLabel")
        self.msg.pack(side="right")

        btn_row = ttk.Frame(act)
        btn_row.pack(fill="x", pady=(12, 0))
        self.add_btn = RoundButton(btn_row, text="🛒 เพิ่มลงรถเข็น", style="Accent.TButton",
                                  command=self.add)
        self.add_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.buy_btn = RoundButton(btn_row, text="สั่งซื้อทันที", command=self.buy)
        self.buy_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))
        if self.stock <= 0:
            for w in (self.add_btn, self.buy_btn, self.minus, self.plus, self.spin):
                w.state(["disabled"])

        ttk.Label(right, text=p["name"], style="Heading.TLabel", wraplength=400,
                  justify="left").pack(anchor="w")
        ttk.Label(right, text=fmt_price(p["price"]), style="Price.TLabel").pack(anchor="w", pady=(4, 2))
        if self.stock <= 0:
            ttk.Label(right, text="สินค้าหมด", style="Danger.TLabel").pack(anchor="w")
        elif self.stock <= 5:
            ttk.Label(right, text=f"เหลือน้อย เพียง {self.stock} ชิ้น", style="Warn.TLabel").pack(anchor="w")
        else:
            ttk.Label(right, text=f"มีสินค้า คงเหลือ {self.stock} ชิ้น", style="Success.TLabel").pack(anchor="w")
        ttk.Separator(right).pack(fill="x", pady=12)

        ttk.Label(right, text="รายละเอียดสินค้า", font=font(12, True)).pack(anchor="w")
        box = ttk.Frame(right)
        box.pack(fill="both", expand=True, pady=(6, 0))
        text = tk.Text(box, wrap="word", relief="flat", bg=BG, fg=TEXT, font=font(11),
                       padx=0, pady=2, highlightthickness=0, borderwidth=0, cursor="arrow",
                       spacing2=3)
        sb = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.tag_configure("muted", foreground=MUTED)
        desc = (p["description"] or "").strip()
        if desc:
            text.insert("1.0", desc)
        else:
            text.insert("1.0", "ยังไม่มีคำบรรยายสินค้า", "muted")
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        self.update_idletasks()
        if text.yview()[1] < 1.0:        # แสดงแถบเลื่อนเฉพาะเมื่อคำบรรยายยาวเกินพื้นที่
            sb.pack(side="right", fill="y")

        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()

    def load_image(self):
        if self.p["image"]:
            try:
                pil_img = Image.open(io.BytesIO(self.p["image"])).resize((260, 260), Image.Resampling.LANCZOS)
                self.img_ref = ImageTk.PhotoImage(pil_img)
                self.img_lbl.config(image=self.img_ref, text="")
            except Exception:
                self.img_lbl.config(text="ไม่มีรูป", image="")
        else:
            self.img_lbl.config(text="ไม่มีรูป", image="")

    def _make_clickable(self, widget):
        widget.bind("<Button-1>", lambda e: self.view_image())
        try:
            widget.configure(cursor="hand2")
        except tk.TclError:
            pass
        for c in widget.winfo_children():
            self._make_clickable(c)

    def view_image(self):
        ImageViewer(self, self.p["name"], self.p["image"])

    def _validate_qty(self, proposed):
        if proposed == "":                    
            return True
        return (proposed.isascii() and proposed.isdigit()
            and int(proposed) <= max(self.stock, 1))

    def _step(self, d):
        try:
            cur = int(self.qty.get())
        except (ValueError, tk.TclError):
            cur = 1
        self.qty.set(min(max(1, cur + d), max(self.stock, 1)))
        self.spin.focus_set()         
        self.spin.icursor("end")      

    def _get_qty(self):
        try:
            q = int(self.qty.get())
            if q <= 0:
                raise ValueError
            return q
        except (ValueError, tk.TclError):
            messagebox.showwarning("จำนวนไม่ถูกต้อง", "กรุณากรอกจำนวนเป็นเลขจำนวนเต็มบวก", parent=self)
            return None

    def add(self):
        q = self._get_qty()
        if q and self.shop.add_to_cart(self.pid, q, parent=self):
            self.msg.config(text="✓ เพิ่มลงรถเข็นแล้ว")
            self.after(2000, self._clear_msg)
            return True
        return False

    def _clear_msg(self):
        try:
            self.msg.config(text="")
        except tk.TclError:
            pass

    def buy(self):
        if self.add():
            shop = self.shop
            self.destroy()
            shop.open_cart()


class ImageViewer(tk.Toplevel):
    """ดูรูปสินค้าขนาดใหญ่ คลิกที่ไหนก็ได้หรือกด Esc เพื่อปิด"""

    def __init__(self, parent, title, blob):
        super().__init__(parent)
        self.parent = parent
        self.title(title)
        self.configure(bg="#1C1917")
        self.transient(parent)
        self.resizable(False, False)
        limit = max(320, min(680, self.winfo_screenheight() - 220, self.winfo_screenwidth() - 120))
        self.photo = blob_to_photo(blob, (limit, limit), upscale=True)
        if self.photo is not None:
            center(self, self.photo.width() + 48, self.photo.height() + 96)
            tk.Label(self, image=self.photo, bg="#1C1917", cursor="hand2").pack(expand=True, padx=24, pady=(24, 8))
        else:
            center(self, 360, 200)
            tk.Label(self, text="ไม่สามารถแสดงรูปได้", bg="#1C1917", fg="#FFFFFF",
                     font=font(12)).pack(expand=True)
        tk.Label(self, text=f"{title}  ·  คลิกหรือกด Esc เพื่อปิด", bg="#1C1917", fg="#D6D3D1",
                 font=font(10)).pack(side="bottom", pady=(0, 14))
        safe_grab(self)
        self.bind("<Button-1>", lambda e: self.close())
        self.bind("<Escape>", lambda e: self.close())
        self.focus_set()

    def close(self):
        parent = self.parent
        self.destroy()
        try:
            parent.grab_set()           
        except tk.TclError:
            pass

class CartWindow(tk.Toplevel):
    def __init__(self, app, on_change):
        super().__init__(app)
        self.app, self.on_change = app, on_change
        self.title("รถเข็นสินค้า")
        self.transient(app)
        center(self, 600, 460)
        self.grab_set()

        body = ttk.Frame(self, padding=(20, 25, 20, 20))
        body.pack(fill="both", expand=True)

        row = ttk.Frame(body)
        row.pack(side="bottom", fill="x")
        RoundButton(row, text="แก้จำนวน", command=self.edit_qty).pack(side="left")
        RoundButton(row, text="ลบออก", style="Danger.TButton", command=self.remove).pack(side="left", padx=6)
        RoundButton(row, text="ล้างรถเข็น", command=self.clear_all).pack(side="left")
        RoundButton(row, text="ไปชำระเงิน", style="Accent.TButton", command=self.checkout).pack(side="right")

        self.total_var = tk.StringVar()
        ttk.Label(body, textvariable=self.total_var, font=font(14, True), foreground=PRIMARY).pack(
            side="bottom", anchor="e", pady=10)

        frame, self.tree = make_tree(body, [("name", "สินค้า", 230, "w"),
                                            ("price", "ราคา", 80, "e"),
                                            ("qty", "จำนวน", 70, "e"),
                                            ("sub", "รวม", 100, "e")], height=5)
        frame.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        clear_tree(self.tree)
        total = 0
        for pid, it in self.app.cart.items():
            sub = it["qty"] * it["price"]
            total += sub
            self.tree.insert("", "end", iid=str(pid),
                             values=(it["name"], f"{it['price']:,.2f}", it["qty"], f"{sub:,.2f}"))
        fee = calc_shipping_fee(total)
        if fee is None:
            self.total_var.set(f"ยอดรวมสินค้า: {total:,.2f} บาท\n" + (order_limit_error(total) if self.app.cart else
                               f"สั่งซื้อขั้นต่ำ {MIN_ORDER:,} บาท / ไม่เกิน {MAX_ORDER:,} บาทต่อออเดอร์"))
        else:
            self.total_var.set(f"ยอดรวมสินค้า (รวม VAT 7% แล้ว): {total:,.2f} บาท\n"
                               f"ค่าส่ง: {fee:,.2f} บาท   รวมที่ต้องชำระ: {total + fee:,.2f} บาท")
        self.on_change()

    def edit_qty(self):
        pid = selected_iid(self.tree)
        if pid is None:
            return messagebox.showinfo("เลือกรายการ", "กรุณาเลือกรายการก่อน", parent=self)
        with get_conn() as conn:
            stock = conn.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()["stock"]
        q = simpledialog.askinteger("แก้จำนวน", f"จำนวนใหม่ (1-{stock}):",
                                    parent=self, minvalue=1, maxvalue=max(stock, 1))
        if q:
            self.app.cart[pid]["qty"] = q
            self.refresh()

    def remove(self):
        pid = selected_iid(self.tree)
        if pid is None:
            return messagebox.showinfo("เลือกรายการ", "กรุณาเลือกสินค้าที่ต้องการลบก่อน", parent=self)
        self.app.cart.pop(pid, None)
        self.refresh()

    def clear_all(self):
        self.app.cart.clear()
        self.refresh()

    def checkout(self):
        goods = sum(it["qty"] * it["price"] for it in self.app.cart.values())
        err = order_limit_error(goods)
        if err:
            return messagebox.showwarning("ยอดสั่งซื้อไม่อยู่ในเงื่อนไข", err, parent=self)

class PaymentWindow(tk.Toplevel):
    """หน้าชำระเงิน: ซ้าย = สรุปรายการ/ค่าส่ง/ที่อยู่แยกช่อง, ขวา = วิธีชำระเงิน/QR/แนบสลิป"""

    ADDR_KEYS = ("no", "road", "subdistrict", "district", "province", "postcode")

    def __init__(self, app, cart_window, on_done):
        super().__init__(app)
        self.app, self.cart_window, self.on_done = app, cart_window, on_done
        self.qr_photo = None
        self.slip_blob = None
        self.slip_photo = None
        self.title("ชำระเงิน")
        self.transient(cart_window)
        center(self, 480, 540)
        self.grab_set()

        body = ttk.Frame(self, padding=(15, 22, 15, 15))
        body.pack(fill="both", expand=True)
        RoundButton(body, text="ยืนยันการสั่งซื้อ", style="Accent.TButton", width=34,
                    command=self.confirm).pack(side="bottom", pady=(10, 0))

        # เนื้อหากว้างคงที่ วางกึ่งกลางหน้าต่าง (หน้าต่างทุกหน้าใหญ่เท่ากัน)
        wrap = ttk.Frame(body, width=1000)
        wrap.pack(fill="y", expand=True)
        wrap.pack_propagate(False)
        left = ttk.Frame(wrap)
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))
        right = ttk.Frame(wrap)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        # ---------- ซ้าย: สรุปรายการ + ค่าส่ง ----------
        ttk.Label(left, text="สรุปรายการสั่งซื้อ", font=font(12, True)).pack(anchor="w")
        items = list(app.cart.values())
        self.goods = sum(it["qty"] * it["price"] for it in items)
        self.fee = calc_shipping_fee(self.goods)
        self.total = self.goods + self.fee

        for it in items[:5]:
            ttk.Label(left, text=f"  {it['name']}  x{it['qty']}  =  {it['qty'] * it['price']:,.2f}").pack(anchor="w")
        if len(items) > 5:
            ttk.Label(left, text=f"  ... และอีก {len(items) - 5} รายการ").pack(anchor="w")
        ttk.Label(left, text=f"ค่าสินค้า (รวม VAT แล้ว): {self.goods:,.2f} บาท").pack(anchor="w", pady=(6, 0))
        ttk.Label(left, text=f"  (ในค่าสินค้านี้เป็น VAT 7%: {calc_vat(self.goods):,.2f} บาท)",
                  foreground=MUTED).pack(anchor="w")
        ttk.Label(left, text=f"ค่าส่ง: {self.fee:,.2f} บาท").pack(anchor="w")
        ttk.Label(left, text=f"ยอดที่ต้องชำระ: {self.total:,.2f} บาท", font=font(14, True),
                  foreground=PRIMARY).pack(anchor="w", pady=(4, 14))

        # ---------- ซ้าย: ที่อยู่จัดส่งแบบแยกช่อง ----------
        ttk.Label(left, text="ที่อยู่จัดส่ง", font=font(12, True)).pack(anchor="w")
        ttk.Label(left, text="กรอกให้ครบทุกช่องที่มี * (ถนนเว้นว่างได้)", foreground=MUTED).pack(
            anchor="w", pady=(0, 4))
        addr = ttk.Frame(left)
        addr.pack(fill="x")
        addr.columnconfigure(0, weight=1)
        addr.columnconfigure(1, weight=1)
        self.v = {k: tk.StringVar() for k in self.ADDR_KEYS}

        def cell(r, c, text):
            f = ttk.Frame(addr)
            f.grid(row=r, column=c, sticky="ew", pady=4,
                   padx=(0, 6) if c == 0 else (6, 0))
            ttk.Label(f, text=text).pack(anchor="w")
            return f

        ttk.Entry(cell(0, 0, "บ้านเลขที่ *"), textvariable=self.v["no"]).pack(fill="x")
        ttk.Entry(cell(0, 1, "ถนน (ถ้ามี)"), textvariable=self.v["road"]).pack(fill="x")
        ttk.Entry(cell(1, 0, "ตำบล / แขวง *"), textvariable=self.v["subdistrict"]).pack(fill="x")
        ttk.Entry(cell(1, 1, "อำเภอ / เขต *"), textvariable=self.v["district"]).pack(fill="x")
        ttk.Combobox(cell(2, 0, "จังหวัด *"), textvariable=self.v["province"], values=PROVINCES,
                     state="readonly", height=12).pack(fill="x")
        only_digits = (self.register(lambda s: s == "" or (s.isascii() and s.isdigit() and len(s) <= 5)), "%P")
        ttk.Entry(cell(2, 1, "รหัสไปรษณีย์ *"), textvariable=self.v["postcode"],
                  validate="key", validatecommand=only_digits).pack(fill="x")
        self.email_var = tk.StringVar(value=(get_user(app.user["id"])["email"] or ""))
        em = cell(3, 0, "อีเมลรับใบเสร็จ (Gmail) ไม่บังคับ")
        em.grid_configure(columnspan=2)
        ttk.Entry(em, textvariable=self.email_var).pack(fill="x")

        # ---------- ขวา: วิธีชำระเงิน ----------
        ttk.Label(right, text="วิธีชำระเงิน", font=font(12, True)).pack(anchor="w")
        self.method = tk.StringVar(value=PAYMENT_METHODS[0])
        for m in PAYMENT_METHODS:
            ttk.Radiobutton(right, text=m, value=m, variable=self.method,
                            command=self.render_payment).pack(anchor="w")

        self.qr_frame = ttk.Frame(right)
        self.qr_frame.pack(pady=8)
        self.info = ttk.Label(right, wraplength=420, foreground=MUTED, justify="left")
        self.info.pack(anchor="w")

        # ---------- ขวา: แนบสลิป (แสดงเฉพาะตอนเลือกโอนเงิน) ----------
        self.slip_box = ttk.Frame(right)
        ttk.Label(self.slip_box, text="แนบสลิปการโอนเงิน *", font=font(11, True)).pack(anchor="w")
        btns = ttk.Frame(self.slip_box)
        btns.pack(anchor="w", pady=4)
        RoundButton(btns, text="เลือกรูปสลิป", command=self.pick_slip).pack(side="left")
        RoundButton(btns, text="ลบสลิป", command=self.clear_slip).pack(side="left", padx=6)
        self.slip_lbl = ttk.Label(self.slip_box, text="ยังไม่ได้แนบสลิป", foreground=MUTED)
        self.slip_lbl.pack(anchor="w")
        self.render_payment()

    def render_payment(self):
        for w in self.qr_frame.winfo_children():
            w.destroy()
        self.qr_photo = None

        if self.method.get() != PAYMENT_METHODS[0]:
            self.slip_box.pack_forget()
            self.info.config(text=f"ชำระเงินสด {self.total:,.2f} บาท กับพนักงานส่งของเมื่อได้รับสินค้า")
            return

        self.slip_box.pack(anchor="w", fill="x", pady=(10, 0))
        pp = get_setting("promptpay_id")
        payload = None
        if pp and HAS_QR:
            try:
                payload = promptpay_payload(pp, round(self.total, 2))
            except ValueError:
                payload = None
        if payload:
            make_qr_canvas(self.qr_frame, payload, 170).pack()
            self.info.config(text=f"สแกนด้วยแอปธนาคารเพื่อชำระ {self.total:,.2f} บาท "
                                  "(ใส่ยอดรวมค่าส่งใน QR ให้แล้ว) จากนั้นแนบรูปสลิปด้านล่าง "
                                  "ออเดอร์จะเป็น 'รอชำระเงิน' จนกว่าร้านจะตรวจสลิปและยืนยัน")
            return
        photo = blob_to_photo(get_setting("qr_image"), (220, 220))
        if photo:
            self.qr_photo = photo
            ttk.Label(self.qr_frame, image=photo).pack()
            self.info.config(text=f"สแกน QR ของร้านเพื่อโอน {self.total:,.2f} บาท (ต้องกรอกยอดเอง) "
                                  "จากนั้นแนบรูปสลิปด้านล่าง")
            return
        hint = ""
        if pp and not HAS_QR:
            hint = "\n(เจ้าของร้านตั้งพร้อมเพย์แล้ว แต่ยังไม่ได้ติดตั้งไลบรารี qrcode: pip install qrcode)"
        self.info.config(text="ร้านยังไม่ได้ตั้งค่า QR สำหรับโอนเงิน กรุณาติดต่อร้าน หรือเลือกเก็บเงินปลายทาง" + hint)

    # ----- สลิป -----
    def pick_slip(self):
        blob = ask_image_blob(self, "เลือกรูปสลิปการโอนเงิน", max_px=1000, jpeg=True)
        if blob:
            self.slip_blob = blob
            self.show_slip()

    def clear_slip(self):
        self.slip_blob = None
        self.show_slip()

    def show_slip(self):
        self.slip_photo = blob_to_photo(self.slip_blob, (170, 230)) if self.slip_blob else None
        if self.slip_photo:
            self.slip_lbl.config(image=self.slip_photo, text="")
        elif self.slip_blob:
            self.slip_lbl.config(image="", text="แนบสลิปแล้ว (แสดงตัวอย่างไม่ได้)")
        else:
            self.slip_lbl.config(image="", text="ยังไม่ได้แนบสลิป")

    # ----- ยืนยัน -----
    def confirm(self):
        err = order_limit_error(self.goods)
        if err:
            return messagebox.showwarning("ยอดสั่งซื้อไม่อยู่ในเงื่อนไข", err, parent=self)
        addr, err = validate_address(*(self.v[k].get() for k in self.ADDR_KEYS))
        if err:
            return messagebox.showwarning("ที่อยู่ไม่ถูกต้อง", err, parent=self)
        email = self.email_var.get().strip()
        if email and not EMAIL_RE.match(email):
            return messagebox.showwarning("อีเมลไม่ถูกต้อง",
                                          "กรุณากรอกอีเมลให้ถูกต้อง หรือเว้นว่างไว้", parent=self)
        transfer = self.method.get() == PAYMENT_METHODS[0]
        if transfer and not self.slip_blob:
            return messagebox.showwarning("ยังไม่ได้แนบสลิป",
                                          "กรุณาโอนเงินแล้วแนบรูปสลิปก่อนกดยืนยัน", parent=self)
        try:
            order_id, _ = place_order(self.app.user["id"], self.app.cart, self.method.get(),
                                      addr, self.fee, self.slip_blob if transfer else None)
        except ValueError as e:
            return messagebox.showerror("สั่งซื้อไม่สำเร็จ", str(e), parent=self)
        app, cart_window, on_done = self.app, self.cart_window, self.on_done
        app.cart.clear()
        cart_window.destroy()
        self.destroy()
        on_done()
        if email and not (get_user(app.user["id"])["email"] or "").strip():
            with get_conn() as conn:                      # โปรไฟล์ยังไม่มีอีเมล -> จำอีเมลนี้ไว้ให้
                conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, app.user["id"]))
        ReceiptWindow(app, order_id, just_placed=True, email=email or None)

class ReceiptWindow(tk.Toplevel):
    """ใบเสร็จ / รายละเอียดคำสั่งซื้อของลูกค้า (เปิดดูได้เฉพาะออเดอร์ของตัวเอง)"""

    def __init__(self, app, order_id, just_placed=False, parent=None, email=None):
        super().__init__(parent or app)
        self.app, self.order_id, self.just_placed = app, order_id, just_placed
        self.email = email                                # อีเมลที่ลูกค้ากรอกตอนสั่งซื้อ (ถ้ามี)
        self.title(f"ใบเสร็จคำสั่งซื้อ #{order_id}")
        self.transient(parent or app)
        center(self, 700, 720)
        self.grab_set()
        self.body = ttk.Frame(self, padding=14)
        self.body.pack(fill="both", expand=True)
        self.render()
        if just_placed:                                   # สั่งเสร็จแล้วส่งใบเสร็จเข้าอีเมลให้อัตโนมัติ
            self.after(400, lambda: self.email_receipt(auto=True))

    def render(self):
        for w in self.body.winfo_children():
            w.destroy()
        o, items = get_order_detail(self.order_id, self.app.user["id"])
        if o is None:
            messagebox.showerror("ไม่พบออเดอร์", "ไม่พบออเดอร์นี้ในบัญชีของคุณ", parent=self)
            self.destroy()
            return
        self.o, self.items = o, items
        transfer = o["payment_method"] == PAYMENT_METHODS[0]
        can_attach = transfer and o["status"] == "รอชำระเงิน"

        inner = ttk.Frame(self.body, width=700)       # เนื้อหากว้างคงที่ วางกึ่งกลางหน้าต่าง
        inner.pack(fill="y", expand=True)
        inner.pack_propagate(False)

        # ล่างสุด: ปุ่ม แล้วตามด้วยยอดรวม (pack ส่วนล่างก่อน จะได้ไม่ถูกตัดเมื่อหน้าต่างเตี้ย)
        bar = ttk.Frame(inner)
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        RoundButton(bar, text="ปิด", command=self.destroy).pack(side="right")
        RoundButton(bar, text="บันทึก / พิมพ์ใบเสร็จ", style="Accent.TButton",
                    command=self.save_receipt).pack(side="right", padx=6)
        RoundButton(bar, text="ส่งใบเสร็จทาง Gmail",
                    command=self.email_receipt).pack(side="right", padx=6)
        if o["has_slip"]:
            RoundButton(bar, text="ดูสลิป", command=self.view_slip).pack(side="left")
        if can_attach:
            RoundButton(bar, text="แนบ / เปลี่ยนสลิป", command=self.attach_slip).pack(side="left", padx=6)

        goods = sum(i["qty"] * i["unit_price"] for i in items)
        tot = ttk.Frame(inner)
        tot.pack(side="bottom", anchor="e", pady=(8, 0))
        for r, (label, val, big) in enumerate((("ค่าสินค้า (รวม VAT แล้ว)", goods, False),
                                               ("  ในนี้เป็น VAT 7%", calc_vat(goods), False),
                                               ("ค่าส่ง", o["shipping_fee"], False),
                                               ("ยอดสุทธิ", o["total"], True))):
            ttk.Label(tot, text=label, font=font(13 if big else 11, big)).grid(
                row=r, column=0, sticky="e", padx=(0, 16))
            ttk.Label(tot, text=f"{val:,.2f} บาท", font=font(13 if big else 11, big),
                      foreground=PRIMARY if big else TEXT).grid(row=r, column=1, sticky="e")

        if self.just_placed:
            ttk.Label(inner, text="✓ สั่งซื้อสำเร็จ ขอบคุณที่อุดหนุนครับ/ค่ะ", font=font(13, True),
                      foreground=SUCCESS).pack(anchor="w", pady=(0, 4))
        ttk.Label(inner, text="ใบเสร็จคำสั่งซื้อ", font=font(16, True), foreground=PRIMARY).pack(anchor="w")
        ttk.Label(inner, text="ร้านหมูยออุบล (UBON MOOYOR SHOP)", foreground=MUTED).pack(anchor="w")

        info = ttk.Frame(inner)
        info.pack(fill="x", pady=(8, 8))
        info.columnconfigure(1, weight=1)
        rows = [("เลขที่ออเดอร์", f"#{o['id']}"),
                ("วันเวลา", o["created_at"].replace("T", " ")),
                ("ผู้สั่งซื้อ", f"{o['full_name']}  โทร {o['phone']}"),
                ("ที่อยู่จัดส่ง", o["address"]),
                ("วิธีชำระเงิน", o["payment_method"]),
                ("สถานะ", o["status"])]
        if transfer:
            rows.append(("สลิปโอนเงิน", "แนบแล้ว" if o["has_slip"] else "ยังไม่ได้แนบ"))
        for r, (k, v) in enumerate(rows):
            ttk.Label(info, text=k, foreground=MUTED).grid(row=r, column=0, sticky="nw", padx=(0, 14), pady=1)
            ttk.Label(info, text=v, wraplength=480, justify="left").grid(row=r, column=1, sticky="w", pady=1)

        frame, tree = make_tree(inner, [("name", "สินค้า", 300, "w"),
                                        ("price", "ราคา/ชิ้น", 90, "e"),
                                        ("qty", "จำนวน", 70, "e"),
                                        ("sub", "รวม", 100, "e")], height=6)
        frame.pack(fill="both", expand=True)
        for i in items:
            tree.insert("", "end", values=(clean_name(i["name"]), f"{i['unit_price']:,.2f}", i["qty"],
                                           f"{i['qty'] * i['unit_price']:,.2f}"))

    def attach_slip(self):
        blob = ask_image_blob(self, "เลือกรูปสลิปการโอนเงิน", max_px=1000, jpeg=True)
        if not blob:
            return
        if set_order_slip(self.order_id, self.app.user["id"], blob):
            messagebox.showinfo("แนบสลิปแล้ว", "ร้านจะตรวจสลิปและยืนยันการชำระเงินให้ครับ/ค่ะ", parent=self)
            self.render()
        else:
            messagebox.showwarning("แนบสลิปไม่ได้", "ออเดอร์นี้ไม่อยู่ในสถานะรอชำระเงินแล้ว", parent=self)

    def email_receipt(self, auto=False):
        if not self.winfo_exists() or not hasattr(self, "o"):
            return
        to_addr = (self.email or get_user(self.app.user["id"])["email"] or "").strip()
        if auto and (not to_addr or not get_setting("gmail_user")):
            return                       # ส่งอัตโนมัติ: ไม่มีอีเมลลูกค้า/ร้านยังไม่ตั้ง Gmail ก็ข้ามไปเงียบ ๆ
        if not to_addr:
            to_addr = (simpledialog.askstring("อีเมลลูกค้า", "กรอกอีเมลที่จะรับใบเสร็จ:",
                                              parent=self) or "").strip()
            if not to_addr:
                return
        if not EMAIL_RE.match(to_addr):
            return messagebox.showwarning("อีเมลไม่ถูกต้อง", "กรุณากรอกอีเมลให้ถูกต้อง", parent=self)
        self.config(cursor="watch")
        self.update_idletasks()
        ok, err = send_receipt_email(to_addr, self.o, self.items)
        self.config(cursor="")
        if ok:
            messagebox.showinfo("ส่งใบเสร็จแล้ว", f"ส่งใบเสร็จไปที่ {to_addr} เรียบร้อย", parent=self)
        else:
            messagebox.showwarning("ส่งอีเมลไม่สำเร็จ", err, parent=self)

    def save_receipt(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="บันทึกใบเสร็จ", defaultextension=".html",
            initialfile=f"ใบเสร็จ_ออเดอร์{self.order_id}.html",
            filetypes=[("ไฟล์ HTML (เปิดแล้วสั่งพิมพ์หรือ Save as PDF ได้)", "*.html")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(receipt_html(self.o, self.items))
        except OSError as e:
            return messagebox.showerror("บันทึกไม่สำเร็จ", str(e), parent=self)
        webbrowser.open(pathlib.Path(path).resolve().as_uri())

class HistoryWindow(tk.Toplevel):
    """ประวัติการสั่งซื้อของลูกค้า: เห็นสินค้าที่ซื้อในแต่ละออเดอร์ และเปิดใบเสร็จได้"""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("ประวัติการสั่งซื้อ")
        self.transient(app)
        center(self, 680, 420)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        row = ttk.Frame(body)
        RoundButton(row, text="ดูรายการที่ซื้อ / ใบเสร็จ", style="Accent.TButton",
                    command=self.open_receipt).pack(side="right")

        frame, self.tree = make_tree(body, [("id", "ออเดอร์", 70, "center"),
                                            ("date", "วันเวลา", 140, "w"),
                                            ("goods", "สินค้าที่สั่ง", 360, "w"),
                                            ("total", "ยอดรวม", 100, "center"),
                                            ("method", "วิธีชำระ", 190, "w"),
                                            ("status", "สถานะสินค้า", 100, "w")], height=12)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.open_receipt())

        with get_conn() as conn:
            rows = conn.execute(
                "SELECT o.id, o.created_at, o.total, o.payment_method, o.status, "
                "(SELECT group_concat(p.name || ' x' || oi.qty, ', ') FROM order_items oi "
                " JOIN products p ON p.id = oi.product_id WHERE oi.order_id = o.id) AS goods "
                "FROM orders o WHERE o.user_id = ? ORDER BY o.id DESC", (app.user["id"],)).fetchall()
        for r in rows:
            goods = re.sub(r"\s*\[ลบแล้ว #\d+\]", "", r["goods"] or "")
            self.tree.insert("", "end", iid=str(r["id"]),
                             values=(r["id"], r["created_at"].replace("T", " "), goods,
                                     f"{r['total']:,.2f}", r["payment_method"], r["status"]))

    def open_receipt(self):
        oid = selected_iid(self.tree)
        if oid is None:
            return messagebox.showinfo("เลือกออเดอร์", "กรุณาเลือกออเดอร์ก่อน", parent=self)
        ReceiptWindow(self.app, oid, parent=self)

THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
GENDERS = ["ไม่ระบุ", "ชาย", "หญิง", "อื่น ๆ"]

class ProfileWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("โปรไฟล์ของฉัน")
        self.transient(app)
        center(self, 680, 520)
        self.grab_set()
        self.configure(bg=BG)
        u = get_user(app.user["id"])
        self.avatar_blob = u["avatar"]

        # --- แถบหัวโปรไฟล์ (รูปวงกลม + ชื่อ) ---
        banner = tk.Frame(self, bg=PRIMARY)
        banner.pack(fill="x")
        inner = tk.Frame(banner, bg=PRIMARY)
        inner.pack(padx=32, pady=24, anchor="w")
        self.avatar = AvatarCanvas(inner, 112, PRIMARY)
        self.avatar.pack(side="left")
        info = tk.Frame(inner, bg=PRIMARY)
        info.pack(side="left", padx=22)
        tk.Label(info, text=u["full_name"], bg=PRIMARY, fg="#FFFFFF",
                 font=font(20, True)).pack(anchor="w")
        tk.Label(info, text="@" + u["username"], bg=PRIMARY, fg="#FED7AA",
                 font=font(12)).pack(anchor="w", pady=(0, 12))
        brow = tk.Frame(info, bg=PRIMARY)
        brow.pack(anchor="w")
        RoundButton(brow, text="📷 เปลี่ยนรูป", style="Cart.TButton",
                    command=self.pick_avatar).pack(side="left")
        RoundButton(brow, text="ลบรูป", style="Header.TButton",
                    command=self.remove_avatar).pack(side="left", padx=8)

        # --- การ์ดข้อมูลส่วนตัว ---
        outer, card = card_frame(self, padding=(28, 22))
        outer.pack(fill="both", expand=True, padx=32, pady=22)
        card.columnconfigure((0, 1), weight=1, uniform="f")
        tk.Label(card, text="ข้อมูลส่วนตัว", bg=CARD, fg=TEXT, font=font(15, True)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        left_pad, right_pad = (0, 12), (12, 0)
        ttk.Label(card, text="ชื่อ-นามสกุล", style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 3), padx=left_pad)
        self.name_var = tk.StringVar(value=u["full_name"])
        ttk.Entry(card, textvariable=self.name_var).grid(
            row=2, column=0, sticky="ew", pady=(0, 14), padx=left_pad)

        ttk.Label(card, text="เพศ", style="CardMuted.TLabel").grid(
            row=1, column=1, sticky="w", pady=(0, 3), padx=right_pad)
        self.gender_var = tk.StringVar(value=u["gender"] or GENDERS[0])
        ttk.Combobox(card, textvariable=self.gender_var, values=GENDERS, state="readonly").grid(
            row=2, column=1, sticky="ew", pady=(0, 14), padx=right_pad)

        cap = tk.Frame(card, bg=CARD)
        cap.grid(row=3, column=0, sticky="ew", pady=(0, 3), padx=left_pad)
        ttk.Label(cap, text="วันเกิด (ค.ศ.)", style="CardMuted.TLabel").pack(side="left")
        clear = tk.Label(cap, text="ล้าง", bg=CARD, fg=PRIMARY, cursor="hand2", font=font(10, True))
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda e: self.clear_birth())
        by = bm = bd = 0
        if u["birthdate"]:
            by, bm, bd = map(int, u["birthdate"].split("-"))
        now_year = datetime.now().year
        years = [str(y) for y in range(now_year, now_year - 100, -1)]
        self.day_var = tk.StringVar(value=str(bd) if bd else "วัน")
        self.month_var = tk.StringVar(value=THAI_MONTHS[bm - 1] if bm else "เดือน")
        self.year_var = tk.StringVar(value=str(by) if by else "ปี ค.ศ.")
        bf = tk.Frame(card, bg=CARD)
        bf.grid(row=4, column=0, sticky="ew", pady=(0, 14), padx=left_pad)
        ttk.Combobox(bf, textvariable=self.day_var, width=4, state="readonly",
                     values=[str(i) for i in range(1, 32)]).pack(side="left")
        ttk.Combobox(bf, textvariable=self.month_var, width=10, state="readonly",
                     values=THAI_MONTHS).pack(side="left", padx=6)
        ttk.Combobox(bf, textvariable=self.year_var, width=8, state="readonly",
                     values=years).pack(side="left")

        ttk.Label(card, text="เบอร์โทรศัพท์", style="CardMuted.TLabel").grid(
            row=3, column=1, sticky="w", pady=(0, 3), padx=right_pad)
        self.phone_var = tk.StringVar(value=u["phone"])
        ttk.Entry(card, textvariable=self.phone_var).grid(
            row=4, column=1, sticky="ew", pady=(0, 14), padx=right_pad)

        ttk.Label(card, text="อีเมล", style="CardMuted.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(0, 3))
        self.email_var = tk.StringVar(value=u["email"] or "")
        ttk.Entry(card, textvariable=self.email_var).grid(
            row=6, column=0, columnspan=2, sticky="ew")

        btns = tk.Frame(card, bg=CARD)
        btns.grid(row=7, column=0, columnspan=2, sticky="e", pady=(24, 0))
        RoundButton(btns, text="ปิด", command=self.destroy).pack(side="left")
        RoundButton(btns, text="บันทึกข้อมูล", style="Accent.TButton",
                    command=self.save).pack(side="left", padx=(8, 0))

        self.show_avatar()

    def show_avatar(self):
        self.avatar.set(self.avatar_blob, self.name_var.get().strip() or self.app.user["username"])

    def pick_avatar(self):
        blob = ask_image_blob(self, "เลือกรูปโปรไฟล์", max_px=400)
        if blob:
            self.avatar_blob = blob
            self.show_avatar()

    def remove_avatar(self):
        self.avatar_blob = None
        self.show_avatar()

    def clear_birth(self):
        self.day_var.set("วัน")
        self.month_var.set("เดือน")
        self.year_var.set("ปี ค.ศ.")

    def save(self):
        name = self.name_var.get().strip()
        phone = self.phone_var.get().strip()
        email = self.email_var.get().strip()
        if not name:
            return messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกชื่อ-นามสกุล", parent=self)
        if not (phone.isdigit() and 9 <= len(phone) <= 10):
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "เบอร์โทรต้องเป็นตัวเลข 9-10 หลัก", parent=self)
        if email and not (email.count("@") == 1 and "." in email.split("@")[1] and " " not in email):
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "รูปแบบอีเมลไม่ถูกต้อง", parent=self)

        d, m, y = self.day_var.get(), self.month_var.get(), self.year_var.get()
        birth = None
        if d.isdigit() or y.isdigit() or m in THAI_MONTHS:
            if not (d.isdigit() and y.isdigit() and m in THAI_MONTHS):
                return messagebox.showwarning("ข้อมูลไม่ครบ",
                                              "กรุณาเลือกวัน เดือน ปีเกิดให้ครบ หรือกดปุ่ม 'ล้าง'", parent=self)
            try:
                dt = datetime(int(y), THAI_MONTHS.index(m) + 1, int(d))
            except ValueError:
                return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "วันเกิดไม่ถูกต้อง", parent=self)
            if dt > datetime.now():
                return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "วันเกิดต้องไม่เป็นวันในอนาคต", parent=self)
            birth = dt.strftime("%Y-%m-%d")

        update_profile(self.app.user["id"], name, phone, self.gender_var.get(),
                       birth, email, self.avatar_blob)
        self.app.user = get_user(self.app.user["id"])      # รีเฟรชข้อมูลผู้ใช้ปัจจุบัน
        messagebox.showinfo("บันทึกแล้ว", "บันทึกข้อมูลโปรไฟล์เรียบร้อย", parent=self)
        self.destroy()

# =====================================================================
#  หน้าจอเจ้าของร้าน: จัดการสินค้า+รูป / ออเดอร์ / ตั้งค่า QR
# =====================================================================
class ProductFormWindow(tk.Toplevel):
    """ฟอร์มเพิ่มสินค้าใหม่ (pid=None) หรือแก้ไขสินค้าเดิม: ชื่อ ราคา คำบรรยาย รูป"""

    def __init__(self, admin, pid=None):
        super().__init__(admin.app)
        self.admin, self.pid = admin, pid
        self.blob, self.image_changed, self.photo = None, False, None
        existing = None
        if pid is not None:
            with get_conn() as conn:
                existing = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if existing is None:
                self.destroy()
                return
            self.blob = existing["image"]
        self.title("แก้ไขสินค้า" if pid is not None else "เพิ่มสินค้าใหม่")
        self.transient(admin.app)
        self.resizable(False, False)
        center(self, 700, 580)
        safe_grab(self)

        body = ttk.Frame(self, padding=(24, 30, 24, 24))
        body.pack(fill="both", expand=True)

        # ซ้าย: รูปสินค้า
        left = ttk.Frame(body)
        left.pack(side="left", anchor="n")
        box = tk.Frame(left, width=240, height=240, bg=IMG_BG)
        box.pack_propagate(False)
        box.pack()
        self.img_lbl = tk.Label(box, bg=IMG_BG, fg=MUTED, font=font(11), justify="center")
        self.img_lbl.place(relx=0.5, rely=0.5, anchor="center")
        row = ttk.Frame(left)
        row.pack(pady=10)
        RoundButton(row, text="เลือกรูป...", command=self.pick_image).pack(side="left")
        RoundButton(row, text="ลบรูป", command=self.clear_image).pack(side="left", padx=6)

        # ขวา: ข้อมูล
        right = ttk.Frame(body, padding=(22, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        btns = ttk.Frame(right)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        RoundButton(btns, text="ยกเลิก", command=self.destroy).pack(side="right")
        RoundButton(btns, text="บันทึก", style="Accent.TButton",
                   command=self.save).pack(side="right", padx=(0, 8))

        ttk.Label(right, text="ชื่อสินค้า").pack(anchor="w", pady=(0, 3))
        self.name = ttk.Entry(right)
        self.name.pack(fill="x", pady=(0, 10))
        ttk.Label(right, text="ราคา (บาท)").pack(anchor="w", pady=(0, 3))
        self.price = ttk.Entry(right)
        self.price.pack(fill="x", pady=(0, 10))
        self.stock = None
        if pid is None:
            ttk.Label(right, text="จำนวนสต็อกเริ่มต้น").pack(anchor="w", pady=(0, 3))
            self.stock = ttk.Entry(right)
            self.stock.insert(0, "0")
            self.stock.pack(fill="x", pady=(0, 10))
        ttk.Label(right, text="รายละเอียดสินค้า (ลูกค้าจะเห็นในหน้ารายละเอียด)").pack(anchor="w", pady=(0, 3))
        self.desc = tk.Text(right, height=7, wrap="word", font=font(11), relief="flat", borderwidth=0,
                            highlightthickness=1, highlightbackground="#D6CCC2", highlightcolor=PRIMARY,
                            padx=8, pady=6, spacing2=3)
        self.desc.pack(fill="both", expand=True)

        if existing is not None:
            self.name.insert(0, existing["name"])
            p = float(existing["price"])
            self.price.insert(0, str(int(p)) if p.is_integer() else str(p))
            self.desc.insert("1.0", existing["description"] or "")
        self.show_image()
        self.name.focus()

    def show_image(self):
        self.photo = blob_to_photo(self.blob, (232, 232)) if self.blob else None
        if self.photo:
            self.img_lbl.config(image=self.photo, text="")
        else:
            self.img_lbl.config(image="", text="🍖\nยังไม่มีรูปสินค้า")

    def pick_image(self):
        blob = ask_image_blob(self, "เลือกรูปสินค้า", max_px=800)
        if blob:
            self.blob, self.image_changed = blob, True
            self.show_image()

    def clear_image(self):
        self.blob, self.image_changed = None, True
        self.show_image()

    def save(self):
        name = self.name.get().strip()
        if not name:
            return messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกชื่อสินค้า", parent=self)
        try:
            price = float(self.price.get().strip())
            if price < 0:
                raise ValueError
        except ValueError:
            return messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "ราคาต้องเป็นตัวเลขที่ไม่ติดลบ", parent=self)
        stock = 0
        if self.stock is not None:
            try:
                stock = int(self.stock.get().strip())
                if stock < 0:
                    raise ValueError
            except ValueError:
                return messagebox.showwarning("ข้อมูลไม่ถูกต้อง",
                                              "จำนวนสต็อกต้องเป็นเลขจำนวนเต็มที่ไม่ติดลบ", parent=self)
        desc = self.desc.get("1.0", "end").strip()
        try:
            with get_conn() as conn:
                if self.pid is None:
                    conn.execute("INSERT INTO products (name, price, stock, description, image) "
                                 "VALUES (?, ?, ?, ?, ?)", (name, price, stock, desc, self.blob))
                elif self.image_changed:
                    conn.execute("UPDATE products SET name = ?, price = ?, description = ?, image = ? "
                                 "WHERE id = ?", (name, price, desc, self.blob, self.pid))
                else:
                    conn.execute("UPDATE products SET name = ?, price = ?, description = ? WHERE id = ?",
                                 (name, price, desc, self.pid))
        except sqlite3.IntegrityError:
            return messagebox.showerror("ผิดพลาด", "มีสินค้าชื่อนี้แล้ว", parent=self)
        self.admin.refresh()
        self.destroy()

class AdminFrame(ttk.Frame):
    STATUSES = ["รอชำระเงิน", "รอจัดส่ง", "จัดส่งแล้ว", "ยกเลิก"]

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.preview_photo = None

        header = ttk.Frame(self, style="Header.TFrame", padding=(22, 14))
        header.pack(side="top", fill="x")
        left = ttk.Frame(header, style="Header.TFrame")
        left.pack(side="left")
        ttk.Label(left, text="🍖 ระบบจัดการร้าน", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(left, text="♡ admin · ubou mooyor shop ♡", style="HeaderSub.TLabel").pack(anchor="w")
        RoundButton(header, text="ออกจากระบบ", style="Header.TButton",
                   command=app.show_login).pack(side="right")
        RoundButton(header, text="สำรองข้อมูล", style="Header.TButton",
                   command=self.manual_backup).pack(side="right", padx=8)
        RoundButton(header, text="✎ ประวัติร้าน", style="Header.TButton",
                    command=lambda: AboutEditWindow(self)).pack(side="right", padx=(0, 0))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=18, pady=16)

        # --- แท็บสินค้า ---
        tab1 = ttk.Frame(nb, padding=12)
        nb.add(tab1, text="  สินค้า / สต็อก  ")
        bar = ttk.Frame(tab1)
        bar.pack(side="bottom", fill="x", pady=(10, 0))

        row_a = ttk.Frame(bar)
        row_a.pack(fill="x")
        RoundButton(row_a, text="➕ เพิ่มสินค้า", style="Accent.TButton",
                   command=self.add_product).pack(side="left")
        RoundButton(row_a, text="แก้ไข(ชื่อสินค้า/ราคา/รายละเอียดสินค้า/รูป)",
                   command=self.edit_product).pack(side="left", padx=6)
        row_b = ttk.Frame(bar)
        row_b.pack(fill="x", pady=(6, 0))
        RoundButton(row_b, text="เพิ่มของในสต็อก", command=self.restock).pack(side="left")
        RoundButton(row_b, text="ลดของในสต็อก", command=self.reduce_stock).pack(side="left", padx=6)
        RoundButton(row_b, text="ลบสินค้า", style="Accent.TButton",
                   command=self.delete_product).pack(side="left")
       
        frame, self.ptree = make_tree(tab1, [("name", "ชื่อสินค้า", 210, "w"),
                                             ("price", "ราคา", 90, "e"),
                                             ("stock", "สต็อก", 110, "center"),
                                             ("desc", "รายละเอียดสินค้า", 360, "w")], height=6, thumbs=True)
        frame.pack(fill="both", expand=True)
        self.ptree.bind("<Double-1>", lambda e: self.edit_product())

        # --- แท็บออเดอร์ ---
        tab2 = ttk.Frame(nb, padding=12)
        nb.add(tab2, text="  ออเดอร์  ")
        row = ttk.Frame(tab2)
        row.pack(side="bottom", fill="x", pady=(0, 4))
        ttk.Label(row, text="เปลี่ยนสถานะเป็น:").pack(side="left")
        for s in self.STATUSES:
            RoundButton(row, text=s, style="Danger.TButton" if s == "ยกเลิก" else "TButton",
                       command=lambda s=s: self.set_status(s)).pack(side="left", padx=3)
        RoundButton(row, text="ดูสลิปโอนเงิน", command=self.view_slip).pack(side="right")

        self.addr_var = tk.StringVar()
        ttk.Label(tab2, textvariable=self.addr_var, wraplength=860).pack(
            side="bottom", anchor="w", pady=8)

        frame, self.otree = make_tree(tab2, [("id", "เลขที่", 60, "center"),
                                             ("date", "เวลาสั่งซื้อ", 140, "w"),
                                             ("cust", "ลูกค้า", 200, "w"),
                                             ("total", "ยอดรวม", 120, "center"),
                                             ("method", "วิธีชำระ", 190, "w"),
                                             ("slip", "สลิป", 60, "center"),
                                             ("status", "สถานะ", 90, "w")], height=8)
        frame.pack(fill="both", expand=True)
        self.otree.bind("<<TreeviewSelect>>", self.show_address)

        # --- หน้าต่างตั้งค่า QR ชำระเงิน (เปิดจากปุ่มมุมขวาของแถบแท็บ) ---
        self.qr_win = tk.Toplevel(self)
        self.qr_win.withdraw()
        self.qr_win.title("ตั้งค่า QR ชำระเงิน")
        self.qr_win.protocol("WM_DELETE_WINDOW", self.qr_win.withdraw)
        tab3 = ttk.Frame(self.qr_win, padding=(16, 22, 16, 16))
        tab3.pack(fill="both", expand=True)

        ttk.Label(tab3, text="เบอร์พร้อมเพย์ (10 หลัก) / เลขบัตรประชาชน-ผู้เสียภาษี (13 หลัก)").pack(anchor="w")
        row = ttk.Frame(tab3)
        row.pack(fill="x", pady=(4, 14))
        self.pp_var = tk.StringVar(value=get_setting("promptpay_id") or "")
        ttk.Entry(row, textvariable=self.pp_var, width=28).pack(side="left")
        RoundButton(row, text="บันทึก", style="Accent.TButton",
                   command=self.save_promptpay).pack(side="left", padx=8)

        ttk.Label(tab3, text="อัปโหลดรูป QR ของร้าน").pack(anchor="w")
        row = ttk.Frame(tab3)
        row.pack(fill="x", pady=(4, 14))
        RoundButton(row, text="อัปโหลดรูป QR", command=self.upload_qr).pack(side="left")
        RoundButton(row, text="ลบรูป QR", style="Danger.TButton",
                   command=self.delete_qr).pack(side="left", padx=6)

        ttk.Label(tab3, text="Gmail ของร้าน (ใช้ส่งใบเสร็จให้ลูกค้า)").pack(anchor="w")
        grow = ttk.Frame(tab3)
        grow.pack(fill="x", pady=(4, 2))
        self.gm_user = tk.StringVar(value=get_setting("gmail_user") or "")
        self.gm_pw = tk.StringVar(value=get_setting("gmail_app_password") or "")
        ttk.Label(grow, text="Gmail").grid(row=0, column=0, sticky="w")
        ttk.Entry(grow, textvariable=self.gm_user, width=30).grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(grow, text="App Password").grid(row=1, column=0, sticky="w")
        ttk.Entry(grow, textvariable=self.gm_pw, width=30, show="•").grid(row=1, column=1, padx=6, pady=2)
        RoundButton(grow, text="บันทึก Gmail", style="Accent.TButton",
                    command=self.save_gmail).grid(row=0, column=2, rowspan=2, padx=6)
        ttk.Label(tab3, text="ต้องเปิดยืนยัน 2 ขั้นตอนใน Google แล้วสร้าง App Password 16 หลัก "
                             "(ไม่ใช่รหัสผ่าน Gmail ปกติ)", foreground=MUTED,
                  wraplength=560).pack(anchor="w", pady=(0, 14))

        if not HAS_QR:
            ttk.Label(tab3, text="⚠ ต้องติดตั้ง qrcode ก่อน: pip install qrcode",
                      foreground=WARN).pack(anchor="w", pady=(0, 8))

        self.preview = ttk.Frame(tab3)
        self.preview.pack(anchor="w")

        # ปุ่มมุมขวาสุดของแถวแท็บ
        qr_btn = RoundButton(nb, text="⚙ ตั้งค่า QR ชำระเงิน", command=self.open_qr_settings)
        qr_btn.place(relx=1.0, x=-4, y=2, anchor="ne")
        tk.Misc.lift(qr_btn)

        # --- แท็บสรุปยอดขาย ---
        tab4 = ttk.Frame(nb, padding=16)
        nb.add(tab4, text="  สรุปยอดขาย  ")
        self.sum_vars = {}
        cards = ttk.Frame(tab4)
        cards.pack(fill="x")
        for i, (key, title) in enumerate([("today", "ยอดขายวันนี้ (บาท)"),
                                          ("month", "ยอดขายเดือนนี้ (บาท)"),
                                          ("orders", "จำนวนออเดอร์ (ไม่รวมยกเลิก)")]):
            cards.columnconfigure(i, weight=1, uniform="sum")
            box = ttk.Frame(cards, style="Card.TFrame", padding=14)
            box.grid(row=0, column=i, padx=(0, 10), sticky="nsew")
            ttk.Label(box, text=title, style="Card.TLabel").pack(anchor="w")
            self.sum_vars[key] = tk.StringVar(value="-")
            ttk.Label(box, textvariable=self.sum_vars[key], style="Price.TLabel",
                      background=CARD).pack(anchor="w")

        low = ttk.Frame(tab4)
        low.pack(fill="both", expand=True, pady=(14, 0))
        low.columnconfigure(0, weight=3)
        low.columnconfigure(1, weight=2)
        low.rowconfigure(0, weight=1)
        left = ttk.Frame(low)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(low)
        right.grid(row=0, column=1, sticky="nsew")

        ttk.Label(left, text="สินค้าขายดี 5 อันดับ", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        fr, self.top_tree = make_tree(left, [("rank", "อันดับ", 60, "center"),
                                             ("name", "สินค้า", 220, "w"),
                                             ("qty", "ขายได้ (ชิ้น)", 100, "center"),
                                             ("sum", "รวม (บาท)", 100, "center")], height=6)
        fr.pack(fill="both", expand=True)

        ttk.Label(right, text="จำนวนออเดอร์แต่ละสถานะ", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        fr, self.stat_tree = make_tree(right, [("status", "สถานะ", 160, "w"),
                                               ("count", "จำนวน", 80, "center")], height=6)
        fr.pack(fill="both", expand=True)

        self.refresh()
        self.refresh_preview()

        # --- แท็บตารางสรุป (ดูตามวัน / เดือน / ปี และแสดง VAT 7% ที่รวมอยู่) ---
        tab5 = ttk.Frame(nb, padding=16)
        nb.add(tab5, text="  ตารางสรุป  ")
        top5 = ttk.Frame(tab5)
        top5.pack(fill="x", pady=(0, 8))
        ttk.Label(top5, text="ดูสรุปยอดขายตาม:", style="Heading.TLabel").pack(side="left")
        self.sum_mode = tk.StringVar(value="วัน")
        for m in ("วัน", "เดือน", "ปี"):
            ttk.Radiobutton(top5, text=m, value=m, variable=self.sum_mode,
                            command=self.refresh_sum_table).pack(side="left", padx=10)
        ttk.Label(top5, text="(ไม่รวมออเดอร์ที่ยกเลิก)", foreground=MUTED).pack(side="left", padx=10)
        self.sum_grand = tk.StringVar()
        ttk.Label(tab5, textvariable=self.sum_grand, font=font(12, True),
                  foreground=PRIMARY).pack(side="bottom", anchor="e", pady=(8, 0))
        fr, self.sum_tree = make_tree(tab5, [("period", "ช่วงเวลา", 120, "w"),
                                             ("orders", "ออเดอร์", 70, "center"),
                                             ("goods", "ค่าสินค้า (รวม VAT)", 140, "e"),
                                             ("vat", "VAT 7% ที่รวมอยู่", 130, "e"),
                                             ("net", "ค่าสินค้าก่อน VAT", 130, "e"),
                                             ("ship", "ค่าส่ง", 90, "e"),
                                             ("total", "ยอดรวมสุทธิ", 130, "e")], height=12)
        fr.pack(fill="both", expand=True)

        nb.bind("<<NotebookTabChanged>>", lambda e: (self.refresh_summary(), self.refresh_sum_table()))
        self.refresh_summary()
        self.refresh_sum_table()

    def refresh_summary(self):
        with get_conn() as conn:
            def one(sql, *args):
                return conn.execute(sql, args).fetchone()[0] or 0
            today = one("""SELECT SUM(total) FROM orders WHERE status != ?
                           AND date(created_at) = date('now', 'localtime')""", "ยกเลิก")
            month = one("""SELECT SUM(total) FROM orders WHERE status != ?
                           AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', 'localtime')""",
                        "ยกเลิก")
            count = one("SELECT COUNT(*) FROM orders WHERE status != ?", "ยกเลิก")
            top = conn.execute("""SELECT p.name, SUM(i.qty) AS q, SUM(i.qty * i.unit_price) AS s
                                  FROM order_items i
                                  JOIN orders o ON o.id = i.order_id
                                  JOIN products p ON p.id = i.product_id
                                  WHERE o.status != ?
                                  GROUP BY p.id ORDER BY q DESC LIMIT 5""", ("ยกเลิก",)).fetchall()
            stat = {r["status"]: r["c"] for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM orders GROUP BY status")}

        self.sum_vars["today"].set(f"{today:,.2f}")
        self.sum_vars["month"].set(f"{month:,.2f}")
        self.sum_vars["orders"].set(str(count))

        clear_tree(self.top_tree)
        for n, r in enumerate(top, 1):
            self.top_tree.insert("", "end", values=(n, r["name"], r["q"], f"{r['s']:,.2f}"))
        clear_tree(self.stat_tree)
        for s in self.STATUSES:
            self.stat_tree.insert("", "end", values=(s, stat.get(s, 0)))

    # ----- สินค้า -----
    def refresh(self):
        clear_tree(self.ptree)
        clear_tree(self.otree)
        with get_conn() as conn:
            insert_product_rows(self.ptree, conn.execute(
                "SELECT * FROM products WHERE active = 1 ORDER BY id").fetchall())
            for r in conn.execute("""SELECT o.id, o.created_at, o.total, o.payment_method, o.status,
                                            (o.slip IS NOT NULL) AS has_slip, u.full_name
                                     FROM orders o JOIN users u ON u.id = o.user_id
                                     ORDER BY o.id DESC"""):
                self.otree.insert("", "end", iid=str(r["id"]),
                                  values=(r["id"], r["created_at"].replace("T", " "), r["full_name"],
                                          f"{r['total']:,.2f}", r["payment_method"],
                                          "มี" if r["has_slip"] else "-", r["status"]))

    def add_product(self):
        ProductFormWindow(self)

    def edit_product(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        ProductFormWindow(self, pid)

    def restock(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        qty = simpledialog.askinteger("เติมสต็อก", "จำนวนที่เติม:", parent=self, minvalue=1)
        if qty:
            with get_conn() as conn:
                conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (qty, pid))
            self.refresh()

    def manual_backup(self):
        try:
            path = backup_db(manual=True)
        except Exception as e:  # noqa: BLE001
            return messagebox.showerror("สำรองข้อมูลไม่สำเร็จ", str(e))
        if path:
            messagebox.showinfo("สำรองข้อมูลแล้ว", f"บันทึกไว้ที่:\n{path}")
        else:
            messagebox.showinfo("ยังไม่มีข้อมูล", "ยังไม่มีฐานข้อมูลให้สำรอง")

    def reduce_stock(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        with get_conn() as conn:
            stock = conn.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()["stock"]
        if stock <= 0:
            return messagebox.showinfo("สต็อกหมดแล้ว", "สินค้านี้ไม่มีสต็อกให้ลด")
        qty = simpledialog.askinteger("ลดสต็อก", f"จำนวนที่ลด (1-{stock}):",
                                      parent=self, minvalue=1, maxvalue=stock)
        if qty and not db_reduce_stock(pid, qty):
            messagebox.showerror("ผิดพลาด", "สต็อกไม่พอ (อาจมีออเดอร์เข้ามาพอดี)")
        self.refresh()

    def delete_product(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        with get_conn() as conn:
            name = conn.execute("SELECT name FROM products WHERE id = ?", (pid,)).fetchone()["name"]
        if not messagebox.askyesno("ยืนยันการลบ", f"ลบสินค้า '{name}' ออกจากร้านใช่ไหม?"):
            return
        result = db_delete_product(pid)
        if result == "hidden":
            messagebox.showinfo("ถอดสินค้าแล้ว",
                                "สินค้านี้เคยมีออเดอร์ จึงถอดออกจากหน้าร้านแทนการลบจริง "
                                "(ประวัติออเดอร์เดิมยังอยู่ครบ)")
        self.refresh()

    # ----- ออเดอร์ -----
    def show_address(self, _event=None):
        oid = selected_iid(self.otree)
        if oid is None:
            return
        with get_conn() as conn:
            o = conn.execute("""SELECT o.address, o.shipping_fee, (o.slip IS NOT NULL) AS has_slip,
                                       u.phone FROM orders o
                                JOIN users u ON u.id = o.user_id WHERE o.id = ?""", (oid,)).fetchone()
        items = conn.execute("""SELECT p.name, oi.qty FROM order_items oi
                                    JOIN products p ON p.id = oi.product_id
                                    WHERE oi.order_id = ?""", (oid,)).fetchall()
        goods = ", ".join(f"{clean_name(i['name'])} x{i['qty']}" for i in items)
        self.addr_var.set(f"สินค้า: {goods}\nที่อยู่: {o['address']}  โทร: {o['phone']}\n"
                          f"ค่าส่ง: {o['shipping_fee']:,.2f} บาท   "
                          f"สลิปโอนเงิน: {'แนบแล้ว' if o['has_slip'] else 'ไม่มี'}")
                     
    def view_slip(self):
        oid = selected_iid(self.otree)
        if oid is None:
            return messagebox.showinfo("เลือกออเดอร์", "กรุณาเลือกออเดอร์ก่อน")
        blob = get_order_slip(oid)
        if not blob:
            return messagebox.showinfo("ไม่มีสลิป", "ออเดอร์นี้ยังไม่มีสลิปโอนเงิน")
        ImageViewer(self.winfo_toplevel(), f"สลิปโอนเงิน ออเดอร์ #{oid}", blob)

    def set_status(self, status):
        oid = selected_iid(self.otree)
        if oid is None:
            return messagebox.showinfo("เลือกออเดอร์", "กรุณาเลือกออเดอร์ก่อน")
        with get_conn() as conn:
            if status == "ยกเลิก":
                cur = conn.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()
                if cur["status"] == "ยกเลิก":
                    return
                # คืนสต็อกเมื่อยกเลิกออเดอร์
                conn.execute("""UPDATE products SET stock = stock +
                                (SELECT qty FROM order_items WHERE order_id = ? AND product_id = products.id)
                                WHERE id IN (SELECT product_id FROM order_items WHERE order_id = ?)""",
                             (oid, oid))
            conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, oid))
        self.refresh()

    # ----- ตั้งค่า QR -----
    def save_promptpay(self):
        value = self.pp_var.get().strip()
        if value:
            try:
                promptpay_payload(value, 1)
            except ValueError as e:
                return messagebox.showwarning("รูปแบบไม่ถูกต้อง", str(e))
        set_setting("promptpay_id", value or None)
        messagebox.showinfo("บันทึกแล้ว", "บันทึกการตั้งค่าพร้อมเพย์เรียบร้อย")
        self.refresh_preview()

    def save_gmail(self):
        user = self.gm_user.get().strip()
        pw = self.gm_pw.get().replace(" ", "")
        if not EMAIL_RE.match(user) or not user.lower().endswith(("@gmail.com", "@googlemail.com")):
            return messagebox.showwarning("Gmail ไม่ถูกต้อง", "กรุณากรอก Gmail ให้ถูกต้อง เช่น shop@gmail.com")
        if len(pw) != 16:
            return messagebox.showwarning("App Password ไม่ถูกต้อง", "App Password ต้องมี 16 ตัวอักษร")
        set_setting("gmail_user", user)
        set_setting("gmail_app_password", pw)
        messagebox.showinfo("บันทึกแล้ว", "บันทึก Gmail ของร้านเรียบร้อย")

    def upload_qr(self):
        blob = ask_image_blob(self.qr_win, "เลือกรูป QR ของร้าน", max_px=800)
        if blob:
            set_setting("qr_image", blob)
            self.refresh_preview()

    def delete_qr(self):
        set_setting("qr_image", None)
        self.refresh_preview()

    def open_qr_settings(self):
        self.refresh_preview()
        center(self.qr_win, 720, 500)
        self.qr_win.deiconify()
        self.qr_win.lift()
        self.qr_win.focus_force()

    def refresh_preview(self):
        for w in self.preview.winfo_children():
            w.destroy()
        col = 0
        pp = get_setting("promptpay_id")
        if pp and HAS_QR:
            try:
                payload = promptpay_payload(pp)
                box = ttk.Frame(self.preview, padding=(0, 0, 24, 0))
                box.grid(row=0, column=col)
                ttk.Label(box, text="ตัวอย่าง QR พร้อมเพย์ (ตอนลูกค้าจ่ายจะใส่ยอดให้อัตโนมัติ)").pack(pady=(0, 4))
                make_qr_canvas(box, payload, 200).pack()
                col += 1
            except ValueError:
                pass
        photo = blob_to_photo(get_setting("qr_image"), (200, 200))
        self.preview_photo = photo
        if photo:
            box = ttk.Frame(self.preview)
            box.grid(row=0, column=col)
            ttk.Label(box, text="รูป QR ที่อัปโหลดไว้").pack(pady=(0, 4))
            ttk.Label(box, image=photo).pack()

# =====================================================================
#  โปรแกรมหลัก
# =====================================================================
class App(tk.Tk):
    def __init__(self):
        global MAIN_WINDOW
        super().__init__()
        MAIN_WINDOW = self
        self.title("UBON MOOYOR SHOP")
        apply_theme(self)
        self.user = None
        self.cart = {}          # product_id -> {"name", "price", "qty"}
        self.current = None
        self.show_login()

    def _switch(self, frame_cls, w, h, min_size=None):
        if self.current is not None:
            self.current.destroy()
        if min_size:
            self.minsize(*min_size)
        
        # คำสั่งนี้คือหัวใจสำคัญ: บังคับให้ทุกหน้าขยายเต็มจอ (Zoomed) อัตโนมัติทันทีที่สลับหน้า
        self.state("zoomed")
        
        self.current = frame_cls(self)
        self.current.pack(fill="both", expand=True)

    def show_login(self):
        self.user, self.cart = None, {}
        w = self.winfo_screenwidth() // 2
        h = max(self.winfo_screenheight() // 2, 640)
        self._switch(LoginFrame, w, h, min_size=(440, 640))

    def show_home(self):
        if self.user["role"] == "admin":
            self._switch(AdminFrame, 1040, 720, min_size=(900, 560))
        else:
            self._switch(ShopFrame, 1040, 740, min_size=(520, 520))
    

if __name__ == "__main__":
    print("ใช้ฐานข้อมูล:", DB_NAME)
    try:
        backup_db()            
    except Exception as e:     
        print("สำรองข้อมูลอัตโนมัติไม่สำเร็จ:", e)
    init_db()
    App().mainloop()
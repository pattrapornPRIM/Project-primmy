"""
ร้านหมูยออุบล - Tkinter + SQLite  (เวอร์ชันมีรูปสินค้า + QR พร้อมเพย์)

ติดตั้งไลบรารีเสริม (แนะนำ):   pip install pillow qrcode
  - pillow : ใช้ไฟล์รูป JPG/PNG/WEBP ได้ทุกชนิด และย่อรูปอัตโนมัติ
             (ถ้าไม่มี จะใช้ได้เฉพาะไฟล์ PNG/GIF)
  - qrcode : สร้าง QR พร้อมเพย์พร้อมยอดเงินอัตโนมัติ
             (ถ้าไม่มี จะใช้รูป QR ที่เจ้าของร้านอัปโหลดแทน)

รัน:  python moo_yor_shop_gui.py
บัญชีเจ้าของร้านเริ่มต้น:  admin / admin1234   (ควรเปลี่ยนรหัสผ่านทันที)

รูปสินค้าและรูป QR เก็บเป็น BLOB ในฐานข้อมูล SQLite (ไฟล์ moo_yor_shop_gui.db)
จึงย้าย/สำรองข้อมูลได้ด้วยไฟล์เดียว
"""
import base64
import hashlib
import io
import math
import secrets
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import qrcode
    HAS_QR = True
except ImportError:
    HAS_QR = False

DB_NAME = "moo_yor_shop_gui.db"
PAYMENT_METHODS = ["โอนเงินผ่านพร้อมเพย์ (สแกน QR)", "เก็บเงินปลายทาง (COD)"]
THUMB = (56, 56)
DETAIL = (220, 220)


# =====================================================================
#  ฐานข้อมูล
# =====================================================================
def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


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
            image BLOB
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
        # อัปเกรดฐานข้อมูลเวอร์ชันเก่าที่ยังไม่มีคอลัมน์รูปภาพ
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(products)")]
        if "image" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN image BLOB")

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


def place_order(user_id, cart, method, address):
    """บันทึกคำสั่งซื้อใน transaction เดียว (ตัดสต็อกพร้อมกัน) คืน (เลขที่ออเดอร์, ยอดรวม)"""
    status = "รอชำระเงิน" if method == PAYMENT_METHODS[0] else "รอจัดส่ง"
    with get_conn() as conn:
        lines, total = [], 0.0
        for pid, item in cart.items():
            row = conn.execute("SELECT price FROM products WHERE id = ?", (pid,)).fetchone()
            cur = conn.execute("UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                               (item["qty"], pid, item["qty"]))
            if row is None or cur.rowcount == 0:
                raise ValueError(f"สินค้า '{item['name']}' มีสต็อกไม่พอ")
            lines.append((pid, item["qty"], row["price"]))
            total += item["qty"] * row["price"]
        cur = conn.execute(
            "INSERT INTO orders (created_at, user_id, total, payment_method, address, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), user_id, total, method, address, status))
        order_id = cur.lastrowid
        conn.executemany("INSERT INTO order_items (order_id, product_id, qty, unit_price) "
                         "VALUES (?, ?, ?, ?)", [(order_id, *ln) for ln in lines])
    return order_id, total


# =====================================================================
#  PromptPay QR (มาตรฐาน EMVCo)
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
def load_image_file(path, max_px=600):
    """อ่านไฟล์รูปจากเครื่อง -> bytes ที่พร้อมเก็บลงฐานข้อมูล"""
    if HAS_PIL:
        img = Image.open(path)
        img = img.convert("RGB")
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
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


def ask_image_blob(parent, title="เลือกรูปภาพ", max_px=600):
    path = filedialog.askopenfilename(
        parent=parent, title=title,
        filetypes=[("ไฟล์รูปภาพ", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("ทุกไฟล์", "*.*")])
    if not path:
        return None
    try:
        return load_image_file(path, max_px)
    except Exception as e:  # noqa: BLE001 - แสดงข้อผิดพลาดทุกแบบให้ผู้ใช้เห็น
        messagebox.showerror("เปิดรูปไม่สำเร็จ", str(e), parent=parent)
        return None


def blob_to_photo(blob, size):
    """แปลง BLOB เป็น PhotoImage ขนาดไม่เกิน size; คืน None ถ้าอ่านไม่ได้"""
    if not blob:
        return None
    try:
        if HAS_PIL:
            img = Image.open(io.BytesIO(blob))
            img.load()
            img = img.convert("RGBA")
            img.thumbnail(size)
            return ImageTk.PhotoImage(img)
        photo = tk.PhotoImage(data=base64.b64encode(blob))
        factor = max(1, math.ceil(photo.width() / size[0]), math.ceil(photo.height() / size[1]))
        return photo.subsample(factor) if factor > 1 else photo
    except Exception:  # noqa: BLE001
        return None


_placeholders = {}
_thumb_cache = {}      # เก็บอ้างอิง PhotoImage ไว้ด้วย (ไม่งั้น Tkinter จะลบรูปทิ้ง)


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
def center(win, w, h):
    win.update_idletasks()
    x = max(0, (win.winfo_screenwidth() - w) // 2)
    y = max(0, (win.winfo_screenheight() - h) // 3)
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
        tree.heading(key, text=title)
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
        tree.insert("", "end", iid=str(r["id"]), image=thumb_for(r["id"], r["image"]),
                    values=(r["name"], f"{r['price']:,.2f}", r["stock"]))


# =====================================================================
#  หน้าต่างเข้าสู่ระบบ + หน้าต่างย่อย สมัครสมาชิก / ลืมรหัสผ่าน
# =====================================================================
class LoginFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=25)
        self.app = app
        ttk.Label(self, text="🐖 ร้านหมูยออุบล", font=("", 18, "bold")).pack(pady=(0, 15))

        ttk.Label(self, text="ชื่อผู้ใช้").pack(anchor="w")
        self.username = ttk.Entry(self)
        self.username.pack(fill="x", pady=(0, 8))
        ttk.Label(self, text="รหัสผ่าน").pack(anchor="w")
        self.password = ttk.Entry(self, show="•")
        self.password.pack(fill="x", pady=(0, 12))

        ttk.Button(self, text="เข้าสู่ระบบ", command=self.login).pack(fill="x")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=10)
        ttk.Button(row, text="สมัครสมาชิก", command=lambda: RegisterWindow(app)).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(row, text="ลืมรหัสผ่าน", command=lambda: ForgotWindow(app)).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.username.focus()
        self.password.bind("<Return>", lambda e: self.login())
        self.username.bind("<Return>", lambda e: self.password.focus())

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
        center(self, 340, 400)
        self.grab_set()
        body = ttk.Frame(self, padding=20)
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
            e.pack(fill="x", pady=(0, 6))
            self.entries[key] = e
        ttk.Button(body, text="สมัครสมาชิก", command=self.submit).pack(fill="x", pady=(10, 0))
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
        center(self, 340, 360)
        self.grab_set()
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="ยืนยันตัวตนด้วยชื่อผู้ใช้และเบอร์โทรที่ใช้สมัคร",
                  wraplength=290).pack(anchor="w", pady=(0, 10))

        self.entries = {}
        for key, label, secret in [("username", "ชื่อผู้ใช้", False),
                                   ("phone", "เบอร์โทรศัพท์", False),
                                   ("password", "รหัสผ่านใหม่ (อย่างน้อย 6 ตัวอักษร)", True),
                                   ("confirm", "ยืนยันรหัสผ่านใหม่", True)]:
            ttk.Label(body, text=label).pack(anchor="w")
            e = ttk.Entry(body, show="•" if secret else "")
            e.pack(fill="x", pady=(0, 6))
            self.entries[key] = e
        ttk.Button(body, text="ตั้งรหัสผ่านใหม่", command=self.submit).pack(fill="x", pady=(10, 0))

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
        super().__init__(app, padding=10)
        self.app = app
        self.detail_photo = None

        top = ttk.Frame(self)
        top.pack(side="top", fill="x", pady=(0, 8))
        ttk.Label(top, text=f"สวัสดี คุณ{app.user['full_name']}", font=("", 12, "bold")).pack(side="left")
        ttk.Button(top, text="ออกจากระบบ", command=app.show_login).pack(side="right")
        ttk.Button(top, text="ประวัติการสั่งซื้อ", command=lambda: HistoryWindow(app)).pack(side="right", padx=6)
        self.cart_btn = ttk.Button(top, command=self.open_cart)
        self.cart_btn.pack(side="right")

        bottom = ttk.Frame(self)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(bottom, text="จำนวน:").pack(side="left")
        self.qty = tk.IntVar(value=1)
        ttk.Spinbox(bottom, from_=1, to=999, textvariable=self.qty, width=6).pack(side="left", padx=6)
        ttk.Button(bottom, text="เพิ่มลงตะกร้า", command=self.add_to_cart).pack(side="left")
        ttk.Button(bottom, text="สั่งซื้อทันที", command=self.buy_now).pack(side="left", padx=6)

        right = ttk.Frame(self, padding=(14, 0, 0, 0))
        right.pack(side="right", fill="y")
        self.detail_img = ttk.Label(right)
        self.detail_img.pack()
        self.detail_name = ttk.Label(right, font=("", 12, "bold"), wraplength=220, justify="center")
        self.detail_name.pack(pady=(8, 2))
        self.detail_info = ttk.Label(right, justify="center")
        self.detail_info.pack()

        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True)
        search = ttk.Frame(left)
        search.pack(fill="x", pady=(0, 6))
        ttk.Label(search, text="ค้นหาสินค้า:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(search, textvariable=self.search_var, width=30).pack(side="left", padx=6)

        frame, self.tree = make_tree(left, [("name", "ชื่อสินค้า", 260, "w"),
                                            ("price", "ราคา (บาท)", 100, "e"),
                                            ("stock", "คงเหลือ", 80, "e")], height=6, thumbs=True)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)

        self.show_detail()
        self.refresh()

    def refresh(self):
        prev = selected_iid(self.tree)
        clear_tree(self.tree)
        like = f"%{self.search_var.get().strip()}%"
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM products WHERE name LIKE ? ORDER BY id", (like,)).fetchall()
        insert_product_rows(self.tree, rows)
        if prev is not None and self.tree.exists(str(prev)):
            self.tree.selection_set(str(prev))
        self.update_cart_label()

    def show_detail(self, _event=None):
        pid = selected_iid(self.tree)
        if pid is None:
            self.detail_photo = placeholder_photo(DETAIL)
            self.detail_img.config(image=self.detail_photo)
            self.detail_name.config(text="เลือกสินค้าเพื่อดูรายละเอียด")
            self.detail_info.config(text="")
            return
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        if p is None:
            return
        self.detail_photo = blob_to_photo(p["image"], DETAIL) or placeholder_photo(DETAIL)
        self.detail_img.config(image=self.detail_photo)
        self.detail_name.config(text=p["name"])
        self.detail_info.config(text=f"{p['price']:,.2f} บาท\nคงเหลือ {p['stock']} ชิ้น")

    def update_cart_label(self):
        n = sum(i["qty"] for i in self.app.cart.values())
        self.cart_btn.config(text=f"🛒 ตะกร้า ({n})")

    def add_to_cart(self):
        pid = selected_iid(self.tree)
        if pid is None:
            messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
            return False
        try:
            qty = int(self.qty.get())
            if qty <= 0:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning("จำนวนไม่ถูกต้อง", "กรุณากรอกจำนวนเป็นเลขจำนวนเต็มบวก")
            return False
        with get_conn() as conn:
            p = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        already = self.app.cart.get(pid, {}).get("qty", 0)
        if qty + already > p["stock"]:
            messagebox.showwarning("สต็อกไม่พอ", f"'{p['name']}' เหลือ {p['stock']} (ในตะกร้าแล้ว {already})")
            return False
        self.app.cart.setdefault(pid, {"name": p["name"], "price": p["price"], "qty": 0})["qty"] += qty
        self.update_cart_label()
        return True

    def buy_now(self):
        if self.add_to_cart():
            self.open_cart()

    def open_cart(self):
        CartWindow(self.app, on_change=self.refresh)


class CartWindow(tk.Toplevel):
    def __init__(self, app, on_change):
        super().__init__(app)
        self.app, self.on_change = app, on_change
        self.title("ตะกร้าสินค้า")
        self.transient(app)
        center(self, 560, 420)
        self.grab_set()

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        frame, self.tree = make_tree(body, [("name", "สินค้า", 230, "w"),
                                            ("price", "ราคา", 80, "e"),
                                            ("qty", "จำนวน", 70, "e"),
                                            ("sub", "รวม", 100, "e")], height=10)
        frame.pack(fill="both", expand=True)

        self.total_var = tk.StringVar()
        ttk.Label(body, textvariable=self.total_var, font=("", 13, "bold")).pack(anchor="e", pady=8)

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Button(row, text="แก้จำนวน", command=self.edit_qty).pack(side="left")
        ttk.Button(row, text="ลบออก", command=self.remove).pack(side="left", padx=6)
        ttk.Button(row, text="ล้างตะกร้า", command=self.clear_all).pack(side="left")
        ttk.Button(row, text="ไปชำระเงิน ▶", command=self.checkout).pack(side="right")
        self.refresh()

    def refresh(self):
        clear_tree(self.tree)
        total = 0
        for pid, it in self.app.cart.items():
            sub = it["qty"] * it["price"]
            total += sub
            self.tree.insert("", "end", iid=str(pid),
                             values=(it["name"], f"{it['price']:,.2f}", it["qty"], f"{sub:,.2f}"))
        self.total_var.set(f"ยอดรวม: {total:,.2f} บาท")
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
        if pid is not None:
            self.app.cart.pop(pid, None)
            self.refresh()

    def clear_all(self):
        self.app.cart.clear()
        self.refresh()

    def checkout(self):
        if not self.app.cart:
            return messagebox.showinfo("ตะกร้าว่าง", "ยังไม่มีสินค้าในตะกร้า", parent=self)
        PaymentWindow(self.app, cart_window=self, on_done=self.on_change)


class PaymentWindow(tk.Toplevel):
    def __init__(self, app, cart_window, on_done):
        super().__init__(app)
        self.app, self.cart_window, self.on_done = app, cart_window, on_done
        self.qr_photo = None
        self.title("ชำระเงิน")
        self.transient(cart_window)
        center(self, 460, 740)
        self.grab_set()

        body = ttk.Frame(self, padding=15)
        body.pack(fill="both", expand=True)
        ttk.Button(body, text="ยืนยันการสั่งซื้อ", command=self.confirm).pack(side="bottom", fill="x", pady=(8, 0))

        ttk.Label(body, text="สรุปรายการสั่งซื้อ", font=("", 12, "bold")).pack(anchor="w")
        items = list(app.cart.values())
        self.total = sum(it["qty"] * it["price"] for it in items)
        for it in items[:4]:
            ttk.Label(body, text=f"  {it['name']}  x{it['qty']}  =  {it['qty'] * it['price']:,.2f}").pack(anchor="w")
        if len(items) > 4:
            ttk.Label(body, text=f"  ... และอีก {len(items) - 4} รายการ").pack(anchor="w")
        ttk.Label(body, text=f"ยอดที่ต้องชำระ: {self.total:,.2f} บาท",
                  font=("", 13, "bold")).pack(anchor="w", pady=(6, 10))

        ttk.Label(body, text="ที่อยู่จัดส่ง").pack(anchor="w")
        self.address = tk.Text(body, height=4, width=42)
        self.address.pack(fill="x", pady=(0, 10))

        ttk.Label(body, text="วิธีชำระเงิน").pack(anchor="w")
        self.method = tk.StringVar(value=PAYMENT_METHODS[0])
        for m in PAYMENT_METHODS:
            ttk.Radiobutton(body, text=m, value=m, variable=self.method,
                            command=self.render_payment).pack(anchor="w")

        self.qr_frame = ttk.Frame(body)
        self.qr_frame.pack(pady=8)
        self.info = ttk.Label(body, wraplength=410, foreground="#555", justify="left")
        self.info.pack(anchor="w")
        self.render_payment()

    def render_payment(self):
        for w in self.qr_frame.winfo_children():
            w.destroy()
        self.qr_photo = None

        if self.method.get() != PAYMENT_METHODS[0]:
            self.info.config(text="ชำระเงินสดกับพนักงานส่งของเมื่อได้รับสินค้า")
            return

        pp = get_setting("promptpay_id")
        if pp and HAS_QR:
            try:
                payload = promptpay_payload(pp, round(self.total, 2))
            except ValueError:
                payload = None
            if payload:
                make_qr_canvas(self.qr_frame, payload, 220).pack()
                self.info.config(text=f"สแกนด้วยแอปธนาคารเพื่อชำระ {self.total:,.2f} บาท "
                                      "(ใส่ยอดเงินใน QR ให้แล้ว) จากนั้นแจ้งชำระกับทางร้าน "
                                      "ออเดอร์จะเป็น 'รอชำระเงิน' จนกว่าร้านจะยืนยัน")
                return

        photo = blob_to_photo(get_setting("qr_image"), (240, 240))
        if photo:
            self.qr_photo = photo
            ttk.Label(self.qr_frame, image=photo).pack()
            self.info.config(text=f"สแกน QR ของร้านเพื่อโอน {self.total:,.2f} บาท (ต้องกรอกยอดเอง) "
                                  "จากนั้นแจ้งชำระกับทางร้าน")
            return

        hint = ""
        if pp and not HAS_QR:
            hint = "\n(เจ้าของร้านตั้งพร้อมเพย์แล้ว แต่ยังไม่ได้ติดตั้งไลบรารี qrcode: pip install qrcode)"
        self.info.config(text="ร้านยังไม่ได้ตั้งค่า QR สำหรับโอนเงิน กรุณาติดต่อร้าน หรือเลือกเก็บเงินปลายทาง" + hint)

    def confirm(self):
        address = self.address.get("1.0", "end").strip()
        if len(address) < 10:
            return messagebox.showwarning("ที่อยู่ไม่ครบ", "กรุณากรอกที่อยู่จัดส่งให้ครบถ้วน", parent=self)
        try:
            order_id, total = place_order(self.app.user["id"], self.app.cart,
                                          self.method.get(), address)
        except ValueError as e:
            return messagebox.showerror("สั่งซื้อไม่สำเร็จ", str(e), parent=self)
        self.app.cart.clear()
        messagebox.showinfo("สั่งซื้อสำเร็จ",
                            f"เลขที่ออเดอร์ #{order_id}\nยอดรวม {total:,.2f} บาท\nขอบคุณที่อุดหนุนครับ/ค่ะ",
                            parent=self)
        self.cart_window.destroy()
        self.destroy()
        self.on_done()


class HistoryWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.title("ประวัติการสั่งซื้อ")
        self.transient(app)
        center(self, 640, 380)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        frame, tree = make_tree(body, [("id", "ออเดอร์", 70, "center"),
                                       ("date", "วันเวลา", 150, "w"),
                                       ("total", "ยอดรวม", 90, "e"),
                                       ("method", "วิธีชำระ", 170, "w"),
                                       ("status", "สถานะ", 100, "w")], height=12)
        frame.pack(fill="both", expand=True)
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC",
                                (app.user["id"],)).fetchall()
        for r in rows:
            tree.insert("", "end", values=(r["id"], r["created_at"].replace("T", " "),
                                           f"{r['total']:,.2f}", r["payment_method"], r["status"]))


# =====================================================================
#  หน้าจอเจ้าของร้าน: จัดการสินค้า+รูป / ออเดอร์ / ตั้งค่า QR
# =====================================================================
class AdminFrame(ttk.Frame):
    STATUSES = ["รอชำระเงิน", "รอจัดส่ง", "จัดส่งแล้ว", "ยกเลิก"]

    def __init__(self, app):
        super().__init__(app, padding=10)
        self.app = app
        self.preview_photo = None
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="ระบบจัดการร้าน (เจ้าของร้าน)", font=("", 13, "bold")).pack(side="left")
        ttk.Button(top, text="ออกจากระบบ", command=app.show_login).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        # --- แท็บสินค้า ---
        tab1 = ttk.Frame(nb, padding=8)
        nb.add(tab1, text="สินค้า / สต็อก / รูป")
        row = ttk.Frame(tab1)
        row.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(row, text="เพิ่มสินค้า", command=self.add_product).pack(side="left")
        ttk.Button(row, text="เปลี่ยนรูป", command=self.change_image).pack(side="left", padx=6)
        ttk.Button(row, text="ลบรูป", command=self.remove_image).pack(side="left")
        ttk.Button(row, text="แก้ราคา", command=self.edit_price).pack(side="left", padx=6)
        ttk.Button(row, text="เติมสต็อก", command=self.restock).pack(side="left")
        frame, self.ptree = make_tree(tab1, [("name", "ชื่อสินค้า", 340, "w"),
                                             ("price", "ราคา", 120, "e"),
                                             ("stock", "สต็อก", 100, "e")], height=6, thumbs=True)
        frame.pack(fill="both", expand=True)

        # --- แท็บออเดอร์ ---
        tab2 = ttk.Frame(nb, padding=8)
        nb.add(tab2, text="ออเดอร์")
        frame, self.otree = make_tree(tab2, [("id", "เลขที่", 60, "center"),
                                             ("date", "วันเวลา", 140, "w"),
                                             ("cust", "ลูกค้า", 130, "w"),
                                             ("total", "ยอดรวม", 90, "e"),
                                             ("method", "วิธีชำระ", 190, "w"),
                                             ("status", "สถานะ", 90, "w")], height=12)
        frame.pack(fill="both", expand=True)
        self.otree.bind("<<TreeviewSelect>>", self.show_address)
        self.addr_var = tk.StringVar()
        ttk.Label(tab2, textvariable=self.addr_var, wraplength=860).pack(anchor="w", pady=6)
        row = ttk.Frame(tab2)
        row.pack(fill="x")
        ttk.Label(row, text="เปลี่ยนสถานะเป็น:").pack(side="left")
        for s in self.STATUSES:
            ttk.Button(row, text=s, command=lambda s=s: self.set_status(s)).pack(side="left", padx=3)

        # --- แท็บตั้งค่า QR ---
        tab3 = ttk.Frame(nb, padding=12)
        nb.add(tab3, text="ตั้งค่า QR ชำระเงิน")
        ttk.Label(tab3, text="เบอร์พร้อมเพย์ (10 หลัก) / เลขบัตรประชาชน-ผู้เสียภาษี (13 หลัก)").pack(anchor="w")
        row = ttk.Frame(tab3)
        row.pack(fill="x", pady=(2, 10))
        self.pp_var = tk.StringVar(value=get_setting("promptpay_id") or "")
        ttk.Entry(row, textvariable=self.pp_var, width=28).pack(side="left")
        ttk.Button(row, text="บันทึก", command=self.save_promptpay).pack(side="left", padx=6)

        ttk.Label(tab3, text="หรืออัปโหลดรูป QR ของร้านเอง (ใช้เมื่อไม่ได้ตั้งพร้อมเพย์ หรือไม่ได้ติดตั้ง qrcode)",
                  wraplength=860).pack(anchor="w")
        row = ttk.Frame(tab3)
        row.pack(fill="x", pady=(2, 10))
        ttk.Button(row, text="อัปโหลดรูป QR", command=self.upload_qr).pack(side="left")
        ttk.Button(row, text="ลบรูป QR", command=self.delete_qr).pack(side="left", padx=6)

        notes = []
        if not HAS_QR:
            notes.append("ยังไม่ได้ติดตั้ง qrcode → pip install qrcode")
        if not HAS_PIL:
            notes.append("ยังไม่ได้ติดตั้ง Pillow (ใช้ได้แค่ PNG/GIF) → pip install pillow")
        if notes:
            ttk.Label(tab3, text="⚠ " + " | ".join(notes), foreground="#b45309").pack(anchor="w", pady=(0, 8))

        self.preview = ttk.Frame(tab3)
        self.preview.pack(anchor="w")

        self.refresh()
        self.refresh_preview()

    # ----- สินค้า -----
    def refresh(self):
        clear_tree(self.ptree)
        clear_tree(self.otree)
        with get_conn() as conn:
            insert_product_rows(self.ptree, conn.execute("SELECT * FROM products ORDER BY id").fetchall())
            for r in conn.execute("""SELECT o.*, u.full_name FROM orders o
                                     JOIN users u ON u.id = o.user_id ORDER BY o.id DESC"""):
                self.otree.insert("", "end", iid=str(r["id"]),
                                  values=(r["id"], r["created_at"].replace("T", " "), r["full_name"],
                                          f"{r['total']:,.2f}", r["payment_method"], r["status"]))

    def add_product(self):
        name = simpledialog.askstring("เพิ่มสินค้า", "ชื่อสินค้า:", parent=self)
        if not name or not name.strip():
            return
        price = simpledialog.askfloat("เพิ่มสินค้า", "ราคา (บาท):", parent=self, minvalue=0)
        stock = simpledialog.askinteger("เพิ่มสินค้า", "จำนวนสต็อก:", parent=self, minvalue=0)
        if price is None or stock is None:
            return
        blob = ask_image_blob(self, "เลือกรูปสินค้า (กดยกเลิกถ้าไม่ใส่รูป)")
        try:
            with get_conn() as conn:
                conn.execute("INSERT INTO products (name, price, stock, image) VALUES (?, ?, ?, ?)",
                             (name.strip(), price, stock, blob))
        except sqlite3.IntegrityError:
            messagebox.showerror("ผิดพลาด", "มีสินค้าชื่อนี้แล้ว")
        self.refresh()

    def change_image(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        blob = ask_image_blob(self, "เลือกรูปสินค้าใหม่")
        if blob:
            with get_conn() as conn:
                conn.execute("UPDATE products SET image = ? WHERE id = ?", (blob, pid))
            self.refresh()

    def remove_image(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        with get_conn() as conn:
            conn.execute("UPDATE products SET image = NULL WHERE id = ?", (pid,))
        self.refresh()

    def edit_price(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        price = simpledialog.askfloat("แก้ราคา", "ราคาใหม่ (บาท):", parent=self, minvalue=0)
        if price is not None:
            with get_conn() as conn:
                conn.execute("UPDATE products SET price = ? WHERE id = ?", (price, pid))
            self.refresh()

    def restock(self):
        pid = selected_iid(self.ptree)
        if pid is None:
            return messagebox.showinfo("เลือกสินค้า", "กรุณาเลือกสินค้าก่อน")
        qty = simpledialog.askinteger("เติมสต็อก", "จำนวนที่เติม:", parent=self, minvalue=1)
        if qty:
            with get_conn() as conn:
                conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (qty, pid))
            self.refresh()

    # ----- ออเดอร์ -----
    def show_address(self, _event=None):
        oid = selected_iid(self.otree)
        if oid is None:
            return
        with get_conn() as conn:
            o = conn.execute("""SELECT o.address, u.phone FROM orders o
                                JOIN users u ON u.id = o.user_id WHERE o.id = ?""", (oid,)).fetchone()
            items = conn.execute("""SELECT p.name, oi.qty FROM order_items oi
                                    JOIN products p ON p.id = oi.product_id
                                    WHERE oi.order_id = ?""", (oid,)).fetchall()
        goods = ", ".join(f"{i['name']} x{i['qty']}" for i in items)
        self.addr_var.set(f"สินค้า: {goods}\nที่อยู่: {o['address']}  โทร: {o['phone']}")

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

    def upload_qr(self):
        blob = ask_image_blob(self, "เลือกรูป QR ของร้าน", max_px=800)
        if blob:
            set_setting("qr_image", blob)
            self.refresh_preview()

    def delete_qr(self):
        set_setting("qr_image", None)
        self.refresh_preview()

    def refresh_preview(self):
        for w in self.preview.winfo_children():
            w.destroy()
        pp = get_setting("promptpay_id")
        col = 0
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
        super().__init__()
        self.title("ร้านหมูยออุบล")
        ttk.Style(self).configure("Thumb.Treeview", rowheight=THUMB[1] + 8)
        self.user = None
        self.cart = {}          # product_id -> {"name", "price", "qty"}
        self.current = None
        self.show_login()

    def _switch(self, frame_cls, w, h):
        if self.current is not None:
            self.current.destroy()
        center(self, w, h)
        self.current = frame_cls(self)
        self.current.pack(fill="both", expand=True)

    def show_login(self):
        self.user, self.cart = None, {}
        self._switch(LoginFrame, 360, 340)

    def show_home(self):
        if self.user["role"] == "admin":
            self._switch(AdminFrame, 960, 640)
        else:
            self._switch(ShopFrame, 940, 560)


if __name__ == "__main__":
    init_db()
    App().mainloop()

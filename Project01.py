import hashlib
import os
import secrets
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

# ไฟล์ฐานข้อมูลจะอยู่โฟลเดอร์เดียวกับไฟล์โค้ดนี้เสมอ (ไม่ขึ้นกับโฟลเดอร์ที่สั่งรัน)
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moo_yor_shop_gui.db")
PAYMENT_METHODS = ["โอนเงินผ่านพร้อมเพย์", "เก็บเงินปลายทาง (COD)"]


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
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0)
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
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            conn.executemany("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
                             [("หมูยอเส้นเล็ก", 35, 50),
                              ("หมูยอเส้นใหญ่", 60, 50),
                              ("หมูยอพริกไทยดำ", 40, 50),
                              ("หมูยอพริกสด", 40, 50),
                              ("หมูยอหนังหมู", 40, 50)])
        if not conn.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone():
            h, s = hash_password("admin1234")
            conn.execute("INSERT INTO users (username, password_hash, salt, full_name, phone, role) "
                         "VALUES ('admin', ?, ?, 'เจ้าของร้าน', '0000000000', 'admin')", (h, s))


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


def sync_cart_prices(cart):
    """อัปเดตราคา/ชื่อในตะกร้าให้ตรงกับฐานข้อมูลล่าสุด (ลบสินค้าที่ไม่มีแล้วออก)"""
    with get_conn() as conn:
        for pid in list(cart):
            row = conn.execute("SELECT name, price FROM products WHERE id = ?", (pid,)).fetchone()
            if row is None:
                cart.pop(pid)
            else:
                cart[pid]["name"] = row["name"]
                cart[pid]["price"] = row["price"]


def get_setting(key, default=""):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def place_order(user_id, cart, method, address):
    """บันทึกคำสั่งซื้อใน transaction เดียว (ตัดสต็อกพร้อมกัน) คืนเลขที่ออเดอร์"""
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
#  ตัวช่วย UI
# =====================================================================
def center(win, w, h):
    win.update_idletasks()
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 3
    win.geometry(f"{w}x{h}+{x}+{y}")


def make_tree(parent, columns, height=12):
    """columns = [(key, หัวข้อ, ความกว้าง, anchor)]"""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                        height=height, selectmode="browse")
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


# =====================================================================
#  หน้าต่างเข้าสู่ระบบ + หน้าต่างย่อย สมัครสมาชิก / ลืมรหัสผ่าน
# =====================================================================
class LoginFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=25)
        self.app = app
        ttk.Label(self, text="ร้านค้า ขายหมูยออุบล", font=("", 18, "bold")).pack(pady=(0, 15))

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
        ttk.Button(self, text="🔑 เข้าสู่ระบบแอดมิน", command=lambda: AdminLoginWindow(app)).pack(fill="x")

        self.username.focus()
        self.password.bind("<Return>", lambda e: self.login())
        self.username.bind("<Return>", lambda e: self.password.focus())

    def login(self):
        user = authenticate(self.username.get().strip(), self.password.get())
        if not user:
            messagebox.showerror("เข้าสู่ระบบไม่สำเร็จ", "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
            self.password.delete(0, "end")
            return
        if user["role"] == "admin":
            messagebox.showinfo("บัญชีแอดมิน", "บัญชีแอดมินกรุณาใช้ปุ่ม 'เข้าสู่ระบบแอดมิน' ด้านล่าง")
            self.password.delete(0, "end")
            return
        self.app.user = dict(user)
        self.app.show_home()


class AdminLoginWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("เข้าสู่ระบบแอดมิน")
        self.transient(app)
        center(self, 320, 250)
        self.grab_set()
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="สำหรับเจ้าของร้าน", font=("", 13, "bold")).pack(pady=(0, 10))
        ttk.Label(body, text="ชื่อผู้ใช้แอดมิน").pack(anchor="w")
        self.username = ttk.Entry(body)
        self.username.pack(fill="x", pady=(0, 8))
        ttk.Label(body, text="รหัสผ่าน").pack(anchor="w")
        self.password = ttk.Entry(body, show="•")
        self.password.pack(fill="x", pady=(0, 12))
        ttk.Button(body, text="เข้าสู่ระบบ", command=self.submit).pack(fill="x")
        self.username.focus()
        self.username.bind("<Return>", lambda e: self.password.focus())
        self.password.bind("<Return>", lambda e: self.submit())

    def submit(self):
        user = authenticate(self.username.get().strip(), self.password.get())
        if not user or user["role"] != "admin":
            messagebox.showerror("เข้าสู่ระบบไม่สำเร็จ",
                                 "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง หรือไม่ใช่บัญชีแอดมิน", parent=self)
            self.password.delete(0, "end")
            return
        self.app.user = dict(user)
        self.destroy()
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
#  หน้าร้านสำหรับลูกค้า: ดูสินค้า / สั่งซื้อ
# =====================================================================
class ShopFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=10)
        self.app = app

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text=f"สวัสดี คุณ{app.user['full_name']}", font=("", 12, "bold")).pack(side="left")
        ttk.Button(top, text="ออกจากระบบ", command=app.show_login).pack(side="right")
        ttk.Button(top, text="ประวัติการสั่งซื้อ", command=lambda: HistoryWindow(app)).pack(side="right", padx=6)
        self.cart_btn = ttk.Button(top, command=self.open_cart)
        self.cart_btn.pack(side="right")

        search = ttk.Frame(self)
        search.pack(fill="x", pady=(0, 6))
        ttk.Label(search, text="ค้นหาสินค้า:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(search, textvariable=self.search_var, width=30).pack(side="left", padx=6)

        frame, self.tree = make_tree(self, [("name", "ชื่อสินค้า", 380, "w"),
                                            ("price", "ราคา (บาท)", 120, "e"),
                                            ("stock", "คงเหลือ", 100, "e")], height=14)
        frame.pack(fill="both", expand=True)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Label(bottom, text="จำนวน:").pack(side="left")
        self.qty = tk.IntVar(value=1)
        ttk.Spinbox(bottom, from_=1, to=999, textvariable=self.qty, width=6).pack(side="left", padx=6)
        ttk.Button(bottom, text="เพิ่มลงตะกร้า", command=self.add_to_cart).pack(side="left")
        ttk.Button(bottom, text="สั่งซื้อทันที", command=self.buy_now).pack(side="left", padx=6)

        self.refresh()

    def refresh(self):
        clear_tree(self.tree)
        like = f"%{self.search_var.get().strip()}%"
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM products WHERE name LIKE ? ORDER BY id", (like,)).fetchall()
        for r in rows:
            self.tree.insert("", "end", iid=str(r["id"]),
                             values=(r["name"], f"{r['price']:,.2f}", r["stock"]))
        self.update_cart_label()

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
        item = self.app.cart.setdefault(pid, {"name": p["name"], "price": p["price"], "qty": 0})
        item["price"] = p["price"]          # ใช้ราคาล่าสุดเสมอ
        item["qty"] += qty
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
        sync_cart_prices(self.app.cart)     # ดึงราคาล่าสุดจากฐานข้อมูลทุกครั้ง
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
        self.title("ชำระเงิน")
        self.transient(cart_window)
        center(self, 440, 540)
        self.grab_set()
        sync_cart_prices(app.cart)          # สรุปยอดด้วยราคาล่าสุด

        body = ttk.Frame(self, padding=15)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="สรุปรายการสั่งซื้อ", font=("", 12, "bold")).pack(anchor="w")
        total = 0
        for it in app.cart.values():
            sub = it["qty"] * it["price"]
            total += sub
            ttk.Label(body, text=f"  {it['name']}  x{it['qty']}  =  {sub:,.2f}").pack(anchor="w")
        self.total = total
        ttk.Label(body, text=f"ยอดที่ต้องชำระ: {total:,.2f} บาท",
                  font=("", 13, "bold")).pack(anchor="w", pady=(6, 10))

        ttk.Label(body, text="ที่อยู่จัดส่ง").pack(anchor="w")
        self.address = tk.Text(body, height=4, width=42)
        self.address.pack(fill="x", pady=(0, 10))

        ttk.Label(body, text="วิธีชำระเงิน").pack(anchor="w")
        self.method = tk.StringVar(value=PAYMENT_METHODS[0])
        for m in PAYMENT_METHODS:
            ttk.Radiobutton(body, text=m, value=m, variable=self.method,
                            command=self.update_info).pack(anchor="w")
        self.info = ttk.Label(body, wraplength=390, foreground="#555")
        self.info.pack(anchor="w", pady=8)
        self.update_info()

        ttk.Button(body, text="ยืนยันการสั่งซื้อ", command=self.confirm).pack(fill="x", pady=(8, 0))

    def update_info(self):
        if self.method.get() == PAYMENT_METHODS[0]:
            pp = get_setting("promptpay_id")
            if pp:
                self.info.config(text=f"โอนเงินเข้าพร้อมเพย์ {pp} แล้วแจ้งชำระกับทางร้าน "
                                      "ออเดอร์จะมีสถานะ 'รอชำระเงิน' จนกว่าร้านจะยืนยัน")
            else:
                self.info.config(text="ร้านยังไม่ได้ตั้งค่าพร้อมเพย์ กรุณาเลือกเก็บเงินปลายทาง หรือติดต่อร้าน")
        else:
            self.info.config(text="ชำระเงินสดกับพนักงานส่งของเมื่อได้รับสินค้า")

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
#  หน้าจอเจ้าของร้าน: จัดการสินค้า / ดูออเดอร์
# =====================================================================
class AdminFrame(ttk.Frame):
    STATUSES = ["รอชำระเงิน", "รอจัดส่ง", "จัดส่งแล้ว", "ยกเลิก"]

    def __init__(self, app):
        super().__init__(app, padding=10)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="ระบบจัดการร้าน (เจ้าของร้าน)", font=("", 13, "bold")).pack(side="left")
        ttk.Button(top, text="ออกจากระบบ", command=app.show_login).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        # --- แท็บสินค้า ---
        tab1 = ttk.Frame(nb, padding=8)
        nb.add(tab1, text="สินค้า / สต็อก")
        frame, self.ptree = make_tree(tab1, [("name", "ชื่อสินค้า", 340, "w"),
                                             ("price", "ราคา", 120, "e"),
                                             ("stock", "สต็อก", 100, "e")], height=12)
        frame.pack(fill="both", expand=True)
        row = ttk.Frame(tab1)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="เพิ่มสินค้า", command=self.add_product).pack(side="left")
        ttk.Button(row, text="แก้ราคา", command=self.edit_price).pack(side="left", padx=6)
        ttk.Button(row, text="เติมสต็อก", command=self.restock).pack(side="left")

        # --- แท็บออเดอร์ ---
        tab2 = ttk.Frame(nb, padding=8)
        nb.add(tab2, text="ออเดอร์")
        frame, self.otree = make_tree(tab2, [("id", "เลขที่", 60, "center"),
                                             ("date", "วันเวลา", 140, "w"),
                                             ("cust", "ลูกค้า", 130, "w"),
                                             ("total", "ยอดรวม", 90, "e"),
                                             ("method", "วิธีชำระ", 150, "w"),
                                             ("status", "สถานะ", 90, "w")], height=12)
        frame.pack(fill="both", expand=True)
        self.otree.bind("<<TreeviewSelect>>", self.show_address)
        self.addr_var = tk.StringVar()
        ttk.Label(tab2, textvariable=self.addr_var, wraplength=800).pack(anchor="w", pady=6)
        row = ttk.Frame(tab2)
        row.pack(fill="x")
        ttk.Label(row, text="เปลี่ยนสถานะเป็น:").pack(side="left")
        for s in self.STATUSES:
            ttk.Button(row, text=s, command=lambda s=s: self.set_status(s)).pack(side="left", padx=3)

        # --- แท็บตั้งค่าร้าน ---
        tab3 = ttk.Frame(nb, padding=15)
        nb.add(tab3, text="ตั้งค่าร้าน")
        ttk.Label(tab3, text="เบอร์พร้อมเพย์ของร้าน (แสดงให้ลูกค้าตอนเลือกโอนเงิน)").pack(anchor="w")
        self.pp_var = tk.StringVar(value=get_setting("promptpay_id"))
        ttk.Entry(tab3, textvariable=self.pp_var, width=30).pack(anchor="w", pady=6)
        ttk.Button(tab3, text="บันทึก", command=self.save_promptpay).pack(anchor="w")

        self.refresh()

    def refresh(self):
        clear_tree(self.ptree)
        clear_tree(self.otree)
        with get_conn() as conn:
            for r in conn.execute("SELECT * FROM products ORDER BY id"):
                self.ptree.insert("", "end", iid=str(r["id"]),
                                  values=(r["name"], f"{r['price']:,.2f}", r["stock"]))
            for r in conn.execute("""SELECT o.*, u.full_name FROM orders o
                                     JOIN users u ON u.id = o.user_id ORDER BY o.id DESC"""):
                self.otree.insert("", "end", iid=str(r["id"]),
                                  values=(r["id"], r["created_at"].replace("T", " "), r["full_name"],
                                          f"{r['total']:,.2f}", r["payment_method"], r["status"]))

    def save_promptpay(self):
        pp = self.pp_var.get().strip()
        if not pp:
            return messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอกเบอร์พร้อมเพย์")
        set_setting("promptpay_id", pp)
        messagebox.showinfo("สำเร็จ", "บันทึกเรียบร้อย")

    def add_product(self):
        name = simpledialog.askstring("เพิ่มสินค้า", "ชื่อสินค้า:", parent=self)
        if not name or not name.strip():
            return
        price = simpledialog.askfloat("เพิ่มสินค้า", "ราคา (บาท):", parent=self, minvalue=0)
        stock = simpledialog.askinteger("เพิ่มสินค้า", "จำนวนสต็อก:", parent=self, minvalue=0)
        if price is None or stock is None:
            return
        try:
            with get_conn() as conn:
                conn.execute("INSERT INTO products (name, price, stock) VALUES (?, ?, ?)",
                             (name.strip(), price, stock))
        except sqlite3.IntegrityError:
            messagebox.showerror("ผิดพลาด", "มีสินค้าชื่อนี้แล้ว")
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


# =====================================================================
#  โปรแกรมหลัก
# =====================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ร้านหมูยออุบล")
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
        self._switch(LoginFrame, 360, 390)

    def show_home(self):
        if self.user["role"] == "admin":
            self._switch(AdminFrame, 900, 560)
        else:
            self._switch(ShopFrame, 720, 520)


if __name__ == "__main__":
    init_db()
    print("ฐานข้อมูลอยู่ที่:", DB_NAME)
    App().mainloop()

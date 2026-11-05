import os
import sqlite3
import asyncio
import aiohttp
import re
from pypdf import PdfReader
import flet as ft

# بيانات محفظة شام كاش والـ API
WALLET_ID = "5c3d499c015d7335eb5474e832d06ff3"
SHAMCASH_API_URL = f"https://api-shamcash.com/api/v1/wallets/shamcash/{WALLET_ID}/transactions?direction=in"
SHAMCASH_API_TOKEN = "sk_8aa2518852cb96ca54da04084d7cbc80b9fd9a882b3607573ad5ec64e1043ef8"

# أسعار الفئات (بالليرة السورية)
CATEGORY_PRICES = {
    "5G": 80,
    "10G": 150,
    "20G": 270,
    "30G": 350,
    "50G": 500,
    "100G": 900
}

USER_ID = 1  # معرف المستخدم المحلي
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

# تحديد مسار قاعدة البيانات بدقة لتجنب قيود الأندرويد
if os.environ.get("RENDER") or (os.path.exists("/data") and os.access("/data", os.W_OK)):
    DB_PATH = "/data/shop.db"
else:
    DB_PATH = "shop.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            is_sold INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (USER_ID,))
    conn.commit()
    conn.close()

def get_user_balance():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (USER_ID,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0.0

def import_cards_from_pdf(pdf_path, target_category):
    if not pdf_path or not os.path.exists(pdf_path):
        return 0
    
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
                
        all_numbers = re.findall(r'\b\d{4,8}\b', text)
        added_count = 0
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        for i in range(0, len(all_numbers) - 1, 2):
            usr = all_numbers[i]
            pwd = all_numbers[i+1]
            
            cursor.execute("SELECT id FROM cards WHERE category = ? AND username = ? AND password = ?", (target_category, usr, pwd))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO cards (category, username, password, is_sold) VALUES (?, ?, ?, 0)", (target_category, usr, pwd))
                added_count += 1
                
        conn.commit()
        conn.close()
        return added_count
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return 0

async def verify_shamcash_transaction(tx_id: str) -> dict:
    headers = {
        "Authorization": f"Bearer {SHAMCASH_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(SHAMCASH_API_URL, headers=headers, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    transactions = []
                    if isinstance(data, list):
                        transactions = data
                    elif isinstance(data, dict):
                        transactions = data.get("data", data.get("transactions", data.get("result", [])))
                        if isinstance(transactions, dict):
                            transactions = transactions.get("data", [])

                    for tx in transactions:
                        t_id = str(tx.get("id", tx.get("tranId", tx.get("transaction_id", tx.get("reference", "")))))
                        if t_id == str(tx_id):
                            amount = float(tx.get("amount", 0))
                            return {"status": True, "amount": amount}
        return {"status": False, "amount": 0}
    except Exception as e:
        return {"status": False, "amount": 0}

def main(page: ft.Page):
    page.title = "SYRIA NET"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 15

    current_balance = get_user_balance()

    balance_text = ft.Text(
        f"الرصيد: {current_balance:,.0f} ل.س",
        size=18,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.GREEN_400
    )

    trans_id_input = ft.TextField(
        label="رقم عملية التحويل (Transaction ID)",
        border_color=ft.Colors.BLUE_400
    )
    
    status_msg = ft.Text("", size=14)
    admin_status_msg = ft.Text("", size=14)
    login_status_msg = ft.Text("", size=14, color=ft.Colors.RED_400)

    # 1. نافذة إظهار بيانات البطاقات عند الشراء
    card_title_text = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    card_user_text = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_200)
    card_pass_text = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.YELLOW)
    
    def close_card_dialog(e):
        card_dialog.open = False
        page.update()

    card_dialog = ft.AlertDialog(
        title=ft.Text("✅ تم الشراء بنجاح!"),
        content=ft.Column([
            card_title_text,
            ft.Text("بيانات الحساب الخاص بك:"),
            ft.Container(
                content=ft.Column([
                    card_user_text,
                    card_pass_text,
                ], spacing=5),
                padding=15,
                bgcolor="#1e1e1e",
                border_radius=8,
                alignment="center"
            ),
            ft.Text("شكراً لاستخدامك خدمات SYRIA NET 💙", size=12, color=ft.Colors.GREY)
        ], tight=True, spacing=10),
        actions=[
            ft.TextButton("إغلاق", on_click=close_card_dialog)
        ]
    )

    # 2. نافذة تنبيه العامة (للأخطاء ونفاد المخزون)
    alert_msg_text = ft.Text("", size=15)
    
    def close_alert_dialog(e):
        alert_dialog.open = False
        page.update()

    alert_dialog = ft.AlertDialog(
        title=ft.Text("تنبيه"),
        content=alert_msg_text,
        actions=[ft.TextButton("حسناً", on_click=close_alert_dialog)]
    )

    def show_alert(title, text):
        alert_dialog.title.value = title
        alert_msg_text.value = text
        alert_dialog.open = True
        page.update()

    # 3. واجهة الشحن عبر شام كاش
    async def handle_deposit_async(e):
        tx_id = trans_id_input.value.strip()
        if not tx_id:
            status_msg.value = "⚠️ الرجاء إدخال رقم العملية أولاً."
            status_msg.color = ft.Colors.RED_400
            page.update()
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT transaction_id FROM transactions WHERE transaction_id = ?", (tx_id,))
        if cursor.fetchone():
            conn.close()
            status_msg.value = "❌ رقم المعاملة هذا تم استخدامه مسبقاً!"
            status_msg.color = ft.Colors.RED_400
            page.update()
            return
        conn.close()

        status_msg.value = "⏳ جاري التحقق من صحة المعاملة..."
        status_msg.color = ft.Colors.BLUE_400
        page.update()

        result = await verify_shamcash_transaction(tx_id)

        if result["status"]:
            amount = result["amount"]
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, USER_ID))
            cursor.execute("INSERT INTO transactions (transaction_id, user_id, amount) VALUES (?, ?, ?)", (tx_id, USER_ID, amount))
            conn.commit()
            conn.close()

            new_bal = get_user_balance()
            balance_text.value = f"الرصيد: {new_bal:,.0f} ل.س"
            status_msg.value = f"✅ تم تأكيد المعاملة وإضافة {amount:,.0f} ل.س بنجاح!"
            status_msg.color = ft.Colors.GREEN_400
            trans_id_input.value = ""
        else:
            status_msg.value = "❌ رقم العملية خطأ أو غير موجود في شبكة شام كاش!"
            status_msg.color = ft.Colors.RED_400
        page.update()

    def handle_deposit(e):
        asyncio.create_task(handle_deposit_async(e))

    deposit_dialog = ft.AlertDialog(
        title=ft.Text("➕ شحن الرصيد عبر شام كاش"),
        content=ft.Column([
            ft.Text("رقم محفظتنا للاستلام:"),
            ft.Container(
                content=ft.Text(WALLET_ID, color=ft.Colors.YELLOW, weight=ft.FontWeight.BOLD, selectable=True),
                padding=10,
                bgcolor="#2d2d2d",
                border_radius=8,
            ),
            trans_id_input,
            status_msg,
        ], tight=True, spacing=10),
        actions=[
            ft.TextButton("إلغاء", on_click=lambda e: setattr(deposit_dialog, 'open', False) or page.update()),
            ft.FilledButton("تأكيد الشحن", on_click=handle_deposit),
        ]
    )

    # 4. إعداد FilePicker لرفع ملفات الـ PDF
    category_dropdown = ft.Dropdown(
        label="اختر الفئة المستهدفة للرفع",
        options=[ft.dropdown.Option(cat) for cat in CATEGORY_PRICES.keys()],
        width=250
    )

    def on_file_picked(e: ft.FilePickerResultEvent):
        if e.files and len(e.files) > 0:
            file_path = e.files[0].path
            cat = category_dropdown.value
            if not cat:
                admin_status_msg.value = "⚠️ يرجى اختيار الفئة أولاً من القائمة!"
                admin_status_msg.color = ft.Colors.RED_400
                page.update()
                return
            
            added = import_cards_from_pdf(file_path, cat)
            admin_status_msg.value = f"✅ تمت إضافة {added} بطاقة بنجاح إلى فئة {cat}!"
            admin_status_msg.color = ft.Colors.GREEN_400
            refresh_packages()
            page.update()

    file_picker = ft.FilePicker(on_result=on_file_picked)

    admin_dialog = ft.AlertDialog(
        title=ft.Text("⚙️ لوحة تحكم المشرف - رفع بطاقات PDF"),
        content=ft.Column([
            ft.Text("اختر الفئة ثم اضغط رفع ملف لاختيار ملف الـ PDF:"),
            category_dropdown,
            admin_status_msg,
        ], tight=True, spacing=15),
        actions=[
            ft.FilledButton("📁 اختيار ملف PDF ورفع", on_click=lambda e: file_picker.pick_files(allow_multiple=False)),
            ft.TextButton("إغلاق", on_click=lambda e: setattr(admin_dialog, 'open', False) or page.update()),
        ]
    )

    # 5. نافذة تسجيل دخول المشرف
    admin_user_input = ft.TextField(label="اسم المستخدم", value="admin")
    admin_pass_input = ft.TextField(label="كلمة المرور", password=True, can_reveal_password=True)

    def check_admin_login(e):
        if admin_user_input.value == ADMIN_USER and admin_pass_input.value == ADMIN_PASS:
            login_dialog.open = False
            admin_status_msg.value = ""
            admin_dialog.open = True
            page.update()
        else:
            login_status_msg.value = "❌ اسم المستخدم أو كلمة المرور غير صحيحة!"
            page.update()

    login_dialog = ft.AlertDialog(
        title=ft.Text("🔒 تسجيل دخول المشرف"),
        content=ft.Column([
            admin_user_input,
            admin_pass_input,
            login_status_msg
        ], tight=True, spacing=10),
        actions=[
            ft.TextButton("إلغاء", on_click=lambda e: setattr(login_dialog, 'open', False) or page.update()),
            ft.FilledButton("دخول", on_click=check_admin_login)
        ]
    )

    # إضافة كافة العناصر وعنصر الاختيار لـ overlay
    page.overlay.append(file_picker)
    page.overlay.append(deposit_dialog)
    page.overlay.append(card_dialog)
    page.overlay.append(admin_dialog)
    page.overlay.append(login_dialog)
    page.overlay.append(alert_dialog)

    def open_deposit(e):
        status_msg.value = ""
        deposit_dialog.open = True
        page.update()

    def open_admin(e):
        login_status_msg.value = ""
        admin_pass_input.value = ""
        login_dialog.open = True
        page.update()

    # 6. منطق شراء الباقات مع التنبيهات الصريحة
    def buy_package(cat_name, price):
        bal = get_user_balance()
        
        # فحص الرصيد أولاً
        if bal < price:
            show_alert("رصيد غير كافٍ", f"❌ عذراً، رصيدك غير كافٍ لشراء فئة {cat_name}.\nتحتاج إلى {price:,.0f} ل.س بينما رصيدك الحالي {bal:,.0f} ل.س.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password FROM cards WHERE category = ? AND is_sold = 0 LIMIT 1", (cat_name,))
        card = cursor.fetchone()

        if card:
            card_id, card_user, card_pass = card
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, USER_ID))
            cursor.execute("UPDATE cards SET is_sold = 1 WHERE id = ?", (card_id,))
            conn.commit()
            conn.close()

            new_bal = get_user_balance()
            balance_text.value = f"الرصيد: {new_bal:,.0f} ل.س"
            
            card_title_text.value = f"📦 فئة {cat_name}"
            card_user_text.value = f"👤 اسم المستخدم: {card_user}"
            card_pass_text.value = f"🔑 كلمة المرور: {card_pass}"
            card_dialog.open = True
            refresh_packages()
        else:
            conn.close()
            show_alert("نفاد المخزون", f"⚠️ عذراً، لا يوجد بطاقات متاحة حالياً لفئة {cat_name}.\nنفذ المخزون من النظام!")

    packages_column = ft.Column(spacing=10)

    def refresh_packages():
        packages_column.controls.clear()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for cat, price in CATEGORY_PRICES.items():
            cursor.execute("SELECT COUNT(*) FROM cards WHERE category = ? AND is_sold = 0", (cat,))
            available_count = cursor.fetchone()[0]
            
            packages_column.controls.append(ft.Card(
                content=ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(f"فئة {cat}", size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(f"السعر: {price} ل.س | (المتوفر: {available_count})", size=12, color=ft.Colors.GREY_400),
                        ]),
                        ft.FilledButton("شراء", on_click=lambda e, c=cat, p=price: buy_package(c, p))
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=15
                )
            ))
        conn.close()
        if page:
            page.update()

    refresh_packages()

    page.add(
        ft.Row([
            balance_text,
            ft.Row([
                ft.FilledButton("⚙️ المشرف", on_click=open_admin, bgcolor=ft.Colors.ORANGE_800),
                ft.FilledButton("➕ شحن الرصيد", on_click=open_deposit),
            ], spacing=10)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Divider(),
        ft.Text("🛒 باقات الإنترنت المتاحة:", size=18, weight=ft.FontWeight.BOLD),
        packages_column
    )

if __name__ == '__main__':
    init_db()
    ft.run(main)
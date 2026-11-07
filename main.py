import os
import sqlite3
import asyncio
import aiohttp
import re
import urllib.parse
from pypdf import PdfReader
import io

# رابط السيرفر الخاص بك على منصة Render جاهز ومربوط
SERVER_URL = "https://kinnawy-app-v1.onrender.com"

# بيانات محفظة شام كاش والـ API الأصلية الصحيحة 100%
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

USER_ID = 1
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

# تحديد مسار قاعدة البيانات بدقة
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

def get_user_balance() -> float:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (USER_ID,))
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row else 0.0

def extract_cards_from_pdf_bytes(file_bytes):
    if not file_bytes:
        return []
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        all_numbers = re.findall(r'\b\d{4,8}\b', text)
        pairs = []
        for i in range(0, len(all_numbers) - 1, 2):
            pairs.append((all_numbers[i], all_numbers[i+1]))
        return pairs
    except Exception as e:
        print(f"Error reading PDF bytes: {e}")
        return []

def save_cards_to_db(pairs, target_category) -> int:
    if not pairs:
        return 0
    added_count = 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for usr, pwd in pairs:
        usr, pwd = str(usr), str(pwd)
        cursor.execute(
            "SELECT id FROM cards WHERE category = ? AND username = ? AND password = ?",
            (target_category, usr, pwd)
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO cards (category, username, password, is_sold) VALUES (?, ?, ?, 0)",
                (target_category, usr, pwd)
            )
            added_count += 1
    conn.commit()
    conn.close()
    return added_count

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
                        t_id = str(tx.get("id", tx.get("tranId", tx.get("transaction_id", tx.get("reference", ""))))).strip()
                        if t_id == str(tx_id).strip():
                            amount = float(tx.get("amount", 0))
                            return {"status": True, "amount": amount}
        return {"status": False, "amount": 0}
    except Exception as e:
        print(f"ShamCash API Error: {e}")
        return {"status": False, "amount": 0}

# ==================== تطبيق الموبايل (Flet) ====================
def run_mobile_app():
    import flet as ft

    def main(page: ft.Page):
        page.title = "SYRIA NET"
        page.vertical_alignment = ft.MainAxisAlignment.START
        page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        page.padding = 15
        page.scroll = ft.ScrollMode.AUTO

        # خدمات Flet الحديثة (بدون وضعها في page.overlay لمنع الشريط الأحمر)
        file_picker = ft.FilePicker()
        clipboard = ft.Clipboard()
        url_launcher = ft.UrlLauncher()

        current_balance = get_user_balance()

        balance_text = ft.Text(
            f"الرصيد: {current_balance:,.0f} ل.س",
            size=18,
            weight=ft.FontWeight.BOLD,
            color="#66BB6A"
        )

        trans_id_input = ft.TextField(
            label="رقم عملية التحويل (Transaction ID)"
        )

        status_msg = ft.Text("", size=14)
        admin_status_msg = ft.Text("", size=14)
        login_status_msg = ft.Text("", size=14, color="#EF5350")

        # دوال إغلاق النوافذ المنبثقة
        def close_alert_dialog(e=None):
            alert_dialog.open = False
            page.update()

        def close_card_dialog(e=None):
            card_dialog.open = False
            page.update()

        def close_deposit_dialog(e=None):
            deposit_dialog.open = False
            page.update()

        def close_admin_dialog(e=None):
            admin_dialog.open = False
            page.update()

        alert_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("تنبيه"),
            content=ft.Text("", size=15),
            actions=[ft.TextButton("حسناً", on_click=close_alert_dialog)],
            on_dismiss=close_alert_dialog
        )

        def show_alert(title, text):
            alert_dialog.title.value = title
            alert_dialog.content.value = text
            alert_dialog.open = True
            page.update()

        card_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("✅ تم الشراء بنجاح!"),
            content=ft.Text("جاري التحميل..."),
            actions=[ft.TextButton("إغلاق", on_click=close_card_dialog)],
            on_dismiss=close_card_dialog
        )

        # مزامنة البطاقات مع سيرفر Render في الخلفية إن وجد
        async def sync_cards_from_server():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{SERVER_URL}/api/cards", timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            cards_by_cat = data.get("cards", {})
                            for cat, pairs in cards_by_cat.items():
                                save_cards_to_db(pairs, cat)
                            refresh_packages()
            except Exception:
                pass

        # 1. واجهة الشحن المباشر عبر شام كاش
        async def handle_deposit(e):
            tx_id = trans_id_input.value.strip()
            if not tx_id:
                status_msg.value = "⚠️ الرجاء إدخال رقم العملية أولاً."
                status_msg.color = "#EF5350"
                page.update()
                return

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT transaction_id FROM transactions WHERE transaction_id = ?", (tx_id,))
            if cursor.fetchone():
                conn.close()
                status_msg.value = "❌ رقم المعاملة هذا تم استخدامه مسبقاً!"
                status_msg.color = "#EF5350"
                page.update()
                return
            conn.close()

            status_msg.value = "⏳ جاري التحقق من صحة المعاملة عبر شام كاش..."
            status_msg.color = "#42A5F5"
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
                status_msg.color = "#66BB6A"
                trans_id_input.value = ""
            else:
                status_msg.value = "❌ رقم العملية خطأ أو غير موجود في شبكة شام كاش!"
                status_msg.color = "#EF5350"
            page.update()

        deposit_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("➕ شحن الرصيد عبر شام كاش"),
            content=ft.Column([
                ft.Text("رقم محفظتنا للاستلام:"),
                ft.Container(
                    content=ft.Text(WALLET_ID, color="#FFEB3B", weight=ft.FontWeight.BOLD, selectable=True),
                    padding=10,
                    bgcolor="#2d2d2d",
                    border_radius=8,
                ),
                trans_id_input,
                status_msg,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("إلغاء", on_click=close_deposit_dialog),
                ft.FilledButton("تأكيد الشحن", on_click=handle_deposit),
            ],
            on_dismiss=close_deposit_dialog
        )

        # 2. نافذة المشرف الموحدة (تسجيل الدخول + رفع ملف PDF)
        admin_user_input = ft.TextField(label="اسم المستخدم", value="admin")
        admin_pass_input = ft.TextField(label="كلمة المرور", password=True, can_reveal_password=True)

        category_dropdown = ft.Dropdown(
            label="اختر الفئة المستهدفة للرفع",
            options=[ft.dropdown.Option(cat) for cat in CATEGORY_PRICES.keys()],
            width=250
        )

        async def trigger_file_selection(e):
            cat = category_dropdown.value
            if not cat:
                admin_status_msg.value = "⚠️ يرجى اختيار الفئة أولاً من القائمة!"
                admin_status_msg.color = "#EF5350"
                page.update()
                return

            admin_status_msg.value = "⏳ جاري فتح مستعرض الملفات..."
            admin_status_msg.color = "#42A5F5"
            page.update()

            try:
                files = await file_picker.pick_files(
                    allow_multiple=False,
                    allowed_extensions=["pdf"],
                    file_type=ft.FilePickerFileType.CUSTOM,
                    with_data=True
                )
                if files and len(files) > 0:
                    file_info = files[0]
                    file_bytes = file_info.bytes

                    if not file_bytes and getattr(file_info, "path", None):
                        with open(file_info.path, "rb") as f:
                            file_bytes = f.read()

                    if file_bytes:
                        pairs = extract_cards_from_pdf_bytes(file_bytes)
                        added = save_cards_to_db(pairs, cat)

                        # إرسال نسخة من البطاقات إلى سيرفر Render في الخلفية
                        try:
                            async with aiohttp.ClientSession() as session:
                                await session.post(
                                    f"{SERVER_URL}/api/admin/upload",
                                    json={
                                        "admin_user": ADMIN_USER,
                                        "admin_pass": ADMIN_PASS,
                                        "category": cat,
                                        "cards": pairs
                                    },
                                    timeout=15
                                )
                        except Exception:
                            pass

                        admin_status_msg.value = f"✅ تمت إضافة {added} بطاقة بنجاح إلى فئة {cat}!"
                        admin_status_msg.color = "#66BB6A"
                        refresh_packages()
                    else:
                        admin_status_msg.value = "❌ تعذر قراءة محتوى ملف الـ PDF."
                        admin_status_msg.color = "#EF5350"
                else:
                    admin_status_msg.value = "⚠️ لم يتم اختيار أي ملف."
                    admin_status_msg.color = "#FFA726"
            except Exception as ex:
                admin_status_msg.value = f"❌ خطأ أثناء اختيار الملف: {ex}"
                admin_status_msg.color = "#EF5350"

            page.update()

        login_view_content = ft.Column([
            admin_user_input,
            admin_pass_input,
            login_status_msg
        ], tight=True, spacing=10)

        upload_view_content = ft.Column([
            ft.Text("اختر الفئة ثم اضغط لاختيار ملف الـ PDF من جهازك:"),
            category_dropdown,
            ft.FilledButton(
                "📁 اختيار ملف PDF ورفع",
                on_click=trigger_file_selection
            ),
            admin_status_msg,
        ], tight=True, spacing=15)

        def check_admin_login(e):
            if admin_user_input.value == ADMIN_USER and admin_pass_input.value == ADMIN_PASS:
                admin_status_msg.value = ""
                admin_dialog.title = ft.Text("⚙️ لوحة تحكم المشرف - رفع بطاقات PDF")
                admin_dialog.content = upload_view_content
                admin_dialog.actions = [
                    ft.TextButton("إغلاق", on_click=close_admin_dialog),
                ]
                page.update()
            else:
                login_status_msg.value = "❌ اسم المستخدم أو كلمة المرور غير صحيحة!"
                page.update()

        admin_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("🔒 تسجيل دخول المشرف"),
            content=login_view_content,
            actions=[
                ft.TextButton("إلغاء", on_click=close_admin_dialog),
                ft.FilledButton("دخول", on_click=check_admin_login)
            ],
            on_dismiss=close_admin_dialog
        )

        # إضافة جميع النوافذ الحوارية الأربعة إلى الـ overlay لضمان عمل جميع الأزرار والتنبيهات
        page.overlay.append(deposit_dialog)
        page.overlay.append(card_dialog)
        page.overlay.append(admin_dialog)
        page.overlay.append(alert_dialog)
        page.update()

        def open_deposit(e):
            status_msg.value = ""
            deposit_dialog.open = True
            page.update()

        def open_admin(e):
            login_status_msg.value = ""
            admin_pass_input.value = ""
            admin_dialog.title = ft.Text("🔒 تسجيل دخول المشرف")
            admin_dialog.content = login_view_content
            admin_dialog.actions = [
                ft.TextButton("إلغاء", on_click=close_admin_dialog),
                ft.FilledButton("دخول", on_click=check_admin_login)
            ]
            admin_dialog.open = True
            page.update()

        async def notify_server_sold(cat_name, card_user, card_pass):
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        f"{SERVER_URL}/api/mark_sold",
                        json={"category": cat_name, "username": card_user, "password": card_pass},
                        timeout=10
                    )
            except Exception:
                pass

        # 3. منطق شراء الباقات (يعمل فوراً وبسلاسة 100%)
        def buy_package(cat_name, price):
            bal = get_user_balance()

            if bal < price:
                show_alert(
                    "رصيد غير كافٍ",
                    f"❌ عذراً، رصيدك غير كافٍ لشراء فئة {cat_name}.\nتحتاج إلى {price:,.0f} ل.س بينما رصيدك الحالي {bal:,.0f} ل.س."
                )
                return

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, username, password FROM cards WHERE category = ? AND is_sold = 0 LIMIT 1",
                (cat_name,)
            )
            card = cursor.fetchone()

            if card:
                card_id, card_user, card_pass = card
                cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, USER_ID))
                cursor.execute("DELETE FROM cards WHERE id = ?", (card_id,))
                conn.commit()
                conn.close()

                page.run_task(notify_server_sold, cat_name, card_user, card_pass)

                new_bal = get_user_balance()
                balance_text.value = f"الرصيد: {new_bal:,.0f} ل.س"

                card_details_text = (
                    f"📦 الفئة: {cat_name}\n"
                    f"👤 اسم المستخدم: {card_user}\n"
                    f"🔑 كلمة المرور: {card_pass}\n"
                    f"💰 الرصيد المتبقي: {new_bal:,.0f} ل.س\n"
                    f"شكراً لاستخدامك متجر syria net ❤️"
                )

                copy_feedback = ft.Text("", size=13, color="#66BB6A", weight=ft.FontWeight.BOLD)

                async def copy_info(e):
                    try:
                        await clipboard.set(card_details_text)
                        copy_feedback.value = "✅ تم نسخ بيانات البطاقة إلى الحافظة!"
                    except Exception:
                        copy_feedback.value = "⚠️ اضغط مطولاً على الرقم لنسخه يدوياً."
                    page.update()

                async def share_whatsapp(e):
                    encoded_msg = urllib.parse.quote(f"تفاصيل بطاقة إنترنت من SYRIA NET:\n{card_details_text}")
                    url = f"https://api.whatsapp.com/send?text={encoded_msg}"
                    try:
                        await url_launcher.launch_url(url)
                    except Exception:
                        pass

                card_dialog.title = ft.Text("✅ تم الشراء بنجاح!")
                card_dialog.content = ft.Column([
                    ft.Text(f"📦 الفئة: {cat_name}", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(f"👤 اسم المستخدم: {card_user}", size=16, weight=ft.FontWeight.BOLD, color="#2196F3", selectable=True),
                    ft.Text(f"🔑 كلمة المرور: {card_pass}", size=16, weight=ft.FontWeight.BOLD, color="#F44336", selectable=True),
                    ft.Divider(),
                    ft.Text(f"💰 رصيدك المتبقي: {new_bal:,.0f} ل.س", size=16, weight=ft.FontWeight.BOLD, color="#4CAF50"),
                    copy_feedback,
                    ft.Text("شكراً لاستخدامك متجر syria net ❤️", size=12, color="#9E9E9E")
                ], tight=True, spacing=10)

                card_dialog.actions = [
                    ft.FilledButton("📋 نسخ", on_click=copy_info),
                    ft.FilledButton("📲 واتساب", on_click=share_whatsapp),
                    ft.TextButton("إغلاق", on_click=close_card_dialog)
                ]

                card_dialog.open = True
                refresh_packages()
                page.update()
            else:
                conn.close()
                show_alert(
                    "نفاد المخزون",
                    f"⚠️ عذراً، لا يوجد بطاقات متاحة حالياً لفئة {cat_name}.\nنفذ المخزون من النظام!"
                )

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
                                ft.Text(f"السعر: {price} ل.س | (المتوفر: {available_count})", size=12, color="#9E9E9E"),
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
                    ft.FilledButton("⚙️ المشرف", on_click=open_admin),
                    ft.FilledButton("➕ شحن الرصيد", on_click=open_deposit),
                ], spacing=10)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Divider(),
            ft.Row([
                ft.Text("🛒 باقات الإنترنت المتاحة:", size=18, weight=ft.FontWeight.BOLD),
                ft.TextButton("🔄 تحديث", on_click=lambda e: page.run_task(sync_cards_from_server))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            packages_column
        )

        page.run_task(sync_cards_from_server)

    ft.run(main)

# ==================== خادم Render لمزامنة البطاقات ====================
def run_render_server():
    from aiohttp import web

    async def handle_home(request):
        return web.Response(text="Syria Net Server is Running!")

    async def handle_get_cards(request):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        result = {}
        for cat in CATEGORY_PRICES.keys():
            cursor.execute("SELECT username, password FROM cards WHERE category = ? AND is_sold = 0", (cat,))
            result[cat] = cursor.fetchall()
        conn.close()
        return web.json_response({"status": True, "cards": result})

    async def handle_admin_upload(request):
        data = await request.json()
        if data.get("admin_user") != ADMIN_USER or data.get("admin_pass") != ADMIN_PASS:
            return web.json_response({"status": False})
        cat = data.get("category")
        pairs = data.get("cards", [])
        added = save_cards_to_db(pairs, cat)
        return web.json_response({"status": True, "added": added})

    async def handle_mark_sold(request):
        data = await request.json()
        cat = data.get("category")
        usr = str(data.get("username", ""))
        pwd = str(data.get("password", ""))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cards WHERE category = ? AND username = ? AND password = ?", (cat, usr, pwd))
        conn.commit()
        conn.close()
        return web.json_response({"status": True})

    app = web.Application()
    app.router.add_get("/", handle_home)
    app.router.add_get("/api/cards", handle_get_cards)
    app.router.add_post("/api/admin/upload", handle_admin_upload)
    app.router.add_post("/api/mark_sold", handle_mark_sold)

    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == '__main__':
    init_db()
    if os.environ.get("RENDER"):
        run_render_server()
    else:
        run_mobile_app()
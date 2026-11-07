import os
import sqlite3
import uuid
import aiohttp
import re
import urllib.parse
from pypdf import PdfReader
import io
import flet as ft

# 🔗 ضع رابط سيرفرك على منصة Render هنا (بدون / في النهاية)
SERVER_URL = "https://kinnawy-app-v1.onrender.com"
WALLET_ID = "5c3d499c015d7335eb5474e832d06ff3"

CATEGORY_PRICES = {
    "5G": 80,
    "10G": 150,
    "20G": 270,
    "30G": 350,
    "50G": 500,
    "100G": 900
}

ADMIN_USER = "admin"
ADMIN_PASS = "123456"

LOCAL_DB = "device_info.db"

def get_device_user_id() -> str:
    try:
        conn = sqlite3.connect(LOCAL_DB)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS device (id TEXT PRIMARY KEY)")
        cursor.execute("SELECT id FROM device LIMIT 1")
        row = cursor.fetchone()
        if row:
            dev_id = row[0]
        else:
            dev_id = uuid.uuid4().hex
            cursor.execute("INSERT INTO device (id) VALUES (?)", (dev_id,))
            conn.commit()
        conn.close()
        return dev_id
    except Exception:
        return "local_user_1"

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
            pairs.append([all_numbers[i], all_numbers[i+1]])
        return pairs
    except Exception:
        return []

def main(page: ft.Page):
    page.title = "SYRIA NET"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.padding = 15
    page.scroll = ft.ScrollMode.AUTO

    user_id = get_device_user_id()

    file_picker = ft.FilePicker()
    clipboard = ft.Clipboard()
    url_launcher = ft.UrlLauncher()

    balance_text = ft.Text("الرصيد: جاري الاتصال...", size=18, weight=ft.FontWeight.BOLD, color="#66BB6A")
    trans_id_input = ft.TextField(label="رقم عملية التحويل (Transaction ID)")
    status_msg = ft.Text("", size=14)
    admin_status_msg = ft.Text("", size=14)
    login_status_msg = ft.Text("", size=14, color="#EF5350")

    stock_counts = {cat: 0 for cat in CATEGORY_PRICES.keys()}
    packages_column = ft.Column(spacing=10)

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

    alert_dialog = ft.AlertDialog(modal=True, title=ft.Text("تنبيه"), content=ft.Text("", size=15), actions=[ft.TextButton("حسناً", on_click=close_alert_dialog)])
    
    def show_alert(title, text):
        alert_dialog.title.value = title
        alert_dialog.content.value = text
        alert_dialog.open = True
        page.update()

    card_dialog = ft.AlertDialog(modal=True, title=ft.Text("✅ تم الشراء بنجاح!"), content=ft.Text("جاري التحميل..."), actions=[ft.TextButton("إغلاق", on_click=close_card_dialog)])

    async def fetch_server_status():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{SERVER_URL}/api/status?user_id={user_id}", timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        bal = data.get("balance", 0)
                        balance_text.value = f"الرصيد: {bal:,.0f} ل.س"
                        srv_stock = data.get("stock", {})
                        for c in CATEGORY_PRICES.keys():
                            stock_counts[c] = srv_stock.get(c, 0)
                        render_packages_ui()
        except Exception:
            balance_text.value = "الرصيد: غير متصل بالسيرفر"
            page.update()

    async def handle_deposit(e):
        tx_id = trans_id_input.value.strip()
        if not tx_id:
            status_msg.value = "⚠️ الرجاء إدخال رقم العملية أولاً."
            status_msg.color = "#EF5350"
            page.update()
            return

        status_msg.value = "⏳ جاري التحقق من المعاملة..."
        status_msg.color = "#42A5F5"
        page.update()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{SERVER_URL}/api/deposit", json={"user_id": user_id, "tx_id": tx_id}, timeout=20) as resp:
                    data = await resp.json()
                    if data.get("status"):
                        new_bal = data.get("balance", 0)
                        balance_text.value = f"الرصيد: {new_bal:,.0f} ل.س"
                        status_msg.value = data.get("message", "✅ تم الشحن بنجاح!")
                        status_msg.color = "#66BB6A"
                        trans_id_input.value = ""
                    else:
                        status_msg.value = data.get("message", "❌ فشل التحقق.")
                        status_msg.color = "#EF5350"
        except Exception as ex:
            status_msg.value = f"❌ خطأ اتصال: {ex}"
            status_msg.color = "#EF5350"
        page.update()

    deposit_dialog = ft.AlertDialog(modal=True, title=ft.Text("➕ شحن الرصيد عبر شام كاش"), content=ft.Column([
        ft.Text("رقم محفظتنا للاستلام:"),
        ft.Container(content=ft.Text(WALLET_ID, color="#FFEB3B", weight=ft.FontWeight.BOLD, selectable=True), padding=10, bgcolor="#2d2d2d", border_radius=8),
        trans_id_input, status_msg,
    ], tight=True, spacing=10), actions=[ft.TextButton("إلغاء", on_click=close_deposit_dialog), ft.FilledButton("تأكيد الشحن", on_click=handle_deposit)])

    admin_user_input = ft.TextField(label="اسم المستخدم", value="admin")
    admin_pass_input = ft.TextField(label="كلمة المرور", password=True, can_reveal_password=True)
    category_dropdown = ft.Dropdown(label="اختر الفئة المستهدفة للرفع", options=[ft.dropdown.Option(cat) for cat in CATEGORY_PRICES.keys()], width=250)

    async def trigger_file_selection(e):
        cat = category_dropdown.value
        if not cat:
            admin_status_msg.value = "⚠️ يرجى اختيار الفئة أولاً!"
            admin_status_msg.color = "#EF5350"
            page.update()
            return

        admin_status_msg.value = "⏳ جاري اختيار الملف..."
        admin_status_msg.color = "#42A5F5"
        page.update()

        try:
            files = await file_picker.pick_files(allow_multiple=False, allowed_extensions=["pdf"], file_type=ft.FilePickerFileType.CUSTOM, with_data=True)
            if files and len(files) > 0:
                file_info = files[0]
                file_bytes = file_info.bytes
                if not file_bytes and getattr(file_info, "path", None):
                    with open(file_info.path, "rb") as f:
                        file_bytes = f.read()

                if file_bytes:
                    cards_pairs = extract_cards_from_pdf_bytes(file_bytes)
                    if not cards_pairs:
                        admin_status_msg.value = "❌ لم يتم العثور على أرقام بطاقات."
                        admin_status_msg.color = "#EF5350"
                        page.update()
                        return

                    admin_status_msg.value = f"⏳ جاري الرفع للسيرفر ({len(cards_pairs)} بطاقة)..."
                    admin_status_msg.color = "#42A5F5"
                    page.update()

                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"{SERVER_URL}/api/admin/upload", json={"admin_user": ADMIN_USER, "admin_pass": ADMIN_PASS, "category": cat, "cards": cards_pairs}, timeout=30) as resp:
                            res_data = await resp.json()
                            if res_data.get("status"):
                                admin_status_msg.value = f"✅ تمت إضافة {res_data.get('added', 0)} بطاقة بنجاح!"
                                admin_status_msg.color = "#66BB6A"
                                await fetch_server_status()
                            else:
                                admin_status_msg.value = res_data.get("message", "❌ فشل الرفع.")
                                admin_status_msg.color = "#EF5350"
                else:
                    admin_status_msg.value = "❌ تعذر قراءة الملف."
                    admin_status_msg.color = "#EF5350"
            else:
                admin_status_msg.value = "⚠️ لم يتم اختيار ملف."
                admin_status_msg.color = "#FFA726"
        except Exception as ex:
            admin_status_msg.value = f"❌ خطأ: {ex}"
            admin_status_msg.color = "#EF5350"
        page.update()

    login_view_content = ft.Column([admin_user_input, admin_pass_input, login_status_msg], tight=True, spacing=10)
    upload_view_content = ft.Column([ft.Text("اختر الفئة واضغط لرفع الـ PDF:"), category_dropdown, ft.FilledButton("📁 اختيار ملف PDF", on_click=trigger_file_selection), admin_status_msg], tight=True, spacing=15)

    def check_admin_login(e):
        if admin_user_input.value == ADMIN_USER and admin_pass_input.value == ADMIN_PASS:
            admin_status_msg.value = ""
            admin_dialog.title = ft.Text("⚙️ لوحة المشرف - رفع بطاقات")
            admin_dialog.content = upload_view_content
            admin_dialog.actions = [ft.TextButton("إغلاق", on_click=close_admin_dialog)]
            page.update()
        else:
            login_status_msg.value = "❌ بيانات الدخول غير صحيحة!"
            page.update()

    admin_dialog = ft.AlertDialog(modal=True, title=ft.Text("🔒 تسجيل دخول المشرف"), content=login_view_content, actions=[ft.TextButton("إلغاء", on_click=close_admin_dialog), ft.FilledButton("دخول", on_click=check_admin_login)])

    page.overlay.append(deposit_dialog)
    page.overlay.append(card_dialog)
    page.overlay.append(admin_dialog)
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
        admin_dialog.actions = [ft.TextButton("إلغاء", on_click=close_admin_dialog), ft.FilledButton("دخول", on_click=check_admin_login)]
        admin_dialog.open = True
        page.update()

    async def buy_package(cat_name, price):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{SERVER_URL}/api/buy", json={"user_id": user_id, "category": cat_name}, timeout=15) as resp:
                    data = await resp.json()

            if data.get("status"):
                card_user, card_pass, new_bal = data["username"], data["password"], data["balance"]
                balance_text.value = f"الرصيد: {new_bal:,.0f} ل.س"
                card_details_text = f"📦 الفئة: {cat_name}\n👤 المستخدم: {card_user}\n🔑 كلمة المرور: {card_pass}\n💰 الرصيد المتبقي: {new_bal:,.0f} ل.س"
                
                copy_feedback = ft.Text("", size=13, color="#66BB6A", weight=ft.FontWeight.BOLD)
                async def copy_info(e):
                    await clipboard.set(card_details_text)
                    copy_feedback.value = "✅ تم النسخ!"
                    page.update()

                async def share_whatsapp(e):
                    url = f"https://api.whatsapp.com/send?text={urllib.parse.quote('تفاصيل بطاقة إنترنت:\n' + card_details_text)}"
                    await url_launcher.launch_url(url)

                card_dialog.title = ft.Text("✅ تم الشراء بنجاح!")
                card_dialog.content = ft.Column([
                    ft.Text(f"📦 الفئة: {cat_name}", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(f"👤 المستخدم: {card_user}", size=16, weight=ft.FontWeight.BOLD, color="#2196F3", selectable=True),
                    ft.Text(f"🔑 الباسورد: {card_pass}", size=16, weight=ft.FontWeight.BOLD, color="#F44336", selectable=True),
                    ft.Divider(),
                    ft.Text(f"💰 الرصيد المتبقي: {new_bal:,.0f} ل.س", size=16, weight=ft.FontWeight.BOLD, color="#4CAF50"),
                    copy_feedback
                ], tight=True, spacing=10)
                card_dialog.actions = [ft.FilledButton("📋 نسخ", on_click=copy_info), ft.FilledButton("📲 واتساب", on_click=share_whatsapp), ft.TextButton("إغلاق", on_click=close_card_dialog)]
                card_dialog.open = True
                await fetch_server_status()
                page.update()
            else:
                show_alert(data.get("title", "تنبيه"), data.get("message", "خطأ في الشراء."))
        except Exception as ex:
            show_alert("خطأ", f"تعذر الاتصال بالسيرفر: {ex}")

    def render_packages_ui():
        packages_column.controls.clear()
        for cat, price in CATEGORY_PRICES.items():
            count = stock_counts.get(cat, 0)
            packages_column.controls.append(ft.Card(content=ft.Container(content=ft.Row([
                ft.Column([ft.Text(f"فئة {cat}", size=16, weight=ft.FontWeight.BOLD), ft.Text(f"السعر: {price} ل.س | المتوفر: {count}", size=12, color="#9E9E9E")]),
                ft.FilledButton("شراء", on_click=lambda e, c=cat, p=price: page.run_task(buy_package, c, p))
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=15)))
        page.update()

    render_packages_ui()
    page.add(
        ft.Row([balance_text, ft.Row([ft.FilledButton("⚙️ المشرف", on_click=open_admin), ft.FilledButton("➕ شحن", on_click=open_deposit)], spacing=10)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Divider(),
        ft.Row([ft.Text("🛒 باقات الإنترنت:", size=18, weight=ft.FontWeight.BOLD), ft.TextButton("🔄 تحديث", on_click=lambda e: page.run_task(fetch_server_status))], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        packages_column
    )
    page.run_task(fetch_server_status)

if __name__ == '__main__':
    ft.run(main)
import flet as ft
import requests
import re

try:
    import pypdf
except ImportError:
    pypdf = None

def main(page: ft.Page):
    page.title = "تطبيق سوريا نت - باقات الإنترنت والمحفظة"
    page.rtl = True
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20

    # -------------------------------------------------------------
    # ⚙️ البيانات الخاصة بشام كاش والأدمن
    # -------------------------------------------------------------
    SHAM_CASH_ACCOUNT = "5c3d499c015d7335eb5474e832d06ff3"  # ضع رقم حساب شام كاش الفعلي الخاص بك
    SHAM_CASH_API_URL = "sk_8aa2518852cb96ca54da04084d7cbc80b9fd9a882b3607573ad5ec64e1043ef8"  # رابط API شام كاش

    # 🔐 بيانات تسجيل دخول الأدمن
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "123"  # يمكنك تغيير كلمة السر هنا إلى أي كلمة تفضلها

    user_balance = [0]  # رصيد المستخدم الحالي
    
    # مخزن الكروت حسب الفئات (يتم تعبئته عبر لوحة الأدمن)
    available_vouchers = {
        "باقة 5 جيجابايت": [],
        "باقة 10 جيجابايت": [],
        "باقة 15 جيجابايت": [],
        "باقة غير محدودة (شهرية)": []
    }

    balance_text = ft.Text(f"الرصيد: {user_balance[0]:,} ل.س", color=ft.Colors.GREEN_400, weight=ft.FontWeight.BOLD)
    admin_status = ft.Text("", size=14)

    selected_category = ft.Dropdown(
        label="اختر الفئة التابعة لها الكروت",
        options=[
            ft.dropdown.Option("باقة 5 جيجابايت"),
            ft.dropdown.Option("باقة 10 جيجابايت"),
            ft.dropdown.Option("باقة 15 جيجابايت"),
            ft.dropdown.Option("باقة غير محدودة (شهرية)"),
        ],
        value="باقة 5 جيجابايت"
    )

    pdf_path_input = ft.TextField(
        label="مسار ملف الـ PDF",
        hint_text=r"مثال: C:\Users\kinnawy\Desktop\cards.pdf",
        border_color=ft.Colors.AMBER_400
    )

    # -------------------------------------------------------------
    # 1. دالة التحقق من شام كاش
    # -------------------------------------------------------------
    def verify_shamcash_transaction(tx_id: str):
        payload = {
            "transaction_id": tx_id,
            "account": SHAM_CASH_ACCOUNT
        }
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            # الاتصال الحقيقي عند تجهيز السيرفر:
             response = requests.post(SHAM_CASH_API_URL, json=payload, headers=headers, timeout=12)
             if response.status_code == 200:
                 data = response.json()
                 if data.get("status") == "success":
                     return True, int(data.get("amount", 0)), "تم تأكيد العملية بنجاح"
                 else:
                     return False, 0, data.get("message", "رقم العملية غير صحيح أو مستخدم مسبقاً")

            # محاكاة للتجربة المحلية
            # if len(tx_id) >= 4:
             #   return True, 50000, "تم تأكيد عملية التحويل بنجاح"
           # else:
            #    return False, 0, "رقم الإشعار غير صحيح"

        except Exception as ex:
            return False, 0, f"خطأ شبكة: {str(ex)}"

    # -------------------------------------------------------------
    # 2. قراءة الكروت من الـ PDF
    # -------------------------------------------------------------
    def process_pdf_path(e):
        file_path = pdf_path_input.value.strip()
        category = selected_category.value

        if not file_path:
            admin_status.value = "❌ يرجى إدخال مسار ملف الـ PDF أولاً!"
            admin_status.color = ft.Colors.RED_400
            page.update()
            return

        try:
            if pypdf:
                reader = pypdf.PdfReader(file_path)
                extracted_text = ""
                for p in reader.pages:
                    extracted_text += p.extract_text() or ""
                
                codes = re.findall(r'\b[A-Za-z0-9]{6,12}\b', extracted_text)
                
                if codes:
                    available_vouchers[category].extend(codes)
                    admin_status.value = f"✅ تم إضافة {len(codes)} كارت بنجاح لـ ({category})!"
                    admin_status.color = ft.Colors.GREEN_400
                else:
                    admin_status.value = "⚠️ لم يتم العثور على أكواد متوافقة داخل الملف."
                    admin_status.color = ft.Colors.AMBER_400
            else:
                admin_status.value = "❌ مكتبة pypdf غير مثبتة. نفذ: pip install pypdf"
                admin_status.color = ft.Colors.RED_400

        except Exception as ex:
            admin_status.value = "❌ خطأ: تأكد من صحة مسار الملف أو وجوده."
            admin_status.color = ft.Colors.RED_400
        
        page.update()

    # -------------------------------------------------------------
    # 3. لوحة الأدمن بعد تسجيل الدخول
    # -------------------------------------------------------------
    def show_admin_dashboard():
        admin_status.value = ""
        pdf_path_input.value = ""

        def close_admin(e):
            admin_sheet.open = False
            page.update()

        admin_sheet = ft.BottomSheet(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text("لوحة التحكم (الأدمن) ⚙️", size=18, weight=ft.FontWeight.BOLD),
                                ft.IconButton(ft.Icons.CLOSE, on_click=close_admin)
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                        ),
                        selected_category,
                        pdf_path_input,
                        ft.Button(
                            content="قراءة وإضافة الكروت من الملف 📄",
                            on_click=process_pdf_path
                        ),
                        admin_status,
                    ],
                    tight=True,
                    spacing=12
                ),
                padding=20,
                bgcolor=ft.Colors.GREY_900,
                border_radius=15
            )
        )

        page.overlay.append(admin_sheet)
        admin_sheet.open = True
        page.update()

    # -------------------------------------------------------------
    # 4. نافذة تسجيل دخول الأدمن 🔐
    # -------------------------------------------------------------
    def open_admin_login(e):
        username_field = ft.TextField(label="اسم المستخدم", border_color=ft.Colors.AMBER_400)
        password_field = ft.TextField(label="كلمة السر", password=True, can_reveal_password=True, border_color=ft.Colors.AMBER_400)
        login_msg = ft.Text("", size=14)

        def close_login(e):
            login_sheet.open = False
            page.update()

        def check_credentials(e):
            if username_field.value.strip() == ADMIN_USERNAME and password_field.value.strip() == ADMIN_PASSWORD:
                login_sheet.open = False
                page.update()
                show_admin_dashboard()
            else:
                login_msg.value = "❌ اسم المستخدم أو كلمة السر غير صحيحة!"
                login_msg.color = ft.Colors.RED_400
                login_sheet.update()

        login_sheet = ft.BottomSheet(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text("تسجيل دخول الأدمن 🔒", size=18, weight=ft.FontWeight.BOLD),
                                ft.IconButton(ft.Icons.CLOSE, on_click=close_login)
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                        ),
                        username_field,
                        password_field,
                        login_msg,
                        ft.Row(
                            [
                                ft.Button(content="إلغاء", on_click=close_login),
                                ft.Button(content="دخول", on_click=check_credentials)
                            ],
                            alignment=ft.MainAxisAlignment.END,
                            spacing=10
                        )
                    ],
                    tight=True,
                    spacing=12
                ),
                padding=20,
                bgcolor=ft.Colors.GREY_900,
                border_radius=15
            )
        )

        page.overlay.append(login_sheet)
        login_sheet.open = True
        page.update()

    # -------------------------------------------------------------
    # 5. نافذة الإيداع
    # -------------------------------------------------------------
    def open_deposit_sheet(e):
        tx_input = ft.TextField(
            label="رقم عملية التحويل (شام كاش)",
            hint_text="أدخل رقم الإشعار",
            keyboard_type=ft.KeyboardType.NUMBER,
            border_color=ft.Colors.AMBER_400
        )
        status_msg = ft.Text("", size=14)

        def close_sheet(e):
            deposit_sheet.open = False
            page.update()

        def copy_account(e):
            snack = ft.SnackBar(ft.Text(f"رقم حساب شام كاش: {SHAM_CASH_ACCOUNT}"), open=True)
            page.overlay.append(snack)
            page.update()

        def process_deposit(e):
            tx_id = tx_input.value.strip()
            if not tx_id:
                status_msg.value = "❌ يرجى إدخال رقم عملية شام كاش أولاً!"
                status_msg.color = ft.Colors.RED_400
                deposit_sheet.update()
                return

            status_msg.value = "⏳ جاري التحقق عبر سيرفر شام كاش..."
            status_msg.color = ft.Colors.AMBER_400
            deposit_sheet.update()

            try:
                success, amount, msg = verify_shamcash_transaction(tx_id)

                if success:
                    user_balance[0] += amount
                    balance_text.value = f"الرصيد: {user_balance[0]:,} ل.س"
                    status_msg.value = f"✅ {msg}! تمت إضافة {amount:,} ل.س بنجاح."
                    status_msg.color = ft.Colors.GREEN_400
                else:
                    status_msg.value = f"❌ {msg}"
                    status_msg.color = ft.Colors.RED_400

            except Exception as ex:
                status_msg.value = f"⚠️ خطأ أثناء الاتصال بالسيرفر: {str(ex)}"
                status_msg.color = ft.Colors.RED_400

            page.update()

        deposit_sheet = ft.BottomSheet(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text("إيداع رصيد عبر شام كاش 💰", size=18, weight=ft.FontWeight.BOLD),
                                ft.IconButton(ft.Icons.CLOSE, on_click=close_sheet)
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                        ),
                        ft.Text("حول المبلغ المطلوب لحساب شام كاش التالي:"),
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Text(SHAM_CASH_ACCOUNT, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400),
                                    ft.IconButton(ft.Icons.COPY, tooltip="عرض الرقم", on_click=copy_account)
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            padding=10,
                            bgcolor=ft.Colors.GREY_800,
                            border_radius=8
                        ),
                        tx_input,
                        status_msg,
                        ft.Row(
                            [
                                ft.Button(content="إلغاء", on_click=close_sheet),
                                ft.Button(content="تأكيد الإيداع", on_click=process_deposit)
                            ],
                            alignment=ft.MainAxisAlignment.END,
                            spacing=10
                        )
                    ],
                    tight=True,
                    spacing=12
                ),
                padding=20,
                bgcolor=ft.Colors.GREY_900,
                border_radius=15
            )
        )

        page.overlay.append(deposit_sheet)
        deposit_sheet.open = True
        page.update()

    # -------------------------------------------------------------
    # 6. الشريط العلوي والباقات
    # -------------------------------------------------------------
    header = ft.Row(
        [
            ft.Text("مرحباً بك 👋", size=16, weight=ft.FontWeight.BOLD),
            ft.Row(
                [
                    ft.Container(
                        content=balance_text,
                        padding=8,
                        bgcolor=ft.Colors.GREY_900,
                        border_radius=8
                    ),
                    ft.Button(content="إيداع ➕", on_click=open_deposit_sheet),
                    ft.IconButton(ft.Icons.ADMIN_PANEL_SETTINGS, tooltip="لوحة الأدمن", on_click=open_admin_login)
                ],
                spacing=8
            )
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )

    categories = [
        {"title": "باقة 5 جيجابايت", "price": 15000},
        {"title": "باقة 10 جيجابايت", "price": 28000},
        {"title": "باقة 15 جيجابايت", "price": 40000},
        {"title": "باقة غير محدودة (شهرية)", "price": 75000},
    ]

    cards_list = ft.ListView(expand=True, spacing=10)

    def buy_card_from_balance(e, cat):
        title = cat["title"]
        price = cat["price"]

        if user_balance[0] < price:
            snack = ft.SnackBar(
                ft.Text(f"❌ رصيدك غير كافٍ للشراء ({price:,} ل.س). يرجى الضغط على إيداع أولاً!"),
                bgcolor=ft.Colors.RED_800,
                open=True
            )
            page.overlay.append(snack)
            page.update()
            return

        if not available_vouchers[title]:
            snack = ft.SnackBar(
                ft.Text(f"⚠️ الباقة غير متوفرة حالياً في المخزن، اطلب من الأدمن إضافة كروت جديدة!"),
                bgcolor=ft.Colors.AMBER_800,
                open=True
            )
            page.overlay.append(snack)
            page.update()
            return

        card_code = available_vouchers[title].pop(0)
        user_balance[0] -= price
        balance_text.value = f"الرصيد: {user_balance[0]:,} ل.س"

        dialog = ft.AlertDialog(
            title=ft.Text("🎉 تم الشراء بنجاح!"),
            content=ft.Column(
                [
                    ft.Text(f"تم تفعيل {title}"),
                    ft.Text("كود البطاقة الخاص بك هو:"),
                    ft.Container(
                        content=ft.Text(card_code, size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                        padding=10,
                        bgcolor=ft.Colors.BLACK,
                        border_radius=8,
                        alignment=ft.alignment.center
                    )
                ],
                tight=True,
                spacing=10
            ),
            actions=[
                ft.Button(content="تم", on_click=lambda _: page.close(dialog))
            ]
        )
        page.dialog = dialog
        dialog.open = True
        page.update()

    for cat in categories:
        cards_list.controls.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Column([
                            ft.Text(cat["title"], size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(f"{cat['price']:,} ل.س", size=14, color=ft.Colors.AMBER_400),
                        ], alignment=ft.MainAxisAlignment.CENTER),
                        ft.Button(
                            content="شراء",
                            on_click=lambda e, c=cat: buy_card_from_balance(e, c)
                        )
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                ),
                padding=15,
                bgcolor=ft.Colors.GREY_900,
                border_radius=10
            )
        )

    page.add(
        header,
        ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
        ft.Text("باقات الإنترنت المتاحة:", size=16, weight=ft.FontWeight.BOLD),
        cards_list
    )

ft.run(main)
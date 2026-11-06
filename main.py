import os
import sqlite3
import re
import aiohttp
import logging
from aiohttp import web
from pypdf import PdfReader
import io
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# بيانات محفظة شام كاش والـ API
WALLET_ID = "5c3d499c015d7335eb5474e832d06ff3"
SHAMCASH_API_URL = f"https://api-shamcash.com/api/v1/wallets/shamcash/{WALLET_ID}/transactions?direction=in"
SHAMCASH_API_TOKEN = "8aa2518852cb96ca54da04084d7cbc80b9fd9a882b3607573ad5ec64e1043ef8"  # تم تعديلها لتوافق كود البوت الخاص بك

# معرف المسؤول (Admin) في تيليجرام
ADMIN_ID = 5429133552
ADMIN_USER = "admin"
ADMIN_PASS = "123456"

# أسعار الفئات (بالليرة السورية)
CATEGORY_PRICES = {
    "5G": 80,
    "10G": 150,
    "20G": 270,
    "30G": 350,
    "50G": 500,
    "100G": 900
}

# تحديد مسار قاعدة البيانات بدقة لـ Render
if os.path.exists("/data") and os.access("/data", os.W_OK):
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
            user_id TEXT PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            user_id TEXT,
            amount REAL
        )
    ''')
    conn.commit()
    conn.close()

def get_or_create_user_balance(user_id: str) -> float:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (str(user_id),))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0.0

def import_cards_from_pdf_bytes(file_bytes, target_category):
    if not file_bytes:
        return 0
    try:
        pdf_file = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_file)
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
        logging.error(f"Error reading PDF bytes: {e}")
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
        logging.error(f"ShamCash API Connection Error: {e}")
        return {"status": False, "amount": 0}

# ==================== أجزاء ويب سيرفر التطبيق (API) ====================
async def handle_status(request):
    user_id = request.query.get("user_id", "default_user")
    balance = get_or_create_user_balance(user_id)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    stock = {}
    for cat in CATEGORY_PRICES.keys():
        cursor.execute("SELECT COUNT(*) FROM cards WHERE category = ? AND is_sold = 0", (cat,))
        stock[cat] = cursor.fetchone()[0]
    conn.close()
    
    return web.json_response({"status": True, "balance": balance, "stock": stock})

async def handle_deposit(request):
    data = await request.json()
    user_id = str(data.get("user_id", "default_user"))
    tx_id = str(data.get("tx_id", "")).strip()
    
    if not tx_id:
        return web.json_response({"status": False, "message": "⚠️ الرجاء إدخال رقم العملية أولاً."})
        
    get_or_create_user_balance(user_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT transaction_id FROM transactions WHERE transaction_id = ?", (tx_id,))
    if cursor.fetchone():
        conn.close()
        return web.json_response({"status": False, "message": "❌ رقم المعاملة هذا تم استخدامه مسبقاً!"})
    conn.close()

    res = await verify_shamcash_transaction(tx_id)
    if res["status"]:
        amount = res["amount"]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("INSERT INTO transactions (transaction_id, user_id, amount) VALUES (?, ?, ?)", (tx_id, user_id, amount))
        conn.commit()
        conn.close()
        new_bal = get_or_create_user_balance(user_id)
        return web.json_response({
            "status": True,
            "amount": amount,
            "balance": new_bal,
            "message": f"✅ تم تأكيد المعاملة وإضافة {amount:,.0f} ل.س بنجاح!"
        })
    else:
        return web.json_response({"status": False, "message": "❌ رقم العملية خطأ أو غير موجود في شبكة شام كاش!"})

async def handle_buy(request):
    data = await request.json()
    user_id = str(data.get("user_id", "default_user"))
    category = str(data.get("category", ""))
    price = CATEGORY_PRICES.get(category, 0)
    
    bal = get_or_create_user_balance(user_id)
    if bal < price:
        return web.json_response({
            "status": False,
            "title": "رصيد غير كافٍ",
            "message": f"❌ عذراً، رصيدك غير كافٍ لشراء فئة {category}.\nتحتاج إلى {price:,.0f} ل.س بينما رصيدك الحالي {bal:,.0f} ل.س."
        })

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password FROM cards WHERE category = ? AND is_sold = 0 LIMIT 1", (category,))
    card = cursor.fetchone()

    if card:
        card_id, card_user, card_pass = card
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
        cursor.execute("UPDATE cards SET is_sold = 1 WHERE id = ?", (card_id,))
        conn.commit()
        conn.close()
        new_bal = get_or_create_user_balance(user_id)
        return web.json_response({
            "status": True,
            "username": card_user,
            "password": card_pass,
            "balance": new_bal
        })
    else:
        conn.close()
        return web.json_response({
            "status": False,
            "title": "نفاد المخزون",
            "message": f"⚠️ عذراً، لا يوجد بطاقات متاحة حالياً لفئة {category}.\nنفذ المخزون من النظام!"
        })

async def handle_admin_upload(request):
    data = await request.json()
    if data.get("admin_user") != ADMIN_USER or data.get("admin_pass") != ADMIN_PASS:
        return web.json_response({"status": False, "message": "❌ بيانات المشرف غير صحيحة!"})
        
    category = data.get("category")
    cards_list = data.get("cards", [])
    added_count = 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for item in cards_list:
        usr, pwd = str(item[0]), str(item[1])
        cursor.execute("SELECT id FROM cards WHERE category = ? AND username = ? AND password = ?", (category, usr, pwd))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO cards (category, username, password, is_sold) VALUES (?, ?, ?, 0)", (category, usr, pwd))
            added_count += 1
    conn.commit()
    conn.close()
    
    return web.json_response({"status": True, "added": added_count})

async def handle_home(request):
    return web.Response(text="Syria Net Unified Server & Bot is Running!")


# ==================== أجزاء بوت التيليجرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name
    
    get_or_create_user_balance(user_id)
    
    keyboard = [
        [InlineKeyboardButton("💳 شراء بطاقة", callback_data="buy_cards")],
        [InlineKeyboardButton("💳 محفظتي ومعلوماتي", callback_data="my_wallet"), InlineKeyboardButton("➕ شحن الرصيد", callback_data="topup_menu")]
    ]
    if user_id == ADMIN_ID:
        keyboard.insert(0, [InlineKeyboardButton("⚙️ لوحة تحكم المشرف (Admin)", callback_data="admin_panel")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        f"🌐 أهلاً بك في SYRIA NET يا {user_name} 🌐\n\n"
        "يمكنك من خلال هذا البوت شحن رصيدك وشراء بطاقات الإنترنت الخاصة بالشبكة.\n"
        "شكراً لاستخدامك خدماتنا 💙"
    )

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text=welcome_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if query.data == "buy_cards":
        keyboard = []
        for cat, price in CATEGORY_PRICES.items():
            cursor.execute("SELECT COUNT(*) FROM cards WHERE category = ? AND is_sold = 0", (cat,))
            count = cursor.fetchone()[0]
            keyboard.append([InlineKeyboardButton(f"فئة {cat} - {price} ل.س (متوفر: {count})", callback_data=f"cat_{cat}")])
        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="🛒 *اختر الفئة التي تريد شراءها:*", reply_markup=reply_markup, parse_mode="Markdown")
        
    elif query.data == "my_wallet":
        balance = get_or_create_user_balance(user_id)
        wallet_text = (
            f"👤 *معلومات حسابك:*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ الاسم: {user.full_name}\n"
            f"🆔 معرف المستخدم (ID): {user_id}\n"
            f"💳 الرصيد الحالي: {balance:,.0f} ل.س\n"
            f"━━━━━━━━━━━━━━━━━━━"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ شحن الرصيد", callback_data="topup_menu")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
        ])
        await query.edit_message_text(text=wallet_text, parse_mode="Markdown", reply_markup=reply_markup)

    elif query.data == "topup_menu":
        context.user_data['waiting_for_tx'] = True
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء العملية", callback_data="main_menu")]])
        await query.edit_message_text(
            text=f"➕ *شحن الرصيد عبر شام كاش*\n\n"
                 f"رقم محفظتنا للاستلام:\n`{WALLET_ID}`\n\n"
                 f"الرجاء تحويل المبلغ، ثم إرسال *رقم المعاملة (Transaction ID)* هنا في رسالة نصية لشحن محفظتك تلقائياً:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    elif query.data == "admin_panel" and user_id == ADMIN_ID:
        stats_text = "📊 إحصائيات ومخزون البطاقات:\n\n"
        for cat in CATEGORY_PRICES.keys():
            cursor.execute("SELECT COUNT(*) FROM cards WHERE category = ? AND is_sold = 0", (cat,))
            available = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM cards WHERE category = ? AND is_sold = 1", (cat,))
            sold = cursor.fetchone()[0]
            stats_text += f"📦 فئة {cat}: متوفر ({available}) | مباع ({sold})\n"
        
        keyboard = [
            [InlineKeyboardButton("📥 رفع PDF لفئة 5G", callback_data="set_pdf_5G"), InlineKeyboardButton("📥 رفع PDF لفئة 10G", callback_data="set_pdf_10G")],
            [InlineKeyboardButton("📥 رفع PDF لفئة 20G", callback_data="set_pdf_20G"), InlineKeyboardButton("📥 رفع PDF لفئة 30G", callback_data="set_pdf_30G")],
            [InlineKeyboardButton("📥 رفع PDF لفئة 50G", callback_data="set_pdf_50G"), InlineKeyboardButton("📥 رفع PDF لفئة 100G", callback_data="set_pdf_100G")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text=stats_text + "\n💡 لإضافة بطاقات: اختر الفئة ثم أرسل ملف الـ PDF هنا.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif query.data.startswith("set_pdf_") and user_id == ADMIN_ID:
        cat_target = query.data.replace("set_pdf_", "")
        context.user_data['target_pdf_category'] = cat_target
        keyboard = [[InlineKeyboardButton("🔙 لوحة التحكم", callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text=f"📤 تم اختيار فئة: {cat_target}\n\nالآن قم بإرسال ملف الـ PDF الخاص بهذه الفئة مباشرة هنا.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    elif query.data.startswith("cat_"):
        category_name = query.data.replace("cat_", "")
        price = CATEGORY_PRICES.get(category_name, 0)
        balance = get_or_create_user_balance(user_id)

        if balance < price:
            await query.edit_message_text(
                text=f"❌ عذراً، رصيدك غير كافٍ لشراء فئة {category_name}.\nسعر البطاقة: {price} ل.س\nرصيدك الحالي: {balance} ل.س",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ شحن الرصيد", callback_data="topup_menu")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="buy_cards")]
                ])
            )
            conn.close()
            return

        cursor.execute("SELECT id, username, password FROM cards WHERE category = ? AND is_sold = 0 LIMIT 1", (category_name,))
        card = cursor.fetchone()

        if card:
            card_id, card_user, card_pass = card
            new_balance = balance - price
            cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, str(user_id)))
            cursor.execute("UPDATE cards SET is_sold = 1 WHERE id = ?", (card_id,))
            conn.commit()
            conn.close()

            await query.edit_message_text(
                text=f"✅ *تم الشراء بنجاح!*\n\n"
                     f"📦 الفئة: {category_name}\n"
                     f"👤 اسم المستخدم: {card_user}\n"
                     f"🔑 كلمة المرور: {card_pass}\n\n"
                     f"💰 رصيدك المتبقي: {new_balance:,.0f} ل.س\n"
                     f"شكراً لاستخدامك متجر syria net ❤️",
                parse_mode="Markdown"
            )
        else:
            conn.close()
            await query.edit_message_text(
                text="⚠️ عذراً، نفدت بطاقات هذه الفئة حالياً من النظام.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="buy_cards")]])
            )
        return
        
    elif query.data == "main_menu":
        context.user_data['waiting_for_tx'] = False
        context.user_data.pop('target_pdf_category', None)
        conn.close()
        await start(update, context)
        
    conn.close()

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
        
    target_category = context.user_data.get('target_pdf_category')
    if not target_category:
        await update.message.reply_text("⚠️ يرجى اختيار الفئة أولاً من لوحة تحكم المشرف.")
        return
        
    doc = update.message.document
    file = await context.bot.get_file(doc.file_id)
    file_bytes = await file.download_as_bytearray()
    
    added = import_cards_from_pdf_bytes(bytes(file_bytes), target_category)
    context.user_data['target_pdf_category'] = None
    
    await update.message.reply_text(
        f"✅ تمت إضافة {added} بطاقة جديدة بنجاح إلى فئة {target_category} عبر بوت التيليجرام!",
        parse_mode="Markdown"
    )

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_tx', False):
        return
        
    tx_id = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT transaction_id FROM transactions WHERE transaction_id = ?", (tx_id,))
    if cursor.fetchone():
        conn.close()
        await update.message.reply_text("⚠️ عذراً، رقم المعاملة هذا تم استخدامه مسبقاً!")
        return
    conn.close()

    msg = await update.message.reply_text("⏳ جاري التحقق من صحة المعاملة عبر شبكة شام كاش...")
    result = await verify_shamcash_transaction(tx_id)
    
    if result["status"]:
        amount = result["amount"]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("INSERT INTO transactions (transaction_id, user_id, amount) VALUES (?, ?, ?)", (tx_id, user_id, amount))
        conn.commit()
        
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        conn.close()
        
        context.user_data['waiting_for_tx'] = False
        await msg.edit_text(
            f"✅ *تم تأكيد المعاملة بنجاح!*\n💰 تمت إضافة {amount:,.0f} ل.س إلى محفظتك.\n💳 رصيدك الحالي: {new_balance:,.0f} ل.س",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 شراء بطاقة", callback_data="buy_cards")]]),
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text("❌ لم يتم العثور على المعاملة أو أنها غير صحيحة. تأكد من رقم المعاملة وحاول مجدداً.")


# ==================== تشغيل السيرفر الموحد (Web Server + Bot) ====================
async def main():
    init_db()
    
    # 1. إعداد تطبيق Web Server للبرنامج
    app_web = web.Application()
    app_web.router.add_get("/", handle_home)
    app_web.router.add_get("/api/status", handle_status)
    app_web.router.add_post("/api/deposit", handle_deposit)
    app_web.router.add_post("/api/buy", handle_buy)
    app_web.router.add_post("/api/admin/upload", handle_admin_upload)
    
    runner = web.AppRunner(app_web)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")

    # 2. إعداد بوت التيليجرام
    TOKEN = "8771941966:AAHGMqDM0_KPYS93A7p7QhrI-MEMW5zV-lo"
    tg_app = ApplicationBuilder().token(TOKEN).build()
    
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CallbackQueryHandler(button_handler))
    tg_app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    logging.info("Telegram bot started polling...")

    # إبقاء السيرفر والبوت قيد التشغيل دائمًا
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("تم إيقاف السيرفر والبوت.")
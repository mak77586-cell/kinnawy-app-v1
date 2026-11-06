import os
import sqlite3
import aiohttp
from aiohttp import web

# بيانات محفظة شام كاش والـ API
WALLET_ID = "5c3d499c015d7335eb5474e832d06ff3"
SHAMCASH_API_URL = f"https://api-shamcash.com/api/v1/wallets/shamcash/{WALLET_ID}/transactions?direction=in"
SHAMCASH_API_TOKEN = "sk_8aa2518852cb96ca54da04084d7cbc80b9fd9a882b3607573ad5ec64e1043ef8"

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
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0.0

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
    except Exception:
        return {"status": False, "amount": 0}

# 1. جلب الرصيد وعدد البطاقات المتوفرة
async def handle_status(request):
    user_id = request.query.get("user_id", "default_user")
    balance = get_or_create_user_balance(user_id)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    stock = {}
    for cat in CATEGORY_PRICES.keys():
        cursor.execute("SELECT COUNT(*) FROM cards WHERE category = ?", (cat,))
        stock[cat] = cursor.fetchone()[0]
    conn.close()
    
    return web.json_response({"status": True, "balance": balance, "stock": stock})

# 2. شحن الرصيد عبر شام كاش
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

# 3. شراء بطاقة
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
    cursor.execute("SELECT id, username, password FROM cards WHERE category = ? LIMIT 1", (category,))
    card = cursor.fetchone()

    if card:
        card_id, card_user, card_pass = card
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
        cursor.execute("DELETE FROM cards WHERE id = ?", (card_id,))
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

# 4. رفع البطاقات من تطبيق المشرف
async def handle_upload_cards(request):
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
    return web.Response(text="Syria Net Server is Running!")

app = web.Application()
app.router.add_get("/", handle_home)
app.router.add_get("/api/status", handle_status)
app.router.add_post("/api/deposit", handle_deposit)
app.router.add_post("/api/buy", handle_buy)
app.router.add_post("/api/admin/upload", handle_upload_cards)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)
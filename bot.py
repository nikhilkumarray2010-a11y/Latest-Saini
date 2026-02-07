import asyncio
import aiohttp
import json
import re
import os
from datetime import datetime, timedelta

from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = 7445620075

BASE_URL = "https://www.futurekul.com/admin/api"
USER_ID = ""

# ================= DB =====================

mongo = MongoClient(MONGO_URI)
db = mongo["extractor"]
users = db["users"]

# ================= HELPERS =================

def is_authorized(user_id: int) -> bool:
    user = users.find_one({"user_id": user_id})
    if not user:
        return False
    return datetime.utcnow() < user["expires_at"]


async def fetch_data(session, url):
    try:
        async with session.get(url, ssl=False) as r:
            text = await r.text()
            try:
                return json.loads(text)
            except:
                for m in re.findall(r'\{.*\}', text, re.DOTALL):
                    try:
                        return json.loads(m)
                    except:
                        continue
    except:
        return None

# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return await update.message.reply_text(
            "🚫 Access Denied\nContact admin for activation"
        )

    buttons = [
        [InlineKeyboardButton("📡 Live Batch", callback_data="live")],
        [InlineKeyboardButton("🎥 Recorded Batch", callback_data="recorded")]
    ]
    await update.message.reply_text(
        "👋 Select Batch Type:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ============== CALLBACKS ==================

async def batch_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        return

    query = update.callback_query
    await query.answer()

    is_live = "1" if query.data == "live" else "0"
    context.user_data["is_live"] = is_live

    await query.edit_message_text("⏳ Fetching batches...")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        url = f"{BASE_URL}/course/135/{is_live}/{USER_ID}"
        data = await fetch_data(session, url)

        batches = data.get("data", [])
        context.user_data["batches"] = batches

        buttons = [
            [InlineKeyboardButton(b["title"], callback_data=f"batch_{i}")]
            for i, b in enumerate(batches)
        ]

        await query.edit_message_text(
            "📚 Select Batch:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def extract_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = datetime.utcnow()
    uid = update.effective_user.id
    uid = update.effective_user.id
    if not is_authorized(uid):
        return

    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[1])
    batch = context.user_data["batches"][idx]

    await query.edit_message_text("⏳ Extracting content...")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        url = f"{BASE_URL}/getCourseDataByTopic-v2/{batch['id']}/{USER_ID}"
        content = await fetch_data(session, url)

        data = content.get("data", {})
        links = []

        for c in data.get("free_class", []):
            if c.get("link"):
                title = re.sub(r"<[^>]+>", "", c.get("class_name", ""))
                links.append(f"{title} : {c['link']}")

        for t in data.get("paid_class", []):
            for c in t.get("class", []):
                if c.get("link"):
                    title = re.sub(r"<[^>]+>", "", c.get("class_name", ""))
                    links.append(f"{title} : {c['link']}")

        filename = batch["title"].replace(" ", "_") + ".txt"
        with open(filename, "w", encoding="utf-8") as f:
            for l in links:
                f.write(l + "\n")

        await query.message.reply_document(open(filename, "rb"))

# ============== ADMIN ======================

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Admin only")

    try:
        uid = int(context.args[0])
        days = int(context.args[1])
    except:
        return await update.message.reply_text("Usage: /add user_id days")

    expiry = datetime.utcnow() + timedelta(days=days)

    users.update_one(
        {"user_id": uid},
        {"$set": {"expires_at": expiry}},
        upsert=True
    )

    await update.message.reply_text(
        f"✅ User {uid} added\nExpires: {expiry.strftime('%d %b %Y')}"
    )


async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    uid = int(context.args[0])
    users.delete_one({"user_id": uid})
    await update.message.reply_text(f"🗑️ User {uid} removed")


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    msg = "📋 Users:\n\n"
    for u in users.find():
        msg += f"{u['user_id']} → {u['expires_at'].strftime('%d %b %Y')}\n"

    await update.message.reply_text(msg or "No users")

# ============== MAIN =======================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_user))
    app.add_handler(CommandHandler("remove", remove_user))
    app.add_handler(CommandHandler("users", list_users))

    app.add_handler(CallbackQueryHandler(batch_type, pattern="^(live|recorded)$"))
    app.add_handler(CallbackQueryHandler(extract_batch, pattern="^batch_"))

    print("🤖 Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()

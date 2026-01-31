import os
import re
import random
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
import uvicorn

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# Optional OpenAI (works only if OPENAI_API_KEY is set)
OPENAI_AVAILABLE = False
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")  # e.g. https://your-service.onrender.com
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ===== Personality / Safety =====
DEFAULT_MODE = "friendly"  # friendly | savage
SAFE_ROAST_RULES = (
    "Roast must be playful, non-hateful, no slurs, no protected traits "
    "(religion, caste, race, sexuality, disability, etc.), no threats, no harassment. "
    "If user asks for hateful roast, refuse politely and switch to light joke."
)

PROTECTED_OR_HATE = re.compile(
    r"(nazi|terrorist|kill|rape|slur|caste|religion|muslim|hindu|christian|"
    r"gay|lesbian|trans|black|white|disabled|handicapped)",
    re.IGNORECASE
)

def looks_like_hate(text: str) -> bool:
    return bool(PROTECTED_OR_HATE.search(text or ""))

def detect_style(text: str) -> str:
    """
    Very simple: if text has lots of Bengali letters -> respond Hinglish
    else English/Hinglish mix.
    """
    bengali_chars = sum(1 for ch in text if "\u0980" <= ch <= "\u09FF")
    if bengali_chars >= 3:
        return "hinglish"
    # If user writes pure English, keep English-friendly
    return "english"

def fallback_chat_reply(user_text: str, style: str, mode: str) -> str:
    friendly_replies_en = [
        "Haha 😂 I got you. Tell me what’s up!",
        "I’m here, boss. Want jokes or help?",
        "Say less 😎 What are we doing today?",
    ]
    friendly_replies_hi = [
        "Arre haan 😂 bolo ki scene!",
        "Main yahin hoon boss 😎 joke chahiye ya help?",
        "Bolo bolo, aaj kya bakchodi karein? 😄",
    ]
    savage_snacks = [
        "Careful… I’m funny but I bite 😈",
        "You want savage? I can do savage. But only playful 😌",
    ]

    if mode == "savage":
        base = random.choice(savage_snacks)
    else:
        base = random.choice(friendly_replies_hi if style == "hinglish" else friendly_replies_en)

    return f"{base}\n\nYou said: “{user_text}”"

def fallback_roast(target: str, style: str, mode: str) -> str:
    # Light roasts only
    roasts_en = [
        f"{target} has the confidence of a lion… and the planning skills of a potato 🥔",
        f"{target} talks like a CEO but executes like Wi-Fi on 1 bar 📶",
        f"{target} is proof that ‘auto-correct’ gives up sometimes 😭",
    ]
    roasts_hi = [
        f"{target} ka attitude toh NASA-level hai, par kaam calculator-level bhi nahi 😭",
        f"{target} itna slow hai ki buffering bhi sharma jaye 📶",
        f"{target} bolta aise hai jaise topper, par vibes full backbencher 😌",
    ]

    if mode == "friendly":
        roast = random.choice(roasts_hi if style == "hinglish" else roasts_en)
        return f"Okay okay 😄 (playful roast only)\n\n{roast}"
    else:
        roast = random.choice(roasts_hi if style == "hinglish" else roasts_en)
        return f"😈 Savage mode ON (still playful)\n\n{roast}"

# ===== OpenAI helper (optional) =====
client = OpenAI(api_key=OPENAI_API_KEY) if (OPENAI_AVAILABLE and OPENAI_API_KEY) else None

SYSTEM_PROMPT = f"""
You are a Telegram chat bot named RoastMate.
You speak Hinglish and English naturally (match user's style).
Personality: friendly, funny, sweet, intelligent. Light teasing allowed.
Roast ONLY when user explicitly asks via /roast.
{SAFE_ROAST_RULES}
Keep replies short, chatty, and not overly formal.
"""

async def ai_reply(user_text: str, mode: str, roast: bool, style: str) -> str:
    if not client:
        # fallback
        if roast:
            return fallback_roast(user_text, style, mode)
        return fallback_chat_reply(user_text, style, mode)

    # Safety gate
    if looks_like_hate(user_text):
        if style == "hinglish":
            return "Nahi boss 😅 is type ka roast nahi. Main sirf playful, safe jokes/roast karta hoon."
        return "Nope 😅 I can’t do that. I only do playful, non-hateful roasts."

    extra = "User requested a roast. Make it playful and non-hateful." if roast else "Normal chat reply."
    vibe = "Be extra sweet and friendly." if mode == "friendly" else "Be a bit sassier but still safe/playful."

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{extra}\n{vibe}\nStyle:{style}\nText:{user_text}"},
        ],
        temperature=0.9,
        max_tokens=180,
    )
    return resp.choices[0].message.content.strip()

# ===== Telegram handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Hey! I’m RoastMate 😄\n\n"
        "• Normal chat: just message me\n"
        "• Roast: /roast @user OR /roast your text\n"
        "• Mode: /mode friendly OR /mode savage\n"
        "I can do Hinglish + English."
    )
    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - start\n"
        "/help - help\n"
        "/mode friendly|savage - set vibe\n"
        "/roast @user|text - playful roast (only on request)\n\n"
        "In groups: mention me or reply to my message for best results."
    )

async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Use: /mode friendly OR /mode savage")
        return
    mode = context.args[0].lower().strip()
    if mode not in ["friendly", "savage"]:
        await update.message.reply_text("Only: friendly or savage")
        return
    context.chat_data["mode"] = mode
    await update.message.reply_text(f"✅ Mode set to: {mode}")

async def roast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.chat_data.get("mode", DEFAULT_MODE)
    target_text = " ".join(context.args).strip()

    if update.message.reply_to_message and not target_text:
        # roast the replied user
        u = update.message.reply_to_message.from_user
        target_text = f"@{u.username}" if u.username else (u.full_name or "that person")

    if not target_text:
        await update.message.reply_text("Use: /roast @username OR reply to someone and /roast")
        return

    style = detect_style(update.message.text or "")
    reply = await ai_reply(target_text, mode=mode, roast=True, style=style)
    await update.message.reply_text(reply)

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    mode = context.chat_data.get("mode", DEFAULT_MODE)
    text = update.message.text.strip()

    # Group rule: reply only if mentioned OR replied-to, to avoid spam
    if update.message.chat.type in ["group", "supergroup"]:
        mentioned = context.bot.username and (f"@{context.bot.username}".lower() in text.lower())
        replied_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user and update.message.reply_to_message.from_user.is_bot
        if not (mentioned or replied_to_bot):
            return

    style = detect_style(text)
    reply = await ai_reply(text, mode=mode, roast=False, style=style)
    await update.message.reply_text(reply)

# ===== FastAPI webhook server (Render friendly) =====
app = FastAPI()
telegram_app: Optional[Application] = None

@app.on_event("startup")
async def on_startup():
    global telegram_app

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    telegram_app = Application.builder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_cmd))
    telegram_app.add_handler(CommandHandler("mode", mode_cmd))
    telegram_app.add_handler(CommandHandler("roast", roast_cmd))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    await telegram_app.initialize()

    # Set webhook after deploy
    if PUBLIC_URL:
        webhook_url = f"{PUBLIC_URL}/webhook"
        await telegram_app.bot.set_webhook(webhook_url)

    await telegram_app.start()

@app.on_event("shutdown")
async def on_shutdown():
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()

@app.post("/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@app.get("/")
def home():
    return {"status": "ok", "bot": "RoastMate"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

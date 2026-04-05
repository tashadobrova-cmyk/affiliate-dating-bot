import os
import json
import asyncio
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
CHAT_ID = os.environ.get("CHAT_ID")
GOOGLE_CREDS = os.environ.get("GOOGLE_CREDS")
SHEET_ID = os.environ.get("SHEET_ID")

groq_client = Groq(api_key=GROQ_API_KEY)

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS)
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).sheet1

def get_found_platforms():
    try:
        sheet = get_sheet()
        values = sheet.col_values(1)
        return set(v.strip().lower() for v in values if v.strip())
    except Exception as e:
        logger.error(f"Sheet read error: {e}")
        return set()

def save_platforms(platforms):
    try:
        sheet = get_sheet()
        existing = get_found_platforms()
        new_rows = []
        for p in platforms:
            name = p.get("name", "").strip()
            if name and name.lower() not in existing:
                new_rows.append([
                    name,
                    p.get("type", ""),
                    p.get("geo", ""),
                    p.get("contact", ""),
                    datetime.now().strftime("%Y-%m-%d")
                ])
        if new_rows:
            sheet.append_rows(new_rows)
        return len(new_rows)
    except Exception as e:
        logger.error(f"Sheet write error: {e}")
        return 0

def find_platforms(count=10):
    found = get_found_platforms()
    exclude_text = ""
    if found:
        sample = list(found)[:30]
        exclude_text = f"\n\nНЕ включай эти площадки (уже найдены ранее):\n" + "\n".join(sample)

    prompt = f"""Найди {count} НОВЫХ площадок для аффилейт-продвижения dating-офферов.

Параметры:
- Тип: все типы (сайты, блоги, YouTube, Instagram, TikTok, подкасты)
- Гео: Tier-1 (US, UK, AU)
- Подниша: casual dating, serious relationships, high traffic
- Важно: только реальные существующие площадки{exclude_text}

Верни ТОЛЬКО валидный JSON без markdown:
{{"platforms":[{{"name":"название","type":"site|youtube|instagram|tiktok|podcast","geo":"US","audience":"аудитория","why":"почему подходит","traffic":"охват","contact":"контакт"}}]}}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.7
    )
    
    text = response.choices[0].message.content
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    data = json.loads(text[start:end])
    return data.get("platforms", [])

async def send_daily(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text="🔍 Ищу новые площадки...")
        platforms = find_platforms(10)
        
        if not platforms:
            await context.bot.send_message(chat_id=CHAT_ID, text="❌ Не удалось найти площадки. Попробую завтра.")
            return

        saved = save_platforms(platforms)
        
        text = f"📋 *Новые площадки для Dating — {datetime.now().strftime('%d.%m.%Y')}*\n"
        text += f"_Найдено новых: {saved} из {len(platforms)}_\n\n"
        
        for i, p in enumerate(platforms, 1):
            text += f"*{i}. {p.get('name')}*\n"
            text += f"📌 {p.get('type')} | 🌍 {p.get('geo')}\n"
            text += f"👥 {p.get('audience')}\n"
            text += f"✅ {p.get('why')}\n"
            text += f"📊 {p.get('traffic')}\n"
            text += f"📬 {p.get('contact')}\n\n"
        
        await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Daily send error: {e}")
        await context.bot.send_message(chat_id=CHAT_ID, text=f"❌ Ошибка: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для поиска аффилейт-площадок.\n\n"
        "Команды:\n"
        "/find — найти 10 новых площадок прямо сейчас\n"
        "/find 20 — найти 20 площадок\n"
        "/status — статистика найденных площадок"
    )

async def find_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = 10
    if context.args:
        try:
            count = min(int(context.args[0]), 30)
        except:
            pass
    
    await update.message.reply_text(f"🔍 Ищу {count} площадок, подожди...")
    
    try:
        platforms = find_platforms(count)
        saved = save_platforms(platforms)
        
        text = f"📋 *Найдено площадок: {len(platforms)}* (новых: {saved})\n\n"
        for i, p in enumerate(platforms, 1):
            text += f"*{i}. {p.get('name')}*\n"
            text += f"📌 {p.get('type')} | 🌍 {p.get('geo')}\n"
            text += f"👥 {p.get('audience')}\n"
            text += f"✅ {p.get('why')}\n"
            text += f"📊 {p.get('traffic')}\n"
            text += f"📬 {p.get('contact')}\n\n"
        
        if len(text) > 4000:
            parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    found = get_found_platforms()
    await update.message.reply_text(f"📊 Всего найдено площадок: {len(found)}\nВсе сохранены в Google Sheets.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("find", find_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    # Ежедневная рассылка в 9:00
    job_queue = app.job_queue
    job_queue.run_daily(send_daily, time=datetime.strptime("09:00", "%H:%M").time())

    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()

import logging
import asyncio
import aiosqlite
import os
import io
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, executor, types
from keep_alive import keep_alive
from threading import Thread

# Запускаем Flask-сервер в отдельном потоке
Thread(target=keep_alive).start()

API_TOKEN = "7797115278:AAGWdTxe-6dgyfynSq0Bhp0nxBCywM5m2nw"
ADMIN_ID = 2107042404  # Замени на свой Telegram ID
DATABASE = "amnam.db"
COIN_IMG = "amnam_coin.png"
TAP_COOLDOWN = 3  # секунд

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

PHRASES = [
    "Ам Ням доволен! 😋",
    "Вкусная монетка! 🍭",
    "Ням-ням, плюс монетка! 🍬",
    "Ам Ням копит богатство! 💰",
    "Сладкий успех! 🧁"
]

LANGS = {
    "ru": {
        "start": "👋 Привет, {name}!\nДобро пожаловать в AmNamCoin 🍬\n\n💰 Баланс: {bal}",
        "menu_caption": "🍬 Продолжай тапать!\n\n💰 Баланс: {bal}",
        "banned": "🚫 Вы были заблокированы.",
        "broadcast_done": "✅ Рассылка завершена.",
        "not_admin": "У вас нет доступа."
    },
    "en": {
        "start": "👋 Hello, {name}!\nWelcome to AmNamCoin 🍬\n\n💰 Balance: {bal}",
        "menu_caption": "🍬 Keep tapping!\n\n💰 Balance: {bal}",
        "banned": "🚫 You have been banned.",
        "broadcast_done": "✅ Broadcast complete.",
        "not_admin": "Access denied."
    }
}

admin_states = {}

# ========== БАЗА ДАННЫХ ==========

async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            daily INTEGER DEFAULT 0,
            last_tap TEXT DEFAULT '',
            reg_date TEXT DEFAULT '',
            lang TEXT DEFAULT 'ru',
            banned INTEGER DEFAULT 0
        )""")
        await db.commit()

async def register_user(uid):
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
        if not await cur.fetchone():
            date = datetime.utcnow().date().isoformat()
            await db.execute("INSERT INTO users (user_id, reg_date) VALUES (?, ?)", (uid, date))
            await db.commit()

async def get_user(uid):
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute("SELECT balance, total, last_tap, daily, reg_date, lang, banned FROM users WHERE user_id=?", (uid,))
        return await cur.fetchone()

async def update_balance(uid, delta=1):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute("SELECT last_tap, daily FROM users WHERE user_id=?", (uid,))
        res = await cur.fetchone()
        last_tap, daily = res if res else ("", 0)
        last_date = datetime.fromisoformat(last_tap).date() if last_tap else None
        today = datetime.utcnow().date()
        if last_date != today:
            daily = 0
        daily += delta
        await db.execute("""
        UPDATE users SET balance = balance + ?, total = total + ?, daily = ?, last_tap = ?
        WHERE user_id = ?""", (delta, delta, daily, now, uid))
        await db.commit()
        cur = await db.execute("SELECT balance, total FROM users WHERE user_id=?", (uid,))
        return await cur.fetchone()

async def can_tap(uid):
    stats = await get_user(uid)
    last_tap = stats[2]
    if not last_tap:
        return True, 0
    last = datetime.fromisoformat(last_tap)
    now = datetime.utcnow()
    wait = TAP_COOLDOWN - (now - last).total_seconds()
    return wait <= 0, max(0, int(wait))

async def reset_user(uid):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET balance=0, total=0, daily=0, last_tap='' WHERE user_id=?", (uid,))
        await db.commit()

async def set_lang(uid, lang):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, uid))
        await db.commit()

async def get_top():
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute("SELECT user_id, total FROM users WHERE banned=0 ORDER BY total DESC LIMIT 10")
        return await cur.fetchall()

async def ban_user(uid):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
        await db.commit()

async def unban_user(uid):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
        await db.commit()

# ========== КНОПКИ ==========

def kb_main():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👆 Тапать", callback_data="tap"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        types.InlineKeyboardButton("🏆 Лидеры", callback_data="leaders"),
        types.InlineKeyboardButton("ℹ️ Инфо", callback_data="info"),
        types.InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
    )
    return kb

def kb_back():
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )

def kb_settings():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔄 Сброс прогресса", callback_data="reset"),
        types.InlineKeyboardButton("🌐 Сменить язык", callback_data="lang"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )
    return kb

def kb_lang():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )
    return kb

def kb_admin_main():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("👥 Список пользователей", callback_data="admin_user_list"),types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("🚫 Забанить пользователя", callback_data="admin_ban"),
        types.InlineKeyboardButton("✅ Разбанить пользователя", callback_data="admin_unban"),
        types.InlineKeyboardButton("💰 Изменить баланс пользователя", callback_data="admin_change_balance"),
        types.InlineKeyboardButton("❌ Удалить пользователя", callback_data="admin_delete_user"),
        types.InlineKeyboardButton("⬅️ Выйти из админ-панели", callback_data="admin_exit")
    )
    return kb

def kb_cancel():
    return types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel")
    )

# ========== ХЭНДЛЕРЫ ==========

@dp.message_handler(commands=['start'])
async def start(msg: types.Message):
    uid = msg.from_user.id
    await register_user(uid)
    stats = await get_user(uid)
    if stats[-1] == 1:
        await msg.answer(LANGS[stats[5]]["banned"])
        return
    bal = stats[0]
    lang = LANGS[stats[5]]
    if os.path.exists(COIN_IMG):
        with open(COIN_IMG, 'rb') as img:
            await msg.answer_photo(img, caption=lang["start"].format(name=msg.from_user.first_name, bal=bal), reply_markup=kb_main())
    else:
        await msg.answer(lang["start"].format(name=msg.from_user.first_name, bal=bal), reply_markup=kb_main())

@dp.callback_query_handler(lambda c: c.data == "tap")
async def tap(cq: types.CallbackQuery):
    uid = cq.from_user.id
    stats = await get_user(uid)
    if stats[-1] == 1:
        await cq.answer("Вы заблокированы", show_alert=True)
        return
    can, wait = await can_tap(uid)
    if not can:
        await cq.answer(f"Подожди {wait} сек", show_alert=True)
        return
    phrase = random.choice(PHRASES)
    bal, _ = await update_balance(uid)
    lang = LANGS[stats[5]]
    caption = f"{phrase}\n\n💰 Баланс: {bal} AmNamCoin"
    if os.path.exists(COIN_IMG):
        with open(COIN_IMG, 'rb') as img:
            await cq.message.edit_media(types.InputMediaPhoto(img, caption=caption), reply_markup=kb_main())
    else:
        await cq.message.edit_caption(caption, reply_markup=kb_main())
    await cq.answer("Тап! +1 монетка")

@dp.callback_query_handler(lambda c: c.data == "profile")
async def profile(cq: types.CallbackQuery):
    uid = cq.from_user.id
    stats = await get_user(uid)
    bal, total, _, daily, reg, lang_code, banned = stats
    if banned == 1:
        await cq.answer("Вы заблокированы", show_alert=True)
        return
    text = (f"👤 Профиль\n\n"
            f"💰 Баланс: {bal} AmNamCoin\n"
            f"📈 Всего заработано: {total}\n"
            f"🎯 Сегодня: {daily}\n"
            f"📅 Дата регистрации: {reg}\n"
            f"🌐 Язык: {lang_code}")
    await cq.message.edit_caption(text, reply_markup=kb_main())
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data == "leaders")
async def leaders(cq: types.CallbackQuery):
    leaders_list = await get_top()
    if not leaders_list:
        await cq.answer("Лидеров пока нет.", show_alert=True)
        return
    text = "🏆 Топ игроков:\n\n"
    for i, (uid, total) in enumerate(leaders_list, 1):
        user = await bot.get_chat(uid)
        name = user.first_name if user else "???"
        text += f"{i}. {name} — {total} 🍬\n"
    await cq.message.edit_caption(text, reply_markup=kb_main())
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data == "info")
async def info(cq: types.CallbackQuery):
    text = ("🍬 AmNamCoin — это игра-тапалка с монетками.\n\n"
            "👆 Тапай по кнопке, чтобы собирать монетки.\n"
            "🏆 Соревнуйся с другими игроками в таблице лидеров.\n"
            "⚙️ Меняй настройки и сбрасывай прогресс.\n\n"
            "🤖 Бот разработан на aiogram.")
    await cq.message.edit_caption(text, reply_markup=kb_main())
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data == "settings")
async def settings(cq: types.CallbackQuery):
    await cq.message.edit_caption("⚙️ Настройки:", reply_markup=kb_settings())
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data == "reset")
async def reset_progress(cq: types.CallbackQuery):
    uid = cq.from_user.id
    await reset_user(uid)
    stats = await get_user(uid)
    bal = stats[0]
    lang = LANGS[stats[5]]
    await cq.message.edit_caption(lang["start"].format(name=cq.from_user.first_name, bal=bal), reply_markup=kb_main())
    await cq.answer("Прогресс сброшен!")

@dp.callback_query_handler(lambda c: c.data == "lang")
async def change_lang(cq: types.CallbackQuery):
    await cq.message.edit_caption("Выберите язык / Choose language:", reply_markup=kb_lang())
    await cq.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("lang_"))
async def set_language(cq: types.CallbackQuery):
    lang_code = cq.data.split("_")[1]
    if lang_code not in LANGS:
        await cq.answer("Язык не поддерживается", show_alert=True)
        return
    uid = cq.from_user.id
    await set_lang(uid, lang_code)
    stats = await get_user(uid)
    bal = stats[0]
    lang = LANGS[lang_code]
    await cq.message.edit_caption(lang["start"].format(name=cq.from_user.first_name, bal=bal), reply_markup=kb_main())
    await cq.answer(f"Язык изменён на {lang_code}")

@dp.callback_query_handler(lambda c: c.data == "back")
async def go_back(cq: types.CallbackQuery):
    uid = cq.from_user.id
    stats = await get_user(uid)
    bal = stats[0]
    lang = LANGS[stats[5]]
    await cq.message.edit_caption(lang["start"].format(name=cq.from_user.first_name, bal=bal), reply_markup=kb_main())
    await cq.answer()

# ===== Админ-панель =====

def is_admin(uid):
    return uid == ADMIN_ID

@dp.message_handler(commands=["admin"])
async def admin_panel(msg: types.Message):
    uid = msg.from_user.id
    if not is_admin(uid):
        await msg.reply("Доступ запрещён.")
        return
    await msg.reply("Админ-панель:", reply_markup=kb_admin_main())

@dp.callback_query_handler(lambda c: c.data.startswith("admin_"))
async def admin_handlers(cq: types.CallbackQuery):
    uid = cq.from_user.id
    if not is_admin(uid):
        await cq.answer("Доступ запрещён.", show_alert=True)
        return
    data = cq.data
    if data == "admin_exit":
        await cq.message.edit_text("Вы вышли из админ-панели.")
        await cq.answer()
        return
    elif data == "admin_broadcast":
        admin_states[uid] = "broadcast"
        await cq.message.answer("Введите сообщение для рассылки:")
        await cq.answer()
        return
    elif data == "admin_user_list":
        if cq.from_user.id != ADMIN_ID:
            await cq.answer("Доступ запрещён.", show_alert=True)
            return

        await cq.answer("Формируем список пользователей...")

        try:
            # Получаем всех пользователей из базы данных
            async with aiosqlite.connect(DATABASE) as db:
                cur = await db.execute("SELECT user_id, lang, balance, reg_date, banned FROM users ORDER BY user_id")
                users = await cur.fetchall()

            if not users:
                await cq.message.answer("В базе нет пользователей.")
                return

            # Формируем содержимое файла
            file_content = "Список пользователей AmNamCoin\n\n"
            file_content += "ID пользователя | Язык | Баланс | Дата регистрации | Статус\n"
            file_content += "="*70 + "\n"

            for uid, lang, bal, reg_date, banned in users:
                try:
                    user = await bot.get_chat(uid)
                    name = user.first_name or "N/A"
                    username = f"@{user.username}" if user.username else "N/A"
                except:
                    name = "N/A"
                    username = "N/A"

                status = "🚫 Забанен" if banned else "✅ Активен"

                file_content += (
                    f"ID: {uid}\n"
                    f"Имя: {name}\n"
                    f"Username: {username}\n"
                    f"Язык: {lang}\n"
                    f"Баланс: {bal} 🪙\n"
                    f"Дата регистрации: {reg_date}\n"
                    f"Статус: {status}\n"
                    f"{'-'*70}\n"
                )

            # Создаем временный файл
            filename = f"users_list_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(file_content)

            # Отправляем файл
            with open(filename, 'rb') as f:
                await bot.send_document(
                    chat_id=cq.from_user.id,
                    document=types.InputFile(f, filename),
                    caption=f"Список пользователей на {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    reply_markup=kb_admin_main()
                )

            # Удаляем временный файл
            os.remove(filename)

        except Exception as e:
            logging.error(f"Ошибка при формировании списка пользователей: {e}")
            await cq.message.answer(f"Произошла ошибка: {e}")
    elif data == "admin_ban":
        admin_states[uid] = "ban"
        await cq.message.answer("Введите user_id для бана:")
        await cq.answer()
        return
    elif data == "admin_unban":
        admin_states[uid] = "unban"
        await cq.message.answer("Введите user_id для разбана:")
        await cq.answer()
        return
    elif data == "admin_change_balance":
        admin_states[uid] = "change_balance"
        await cq.message.answer("Введите user_id и новый баланс через пробел:")
        await cq.answer()
        return
    elif data == "admin_delete_user":
        admin_states[uid] = "delete_user"
        await cq.message.answer("Введите user_id для удаления из базы:")
        await cq.answer()
        return
    elif data == "admin_cancel":
        admin_states.pop(uid, None)
        await cq.message.answer("Операция отменена.")
        await cq.answer()
        return

@dp.message_handler(lambda m: m.from_user.id == ADMIN_ID)
async def admin_messages(msg: types.Message):
    uid = msg.from_user.id
    if uid not in admin_states:
        return
    state = admin_states[uid]
    text = msg.text.strip()
    if state == "broadcast":
        count = 0
        async with aiosqlite.connect(DATABASE) as db:
            cur = await db.execute("SELECT user_id FROM users WHERE banned=0")
            users = await cur.fetchall()
        for (user_id,) in users:
            try:
                await bot.send_message(user_id, text)
                count += 1
                await asyncio.sleep(0.05)
            except Exception:
                continue
        await msg.reply(f"Рассылка завершена. Отправлено: {count} сообщений.")
        admin_states.pop(uid, None)
    elif state == "ban":
        try:
            target = int(text)
            await ban_user(target)
            await msg.reply(f"Пользователь {target} заблокирован.")
        except Exception:
            await msg.reply("Ошибка при вводе user_id.")
        admin_states.pop(uid, None)
    elif state == "unban":
        try:
            target = int(text)
            await unban_user(target)
            await msg.reply(f"Пользователь {target} разблокирован.")
        except Exception:
            await msg.reply("Ошибка при вводе user_id.")
        admin_states.pop(uid, None)
    elif state == "change_balance":
        try:
            parts = text.split()
            target = int(parts[0])
            new_bal = int(parts[1])
            async with aiosqlite.connect(DATABASE) as db:
                await db.execute("UPDATE users SET balance=?, total=? WHERE user_id=?", (new_bal, new_bal, target))
                await db.commit()
            await msg.reply(f"Баланс пользователя {target} установлен в {new_bal}.")
        except Exception:
            await msg.reply("Ошибка! Введите user_id и баланс через пробел.")
        admin_states.pop(uid, None)
    elif state == "delete_user":
        try:
            target = int(text)
            async with aiosqlite.connect(DATABASE) as db:
                await db.execute("DELETE FROM users WHERE user_id=?", (target,))
                await db.commit()
            await msg.reply(f"Пользователь {target} удалён из базы.")
        except Exception:
            await msg.reply("Ошибка при вводе user_id.")
        admin_states.pop(uid, None)



# ========== ЗАПУСК БОТА ==========

async def on_startup(dp):
    logging.info("Bot starting up...")
    await init_db()

async def on_shutdown(dp):
    logging.info("Bot shutting down...")
    await bot.close()

async def run_bot():
    while True:
        try:
            await init_db()
            await dp.start_polling()
        except Exception as e:
            logging.error(f"Bot crashed: {e}")
            logging.info("Restarting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    keep_alive()  # Запускаем Flask-сервер

    # Настройка логгирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Запуск бота с автоматическим перезапуском
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
import json
import os
import logging
import asyncio
import threading
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes
)

# ==================== АВТОПИНГ (чтобы бот не засыпал) ====================
class AutoPinger:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.running = True
        self.ping_count = 0
    
    def ping_self(self):
        """Отправляет команду /start самому себе"""
        import requests
        try:
            # Отправляем запрос к Telegram API
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                self.ping_count += 1
                current_time = datetime.now().strftime("%H:%M:%S")
                print(f"✅ Автопинг #{self.ping_count} в {current_time} - бот активен")
            else:
                print(f"⚠️ Автопинг вернул код: {response.status_code}")
        except Exception as e:
            print(f"❌ Ошибка автопинга: {e}")
    
    def start_pinging(self):
        """Запускает цикл пинга"""
        print("⏰ Автопинг запущен (каждые 10 минут)")
        while self.running:
            self.ping_self()
            # Ждём 10 минут (600 секунд)
            for _ in range(600):
                if not self.running:
                    break
                time.sleep(1)
    
    def stop(self):
        self.running = False

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8700012095:AAFkpm_sD2hK0CAe5gfxzANnf5QpJvM_A6c"  # ТВОЙ ТОКЕН
ADMIN_ID = 8465724699  # ТВОЙ ID

STAR_PRICE = 1.4
MIN_STARS = 50

# ГОТОВЫЕ ТАРИФЫ
TARIFFS = {
    50: 70,
    100: 137,
    150: 207,
    200: 273,
    250: 343,
    300: 410,
    500: 685,
    1000: 1370
}

# ТВОИ ССЫЛКИ
CHANNEL_LINK = "https://t.me/PixelTVS"
REVIEW_POST_LINK = "https://t.me/PixelTVS/10"
SUPPORT_USERNAME = "BlackSupportt"

# ==================== СОСТОЯНИЯ ====================
(
    ENTERING_CUSTOM_STARS,
    ENTERING_GIFT_USERNAME,
    WAITING_SCREENSHOT
) = range(3)

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self):
        self.db_file = "database.json"
        self.load()
    
    def load(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        else:
            self.data = {
                "users": {},
                "orders": [],
                "pending_orders": {}
            }
            self.save()
    
    def save(self):
        with open(self.db_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def get_user(self, user_id):
        user_id = str(user_id)
        if user_id not in self.data["users"]:
            self.data["users"][user_id] = {
                "stars_bought": 0,
                "total_spent": 0,
                "orders": [],
                "first_seen": datetime.now().isoformat()
            }
            self.save()
        return self.data["users"][user_id]
    
    def save_pending(self, user_id, data):
        self.data["pending_orders"][str(user_id)] = data
        self.save()
    
    def get_pending(self, user_id):
        return self.data["pending_orders"].get(str(user_id))
    
    def clear_pending(self, user_id):
        if str(user_id) in self.data["pending_orders"]:
            del self.data["pending_orders"][str(user_id)]
            self.save()
    
    def add_order(self, user_id, username, stars, amount, screenshot_id, gift_for=None):
        order = {
            "id": len(self.data["orders"]) + 1,
            "user_id": str(user_id),
            "username": username,
            "stars": stars,
            "amount": round(amount, 2),
            "screenshot_id": screenshot_id,
            "gift_for": gift_for,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        self.data["orders"].append(order)
        
        user = self.get_user(user_id)
        user["orders"].append(order["id"])
        user["stars_bought"] += stars
        user["total_spent"] += round(amount, 2)
        
        self.save()
        return order
    
    def get_order(self, order_id):
        for order in self.data["orders"]:
            if order["id"] == order_id:
                return order
        return None
    
    def get_pending_orders(self):
        return [o for o in self.data["orders"] if o["status"] == "pending"]
    
    def update_order_status(self, order_id, status):
        for order in self.data["orders"]:
            if order["id"] == order_id:
                order["status"] = status
                order["updated_at"] = datetime.now().isoformat()
                self.save()
                return order
        return None

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
db = Database()

# ==================== ФУНКЦИИ ====================
def calculate_price(stars):
    if stars in TARIFFS:
        return TARIFFS[stars]
    raw = stars * STAR_PRICE
    rounded = int(raw)
    return rounded + 1 if raw - rounded >= 0.5 else rounded

# ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("⭐️ Купить для себя", callback_data="buy_self")],
        [InlineKeyboardButton("🎁 Подарить другу", callback_data="buy_gift")],
        [InlineKeyboardButton("📊 Тарифы", callback_data="show_tariffs")],
        [InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")],
        [InlineKeyboardButton("📢 Канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton("💬 Отзывы", url=REVIEW_POST_LINK)],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_stars_keyboard(for_gift=False):
    keyboard = []
    prefix = "gift_" if for_gift else ""
    
    for stars, price in TARIFFS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"⭐️ {stars} звёзд = {price} ₽",
                callback_data=f"{prefix}stars_{stars}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("✏️ Своё количество", callback_data=f"{prefix}custom")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    
    return InlineKeyboardMarkup(keyboard)

def get_payment_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 Я оплатил", callback_data="paid")],
        [InlineKeyboardButton("🔙 Отмена", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_order_keyboard(order_id):
    keyboard = [
        [InlineKeyboardButton("✅ ПОДТВЕРДИТЬ ЗАКАЗ", callback_data=f"admin_approve_{order_id}")],
        [InlineKeyboardButton("❌ ОТКЛОНИТЬ ЗАКАЗ", callback_data=f"admin_reject_{order_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_support_keyboard():
    keyboard = [
        [InlineKeyboardButton("📞 Написать поддержке", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Ожидающие заказы", callback_data="admin_pending")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== ОБРАБОТЧИКИ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.get_user(user_id)
    
    # Проверяем, это автопинг или реальный пользователь
    if update.message.from_user.is_bot:
        return  # Игнорируем сообщения от ботов
    
    text = f"""
🌟 Добро пожаловать в магазин звёзд! 🌟

⭐️ Цена: 1 звезда = {STAR_PRICE} руб
⚠️ Минимальная покупка: {MIN_STARS} звёзд

📊 Наши тарифы:
• 50 звёзд — 70 ₽
• 100 звёзд — 137 ₽
• 150 звёзд — 207 ₽
• 200 звёзд — 273 ₽
• 250 звёзд — 343 ₽
• 300 звёзд — 410 ₽
• 500 звёзд — 685 ₽
• 1000 звёзд — 1370 ₽

✨ Можно выбрать своё количество!
🎁 Есть функция подарка другу!

👇 Выберите действие:
"""
    
    await update.message.reply_text(text, reply_markup=get_main_keyboard())
    
    await update.message.reply_text(
        f"""
📋 Обязательные условия:

✅ Подписка на канал: {CHANNEL_LINK}
✅ Отзыв после покупки: {REVIEW_POST_LINK}

❗️ Без выполнения условий оплата не подтверждается!

По вопросам: @{SUPPORT_USERNAME}
        """
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "back_to_main":
        await query.edit_message_text(
            "🌟 Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    elif data == "show_tariffs":
        text = "📊 Наши тарифы:\n\n"
        for stars, price in TARIFFS.items():
            text += f"• {stars} звёзд — {price} ₽\n"
        text += f"\n💡 Можно заказать любое количество от {MIN_STARS} звёзд!"
        
        await query.edit_message_text(text, reply_markup=get_main_keyboard())
        return ConversationHandler.END
    
    elif data == "help":
        text = f"""
❓ Помощь

1. Выберите количество звёзд
2. Оплатите на карту 2200 7021 1888 7905
3. Отправьте скриншот оплаты
4. Подпишитесь на канал
5. Дождитесь подтверждения

⏳ Время проверки: 5-20 минут

📞 По вопросам: @{SUPPORT_USERNAME}
        """
        await query.edit_message_text(text, reply_markup=get_main_keyboard())
        return ConversationHandler.END
    
    elif data == "my_orders":
        user_id = update.effective_user.id
        orders = [o for o in db.data["orders"] if o["user_id"] == str(user_id)]
        
        if not orders:
            await query.edit_message_text("📭 У вас пока нет заказов", reply_markup=get_main_keyboard())
            return ConversationHandler.END
        
        text = "📋 Ваши заказы:\n\n"
        for order in orders[-5:]:
            status_emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(order["status"], "❓")
            gift = f" (подарок @{order['gift_for']})" if order.get("gift_for") else ""
            date = datetime.fromisoformat(order["created_at"]).strftime("%d.%m %H:%M")
            text += f"{status_emoji} #{order['id']}: {order['stars']}⭐️ {order['amount']}₽{gift} - {date}\n"
        
        await query.edit_message_text(text, reply_markup=get_main_keyboard())
        return ConversationHandler.END
    
    elif data == "buy_self":
        context.user_data['is_gift'] = False
        await query.edit_message_text(
            "⭐️ Выберите количество звёзд:",
            reply_markup=get_stars_keyboard(for_gift=False)
        )
        return ConversationHandler.END
    
    elif data == "buy_gift":
        context.user_data['is_gift'] = True
        await query.edit_message_text(
            "🎁 Выберите количество звёзд для подарка:",
            reply_markup=get_stars_keyboard(for_gift=True)
        )
        return ConversationHandler.END
    
    elif data.startswith("stars_") or data.startswith("gift_stars_"):
        if data.startswith("gift_stars_"):
            stars = int(data.split("_")[2])
            context.user_data['is_gift'] = True
        else:
            stars = int(data.split("_")[1])
            context.user_data['is_gift'] = False
        
        price = TARIFFS[stars]
        context.user_data['stars'] = stars
        context.user_data['amount'] = price
        
        if context.user_data.get('is_gift', False):
            await query.edit_message_text(
                f"🎁 Введите @username друга, которому хотите подарить {stars} звёзд:"
            )
            return ENTERING_GIFT_USERNAME
        else:
            await query.edit_message_text(
                f"""
💳 Оплата

Переведите {price} ₽ на карту:
`2200 7021 1888 7905`
Получатель: Кирилл Т.

⭐️ {stars} звёзд

После оплаты нажмите кнопку ниже и отправьте скриншот
                """,
                reply_markup=get_payment_keyboard()
            )
            return WAITING_SCREENSHOT
    
    elif data.endswith("custom"):
        await query.edit_message_text(
            f"✏️ Введите количество звёзд (от {MIN_STARS}):"
        )
        return ENTERING_CUSTOM_STARS
    
    elif data == "paid":
        await query.edit_message_text("📸 Отправьте скриншот подтверждения оплаты:")
        return WAITING_SCREENSHOT
    
    # АДМИНСКИЕ КОМАНДЫ
    elif data == "admin_pending":
        if update.effective_user.id != ADMIN_ID:
            await query.edit_message_text("❌ Нет прав")
            return ConversationHandler.END
        
        pending = db.get_pending_orders()
        
        if not pending:
            await query.edit_message_text(
                "📭 Нет ожидающих заказов",
                reply_markup=get_admin_panel_keyboard()
            )
            return ConversationHandler.END
        
        text = "⏳ Ожидающие заказы:\n\n"
        for order in pending[-10:]:
            date = datetime.fromisoformat(order["created_at"]).strftime("%d.%m %H:%M")
            gift = f" (для @{order['gift_for']})" if order.get("gift_for") else ""
            text += f"• #{order['id']}: @{order['username']} - {order['stars']}⭐️ {order['amount']}₽{gift} - {date}\n"
        
        text += "\n🔍 Нажми на заказ в переписке выше для просмотра"
        
        await query.edit_message_text(text, reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    
    elif data == "admin_stats":
        if update.effective_user.id != ADMIN_ID:
            await query.edit_message_text("❌ Нет прав")
            return ConversationHandler.END
        
        orders = db.data["orders"]
        total_orders = len(orders)
        pending = len([o for o in orders if o["status"] == "pending"])
        approved = len([o for o in orders if o["status"] == "approved"])
        rejected = len([o for o in orders if o["status"] == "rejected"])
        
        total_stars = sum(o["stars"] for o in orders if o["status"] == "approved")
        total_money = sum(o["amount"] for o in orders if o["status"] == "approved")
        unique_users = len(set(o["user_id"] for o in orders))
        
        text = f"""
📊 СТАТИСТИКА

📦 Всего заказов: {total_orders}
⏳ Ожидают: {pending}
✅ Подтверждено: {approved}
❌ Отклонено: {rejected}

⭐️ Продано звёзд: {total_stars}
💰 Выручка: {total_money:.2f} ₽
👥 Покупателей: {unique_users}
        """
        
        await query.edit_message_text(text, reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    
    elif data.startswith("admin_approve_"):
        if update.effective_user.id != ADMIN_ID:
            await query.answer("❌ Нет прав")
            return ConversationHandler.END
        
        order_id = int(data.split("_")[2])
        order = db.get_order(order_id)
        
        if not order:
            await query.answer("❌ Заказ не найден")
            return ConversationHandler.END
        
        order = db.update_order_status(order_id, "approved")
        gift_text = f" для @{order['gift_for']}" if order.get('gift_for') else ""
        
        try:
            await context.bot.send_message(
                chat_id=int(order['user_id']),
                text=f"""
✅ ЗАКАЗ #{order_id} ПОДТВЕРЖДЁН! ✅

⭐️ {order['stars']} звёзд{gift_text} зачислены!
💰 Сумма: {order['amount']} ₽

Спасибо за покупку! ❤️
                """
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю: {e}")
        
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ ЗАКАЗ ПОДТВЕРЖДЁН ✅",
            reply_markup=None
        )
        
        await query.answer("✅ Заказ подтверждён!")
        return ConversationHandler.END
    
    elif data.startswith("admin_reject_"):
        if update.effective_user.id != ADMIN_ID:
            await query.answer("❌ Нет прав")
            return ConversationHandler.END
        
        order_id = int(data.split("_")[2])
        order = db.get_order(order_id)
        
        if not order:
            await query.answer("❌ Заказ не найден")
            return ConversationHandler.END
        
        order = db.update_order_status(order_id, "rejected")
        
        try:
            await context.bot.send_message(
                chat_id=int(order['user_id']),
                text=f"""
❌ ЗАКАЗ #{order_id} ОТКЛОНЁН ❌

Платёж не найден. Возможные причины:
• Неверная сумма перевода
• Платёж не поступил на карту
• Скриншот нечитаемый

Попробуйте оформить заказ заново или свяжитесь с @{SUPPORT_USERNAME}
                """
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю: {e}")
        
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ ЗАКАЗ ОТКЛОНЁН ❌",
            reply_markup=None
        )
        
        await query.answer("❌ Заказ отклонён")
        return ConversationHandler.END
    
    return ConversationHandler.END

async def custom_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stars = int(update.message.text)
        if stars < MIN_STARS:
            await update.message.reply_text(f"❌ Минимальное количество: {MIN_STARS} звёзд")
            return ENTERING_CUSTOM_STARS
        
        price = calculate_price(stars)
        is_gift = context.user_data.get('is_gift', False)
        
        context.user_data['stars'] = stars
        context.user_data['amount'] = price
        
        if is_gift:
            await update.message.reply_text(
                f"🎁 Введите @username друга, которому хотите подарить {stars} звёзд:"
            )
            return ENTERING_GIFT_USERNAME
        else:
            await update.message.reply_text(
                f"""
💳 Оплата

Переведите {price} ₽ на карту:
`2200 7021 1888 7905`
Получатель: Кирилл Т.

⭐️ {stars} звёзд

После оплаты нажмите кнопку ниже и отправьте скриншот
                """,
                reply_markup=get_payment_keyboard()
            )
            return WAITING_SCREENSHOT
            
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return ENTERING_CUSTOM_STARS

async def gift_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip().replace('@', '')
    stars = context.user_data['stars']
    price = context.user_data['amount']
    
    context.user_data['gift_username'] = username
    
    await update.message.reply_text(
        f"""
🎁 Подарок для @{username}

💳 Оплата

Переведите {price} ₽ на карту:
`2200 7021 1888 7905`
Получатель: Кирилл Т.

Почему перевод? 

🇷🇺 Работаем без ИП и юридических лиц
💰 Предлагаем вам лучшие цены (без налогов)
⚡️ Моментальное зачисление средств
🔒 Безопасность ваших данных
🤝 Личный подход к каждому клиенту

⭐️ {stars} звёзд (подарок)

После оплаты нажмите кнопку ниже и отправьте скриншот
        """,
        reply_markup=get_payment_keyboard()
    )
    return WAITING_SCREENSHOT

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    
    if not update.message.photo:
        await update.message.reply_text("❌ Пожалуйста, отправьте фото (скриншот)")
        return WAITING_SCREENSHOT
    
    stars = context.user_data['stars']
    amount = context.user_data['amount']
    gift_for = context.user_data.get('gift_username')
    
    photo = update.message.photo[-1]
    
    order = db.add_order(
        user_id=user_id,
        username=username,
        stars=stars,
        amount=amount,
        screenshot_id=photo.file_id,
        gift_for=gift_for
    )
    
    admin_text = f"""
💰 НОВЫЙ ПЛАТЁЖ #{order['id']} 💰

👤 Покупатель: @{username}
🆔 User ID: `{user_id}`
{f'🎁 Подарок для: @{gift_for}' if gift_for else ''}
⭐️ Звёзд: {stars}
💵 Сумма: {amount} ₽
📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}

━━━━━━━━━━━━━━━━━━━━━
⬇️ ДЕЙСТВИЕ ⬇️
    """
    
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo.file_id,
        caption=admin_text,
        reply_markup=get_admin_order_keyboard(order['id'])
    )
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 Поступил новый заказ #{order['id']}! Нажми кнопки под фото выше 👆",
        reply_markup=get_admin_panel_keyboard()
    )
    
    await update.message.reply_text(
        f"""
✅ Скриншот получен!

⏳ Менеджер проверит оплату в течение 5-20 минут

📢 Не забудьте подписаться на канал: {CHANNEL_LINK}
{f'🎁 Подарок для @{gift_for} будет активирован после проверки' if gift_for else ''}

⏰ Если через 20 минут статус не изменится - напишите @{SUPPORT_USERNAME}
        """,
        reply_markup=get_support_keyboard()
    )
    
    db.clear_pending(user_id)
    context.user_data.clear()
    
    return ConversationHandler.END

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет прав администратора")
        return
    
    text = """
👑 АДМИН-ПАНЕЛЬ 👑

Выберите действие:
    """
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard())

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Действие отменено", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Пожалуйста, используйте кнопки меню для заказа")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Используйте кнопки меню")

# ==================== ЗАПУСК ====================
def main():
    print("="*50)
    print("🚀 ЗАПУСК БОТА ДЛЯ ПРОДАЖИ ЗВЁЗД")
    print("="*50)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"📢 Канал: {CHANNEL_LINK}")
    print(f"💰 Цена звезды: {STAR_PRICE} ₽")
    print(f"⭐️ Мин. покупка: {MIN_STARS} звёзд")
    print("="*50)
    
    # Запускаем автопинг в отдельном потоке
    pinger = AutoPinger(BOT_TOKEN)
    ping_thread = threading.Thread(target=pinger.start_pinging, daemon=True)
    ping_thread.start()
    
    # Проверка токена
    if BOT_TOKEN == "8076134858:AAHj1rCv7bqD23KZ2oRzhSx92THq67UyKi4":
        print("❌ ОШИБКА: Токен недействителен!")
        print("👉 Токен уже заменен на правильный?")
        return
    
    # Создаём приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Создаём ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback)],
        states={
            ENTERING_CUSTOM_STARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_stars)],
            ENTERING_GIFT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_username)],
            WAITING_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("✅ Бот готов к работе!")
    print("⏰ Автопинг будет каждые 10 минут")
    print("="*50)
    
    # Запускаем бота
    application.run_polling()

if __name__ == "__main__":
    main()
import asyncio
import sys
import random
import string
import aiomysql
from vkbottle.bot import Bot, Message
from loguru import logger

# Настройка логирования через loguru (устраняет конфликт с vkbottle)
logger.remove()
logger.add(sys.stderr, level="INFO")

# Глобальная переменная для пула БД (чтобы не пересоздавать подключения каждые 2 секунды)
db_pool = None

# --- НАСТРОЙКИ ---
VK_TOKEN = "vk1.a.H1rjLQfSqO5dsC2zeIX-GqTK0OlcrEX55_8HZKIVNmXrhBVK7vzFnI7OOq-yvIJqWNm3MNe4PDW1yn2iVZO_cWNGV2R97nddUQc1Xdtmi9x0Ign1NMNztxO9QjuE0a4Al1ZEY1U-Uo09j5vAD12xRHyf50anP625Z2QHGfeO7jyZvohZh88YhAb-1d7ycJNpu7Ck8np6acFF1I42QSqhVQ"
DB_CONFIG = {
    "host": "80.242.59.112",  # Удаленный хост базы данных
    "user": "gs330867",
    "password": "HeZ5icJZQtXW",
    "db": "gs330867",
    "autocommit": True
}
SERVER_NAME = "TEST SERVER"
# ------------------

bot = Bot(token=VK_TOKEN)

# Функция для генерации случайного цифрового кода (Первая цифра строго от 1 до 9)
def generate_login_code(length=4):
    first_digit = random.choice("123456789")  # Исключаем 0 для первой цифры
    other_digits = ''.join(random.choice(string.digits) for _ in range(length - 1))
    return first_digit + other_digits

# --- ФОНОВАЯ ФУНКЦИЯ ЦИКЛИЧЕСКОЙ ПРОВЕРКИ БД ---
async def database_polling_loop():
    global db_pool
    while True:
        try:
            # Инициализируем пул подключений один раз при старте
            if db_pool is None:
                db_pool = await aiomysql.create_pool(**DB_CONFIG)

            async with db_pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    # Ищем аккаунты, требующие генерации кода для авторизации
                    await cur.execute("SELECT * FROM `accounts` WHERE `AloginGET` = 1")
                    accounts = await cur.fetchall()

                    for acc in accounts:
                        vk_id = acc.get("AloginVK")
                        if not vk_id or vk_id == 0:
                            continue

                        last_ip = acc.get("AloginIP", "0.0.0.0") 
                        conn_ip = acc.get("AloginCIP", "0.0.0.0") 
                        nickname = acc.get("name")  # Имя столбца изменено на "name"

                        auth_code = generate_login_code(4)

                        msg_text = (
                            f"Last IP: \"{last_ip}\" Connect IP: \"{conn_ip}\" "
                            f"Никнейм \"{nickname}\" Сервер \"{SERVER_NAME}\"\n"
                            f"Код для входа: {auth_code}"
                        )

                        try:
                            # Отправляем сообщение пользователю в VK
                            await bot.api.messages.send(
                                user_id=int(vk_id),
                                message=msg_text,
                                random_id=0
                            )
                            
                            # Записываем код в AloginSend и сбрасываем флаг AloginGET
                            await cur.execute(
                                "UPDATE `accounts` SET `AloginSend` = %s, `AloginGET` = 0 WHERE `id` = %s",
                                (auth_code, acc.get("id"))
                            )
                            logger.info(f"Код авторизации отправлен игроку {nickname} (VK: {vk_id})")

                        except Exception as vk_err:
                            logger.error(f"Не удалось отправить VK сообщение для {nickname}: {vk_err}")

        except Exception as db_err:
            logger.error(f"Ошибка в цикле опроса БД: {db_err}")
        
        # Задержка цикла опроса БД
        await asyncio.sleep(2)


# --- ОБРАБОТКА КОМАНД VK BOT ---

# Обработка команды "Начать"
@bot.on.private_message(text=["Начать", "начать"])
async def start_handler(message: Message):
    await message.answer(
        "Привет! Для привязки игрового аккаунта отправь мне 6-значный код, который ты получил в игре."
    )

# Обработка отправки 6-значного кода привязки
@bot.on.private_message()
async def code_handler(message: Message):
    global db_pool
    text = message.text.strip()
    
    if len(text) == 6 and text.isdigit():
        try:
            if db_pool is None:
                db_pool = await aiomysql.create_pool(**DB_CONFIG)

            async with db_pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    # Ищем аккаунты с таким AloginCode
                    await cur.execute("SELECT * FROM `accounts` WHERE `AloginCode` = %s", (text,))
                    acc = await cur.fetchone()

                    if acc:
                        nickname = acc.get("name")  # Имя столбца изменено на "name"
                        
                        # Обновляем данные аккаунта
                        await cur.execute(
                            "UPDATE `accounts` SET `AloginVK` = %s, `AloginCode` = 0 WHERE `id` = %s",
                            (message.from_id, acc.get("id"))
                        )
                        
                        await message.answer(
                            f"Аккаунт \"{nickname}\" на сервере \"{SERVER_NAME}\" успешно привязан!"
                        )
        except Exception as e:
            logger.error(f"Ошибка при обработке кода привязки: {e}")
    else:
        await message.answer("Неизвестная команда. Чтобы привязать аккаунт, введите 6-значный цифровой код из игры.")


# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    logger.info("Бот успешно запущен!")
    
    # Интегрируем фоновую задачу прямо в жизненный цикл vkbottle
    bot.loop_wrapper.add_task(database_polling_loop())
    
    # Запускаем бесконечный цикл работы бота
    bot.run_forever()

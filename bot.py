import asyncio
import sys
import time
import aiomysql
from vkbottle.bot import Bot, Message
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

db_pool = None
pending_registrations = {}

VK_TOKEN = "vk1.a.H1rjLQfSqO5dsC2zeIX-GqTK0OlcrEX55_8HZKIVNmXrhBVK7vzFnI7OOq-yvIJqWNm3MNe4PDW1yn2iVZO_cWNGV2R97nddUQc1Xdtmi9x0Ign1NMNztxO9QjuE0a4Al1ZEY1U-Uo09j5vAD12xRHyf50anP625Z2QHGfeO7jyZvohZh88YhAb-1d7ycJNpu7Ck8np6acFF1I42QSqhVQ"
DB_CONFIG = {
    "host": "80.242.59.112",
    "user": "gs330867",
    "password": "HeZ5icJZQtXW",
    "db": "gs330867",
    "autocommit": True
}
SERVER_NAME = "TEST SERVER"
REGISTRATION_TIMEOUT = 300

bot = Bot(token=VK_TOKEN)


async def database_polling_loop():
    global db_pool
    while True:
        try:
            if db_pool is None:
                db_pool = await aiomysql.create_pool(**DB_CONFIG)

            async with db_pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    current_time = time.time()
                    expired_ids = [
                        acc_id for acc_id, data in pending_registrations.items()
                        if current_time >= data["expires_at"]
                    ]
                    
                    for acc_id in expired_ids:
                        reg_data = pending_registrations.pop(acc_id)
                        await cur.execute(
                            "UPDATE `accounts` SET `AloginCode` = 0, `AloginGET` = 0 WHERE `id` = %s",
                            (acc_id,)
                        )
                        logger.info(
                            f"Время ожидания привязки истекло (5 мин) для {reg_data['name']} (ID: {acc_id}). Код сброшен."
                        )

                    await cur.execute("SELECT * FROM `accounts` WHERE `AloginGET` = 1")
                    accounts = await cur.fetchall()

                    for acc in accounts:
                        acc_id = acc.get("id")
                        vk_id = acc.get("AloginVK")
                        nickname = acc.get("name")

                        if not vk_id or int(vk_id) == 0:
                            reg_code = str(acc.get("AloginCode", "")).strip()
                            
                            if reg_code and reg_code != "0" and acc_id not in pending_registrations:
                                pending_registrations[acc_id] = {
                                    "code": reg_code,
                                    "expires_at": time.time() + REGISTRATION_TIMEOUT,
                                    "name": nickname
                                }
                                logger.info(
                                    f"[Регистрация] Ожидание кода ({reg_code}) от {nickname} (ID: {acc_id}) на 5 минут."
                                )
                        else:
                            conn_ip = acc.get("AloginCIP", "0.0.0.0")
                            auth_code = acc.get("AloginSend")

                            msg_text = (
                                f"Connect IP: \"{conn_ip}\" "
                                f"Никнейм \"{nickname}\" Сервер \"{SERVER_NAME}\"\n"
                                f"Код для входа: {auth_code}"
                            )

                            try:
                                await bot.api.messages.send(
                                    user_id=int(vk_id),
                                    message=msg_text,
                                    random_id=0
                                )

                                await cur.execute(
                                    "UPDATE `accounts` SET `AloginGET` = 0, `AloginCIP` = '0.0.0.0' WHERE `id` = %s",
                                    (acc_id,)
                                )
                                logger.info(
                                    f"[Авторизация] Код {auth_code} отправлен игроку {nickname} (VK: {int(vk_id)}). AloginCIP сброшен."
                                )

                            except Exception as vk_err:
                                logger.error(f"[Авторизация] Ошибка отправки сообщения для {nickname}: {vk_err}")

        except Exception as db_err:
            logger.error(f"Ошибка в цикле опроса БД: {db_err}")

        await asyncio.sleep(2)


@bot.on.private_message(text=["Начать", "начать"])
async def start_handler(message: Message):
    await message.answer(
        "Привет! Для привязки игрового аккаунта отправь мне 6-значный код, который ты получил в игре."
    )


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
                    await cur.execute(
                        "SELECT * FROM `accounts` WHERE `AloginCode` = %s AND `AloginGET` = 1 AND `AloginVK` = 0",
                        (text,)
                    )
                    acc = await cur.fetchone()

                    if acc:
                        acc_id = acc.get("id")
                        nickname = acc.get("name")
                        user_vk_id = int(message.from_id)

                        await cur.execute(
                            "UPDATE `accounts` SET `AloginVK` = %s, `AloginCode` = 0, `AloginGET` = 0, `AloginCIP` = '0.0.0.0' WHERE `id` = %s",
                            (user_vk_id, acc_id)
                        )
                        
                        pending_registrations.pop(acc_id, None)

                        await message.answer(
                            f"Аккаунт \"{nickname}\" на сервере \"{SERVER_NAME}\" успешно привязан!"
                        )
                        logger.info(f"[Регистрация] Игрок {nickname} (ID: {acc_id}) привязал VK ID: {user_vk_id}")

        except Exception as e:
            logger.error(f"Ошибка при обработке кода привязки: {e}")


if __name__ == "__main__":
    logger.info("Бот успешно запущен!")
    bot.loop_wrapper.add_task(database_polling_loop())
    bot.run_forever()

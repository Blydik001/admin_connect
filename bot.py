import asyncio
import sys
import time
import aiomysql
from vkbottle.bot import Bot, Message
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

VK_TOKEN = "vk1.a.H1rjLQfSqO5dsC2zeIX-GqTK0OlcrEX55_8HZKIVNmXrhBVK7vzFnI7OOq-yvIJqWNm3MNe4PDW1yn2iVZO_cWNGV2R97nddUQc1Xdtmi9x0Ign1NMNztxO9QjuE0a4Al1ZEY1U-Uo09j5vAD12xRHyf50anP625Z2QHGfeO7jyZvohZh88YhAb-1d7ycJNpu7Ck8np6acFF1I42QSqhVQ"
DB_CONFIG = {
    "host": "80.242.59.112",
    "user": "gs330867",
    "password": "HeZ5icJZQtXW",
    "db": "gs330867",
    "autocommit": True,
}
SERVER_NAME = "TEST SERVER"
REGISTRATION_TIMEOUT = 300

bot = Bot(token=VK_TOKEN)
db_pool: aiomysql.Pool | None = None
pending_registrations: dict[int, dict] = {}


async def get_db_pool() -> aiomysql.Pool:
    global db_pool
    if db_pool is None:
        db_pool = await aiomysql.create_pool(**DB_CONFIG)
    return db_pool


async def database_polling_loop() -> None:
    while True:
        try:
            pool = await get_db_pool()
            async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
                now = time.time()
                expired_ids = [
                    acc_id for acc_id, data in pending_registrations.items()
                    if now >= data["expires_at"]
                ]

                for acc_id in expired_ids:
                    reg_data = pending_registrations.pop(acc_id)
                    await cur.execute(
                        "UPDATE `accounts` SET `AloginCode` = 0, `AloginGET` = 0 WHERE `id` = %s",
                        (acc_id,),
                    )
                    logger.info(
                        f"Время ожидания привязки истекло для {reg_data['name']} (ID: {acc_id}). Код сброшен."
                    )

                await cur.execute("SELECT * FROM `accounts` WHERE `AloginGET` = 1")
                accounts = await cur.fetchall()

                for acc in accounts:
                    acc_id = acc["id"]
                    vk_id = int(acc.get("AloginVK") or 0)
                    nickname = acc["name"]

                    if vk_id == 0:
                        reg_code = str(acc.get("AloginCode") or "").strip()
                        if reg_code and reg_code != "0" and acc_id not in pending_registrations:
                            pending_registrations[acc_id] = {
                                "code": reg_code,
                                "expires_at": now + REGISTRATION_TIMEOUT,
                                "name": nickname,
                            }
                            logger.info(
                                f"[Регистрация] Ожидание кода ({reg_code}) от {nickname} (ID: {acc_id})."
                            )
                        continue

                    conn_ip = acc.get("AloginCIP", "0.0.0.0")
                    auth_code = acc.get("AloginSend")
                    msg_text = (
                        f'Connect IP: "{conn_ip}"\n'
                        f'Никнейм: "{nickname}"\n'
                        f'Сервер: "{SERVER_NAME}"\n'
                        f"Код для входа: {auth_code}"
                    )

                    try:
                        await bot.api.messages.send(
                            user_id=vk_id,
                            message=msg_text,
                            random_id=0,
                        )
                        await cur.execute(
                            "UPDATE `accounts` SET `AloginGET` = 0, `AloginCIP` = '0.0.0.0' WHERE `id` = %s",
                            (acc_id,),
                        )
                        logger.info(
                            f"[Авторизация] Код {auth_code} отправлен игроку {nickname} (VK: {vk_id})."
                        )
                    except Exception as vk_err:
                        logger.error(f"[Авторизация] Ошибка отправки для {nickname}: {vk_err}")

        except Exception as db_err:
            logger.error(f"Ошибка в цикле опроса БД: {db_err}")

        await asyncio.sleep(2)


@bot.on.private_message(func=lambda msg: len(msg.text.strip()) == 6 and msg.text.strip().isdigit())
async def handle_verification_code(message: Message) -> None:
    code = message.text.strip()
    user_vk_id = int(message.from_id)

    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn, conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT `id`, `name` FROM `accounts` "
                "WHERE `AloginCode` = %s AND `AloginGET` = 1 AND `AloginVK` = 0",
                (code,),
            )
            acc = await cur.fetchone()

            if not acc:
                return

            acc_id = acc["id"]
            nickname = acc["name"]

            await cur.execute(
                "UPDATE `accounts` "
                "SET `AloginVK` = %s, `AloginCode` = 0, `AloginGET` = 0, `AloginCIP` = '0.0.0.0' "
                "WHERE `id` = %s",
                (user_vk_id, acc_id),
            )
            pending_registrations.pop(acc_id, None)

            await message.answer(
                f"Вы успешно привязали аккаунт {nickname} на сервере {SERVER_NAME}."
            )
            logger.info(f"[Регистрация] Игрок {nickname} (ID: {acc_id}) привязал VK ID: {user_vk_id}")

    except Exception as e:
        logger.error(f"Ошибка при обработке кода привязки: {e}")


if __name__ == "__main__":
    logger.info("Бот запущен.")
    bot.loop_wrapper.add_task(database_polling_loop())
    bot.run_forever()

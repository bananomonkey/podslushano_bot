import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import CommandStart, Command, StateFilter, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, BotCommand, BotCommandScopeChat, BotCommandScopeDefault,
    MessageOriginUser,
)
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, SIGNATURE
from database import (
    init_db, add_post, get_post, update_post_status,
    save_dialog, get_dialog_user,
    add_subadmin, remove_subadmin, is_subadmin, get_subadmins,
)
from keyboards import (
    main_menu_kb, cancel_kb, moderation_kb, ModerationCB,
    admin_panel_kb, admin_remove_kb, AdminPanelCB, AdminRemoveCB,
)

# Публичные команды видят все пользователи.
PUBLIC_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
]
# Команды для админов — /admin виден только им.
ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="admin", description="Админ-панель"),
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()


# ---------- Состояния ----------

class SubmitPost(StatesGroup):
    waiting_content = State()


class ContactAdmin(StatesGroup):
    waiting_message = State()


class AddAdmin(StatesGroup):
    waiting_id = State()


# ---------- Проверка прав ----------

async def is_admin(user_id: int) -> bool:
    """Главный админ из конфига или суб-админ из базы."""
    return user_id == ADMIN_ID or await is_subadmin(user_id)


async def get_all_admin_ids() -> list[int]:
    """Список ID всех админов: главный + суб-админы."""
    sub_ids = await get_subadmins()
    return [ADMIN_ID] + [uid for uid in sub_ids if uid != ADMIN_ID]


# ---------- Кастомные фильтры ----------

class IsAdmin(Filter):
    """Пропускает только админов, возвращает флаг is_super."""
    async def __call__(self, event) -> bool | dict:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        if user.id == ADMIN_ID:
            return {"is_super": True}
        if await is_subadmin(user.id):
            return {"is_super": False}
        return False


class IsAdminDialogReply(Filter):
    async def __call__(self, message: Message):
        if not message.reply_to_message or not await is_admin(message.from_user.id):
            return False
        user_id = await get_dialog_user(message.reply_to_message.message_id)
        if not user_id:
            return False
        return {"dialog_user_id": user_id}


# ---------- Старт и меню ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    # Если админ запустил бота — гарантируем ему видимость /admin.
    if await is_admin(message.from_user.id):
        await set_admin_commands(message.bot, message.from_user.id)
    await message.answer(
        "👋 Привет! Это бот проекта <b>«Подслушано в Колледже»</b>.\n\n"
        "Здесь можно анонимно предложить пост в канал или написать администрации.",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "📝 Предложить пост")
async def btn_submit_post(message: Message, state: FSMContext):
    await state.set_state(SubmitPost.waiting_content)
    await message.answer(
        "Отправь текст, фото или видео для публикации.\n"
        "Пост будет опубликован <b>анонимно</b> после проверки администратором.",
        reply_markup=cancel_kb(),
    )


@router.message(F.text == "💬 Связь с админом")
async def btn_contact_admin(message: Message, state: FSMContext):
    await state.set_state(ContactAdmin.waiting_message)
    await message.answer(
        "Напиши сообщение администрации. Ответ придёт тебе через этого же бота.",
        reply_markup=cancel_kb(),
    )


@router.message(
    F.text == "❌ Отмена",
    StateFilter(SubmitPost.waiting_content, ContactAdmin.waiting_message, AddAdmin.waiting_id),
)
async def cancel_action(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu_kb())


# ---------- Ответ админа пользователю (диалог) ----------

@router.message(IsAdminDialogReply())
async def process_admin_reply(message: Message, dialog_user_id: int):
    try:
        await message.copy_to(dialog_user_id)
        await message.reply("✅ Ответ отправлен пользователю.")
    except TelegramForbiddenError:
        await message.reply("⚠️ Не удалось отправить — пользователь заблокировал бота.")
    except TelegramBadRequest as e:
        await message.reply(f"⚠️ Ошибка отправки: {e}")


# ---------- Приём поста от пользователя ----------

@router.message(
    SubmitPost.waiting_content,
    F.content_type.in_({ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO}),
)
async def process_new_post(message: Message, state: FSMContext):
    user = message.from_user

    if message.content_type == ContentType.TEXT:
        content_type, text_content, file_id = "text", message.text, None
    elif message.content_type == ContentType.PHOTO:
        content_type, text_content, file_id = "photo", message.caption, message.photo[-1].file_id
    else:
        content_type, text_content, file_id = "video", message.caption, message.video.file_id

    post_id = await add_post(user.id, user.full_name, content_type, text_content, file_id)

    info_text = (
        "🆕 <b>Новый пост на модерацию</b>\n\n"
        f"👤 Имя: {user.full_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Username: @{user.username if user.username else 'отсутствует'}"
    )

    delivered = 0
    for admin_id in await get_all_admin_ids():
        try:
            await message.bot.send_message(admin_id, info_text)
            await message.copy_to(admin_id, reply_markup=moderation_kb(post_id))
            delivered += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            continue

    if delivered == 0:
        await message.answer("⚠️ Не удалось отправить пост администратору. Попробуйте позже.")
        await state.clear()
        return

    await message.answer(
        "✅ Спасибо! Твой пост отправлен на модерацию.",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


@router.message(SubmitPost.waiting_content)
async def process_new_post_invalid(message: Message):
    await message.answer("Пожалуйста, отправь текст, фото или видео (или нажми «❌ Отмена»).")


# ---------- Сообщение администрации ----------

@router.message(ContactAdmin.waiting_message)
async def process_contact_admin(message: Message, state: FSMContext):
    user = message.from_user
    info_text = (
        "💬 <b>Сообщение от пользователя</b>\n\n"
        f"👤 Имя: {user.full_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Username: @{user.username if user.username else 'отсутствует'}\n\n"
        "Чтобы ответить — нажми «Ответить» (Reply) на следующее сообщение."
    )

    delivered = 0
    for admin_id in await get_all_admin_ids():
        try:
            await message.bot.send_message(admin_id, info_text)
            sent = await message.copy_to(admin_id)
            await save_dialog(sent.message_id, user.id)
            delivered += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            continue

    if delivered == 0:
        await message.answer("⚠️ Не удалось отправить сообщение администратору.")
        await state.clear()
        return

    await message.answer("✅ Сообщение отправлено администратору.", reply_markup=main_menu_kb())
    await state.clear()


# ---------- Модерация: публикация / отклонение ----------

async def publish_post(bot: Bot, post: dict) -> None:
    text_content = post["text_content"] or ""
    caption = (text_content + SIGNATURE) if text_content.strip() else SIGNATURE.strip()

    if post["content_type"] == "text":
        await bot.send_message(CHANNEL_ID, text_content + SIGNATURE)
    elif post["content_type"] == "photo":
        await bot.send_photo(CHANNEL_ID, post["file_id"], caption=caption)
    elif post["content_type"] == "video":
        await bot.send_video(CHANNEL_ID, post["file_id"], caption=caption)


@router.callback_query(ModerationCB.filter())
async def process_moderation(callback: CallbackQuery, callback_data: ModerationCB):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    post = await get_post(callback_data.post_id)
    if not post:
        await callback.answer("Пост не найден.", show_alert=True)
        return
    if post["status"] != "pending":
        await callback.answer("Пост уже обработан.", show_alert=True)
        return

    if callback_data.action == "approve":
        try:
            await publish_post(callback.bot, post)
        except TelegramForbiddenError:
            await callback.message.reply(
                "⚠️ Бот не добавлен в канал как администратор "
                "или у него нет права публикации сообщений."
            )
            await callback.answer()
            return
        except TelegramBadRequest as e:
            await callback.message.reply(f"⚠️ Ошибка публикации: {e}")
            await callback.answer()
            return

        await update_post_status(post["id"], "approved")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply("✅ Пост опубликован в канале.")
        await callback.answer("Опубликовано")

    else:  # reject
        await update_post_status(post["id"], "rejected")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.reply("❌ Пост отклонён.")
        await callback.answer("Отклонено")


# ---------- Админ-панель ----------

def admin_panel_text(is_super: bool) -> str:
    if is_super:
        role = "👑 Ты <b>главный администратор</b>."
    else:
        role = "👤 Ты <b>суб-администратор</b>."
    return f"🛠 <b>Админ-панель</b>\n\n{role}\n\nВыбери действие:"


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message, state: FSMContext, is_super: bool):
    await state.clear()
    await message.answer(admin_panel_text(is_super), reply_markup=admin_panel_kb(is_super))


@router.message(Command("admin"))
async def cmd_admin_denied(message: Message, state: FSMContext):
    # Для не-админов команда должна быть невидимой — молча игнорируем.
    await state.clear()


@router.callback_query(AdminPanelCB.filter(), IsAdmin())
async def process_admin_panel(
    callback: CallbackQuery, callback_data: AdminPanelCB, state: FSMContext, is_super: bool
):
    action = callback_data.action

    if action == "close":
        await state.clear()
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        return

    if action == "back":
        await state.clear()
        await callback.message.edit_text(
            admin_panel_text(is_super), reply_markup=admin_panel_kb(is_super)
        )
        await callback.answer()
        return

    if action == "list":
        subs = await get_subadmins()
        lines = [f"👑 <b>Главный админ:</b> <code>{ADMIN_ID}</code>"]
        if subs:
            lines.append("\n👤 <b>Суб-админы:</b>")
            lines.extend(f"• <code>{uid}</code>" for uid in subs)
        else:
            lines.append("\nСуб-админов пока нет.")
        try:
            await callback.message.edit_text(
                "\n".join(lines), reply_markup=admin_panel_kb(is_super)
            )
        except TelegramBadRequest:
            await callback.message.answer("\n".join(lines), reply_markup=admin_panel_kb(is_super))
        await callback.answer()
        return

    # Добавление / удаление доступны только главному админу.
    if not is_super:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if action == "add":
        await state.set_state(AddAdmin.waiting_id)
        await callback.message.answer(
            "➕ <b>Добавление суб-админа</b>\n\n"
            "Перешли мне любое сообщение от этого пользователя "
            "или отправь его числовой ID.\n\n"
            "Он сможет фильтровать и публиковать контент.",
            reply_markup=cancel_kb(),
        )
        await callback.answer()
        return

    if action == "remove":
        subs = await get_subadmins()
        if not subs:
            await callback.answer("Суб-админов пока нет.", show_alert=True)
            return
        try:
            await callback.message.edit_text(
                "➖ <b>Удаление суб-админа</b>\n\nВыбери, кого удалить:",
                reply_markup=admin_remove_kb(subs),
            )
        except TelegramBadRequest:
            await callback.message.answer(
                "➖ <b>Удаление суб-админа</b>\n\nВыбери, кого удалить:",
                reply_markup=admin_remove_kb(subs),
            )
        await callback.answer()


@router.callback_query(AdminRemoveCB.filter(), IsAdmin())
async def process_admin_remove(
    callback: CallbackQuery, callback_data: AdminRemoveCB, is_super: bool
):
    if not is_super:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    removed = await remove_subadmin(callback_data.user_id)
    # Возвращаем пользователю обычный список команд (скрываем /admin).
    await set_public_commands(callback.bot, callback_data.user_id)

    if removed:
        await callback.answer("Админ удалён.")
        await callback.message.edit_text(
            f"✅ Пользователь <code>{callback_data.user_id}</code> больше не админ.",
            reply_markup=admin_panel_kb(is_super),
        )
    else:
        await callback.answer("Пользователь не найден.", show_alert=True)


@router.message(AddAdmin.waiting_id)
async def process_add_admin(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await state.clear()
        await message.answer("Недостаточно прав.")
        return

    user_id = extract_forwarded_user_id(message)
    if user_id is None:
        text = (message.text or "").strip()
        if text.lstrip("-").isdigit():
            user_id = int(text)

    if user_id is None:
        await message.answer(
            "Не понял. Перешли сообщение пользователя или отправь его числовой ID."
        )
        return

    if user_id == ADMIN_ID:
        await message.answer("Это главный администратор, он уже имеет полный доступ.")
        return

    await add_subadmin(user_id, message.from_user.id)
    await set_admin_commands(message.bot, user_id)
    await message.answer(
        f"✅ Пользователь <code>{user_id}</code> добавлен как суб-админ.\n"
        "Теперь он видит команду /admin и может модерировать посты.",
        reply_markup=admin_panel_kb(True),
    )
    await state.clear()


def extract_forwarded_user_id(message: Message) -> int | None:
    """Достаёт ID пользователя из пересланного сообщения (если скрыт — None)."""
    if getattr(message, "forward_from", None):
        return message.forward_from.id
    origin = getattr(message, "forward_origin", None)
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.id
    return None


async def set_admin_commands(bot: Bot, user_id: int) -> None:
    try:
        await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=user_id))
    except Exception as e:
        logger.warning(f"Не удалось установить команды для админа {user_id}: {e}")


async def set_public_commands(bot: Bot, user_id: int) -> None:
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeChat(chat_id=user_id))
    except Exception as e:
        logger.warning(f"Не удалось сбросить команды для {user_id}: {e}")


async def setup_bot_commands(bot: Bot) -> None:
    """Публичный список команд для всех + расширенный для админов."""
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        logger.warning(f"Не удалось установить публичные команды: {e}")

    for admin_id in await get_all_admin_ids():
        await set_admin_commands(bot, admin_id)


# ---------- Заглушка на прочие сообщения ----------

@router.message(StateFilter(None))
async def fallback(message: Message):
    await message.answer("Пожалуйста, используй кнопки меню ниже 👇", reply_markup=main_menu_kb())


# ---------- Точка входа ----------

async def main() -> None:
    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await setup_bot_commands(bot)

    try:
        chat = await bot.get_chat(CHANNEL_ID)
        logger.info(f"Канал доступен: {chat.title or chat.id}")
    except Exception as e:
        logger.warning(f"Не удалось проверить доступ к каналу: {e}")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

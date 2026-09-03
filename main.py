import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import CommandStart, StateFilter, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, SIGNATURE
from database import (
    init_db, add_post, get_post, update_post_status,
    save_dialog, get_dialog_user,
)
from keyboards import main_menu_kb, cancel_kb, moderation_kb, ModerationCB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()


# ---------- Состояния ----------

class SubmitPost(StatesGroup):
    waiting_content = State()


class ContactAdmin(StatesGroup):
    waiting_message = State()


# ---------- Кастомный фильтр: ответ админа в диалоге с пользователем ----------

class IsAdminDialogReply(Filter):
    async def __call__(self, message: Message):
        if message.from_user.id != ADMIN_ID or not message.reply_to_message:
            return False
        user_id = await get_dialog_user(message.reply_to_message.message_id)
        if not user_id:
            return False
        return {"dialog_user_id": user_id}


# ---------- Старт и меню ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
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


@router.message(F.text == "❌ Отмена", StateFilter(SubmitPost.waiting_content, ContactAdmin.waiting_message))
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

    try:
        await message.bot.send_message(ADMIN_ID, info_text)
        await message.copy_to(ADMIN_ID, reply_markup=moderation_kb(post_id))
    except TelegramForbiddenError:
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

    try:
        await message.bot.send_message(ADMIN_ID, info_text)
        sent = await message.copy_to(ADMIN_ID)
    except TelegramForbiddenError:
        await message.answer("⚠️ Не удалось отправить сообщение администратору.")
        await state.clear()
        return

    await save_dialog(sent.message_id, user.id)
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
    if callback.from_user.id != ADMIN_ID:
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

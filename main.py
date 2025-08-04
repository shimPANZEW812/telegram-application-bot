"""
Telegram application bot for processing user applications with moderator approval.

This bot asks a series of questions to the user via a simple questionnaire. Once all
answers are collected, the bot forwards the compiled application to a moderator
chat. Moderators can approve or reject the application by pressing inline buttons
attached to the forwarded message. Upon approval, the applicant receives a
confirmation message along with a link to a private channel. If rejected, the
moderator is prompted for a reason, which is relayed back to the applicant along
with guidance on resubmitting their application.

Environment variables used:
    BOT_TOKEN     – The Telegram bot token obtained from BotFather.
    MOD_CHAT_ID   – The ID of the moderator chat (a group or channel) where
                    applications should be sent and managed.
    CHANNEL_LINK  – The invitation link to the private channel that successful
                    applicants will receive.

To run this bot locally, set the above environment variables and execute:

    python3 main.py

This script uses the python-telegram-bot library (>= 20.0) for asynchronous
handling of Telegram messages and callback queries. See
https://docs.python-telegram-bot.org/ for more information on usage.
"""

import asyncio
import logging
import os
from typing import Dict, Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# Enable logging to stdout for debugging and visibility when hosted.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# Conversation state keys for storing user answers in context.user_data.
# Each key corresponds to a questionnaire question. The questionnaire now
# consists of four questions: age, prior experience, willingness to invest
# in supplies, and source of information about the team.
AGE_KEY = "age"
EXPERIENCE_KEY = "experience"
FINANCE_KEY = "finance"
SOURCE_KEY = "source"

# State to indicate that the moderator awaits a reason for rejection.
PENDING_REASON_KEY = "pending_reason"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /start command. Greets the user and begins the questionnaire."""
    user = update.effective_user
    # Reset user data for a fresh application.
    context.user_data.clear()
    # Send a welcome message introducing the project and describing
    # the benefits of joining. This message is separate from the first
    # questionnaire question so that it appears clearly before the user
    # begins answering.
    await update.message.reply_text(
        "Приветствуем тебя! С тобой бот Keepers Team.\n\n"
        "Мы открыли набор в нашу команду, работающую в сфере NFT‑подарков через Telegram.\n"
        "Уже сейчас ты можешь начать зарабатывать на одном из самых перспективных направлений\n\n"
        "🔺 Мы предлагаем одни из лучших условий на рынке:\n\n"
        "— 60% от оценки скупа — твоя чистая прибыль.\n"
        "Для ТОП‑воркеров предусмотрен индивидуальный процент и бонусные условия.\n\n"
        "— Пошаговые мануалы, основанные на реальном опыте.\n"
        "Также доступны обучающие методички\n\n"
        "— Постоянная поддержка от ТОПОВ\n\n"
        "📈 Благодаря нашей системе распределения процентов ты сможешь выстроить пассивный доход без ограничений — всё зависит только от твоего желания и активности.\n\n"
        "👥 Уже создавал или планируешь собрать собственную команду?\n"
        "Для филиалов и опытных воркеров — особые условия сотрудничества и поддержка на старте."
    )
    # Prompt the first question in a separate message.
    await update.message.reply_text(
        "Сколько вам лет?"
    )
    # Reset user questionnaire state. Use next_question to track the current question
    # and application_submitted flag to detect when the user has already submitted.
    context.user_data.clear()
    context.user_data["next_question"] = 1
    context.user_data["application_submitted"] = False
    logger.info("Started questionnaire for user %s (%s)", user.id, user.full_name)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles incoming text messages from users during the questionnaire. Depending
    on which question is pending, stores the response and asks the next question.
    """
    message = update.message
    user = update.effective_user
    if not message:
        return

    # If the user has already submitted their application, politely remind them
    # that their application is under review and ignore further input. This
    # prevents them from accidentally restarting the questionnaire while they
    # await a decision.
    if context.user_data.get("application_submitted"):
        await message.reply_text(
            "Ваша заявка отправлена на рассмотрение. Ментор ответит вам, как только примет решение."
        )
        logger.info("User %s sent message after submission; reminder sent.", user.id)
        return

    # Determine which question we expect next. Default to 1 if not set.
    question_number = context.user_data.get("next_question", 1)

    # Capture answer based on current question number and set up next question.
    if question_number == 1:
        # First question: Age
        context.user_data[AGE_KEY] = message.text.strip()
        context.user_data["next_question"] = 2
        await message.reply_text(
            "Уже работал в этой сфере?  Если да — где и с каким капиталом?\n"
            "Если нет — расскажи, в каких сферах у тебя был опыт\n"
            "(Одним сообщением)"
        )
        logger.info("Recorded age for user %s: %s", user.id, context.user_data[AGE_KEY])
    elif question_number == 2:
        # Second question: Prior experience and capital
        context.user_data[EXPERIENCE_KEY] = message.text.strip()
        context.user_data["next_question"] = 3
        await message.reply_text(
            "Готовы ли вы вложить 10–35 $ на оплату расходников?"
        )
        logger.info(
            "Recorded experience for user %s: %s", user.id, context.user_data[EXPERIENCE_KEY]
        )
    elif question_number == 3:
        # Third question: Willingness to invest in supplies
        context.user_data[FINANCE_KEY] = message.text.strip()
        context.user_data["next_question"] = 4
        await message.reply_text(
            "Ссылка на форум или источник, откуда вы о нас узнали\n"
            "(Одним сообщением)"
        )
        logger.info(
            "Recorded finance willingness for user %s: %s", user.id, context.user_data[FINANCE_KEY]
        )
    elif question_number == 4:
        # Fourth question: Source link or information
        context.user_data[SOURCE_KEY] = message.text.strip()
        # Questionnaire finished; send application to moderator chat and mark submitted.
        await send_application_to_moderators(update, context)
        context.user_data["next_question"] = None
        context.user_data["application_submitted"] = True
        logger.info(
            "Recorded source for user %s: %s", user.id, context.user_data[SOURCE_KEY]
        )
        # Do not send a follow‑up message here. Any subsequent user messages
        # will trigger a reminder via the application_submitted flag.
    else:
        # Unexpected input when not expecting any question; instruct to restart.
        await message.reply_text(
            "Неожиданный ввод. Пожалуйста, удалите переписку с ботом и начните заново командой /start."
        )
        logger.warning("User %s sent unexpected message: %s", user.id, message.text)


async def send_application_to_moderators(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Compiles the applicant's answers and sends them to the moderator chat with
    inline buttons for approval or rejection.
    """
    user = update.effective_user
    chat_id = os.getenv("MOD_CHAT_ID")
    if not chat_id:
        logger.error("MOD_CHAT_ID environment variable not set. Cannot forward application.")
        return

    answers = (
        f"<b>Новая заявка от пользователя:</b> @{user.username or user.id}\n"
        f"<b>ID:</b> {user.id}\n\n"
        f"<b>Сколько вам лет?</b> {context.user_data.get(AGE_KEY, '—')}\n"
        f"<b>Уже работал в этой сфере? Если да — где и с каким капиталом?\nЕсли нет — расскажи, в каких сферах у тебя был опыт</b>"
        f" {context.user_data.get(EXPERIENCE_KEY, '—')}\n"
        f"<b>Готовы ли вы вложить 10–35 $ на оплату расходников?</b> {context.user_data.get(FINANCE_KEY, '—')}\n"
        f"<b>Ссылка на форум или источник, откуда вы о нас узнали</b> {context.user_data.get(SOURCE_KEY, '—')}"
    )

    # Inline keyboard for moderator actions: accept or reject.
    keyboard = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"accept:{user.id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{user.id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the application to the moderator chat.
    try:
        await context.bot.send_message(
            chat_id=int(chat_id),
            text=answers,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info("Sent application from user %s to moderator chat", user.id)
        # Do not send a submission confirmation here. Subsequent messages from the
        # applicant will trigger a reminder via application_submitted flag in handle_message().
    except Exception as e:
        logger.exception("Failed to send application to moderator chat: %s", e)
        await update.message.reply_text(
            "Произошла ошибка при отправке заявки. Пожалуйста, попробуйте позже."
        )


async def handle_moderator_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles callback queries from inline buttons in the moderator chat. Depending
    on whether the moderator accepts or rejects, take appropriate action.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()  # Acknowledge the callback to Telegram.
    data = query.data or ""
    user_id_str = None
    action = None
    try:
        action, user_id_str = data.split(":", 1)
    except ValueError:
        logger.warning("Malformed callback data: %s", data)
        return

    chat_id_env = os.getenv("MOD_CHAT_ID")
    if not chat_id_env:
        logger.error("MOD_CHAT_ID not set; cannot process moderator callbacks.")
        return

    # Ensure callback originates from the configured moderator chat.
    if query.message and query.message.chat and (str(query.message.chat.id) != str(chat_id_env)):
        logger.warning(
            "Callback from unauthorized chat %s (expected %s)",
            query.message.chat.id,
            chat_id_env,
        )
        return

    # Convert to integer user ID.
    try:
        target_user_id = int(user_id_str)
    except ValueError:
        logger.error("Invalid user ID in callback: %s", user_id_str)
        return

    if action == "accept":
        await handle_accept(query, context, target_user_id)
    elif action == "reject":
        await handle_reject(query, context, target_user_id)
    else:
        logger.warning("Unknown callback action: %s", action)


async def handle_accept(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Handles acceptance of an application. Sends confirmation and channel link."""
    channel_link = os.getenv("CHANNEL_LINK")
    if not channel_link:
        logger.error("CHANNEL_LINK not set; cannot send channel invite to user.")
        channel_link = ""

    # Notify the applicant.
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "Удачной игры!\n"
                "#blood_play 🩸🎮\n\n"
                f"{channel_link}"
            ),
        )
        logger.info("Application accepted. Sent invitation to user %s", user_id)
    except Exception as e:
        logger.exception("Failed to send acceptance to user %s: %s", user_id, e)

    # Edit the moderator's message to indicate the outcome.
    try:
        await query.edit_message_text(
            text=f"Заявка от пользователя {user_id} принята.",
        )
    except Exception:
        # It's okay if we cannot edit; maybe the message was already edited.
        pass


async def handle_reject(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """
    Handles rejection of an application. Asks the moderator for a rejection reason
    and stores context so that the next message from this moderator will be
    treated as the reason.
    """
    moderator_id = query.from_user.id
    # Store pending reason in bot_data keyed by moderator ID so we know who owes a reason.
    context.bot_data.setdefault(PENDING_REASON_KEY, {})[moderator_id] = {
        "user_id": user_id,
        "original_message_id": query.message.message_id,
    }
    # Ask the moderator for the reason.
    await query.edit_message_text(
        text=(
            f"Отклонить заявку пользователя {user_id}.\n"
            "Пожалуйста, напишите причину отказа одним сообщением."
        )
    )
    logger.info(
        "Awaiting rejection reason from moderator %s for user %s",
        moderator_id,
        user_id,
    )


async def handle_moderator_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles text messages from moderators. If a moderator previously rejected an
    application, the next message is interpreted as the rejection reason and
    forwarded to the applicant.
    """
    moderator_id = update.effective_user.id
    pending = context.bot_data.get(PENDING_REASON_KEY, {}).get(moderator_id)
    if not pending:
        return  # Not expecting a reason from this moderator.

    reason_text = update.message.text.strip()
    user_id = pending["user_id"]
    original_message_id = pending["original_message_id"]

    # Send rejection reason to applicant.
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "Ваша заявка была отклонена. Причина:\n"
                f"{reason_text}\n\n"
                "Если вы хотите подать заявку повторно, удалите переписку с ботом и начните сначала.\n"
                "(Если бот не отвечает — убедитесь, что он не в чёрном списке.)"
            ),
        )
        logger.info("Sent rejection reason to user %s", user_id)
    except Exception as e:
        logger.exception("Failed to send rejection reason to user %s: %s", user_id, e)

    # Edit the moderator's message to indicate completion.
    try:
        chat_id_env = os.getenv("MOD_CHAT_ID")
        if chat_id_env:
            await context.bot.edit_message_text(
                chat_id=int(chat_id_env),
                message_id=original_message_id,
                text=f"Заявка пользователя {user_id} отклонена.",
            )
    except Exception:
        pass

    # Remove pending state.
    context.bot_data[PENDING_REASON_KEY].pop(moderator_id, None)


def _create_application(token: str) -> Application:
    """
    Helper to build and configure the Application instance with all handlers attached.

    This function isolates the setup of the Telegram bot so it can be run in a
    separate thread alongside a simple HTTP server. Passing in the token avoids
    capturing environment variables inside thread entry points.
    """
    application = Application.builder().token(token).build()

    # Attach command handlers and message handlers for the questionnaire.
    # Register handlers. Restrict the main questionnaire handler to private chats
    # to ensure moderator messages are not inadvertently processed.
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & (~filters.COMMAND),
            handle_message,
        )
    )
    # Handle callback queries from the moderator inline buttons.
    application.add_handler(CallbackQueryHandler(handle_moderator_callback))
    # Handle moderator replies containing rejection reasons. Scope the handler to the
    # moderator chat by ID so it only triggers in that chat. Note: using
    # `filters.Chat` with int(...) ensures the handler triggers only for the specified chat.
    mod_chat_id = int(os.getenv("MOD_CHAT_ID", "0"))
    if mod_chat_id != 0:
        application.add_handler(
            MessageHandler(filters.Chat(mod_chat_id) & filters.TEXT, handle_moderator_message),
        )
    return application


def _start_health_server() -> None:
    """Runs a simple Flask-based health check server.

    Render's free tier expects services to bind to an HTTP port. Starting a
    lightweight web server keeps the service alive and provides an endpoint
    that external uptime services can ping to prevent sleeping. This server
    runs in its own thread so that the Telegram bot can execute in the main
    thread without interference.
    """
    from flask import Flask

    http_app = Flask(__name__)

    @http_app.route("/")
    def index() -> str:
        return "OK"

    # Determine the port Render expects us to listen on. When running locally,
    # default to port 10000. On Render, the PORT environment variable is set
    # automatically. See: https://render.com/docs/web-services#port-binding
    port = int(os.getenv("PORT", "10000"))
    logger.info("Starting health check server on port %s", port)
    http_app.run(host="0.0.0.0", port=port)


def main() -> None:
    """
    Entry point for the application.

    This function starts two components:

    1. A background HTTP server used solely for health checks and keeping the
       Render service alive. It runs in a daemon thread so that it does not
       block the main execution flow. This server listens on the port defined
       by the PORT environment variable (or 10000 locally) and responds with
       "OK" on the root path.

    2. The Telegram bot itself, which runs in the main thread. Running the bot
       in the main thread avoids complications around event loop management in
       secondary threads and ensures proper signal handling. Because the Flask
       server runs in a separate thread, the bot can block on polling without
       preventing the HTTP server from handling requests.
    """
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable must be set.")

    import threading

    # Launch the health check server in a daemon thread. If this thread exits,
    # it will not prevent the application from shutting down. The server
    # continues to run while the bot polls for updates.
    http_thread = threading.Thread(target=_start_health_server, daemon=True)
    http_thread.start()

    # Build and configure the Telegram application in the main thread.
    application = _create_application(token)
    logger.info("Bot starting...")
    # Start polling for updates. Without specifying stop_signals, python-telegram-bot
    # installs handlers for SIGINT/SIGTERM in the main thread which is safe.
    # When running in the main thread on Render, these signals allow graceful
    # shutdowns if the platform terminates the process. If necessary, we could
    # pass stop_signals=None to disable signal handlers.
    application.run_polling()


if __name__ == "__main__":
    try:
        # Call main() directly without asyncio.run to avoid issues with closing the event loop.
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
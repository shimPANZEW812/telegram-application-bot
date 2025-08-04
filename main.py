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
AGE_KEY = "age"
EXPERIENCE_KEY = "experience"
FINANCE_KEY = "finance"

# State to indicate that the moderator awaits a reason for rejection.
PENDING_REASON_KEY = "pending_reason"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for the /start command. Greets the user and begins the questionnaire."""
    user = update.effective_user
    # Reset user data for a fresh application.
    context.user_data.clear()
    await update.message.reply_text(
        "Здравствуйте! Давайте начнём небольшую анкету.\n"
        "Пожалуйста, отвечайте на каждый вопрос одним сообщением.\n\n"
        "Сколько вам лет?"
    )
    # Record that we're waiting for the age answer next.
    context.user_data["next_question"] = 1
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

    # Determine which question we expect next. Default to 1 if not set.
    question_number = context.user_data.get("next_question", 1)

    # Capture answer based on current question number and set up next question.
    if question_number == 1:
        # First question: Age
        context.user_data[AGE_KEY] = message.text.strip()
        context.user_data["next_question"] = 2
        await message.reply_text(
            "Есть ли у вас опыт работы? Какой у вас стартовый капитал?"
        )
        logger.info("Recorded age for user %s: %s", user.id, context.user_data[AGE_KEY])
    elif question_number == 2:
        # Second question: Work experience and starting capital
        context.user_data[EXPERIENCE_KEY] = message.text.strip()
        context.user_data["next_question"] = 3
        await message.reply_text(
            "Есть ли у вас финансовая возможность покрыть расходы на расходники?"
        )
        logger.info(
            "Recorded experience for user %s: %s", user.id, context.user_data[EXPERIENCE_KEY]
        )
    elif question_number == 3:
        # Third question: Financial means to cover supplies
        context.user_data[FINANCE_KEY] = message.text.strip()
        # Questionnaire finished; send application to moderator chat.
        await send_application_to_moderators(update, context)
        # Clear the questionnaire state.
        context.user_data["next_question"] = None
        logger.info(
            "Recorded finance for user %s: %s", user.id, context.user_data[FINANCE_KEY]
        )
    else:
        # The user wrote something unexpected; instruct them to restart.
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
        f"<b>Есть ли у вас опыт работы? Какой у вас стартовый капитал?</b> {context.user_data.get(EXPERIENCE_KEY, '—')}\n"
        f"<b>Есть ли у вас финансовая возможность покрыть расходы на расходники?</b> {context.user_data.get(FINANCE_KEY, '—')}"
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
        sent_message = await context.bot.send_message(
            chat_id=int(chat_id),
            text=answers,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info("Sent application from user %s to moderator chat", user.id)
        # Optionally notify user that their application has been submitted.
        await update.message.reply_text(
            "Спасибо! Ваша заявка отправлена на рассмотрение. Ожидайте ответа."
        )
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


def main() -> None:
    """Starts the bot using polling."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable must be set.")

    application = Application.builder().token(token).build()

    # Handlers for the user questionnaire.
    application.add_handler(CommandHandler("start", start))
    # Text messages from normal chats go to handle_message.
    # Handle text messages from users (not commands). Callback queries are handled separately by
    # CallbackQueryHandler; they do not trigger message handlers in python‑telegram‑bot 22.x, so
    # there is no need to explicitly filter them out. Using only TEXT and ~COMMAND filters
    # prevents commands like /start from being treated as regular text.
    application.add_handler(
        MessageHandler(
            filters.TEXT & (~filters.COMMAND),
            handle_message,
        )
    )

    # Callback queries from moderator chat.
    application.add_handler(CallbackQueryHandler(handle_moderator_callback))
    # Moderator messages (rejection reasons).
    application.add_handler(
        MessageHandler(filters.ALL & filters.Chat(int(os.getenv("MOD_CHAT_ID", "0"))), handle_moderator_message),
    )

    # Start the bot.
    logger.info("Bot starting...")
    # run_polling is a blocking call that internally runs the event loop and handles graceful shutdown.
    application.run_polling()


if __name__ == "__main__":
    try:
        # Call main() directly without asyncio.run to avoid issues with closing the event loop.
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
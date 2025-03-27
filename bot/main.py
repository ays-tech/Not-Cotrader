import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler,filters,ConversationHandler
from telegram.error import BadRequest
from sqlalchemy.ext.asyncio import AsyncSession
from database.db import get_async_session, get_user, add_user, update_user_ai_mode
from bot.handlers.buy import buy_handler, buy_conv_handler
from bot.handlers.wallet import wallet_handler, wallet_callbacks
from bot.handlers.sell import sell_handler, sell_conv_handler
from bot.handlers.start import start_handler, start_callback_handler
from bot.handlers.settings import settings_handler  
from bot.handlers.help import handler as help_command_handler, callback_handler as help_callback_handler
from bot.handlers.settings import settings_command_handler, settings_callback_handler, settings_input_handler
from bot.handlers.positions import positions_handler
from bot.handlers.pnl import pnl_handler
from bot.handlers.token_list import token_list_handler
from bot.handlers.watchlist import watchlist_handler
from bot.handlers.feedback import feedback_conv_handler , feedback_handler
from bot.ai.agents.trading_agent import trading_agent
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage,SystemMessage
from bot.ai.prompts.trading_prompts import TRADING_PROMPT
from services.token_info import detect_chain 
from bot.handlers.token_details import token_details

load_dotenv()
# Configure logging to save to a file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),  # Save logs to bot.log
        logging.StreamHandler()          # Optional: Keep console output
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    logger.critical("TELEGRAM_TOKEN is missing from the environment!")
    sys.exit(1)


MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🟩 Buy", callback_data="buy"),
     InlineKeyboardButton("🟥 Sell", callback_data="sell")],
    [InlineKeyboardButton("Positions", callback_data="positions"),
     InlineKeyboardButton("Token List", callback_data="token_list")],
    [InlineKeyboardButton("P&L", callback_data="pnl"),
     InlineKeyboardButton("Watchlist", callback_data="watchlist")], 
    [InlineKeyboardButton("Wallet", callback_data="wallet"),
     InlineKeyboardButton("Settings", callback_data="settings"),
     InlineKeyboardButton("Feedback", callback_data="feedback")],
    [InlineKeyboardButton("Help", callback_data="help")]
])

async def toggle_ai_mode(user_id: int, sess: AsyncSession, current_mode: bool) -> bool:
    """Toggle AI mode in the database."""
    new_mode = not current_mode
    await update_user_ai_mode(user_id, sess, new_mode)
    return new_mode

async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    async with await get_async_session() as session:
        user = await get_user(user_id, session)
        if not user:
            await add_user(user_id, session)
            user = await get_user(user_id, session)
        new_mode = await toggle_ai_mode(user_id, session, user.ai_mode)
        
        if new_mode:
            await update.message.reply_text("AI Mode is now ON. Let’s chat!")
            state = {"messages": [SystemMessage(content=TRADING_PROMPT), HumanMessage(content="Hi")], "user_id": user_id}
            config = {"configurable": {"thread_id": str(user_id)}}
            logger.info(f"Invoking agent with state: {state}")
            try:
                result = await trading_agent.ainvoke(state, config)
                response = result["messages"][-1].content
                await update.message.reply_text(response, parse_mode="Markdown")
                context.user_data["ai_messages"] = result["messages"]
            except Exception as e:
                logger.error(f"Agent invocation failed: {str(e)}")
                await update.message.reply_text("Oops, AI hiccup! Try again.")
        else:
            await update.message.reply_text("AI Mode is now OFF. Back to normal bot mode.")
            context.user_data.pop("ai_messages", None)
            logger.info(f"User {user_id} toggled AI mode to OFF")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Central dispatcher for text messages."""
    user_id = update.effective_user.id
    user_input = update.message.text.strip()
    
    async with await get_async_session() as session:
        user = await get_user(user_id, session)
        if not user:
            logger.debug(f"User {user_id} not found")
            await update.message.reply_text("Please start the bot with /start first!")
            return

        if user.ai_mode:
            await handle_ai_message(update, context, user_id, user_input)
        else:
            # Try token details first; if not a token address, pass to other logic or ignore
            try:
                chain = detect_chain(user_input)
                await token_details(update, context)  # Call token_details directly
            except ValueError:
                logger.debug(f"Not a token address: {user_input}, no action taken")
                # Optionally add fallback logic for other text commands here
                # e.g., await some_other_handler(update, context)

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, user_input: str) -> None:
    """Handle AI mode messages."""
    logger.info(f"User {user_id} sent AI input: {user_input}")
    messages = context.user_data.get("ai_messages", [SystemMessage(content=TRADING_PROMPT)])
    messages.append(HumanMessage(content=user_input))
    state = {"messages": messages, "user_id": user_id}
    config = {"configurable": {"thread_id": str(user_id)}}
    
    try:
        result = await trading_agent.ainvoke(state, config)
        response = result["messages"][-1].content
        if not response:
            logger.warning(f"Empty response from agent for user {user_id}")
            await update.message.reply_text("Hmm, I’m stumped! Try again?")
            return
        context.user_data["ai_messages"] = result["messages"]
        await update.message.reply_text(response, parse_mode="Markdown")
        logger.info(f"Sent AI response to user {user_id}: {response}")
    except Exception as e:
        logger.error(f"Agent invocation failed for user {user_id}: {str(e)}")
        await update.message.reply_text("AI glitch! Let’s try that again.")

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the main menu display and basic button clicks.

    This function processes callback queries for the main menu, displaying the menu
    or redirecting to specific handlers based on the button clicked.

    Args:
        update (Update): The Telegram update object containing the callback query.
        context (ContextTypes.DEFAULT_TYPE): The Telegram context object.

    Returns:
        None

    Notes:
        - Logs user interactions and warns on unknown callback data.
        - Provides a fallback message for unhandled options.
    """
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        await query.edit_message_text("Welcome to Not-Cotrader! Choose an option:", reply_markup=MAIN_MENU)
        logger.info(f"User {update.effective_user.id} returned to main menu")
    elif query.data == "buy":
        await buy_handler(update, context)  # Delegate to buy_handler
    elif query.data == "sell":
        await sell_handler(update, context)  # Delegate to sell_handler
    elif query.data == "settings":
        await settings_handler(update, context)
    elif query.data == "wallet":
        await wallet_handler(update, context)
    elif query.data == "positions":
        await positions_handler(update, context)
    elif query.data == "pnl":
        await pnl_handler(update, context)
    elif query.data == "token_list":
        await token_list_handler(update, context)
    elif query.data == "help":
        await help_callback_handler(update, context)
    elif query.data == "feedback":
        await feedback_handler(update, context)
    else:
        logger.warning(f"Unknown callback data: {query.data}")
        await query.edit_message_text("Invalid option. Use the menu below.", reply_markup=MAIN_MENU)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle uncaught exceptions and notify the user, suppressing 'Message is not modified' errors.

    This function logs errors and sends an error message to the user, while ignoring
    non-critical Telegram BadRequest errors related to unchanged messages.

    Args:
        update (Update): The Telegram update object (may be None).
        context (ContextTypes.DEFAULT_TYPE): The Telegram context object containing the error.

    Returns:
        None

    Notes:
        - Logs full exception details with stack traces for debugging.
        - Handles both callback queries and message updates appropriately.
    """
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        logger.debug("Suppressed 'Message is not modified' error")
        return

    logger.error(f"Exception occurred: {context.error}", exc_info=True)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("An error occurred. Please try again later.", parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text("An error occurred. Please try again later.", parse_mode="Markdown")
    else:
        logger.warning("Update object has no query or message to respond to.")

def main() -> None:
    """
    Initialize and run the Telegram bot.

    This function sets up the Telegram bot application, registers all handlers,
    and starts the polling loop with job queue support.

    Returns:
        None

    Raises:
        Exception: If bot initialization or polling fails (logged as critical).

    Notes:
        - Registers handlers in a specific order: specific handlers first, catch-all last.
        - Starts the job queue for scheduled tasks.
    """
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # Register handlers
        app.add_handler(CommandHandler("ai", ai_command))
        app.add_handler(start_handler)
        app.add_handler(feedback_conv_handler)
        app.add_handler(start_callback_handler)
        app.add_handler(wallet_handler)
        for callback in wallet_callbacks:
            app.add_handler(callback)
        app.add_handler(buy_conv_handler)
        app.add_handler(sell_conv_handler)
        app.add_handler(watchlist_handler)
        # Single text message handler more robust handler coming
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
        app.add_handler(help_command_handler)
        app.add_handler(help_callback_handler)
        app.add_handler(settings_command_handler)
        app.add_handler(settings_callback_handler)
        app.add_handler(settings_input_handler)
        app.add_handler(positions_handler)
        app.add_handler(pnl_handler)
        app.add_handler(token_list_handler)
        app.add_handler(CallbackQueryHandler(main_menu_handler))
        # Error handler
        app.add_error_handler(error_handler)

        # Initialize the job queue
        app.job_queue.start() 

        logger.info("Bot starting with job queue enabled...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.critical(f"Failed to start bot: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()
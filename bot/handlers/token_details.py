import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters
from services.token_info import get_token_info, format_token_info, detect_chain
from services.wallet_management import get_wallet

logger = logging.getLogger(__name__)

async def token_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text input of a token address, display minimal token details."""
    user_input = update.message.text.strip()
    user_id = str(update.effective_user.id)

    try:
        chain = detect_chain(user_input)
        token_info = await get_token_info(user_input)
        if not token_info:
            await update.message.reply_text("Couldn’t fetch token info. Check the address and try again.")
            return

        # Stubbed wallet balance for now
        wallet = get_wallet(user_id, chain)
        balance = 0.05 if chain == "solana" else 0.1  # Stub; replace with real balance later

        formatted_info = await format_token_info(token_info, chain, balance)
        amounts = [0.01, 0.02, 0.03, 0.04, 0.05] if chain == "solana" else [0.02, 0.04, 0.06, 0.08, 0.1]
        keyboard = [
            [InlineKeyboardButton(f"{amt} {chain.upper()}", callback_data=f"buy_{amt}") for amt in amounts],
            [InlineKeyboardButton(f"Buy {amounts[0]} {chain.upper()}", callback_data=f"buy_{amounts[0]}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(formatted_info, reply_markup=reply_markup, parse_mode="Markdown")
        context.user_data["token_info"] = token_info  # Store for buy action
        logger.info(f"Displayed token details for {user_input} to user {user_id}")

    except ValueError:
        await update.message.reply_text("Invalid token address. Please provide a valid Solana or TON address.")
    except Exception as e:
        logger.error(f"Error in token_details for {user_id}: {str(e)}")
        await update.message.reply_text("An error occurred. Try again later.")

token_details_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, token_details)
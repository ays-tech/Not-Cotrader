import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

# Default chain-specific settings
DEFAULT_TON_SETTINGS = {
    "buy_settings": {
        "presets": [1, 4, 5, 10],  # in TON
        "slippage": 1  # in percentage (single value)
    },
    "sell_settings": {
        "percentages": [25, 50, 70, 100],  # in percentage
        "slippage": 1  # in percentage (single value)
    }
}

DEFAULT_SOLANA_SETTINGS = {
    "buy_settings": {
        "presets": [0.1, 0.5, 1, 1.5],  # in SOL
        "slippage": 1  # in percentage (single value)
    },
    "sell_settings": {
        "percentages": [25, 50, 70, 100],  # in percentage
        "slippage": 1  # in percentage (single value)
    }
}

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to choose which chain's settings to edit."""
    user_id = str(update.effective_user.id)

    if "settings" not in context.user_data:
        context.user_data["settings"] = {
            "ton": DEFAULT_TON_SETTINGS.copy(),
            "solana": DEFAULT_SOLANA_SETTINGS.copy()
        }

    keyboard = [
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        [InlineKeyboardButton("TON Settings", callback_data="chain_settings_ton"),
         InlineKeyboardButton("Solana Settings", callback_data="chain_settings_solana")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            "⚙️ Which wallet’s settings would you like to edit?",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            "⚙️ Which wallet’s settings would you like to edit?",
            reply_markup=reply_markup
        )

    logger.info(f"Prompted user {user_id} to choose settings chain")

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings menu interactions."""
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)

    # Initialize settings if not present
    if "settings" not in context.user_data:
        context.user_data["settings"] = {
            "ton": DEFAULT_TON_SETTINGS.copy(),
            "solana": DEFAULT_SOLANA_SETTINGS.copy()
        }
    settings = context.user_data["settings"]

    data = query.data
    chain = context.user_data.get("current_chain")

    if data.startswith("chain_settings_"):
        chain = data.split("_")[2]
        context.user_data["current_chain"] = chain
        await show_chain_settings_menu(query, context, chain)
        logger.info(f"User {user_id} selected {chain} settings")

    elif data == "set_buy_settings":
        await show_buy_settings_menu(query, context, chain)

    elif data == "set_sell_settings":
        await show_sell_settings_menu(query, context, chain)

    elif data.startswith("edit_buy_preset_"):
        preset_index = int(data.split("_")[3])
        context.user_data["editing_buy_preset_index"] = preset_index
        await query.edit_message_text(
            f"Enter new buy preset value for {chain.upper()} (current: {settings[chain]['buy_settings']['presets'][preset_index]}):"
        )

    elif data == "edit_buy_slippage":
        context.user_data["editing_buy_slippage"] = True
        await query.edit_message_text(
            f"Enter new buy slippage value (%) for {chain.upper()} (current: {settings[chain]['buy_settings']['slippage']}):"
        )

    elif data.startswith("edit_sell_percent_"):
        percent_index = int(data.split("_")[3])
        context.user_data["editing_sell_percent_index"] = percent_index
        await query.edit_message_text(
            f"Enter new sell percentage value for {chain.upper()} (current: {settings[chain]['sell_settings']['percentages'][percent_index]}%):"
        )

    elif data == "edit_sell_slippage":
        context.user_data["editing_sell_slippage"] = True
        await query.edit_message_text(
            f"Enter new sell slippage value (%) for {chain.upper()} (current: {settings[chain]['sell_settings']['slippage']}):"
        )

    elif data == "settings_done":
        await query.edit_message_text(
            f"✅ {chain.capitalize()} settings saved! Use /settings to adjust anytime."
        )
        logger.info(f"User {user_id} saved {chain} settings: {settings[chain]}")
        del context.user_data["current_chain"]

    elif data == "settings_back":
        await settings_handler(update, context)

    else:
        await query.edit_message_text("Unknown option. Please try again.")
        logger.warning(f"User {user_id} selected unknown option: {data}")

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text input for editing presets, percentages, and slippages."""
    user_id = str(update.effective_user.id)
    chain = context.user_data.get("current_chain")
    if "settings" not in context.user_data:
        context.user_data["settings"] = {
            "ton": DEFAULT_TON_SETTINGS.copy(),
            "solana": DEFAULT_SOLANA_SETTINGS.copy()
        }
    settings = context.user_data["settings"]

    if "editing_buy_preset_index" in context.user_data:
        try:
            new_value = float(update.message.text)
            preset_index = context.user_data["editing_buy_preset_index"]
            settings[chain]["buy_settings"]["presets"][preset_index] = new_value
            del context.user_data["editing_buy_preset_index"]
            await update.message.reply_text(
                f"⚙️ Adjust your {chain.upper()} buy settings:",
                reply_markup=await show_buy_settings_menu(None, context, chain)
            )
            logger.info(f"User {user_id} updated {chain} buy preset {preset_index} to {new_value}")
        except ValueError:
            await update.message.reply_text("Please enter a valid number.")

    elif "editing_buy_slippage" in context.user_data:
        try:
            new_value = float(update.message.text)
            settings[chain]["buy_settings"]["slippage"] = new_value
            del context.user_data["editing_buy_slippage"]
            await update.message.reply_text(
                f"⚙️ Adjust your {chain.upper()} buy settings:",
                reply_markup=await show_buy_settings_menu(None, context, chain)
            )
            logger.info(f"User {user_id} updated {chain} buy slippage to {new_value}")
        except ValueError:
            await update.message.reply_text("Please enter a valid percentage.")

    elif "editing_sell_percent_index" in context.user_data:
        try:
            new_value = float(update.message.text)
            if 0 <= new_value <= 100:
                percent_index = context.user_data["editing_sell_percent_index"]
                settings[chain]["sell_settings"]["percentages"][percent_index] = new_value
                del context.user_data["editing_sell_percent_index"]
                await update.message.reply_text(
                    f"⚙️ Adjust your {chain.upper()} sell settings:",
                    reply_markup=await show_sell_settings_menu(None, context, chain)
                )
                logger.info(f"User {user_id} updated {chain} sell percentage {percent_index} to {new_value}")
            else:
                await update.message.reply_text("Please enter a percentage between 0 and 100.")
        except ValueError:
            await update.message.reply_text("Please enter a valid number.")

    elif "editing_sell_slippage" in context.user_data:
        try:
            new_value = float(update.message.text)
            settings[chain]["sell_settings"]["slippage"] = new_value
            del context.user_data["editing_sell_slippage"]
            await update.message.reply_text(
                f"⚙️ Adjust your {chain.upper()} sell settings:",
                reply_markup=await show_sell_settings_menu(None, context, chain)
            )
            logger.info(f"User {user_id} updated {chain} sell slippage to {new_value}")
        except ValueError:
            await update.message.reply_text("Please enter a valid percentage.")

async def show_chain_settings_menu(query, context: ContextTypes.DEFAULT_TYPE, chain: str) -> None:
    """Display chain-specific settings menu."""
    keyboard = [
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        [InlineKeyboardButton("Buy Settings", callback_data="set_buy_settings")],
        [InlineKeyboardButton("Sell Settings", callback_data="set_sell_settings")],
        [InlineKeyboardButton("Done", callback_data="settings_done")]
    ]

    await query.edit_message_text(
        f"⚙️ Adjust your {chain.upper()} trading settings below:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_buy_settings_menu(query, context: ContextTypes.DEFAULT_TYPE, chain: str) -> None:
    """Show buy settings menu with presets and single slippage in single buttons."""
    settings = context.user_data["settings"][chain]["buy_settings"]
    unit = "TON" if chain == "ton" else "SOL"
    
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    
    # Buy Presets
    keyboard.append([InlineKeyboardButton(f"Buy Presets ({unit}):", callback_data="noop")])
    for i, preset in enumerate(settings["presets"]):
        keyboard.append([
            InlineKeyboardButton(f"{preset} {unit} ✏️", callback_data=f"edit_buy_preset_{i}")
        ])
    
    # Buy Slippage
    keyboard.append([
        InlineKeyboardButton(f"Slippage: {settings['slippage']}% ✏️", callback_data="edit_buy_slippage")
    ])
    
    keyboard.append([InlineKeyboardButton("Back", callback_data="settings_back")])
    
    if query:
        await query.edit_message_text(
            f"⚙️ Adjust your {chain.upper()} buy settings:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return None
    else:
        return InlineKeyboardMarkup(keyboard)

async def show_sell_settings_menu(query, context: ContextTypes.DEFAULT_TYPE, chain: str) -> None:
    """Show sell settings menu with percentages and single slippage in single buttons."""
    settings = context.user_data["settings"][chain]["sell_settings"]
    
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    
    # Sell Percentages
    keyboard.append([InlineKeyboardButton(f"Sell Percentages:", callback_data="noop")])
    for i, percent in enumerate(settings["percentages"]):
        keyboard.append([
            InlineKeyboardButton(f"{percent}% ✏️", callback_data=f"edit_sell_percent_{i}")
        ])
    
    # Sell Slippage
    keyboard.append([
        InlineKeyboardButton(f"Slippage: {settings['slippage']}% ✏️", callback_data="edit_sell_slippage")
    ])
    
    keyboard.append([InlineKeyboardButton("Back", callback_data="settings_back")])
    
    if query:
        await query.edit_message_text(
            f"⚙️ Adjust your {chain.upper()} sell settings:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return None
    else:
        return InlineKeyboardMarkup(keyboard)

# Export handlers
settings_command_handler = CommandHandler("settings", settings_handler)
settings_callback_handler = CallbackQueryHandler(
    settings_callback,
    pattern=r"^(set_|chain_|edit_buy_|edit_sell_|settings_|main_menu)"
)
settings_input_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input)
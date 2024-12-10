import requests
import os
from datetime import datetime
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Telegram bot setup
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Webhook settings
WEBHOOK_HOST = "unuion-portfolio.onrender.com"  # Replace with your Render domain
WEBHOOK_PATH = f"/webhook"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

# API URL for fetching portfolio data
API_URL = "https://api2.icodrops.com/portfolio/api/portfolioGroup/individualShare/main-jni9xrqfbu"

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# Global variables
previous_portfolio = None
user_chat_id = None
application = None  # Make the application globally accessible

# Initialize the scheduler
scheduler = AsyncIOScheduler()

async def set_user_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the chat ID from the user sending a message."""
    global user_chat_id
    user_chat_id = update.message.chat_id
    logger.info(f"Chat ID set: {user_chat_id}")
    await context.bot.send_message(chat_id=user_chat_id, text="Chat ID set. You will now receive updates.")

async def send_telegram_message(app, message):
    """Send a message to the specified Telegram chat."""
    if user_chat_id:
        logger.info(f"Sending message to chat ID {user_chat_id}: {message}")
        await app.bot.send_message(chat_id=user_chat_id, text=message)
    else:
        logger.warning("No user chat ID set. Unable to send message.")

def fetch_portfolio():
    """Fetch the portfolio data from the API."""
    try:
        logger.debug(f"Fetching portfolio from {API_URL}")
        response = requests.get(API_URL)
        response.raise_for_status()
        portfolio = response.json()
        logger.info(f"Portfolio fetched successfully. Tokens in portfolio: {len(portfolio.get('portfolios', []))}")
        return portfolio
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching portfolio data: {e}")
        return None

def get_portfolio_summary(portfolio):
    """Generate a summary of the current portfolio."""
    excluded_symbols = {"USD", "USDT", "USDC"}
    summary = []

    logger.debug("Generating portfolio summary...")
    for token in portfolio.get("portfolios", []):
        if token["symbol"] in excluded_symbols:
            continue

        symbol = token["symbol"]
        total_invested = sum(
            float(tx["priceUsd"]) * float(tx["quantity"])
            for tx in token.get("transactions", [])
            if tx["transactionType"] == "BUY"
        )
        current_profit_usd = float(token.get("unrealizedProfit", {}).get("usd", 0))
        current_profit_percent = float(token.get("unrealizedProfitPercent", {}).get("usd", 0))

        summary.append(
            f"Symbol: {symbol}\n"
            f"Total Invested: {total_invested:.2f} USD\n"
            f"Current Profit: {current_profit_usd:.2f} USD ({current_profit_percent:.2f}%)\n"
        )
    logger.debug("Portfolio summary generated.")
    return "\n\n".join(summary)

async def update_portfolio():
    """Check for portfolio updates periodically and notify on changes."""
    global previous_portfolio, application
    logger.debug(f"[{datetime.now()}] Checking for portfolio updates...")

    current_portfolio = fetch_portfolio()
    if current_portfolio:
        logger.debug(f"Fetched portfolio. Tokens in portfolio: {len(current_portfolio.get('portfolios', []))}")
        logger.debug(f"Previous portfolio size: {len(previous_portfolio.get('portfolios', [])) if previous_portfolio else 'None'}")

        changes = analyze_changes(current_portfolio, previous_portfolio)
        if changes:
            logger.info(f"{len(changes)} changes detected. Sending updates.")
            for change in changes:
                logger.info(f"Change details: {change}")
                if user_chat_id:
                    await send_telegram_message(application, f"Portfolio Update:\n\n{change}")
                else:
                    logger.warning("No user chat ID set. Unable to send update.")
        else:
            logger.debug("No changes detected in portfolio.")
        previous_portfolio = current_portfolio
        logger.debug(f"Updated previous_portfolio state.")
    else:
        logger.error("Failed to fetch portfolio data during update check.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command to send the current portfolio summary and set the chat ID."""
    global user_chat_id, previous_portfolio
    user_chat_id = update.message.chat_id

    logger.info("/start command received. Fetching portfolio...")
    portfolio = fetch_portfolio()
    if portfolio:
        logger.info("Portfolio fetched successfully. Generating summary...")
        summary = get_portfolio_summary(portfolio)
        await context.bot.send_message(chat_id=user_chat_id, text=f"Portfolio Summary:\n\n{summary}")
        
        # Synchronize previous_portfolio
        previous_portfolio = portfolio
        logger.debug(f"Synchronized previous_portfolio.")
    else:
        logger.error("Failed to fetch portfolio data.")
        await context.bot.send_message(chat_id=user_chat_id, text="Failed to fetch portfolio data. Please try again later.")

async def webhook_handler(request):
    """Handle incoming webhook updates."""
    bot_application = request.app["bot_application"]
    update = await request.json()
    await bot_application.process_update(Update.de_json(update, bot_application.bot))
    return web.Response(text="OK")

async def main():
    """Main function to start the bot with webhook."""
    global application  # Declare application as global to make it accessible
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command and message handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_chat_id))

    logger.info("Initializing application...")
    await application.initialize()

    logger.info("Setting webhook...")
    await application.bot.set_webhook(url=WEBHOOK_URL)

    # Start the webhook server
    app = web.Application()
    app["bot_application"] = application
    app.router.add_post(WEBHOOK_PATH, webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8443)
    await site.start()

    scheduler.add_job(update_portfolio, "interval", minutes=2)
    scheduler.start()

    logger.info(f"Webhook listening at {WEBHOOK_URL}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

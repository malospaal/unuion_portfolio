import requests
from datetime import datetime
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from aiohttp import web

# Telegram bot setup
TELEGRAM_BOT_TOKEN = "7636233675:AAGwIkuHZV7n5ndyQ0DgiN5XfjPHHDXMpDA"

# Webhook settings
WEBHOOK_HOST = "https://broken-brook-58af.mr-kirindyasov28.workers.dev/"  # Replace with your domain or ngrok URL
WEBHOOK_PORT = 8443  # Standard port for HTTPS
WEBHOOK_PATH = f"/{TELEGRAM_BOT_TOKEN}"  # Unique path for webhook
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

# API URL for fetching portfolio data
API_URL = "https://api2.icodrops.com/portfolio/api/portfolioGroup/individualShare/main-jni9xrqfbu"

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Store the initial state of the portfolio
previous_portfolio = None
user_chat_id = None

async def set_user_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the chat ID from the user sending a message."""
    global user_chat_id
    user_chat_id = update.message.chat_id
    await context.bot.send_message(chat_id=user_chat_id, text="Chat ID set. You will now receive updates.")

async def send_telegram_message(application: Application, message):
    """Send a message to the specified Telegram chat."""
    if user_chat_id:
        await application.bot.send_message(chat_id=user_chat_id, text=message)
    else:
        print("No user chat ID set. Unable to send message.")

def fetch_portfolio():
    """Fetch the portfolio data from the API."""
    try:
        response = requests.get(API_URL)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching portfolio data: {e}")
        return None

def get_portfolio_summary(portfolio):
    """Generate a summary of the current portfolio."""
    excluded_symbols = {"USD", "USDT", "USDC"}
    summary = []

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

    return "\n\n".join(summary)

def analyze_changes(current_portfolio, previous_portfolio):
    """Analyze the portfolio for changes."""
    if previous_portfolio is None:
        print("Initial portfolio state loaded.")
        return []

    excluded_symbols = {"USD", "USDT", "USDC"}
    changes = []

    # Compare portfolios for changes
    for current_token in current_portfolio.get("portfolios", []):
        if current_token["symbol"] in excluded_symbols:
            continue

        prev_token = next((p for p in previous_portfolio.get("portfolios", []) if p["id"] == current_token["id"]), None)
        if not prev_token:
            for transaction in current_token.get("transactions", []):
                if transaction['transactionType'] == 'BUY':
                    changes.append(
                        f"BUY of {current_token['symbol']}\n"
                        f"Quantity: {float(transaction['quantity']):.2f}\n"
                        f"Price: {float(transaction['priceUsd']):.2f} USD\n"
                        f"Money spent: {float(transaction['quantity']) * float(transaction['priceUsd']):.2f} USD\n"
                        f"Remaining quantity: {float(current_token['quantity']):.2f}\n"
                    )
        else:
            # Check for changes in quantity
            quantity_diff = float(current_token["quantity"]) - float(prev_token["quantity"])

            # Handle BUY transactions
            if quantity_diff > 0:
                for transaction in current_token.get("transactions", []):
                    if transaction['transactionType'] == 'BUY' and float(transaction['quantity']) == quantity_diff:
                        changes.append(
                            f"BUY of {current_token['symbol']}\n"
                            f"Quantity: {float(transaction['quantity']):.2f}\n"
                            f"Price: {float(transaction['priceUsd']):.2f} USD\n"
                            f"Money spent: {float(transaction['quantity']) * float(transaction['priceUsd']):.2f} USD\n"
                            f"Remaining quantity: {float(current_token['quantity']):.2f}\n"
                        )

            # Handle SELL transactions
            if quantity_diff < 0:
                for transaction in current_token.get("transactions", []):
                    if transaction['transactionType'] == 'SELL' and float(transaction['quantity']) <= abs(quantity_diff):
                        changes.append(
                            f"SELL of {current_token['symbol']}\n"
                            f"Quantity: {float(transaction['quantity']):.2f}\n"
                            f"Price: {float(transaction['priceUsd']):.2f} USD\n"
                            f"Money received: {float(transaction['quantity']) * float(transaction['priceUsd']):.2f} USD\n"
                            f"Remaining quantity: {float(current_token['quantity']):.2f}\n"
                        )
                        quantity_diff += float(transaction['quantity'])  # Update to account for processed transaction

    # Check for removed tokens
    for prev_token in previous_portfolio.get("portfolios", []):
        if prev_token["symbol"] in excluded_symbols:
            continue

        if not any(p["id"] == prev_token["id"] for p in current_portfolio.get("portfolios", [])):
            changes.append(f"Token sold out: {prev_token['symbol']} (Symbol: {prev_token['symbol']})")

    return changes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command to set chat ID and fetch the portfolio summary."""
    global user_chat_id
    user_chat_id = update.message.chat_id

    print("/start command received. Fetching portfolio...")
    portfolio = fetch_portfolio()

    if portfolio:
        print("Portfolio fetched successfully. Generating summary...")
        summary = get_portfolio_summary(portfolio)
        await context.bot.send_message(chat_id=user_chat_id, text=f"Portfolio Summary:\n\n{summary}")
    else:
        print("Failed to fetch portfolio data.")
        await context.bot.send_message(chat_id=user_chat_id, text="Failed to fetch portfolio data. Please try again later.")
        
async def update_portfolio_manually(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually triggered update of portfolio."""
    global previous_portfolio
    print(f"[{datetime.now()}] Checking for updates manually...")
    current_portfolio = fetch_portfolio()

    if current_portfolio:
        changes = analyze_changes(current_portfolio, previous_portfolio)
        if changes:
            print("\nNew Changes Detected:")
            for change in changes:
                print(f"- {change}")
                if user_chat_id:
                    await context.bot.send_message(chat_id=user_chat_id, text=f"Update:\n\n{change}")
                else:
                    print("No user chat ID set. Unable to send update.")
        else:
            print("No changes detected.")
        previous_portfolio = current_portfolio
    else:
        print("Failed to fetch portfolio data.")
        
async def webhook_handler(request):
    """Handle incoming webhook updates."""
    bot_application = request.app["bot_application"]
    update = await request.json()
    await bot_application.process_update(Update.de_json(update, bot_application.bot))
    return web.Response(text="OK")

async def main():
    """Main function to start the bot with webhook."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("update", update_portfolio_manually))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_chat_id))

    # Set the webhook
    print("Setting webhook...")
    await application.bot.set_webhook(url=WEBHOOK_URL)

    # Start the webhook server
    app = web.Application()
    app["bot_application"] = application
    app.router.add_post(WEBHOOK_PATH, webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)
    await site.start()

    print(f"Webhook listening at {WEBHOOK_URL}")
    await asyncio.Event().wait()  # Keep the webhook server running

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

import asyncio
import os
import random
from typing import Dict, List, Set, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# Simple in-memory state: supports one active game and a lobby message
STATE = {
    "players": {},   # user_id -> {"name": str, "card": List[List[int]], "marks": Set[int]}
    "called": set(), # numbers drawn so far
    "draw_pool": list(range(1, 76)),
    "running": False,
    "lobby": {"chat_id": None, "message_id": None},
    "auto_draw": {"enabled": False, "interval": 30, "task": None},
}

TOKEN = os.environ.get("BINGO_TOKEN") or "PUT_YOUR_TOKEN_HERE"


def generate_card() -> List[List[int]]:
    # Standard 5x5 Bingo (B:1-15, I:16-30, N:31-45, G:46-60, O:61-75)
    card = []
    ranges = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75)]
    for col_idx, (a, b) in enumerate(ranges):
        col = random.sample(range(a, b + 1), 5)
        card.append(col)
    # build rows from columns
    rows = [[card[c][r] for c in range(5)] for r in range(5)]
    # center free
    rows[2][2] = 0
    return rows


def card_to_text(rows: List[List[int]], marks: Set[int]) -> str:
    lines = []
    header = " B  | I  | N  | G  | O "
    lines.append(header)
    lines.append("-" * len(header))
    for r in rows:
        line = []
        for v in r:
            if v == 0:
                s = " FS"  # free space
            else:
                s = f"{v:2d}"
            if v in marks or v == 0:
                s = f"[{s}]"
            else:
                s = f" {s} "
            line.append(s)
        lines.append("|".join(line))
    return "\n".join(lines)


def check_bingo(rows: List[List[int]], marks: Set[int]) -> bool:
    # treat 0 (free center) as always marked
    def marked(v):
        return v == 0 or v in marks

    # check rows
    for r in rows:
        if all(marked(v) for v in r):
            return True
    # check columns
    for c in range(5):
        if all(marked(rows[r][c]) for r in range(5)):
            return True
    # diagonals
    if all(marked(rows[i][i]) for i in range(5)):
        return True
    if all(marked(rows[i][4 - i]) for i in range(5)):
        return True
    return False


def build_lobby_text() -> str:
    n_players = len(STATE["players"])
    status = "running" if STATE["running"] else "idle"
    ad = STATE["auto_draw"]
    ad_status = f"on ({ad['interval']}s)" if ad["enabled"] else "off"
    return f"ATM Bingo — players: {n_players} | status: {status} | auto-draw: {ad_status}"


def build_lobby_keyboard() -> InlineKeyboardMarkup:
    ad = STATE["auto_draw"]
    ad_label = "Auto: On" if ad["enabled"] else "Auto: Off"
    kb = [
        [
            InlineKeyboardButton("Join", callback_data="join"),
            InlineKeyboardButton("Leave", callback_data="leave"),
            InlineKeyboardButton("Card", callback_data="card"),
        ],
        [
            InlineKeyboardButton("Start Game", callback_data="start"),
            InlineKeyboardButton("Draw", callback_data="draw"),
            InlineKeyboardButton("Called", callback_data="called"),
        ],
        [
            InlineKeyboardButton(ad_label, callback_data="autotoggle"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


async def post_or_update_lobby(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Post the lobby message if missing, otherwise update it."""
    text = build_lobby_text()
    keyboard = build_lobby_keyboard()
    lobby = STATE["lobby"]
    try:
        if lobby["chat_id"] == chat_id and lobby["message_id"]:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=lobby["message_id"],
                text=text,
                reply_markup=keyboard,
            )
        else:
            msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
            lobby["chat_id"] = chat_id
            lobby["message_id"] = msg.message_id
    except Exception:
        # in case message was deleted or bot cannot edit, try to send new lobby message
        msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        lobby["chat_id"] = chat_id
        lobby["message_id"] = msg.message_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to ATM Bingo! Use the buttons below to join, view your card, or start the game."
    )
    chat_id = update.effective_chat.id
    await post_or_update_lobby(context, chat_id)


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    if uid in STATE["players"]:
        await update.message.reply_text("You're already in the game.")
        return
    card = generate_card()
    STATE["players"][uid] = {"name": name, "card": card, "marks": set()}
    await update.message.reply_text(f"{name}, you've joined the game. Use the lobby buttons to view your card.")
    await post_or_update_lobby(context, update.effective_chat.id)


async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in STATE["players"]:
        STATE["players"].pop(uid)
        await update.message.reply_text("You left the game.")
    else:
        await update.message.reply_text("You are not in the game.")
    await post_or_update_lobby(context, update.effective_chat.id)


async def card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    p = STATE["players"].get(uid)
    if not p:
        await update.message.reply_text("You are not in the game. Use /join first.")
        return
    text = card_to_text(p["card"], p["marks"])
    # try to send privately; fall back to replying in chat
    try:
        await context.bot.send_message(chat_id=uid, text=f"Your card:\n{text}")
        await update.message.reply_text("I've sent your card to you privately.")
    except Exception:
        await update.message.reply_text(f"Your card:\n{text}")


async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if STATE["running"]:
        await update.message.reply_text("Game already running.")
        return
    if len(STATE["players"]) < 1:
        await update.message.reply_text("At least one player needed to start.")
        return
    STATE["running"] = True
    STATE["called"].clear()
    STATE["draw_pool"] = list(range(1, 76))
    random.shuffle(STATE["draw_pool"])
    await update.message.reply_text("Game started! Use Draw to draw numbers.")
    await post_or_update_lobby(context, update.effective_chat.id)
    # If auto-draw is enabled, start background loop
    if STATE["auto_draw"]["enabled"] and STATE["auto_draw"]["task"] is None:
        STATE["auto_draw"]["task"] = asyncio.create_task(auto_draw_loop(context, update.effective_chat.id))


async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not STATE["running"]:
        await update.message.reply_text("No game running — use /startgame to begin.")
        return
    if not STATE["draw_pool"]:
        await update.message.reply_text("All numbers drawn.")
        return
    n = STATE["draw_pool"].pop()
    STATE["called"].add(n)
    winners = []
    for uid, p in STATE["players"].items():
        # mark the number if present
        for r in p["card"]:
            for v in r:
                if v == n:
                    p["marks"].add(n)
        if check_bingo(p["card"], p["marks"]):
            winners.append(p["name"])
    text = f"Number drawn: {n}\nCalled so far: {sorted(STATE['called'])}\n"
    if winners:
        text += "BINGO! Winner(s): " + ", ".join(winners)
        STATE["running"] = False
    await update.message.reply_text(text)
    await post_or_update_lobby(context, update.effective_chat.id)


async def called_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Called numbers: {sorted(STATE['called'])}")


# --- Auto-draw implementation ---
async def auto_draw_loop(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        while STATE["auto_draw"]["enabled"] and STATE["running"]:
            interval = STATE["auto_draw"]["interval"]
            await asyncio.sleep(interval)
            # stop if conditions changed
            if not STATE["auto_draw"]["enabled"] or not STATE["running"]:
                break
            if not STATE["draw_pool"]:
                await context.bot.send_message(chat_id=chat_id, text="Auto-draw: all numbers drawn.")
                STATE["running"] = False
                break
            n = STATE["draw_pool"].pop()
            STATE["called"].add(n)
            winners = []
            for uid, p in STATE["players"].items():
                for r in p["card"]:
                    for v in r:
                        if v == n:
                            p["marks"].add(n)
                if check_bingo(p["card"], p["marks"]):
                    winners.append(p["name"])
            text = f"Auto-draw number: {n}\nCalled so far: {sorted(STATE['called'])}"
            if winners:
                text += "\nBINGO! Winner(s): " + ", ".join(winners)
                STATE["running"] = False
            await context.bot.send_message(chat_id=chat_id, text=text)
            await post_or_update_lobby(context, chat_id)
    except asyncio.CancelledError:
        # Task cancelled (auto-draw turned off)
        pass
    finally:
        STATE["auto_draw"]["task"] = None


# --- CallbackQuery handlers for inline buttons ---
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    chat_id = query.message.chat.id

    # Helper: check admin for actions
    async def is_admin(user_id: int) -> bool:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            return member.status in ("administrator", "creator")
        except Exception:
            return False

    if data == "join":
        if user.id in STATE["players"]:
            await query.answer(text="You're already in the game.", show_alert=False)
            return
        card = generate_card()
        STATE["players"][user.id] = {"name": user.first_name, "card": card, "marks": set()}
        await query.answer(text="You joined the game.")
        await post_or_update_lobby(context, chat_id)

    elif data == "leave":
        if user.id in STATE["players"]:
            STATE["players"].pop(user.id)
            await query.answer(text="You left the game.")
        else:
            await query.answer(text="You were not in the game.")
        await post_or_update_lobby(context, chat_id)

    elif data == "card":
        p = STATE["players"].get(user.id)
        if not p:
            await query.answer(text="You're not in the game.")
            return
        text = card_to_text(p["card"], p["marks"])
        # try private send
        try:
            await context.bot.send_message(chat_id=user.id, text=f"Your card:\n{text}")
            await query.answer(text="I've sent your card privately.")
        except Exception:
            # fallback to ephemeral alert with the card text trimmed
            await query.answer(text="Can't send private message — open a chat with the bot.")

    elif data == "start":
        # admin-only
        if not await is_admin(user.id):
            await query.answer(text="Only chat admins can start the game.")
            return
        if STATE["running"]:
            await query.answer(text="Game already running.")
            return
        if len(STATE["players"]) < 1:
            await query.answer(text="Need at least one player to start.")
            return
        STATE["running"] = True
        STATE["called"].clear()
        STATE["draw_pool"] = list(range(1, 76))
        random.shuffle(STATE["draw_pool"])
        await query.answer(text="Game started!")
        await post_or_update_lobby(context, chat_id)
        # start auto-draw if enabled
        if STATE["auto_draw"]["enabled"] and STATE["auto_draw"]["task"] is None:
            STATE["auto_draw"]["task"] = asyncio.create_task(auto_draw_loop(context, chat_id))

    elif data == "draw":
        # admin-only
        if not await is_admin(user.id):
            await query.answer(text="Only chat admins can draw numbers.")
            return
        if not STATE["running"]:
            await query.answer(text="No game running.")
            return
        if not STATE["draw_pool"]:
            await query.answer(text="All numbers drawn.")
            return
        n = STATE["draw_pool"].pop()
        STATE["called"].add(n)
        winners = []
        for uid, p in STATE["players"].items():
            for r in p["card"]:
                for v in r:
                    if v == n:
                        p["marks"].add(n)
            if check_bingo(p["card"], p["marks"]):
                winners.append(p["name"])
        text = f"Number drawn: {n}\nCalled so far: {sorted(STATE['called'])}"
        if winners:
            text += "\nBINGO! Winner(s): " + ", ".join(winners)
            STATE["running"] = False
        # Post result to chat
        await context.bot.send_message(chat_id=chat_id, text=text)
        await post_or_update_lobby(context, chat_id)
        await query.answer()

    elif data == "called":
        await query.answer()
        await context.bot.send_message(chat_id=chat_id, text=f"Called numbers: {sorted(STATE['called'])}")

    elif data == "autotoggle":
        # admin-only toggle
        if not await is_admin(user.id):
            await query.answer(text="Only chat admins can toggle auto-draw.")
            return
        # toggle
        STATE["auto_draw"]["enabled"] = not STATE["auto_draw"]["enabled"]
        if STATE["auto_draw"]["enabled"]:
            await query.answer(text=f"Auto-draw enabled ({STATE['auto_draw']['interval']}s)")
            # start task if game running
            if STATE["running"] and STATE["auto_draw"]["task"] is None:
                STATE["auto_draw"]["task"] = asyncio.create_task(auto_draw_loop(context, chat_id))
        else:
            # disable and cancel task
            task = STATE["auto_draw"].get("task")
            if task:
                task.cancel()
            STATE["auto_draw"]["task"] = None
            await query.answer(text="Auto-draw disabled")
        await post_or_update_lobby(context, chat_id)


# --- Auto-draw command handlers (admin-only for control) ---
async def autodraw_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    # admin check
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("Only chat admins can enable auto-draw.")
            return
    except Exception:
        await update.message.reply_text("Could not verify admin status.")
        return
    STATE["auto_draw"]["enabled"] = True
    await update.message.reply_text(f"Auto-draw enabled ({STATE['auto_draw']['interval']}s)")
    # start loop if game running
    if STATE["running"] and STATE["auto_draw"]["task"] is None:
        STATE["auto_draw"]["task"] = asyncio.create_task(auto_draw_loop(context, chat_id))
    await post_or_update_lobby(context, chat_id)


async def autodraw_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("Only chat admins can disable auto-draw.")
            return
    except Exception:
        await update.message.reply_text("Could not verify admin status.")
        return
    STATE["auto_draw"]["enabled"] = False
    task = STATE["auto_draw"].get("task")
    if task:
        task.cancel()
    STATE["auto_draw"]["task"] = None
    await update.message.reply_text("Auto-draw disabled")
    await post_or_update_lobby(context, chat_id)


async def autodraw_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ad = STATE["auto_draw"]
    await update.message.reply_text(f"Auto-draw: {'enabled' if ad['enabled'] else 'disabled'}; interval={ad['interval']}s")


async def autodraw_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("Only chat admins can set auto-draw interval.")
            return
    except Exception:
        await update.message.reply_text("Could not verify admin status.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /autodraw_set <seconds>")
        return
    try:
        sec = int(args[0])
        if sec < 5:
            await update.message.reply_text("Minimum interval is 5 seconds.")
            return
        STATE["auto_draw"]["interval"] = sec
        await update.message.reply_text(f"Auto-draw interval set to {sec}s")
    except ValueError:
        await update.message.reply_text("Please provide an integer number of seconds.")


# --- CallbackQuery handlers and commands registration ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers (kept for compatibility)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("card", card_cmd))
    app.add_handler(CommandHandler("startgame", startgame_cmd))
    app.add_handler(CommandHandler("draw", draw_cmd))
    app.add_handler(CommandHandler("called", called_cmd))

    # Auto-draw commands
    app.add_handler(CommandHandler("autodraw_on", autodraw_on))
    app.add_handler(CommandHandler("autodraw_off", autodraw_off))
    app.add_handler(CommandHandler("autodraw_status", autodraw_status))
    app.add_handler(CommandHandler("autodraw_set", autodraw_set))

    # CallbackQuery handler for inline buttons
    app.add_handler(CallbackQueryHandler(on_button))

    print("Starting bot (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()

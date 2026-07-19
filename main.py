import asyncio
import os
import random
from typing import Dict, List, Set

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Simple in-memory state: supports one active game
STATE = {
    "players": {},   # user_id -> {"name": str, "card": List[List[int]], "marks": Set[int]}
    "called": set(), # numbers drawn so far
    "draw_pool": list(range(1, 76)),
    "running": False,
}

TOKEN = os.environ.get("BINGO_TOKEN") or "PUT_YOUR_TOKEN_HERE"

def generate_card() -> List[List[int]]:
    # Standard 5x5 Bingo (B:1-15, I:16-30, N:31-45, G:46-60, O:61-75)
    card = []
    ranges = [(1,15), (16,30), (31,45), (46,60), (61,75)]
    for col_idx, (a,b) in enumerate(ranges):
        col = random.sample(range(a, b+1), 5)
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
    if all(marked(rows[i][4-i]) for i in range(5)):
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Bingo Bot! Commands:\n"
        "/join - join the current game\n"
        "/card - view your card\n"
        "/startgame - start drawing numbers (admin)\n"
        "/draw - draw next number (admin)\n"
        "/called - show called numbers\n"
        "/leave - leave the game\n"
    )

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    if uid in STATE["players"]:
        await update.message.reply_text("You're already in the game.")
        return
    card = generate_card()
    STATE["players"][uid] = {"name": name, "card": card, "marks": set()}
    await update.message.reply_text(f"{name}, you've joined the game. Use /card to see your Bingo card.")

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in STATE["players"]:
        STATE["players"].pop(uid)
        await update.message.reply_text("You left the game.")
    else:
        await update.message.reply_text("You are not in the game.")

async def card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    p = STATE["players"].get(uid)
    if not p:
        await update.message.reply_text("You are not in the game. Use /join first.")
        return
    text = card_to_text(p["card"], p["marks"])
    await update.message.reply_text(f"Your card:\n{text}")

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if STATE["running"]:
        await update.message.reply_text("Game already running.")
        return
    if len(STATE["players"]) < 1:
        await update.message.reply_text("At least one player needed to start.")
        return
    STATE["running"] = True
    STATE["called"].clear()
    STATE["draw_pool"] = list(range(1,76))
    random.shuffle(STATE["draw_pool"])
    await update.message.reply_text("Game started! Admin can draw numbers with /draw")

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not STATE["running"]:
        await update.message.reply_text("No game running — use /startgame to begin.")
        return
    if not STATE["draw_pool"]:
        await update.message.reply_text("All numbers drawn.")
        return
    n = STATE["draw_pool"].pop()
    STATE["called"].add(n)
    # Mark players' cards
    winners = []
    for uid, p in STATE["players"].items():
        # mark the number if present
        for r in p["card"]:
            for v in r:
                if v == n:
                    p["marks"].add(n)
        if check_bingo(p["card"], p["marks"]):
            winners.append(p["name"])
    text = f"Number drawn: {n}\n"
    text += f"Called so far: {sorted(STATE['called'])}\n"
    if winners:
        text += "BINGO! Winner(s): " + ", ".join(winners)
        STATE["running"] = False
    await update.message.reply_text(text)

async def called(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Called numbers: {sorted(STATE['called'])}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("card", card))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("draw", draw))
    app.add_handler(CommandHandler("called", called))

    print("Starting bot (polling)...")
    app.run_polling()

if __name__ == "__main__":
    main()

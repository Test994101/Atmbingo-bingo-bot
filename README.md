# ATM Bingo Bot

This repository contains a minimal, easy-to-run Telegram Bingo bot written in Python using python-telegram-bot.

Features
- In-memory single-game Bingo server (polling)
- Commands: /join, /leave, /card, /startgame, /draw, /called

Quick start (local)

1. Revoke/regenerate any bot tokens you posted publicly. Never commit tokens to source.
2. Create a Telegram bot and get its token from @BotFather.
3. Set the token in your environment:

   Linux/macOS:
   ```bash
   export BINGO_TOKEN="1234:ABCD..."
   ```

   Windows PowerShell:
   ```powershell
   $env:BINGO_TOKEN = "1234:ABCD..."
   ```

4. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\Activate
   pip install -r requirements.txt
   ```

5. Run the bot:

   ```bash
   python main.py
   ```

Notes
- The bot uses polling and stores all game state in memory. If the process restarts, games are lost.
- For production use, consider using webhooks (instead of polling) and add persistence (Redis or PostgreSQL) to support multiple concurrent games and survive restarts.
- The included Procfile is for Heroku (worker process since this bot uses polling).
- To run in Docker, see the Dockerfile.

Contributing
- Feel free to open issues or PRs. If you want multi-room support or persistent storage, tell me and I can add it.

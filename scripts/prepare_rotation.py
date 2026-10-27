"""Prepare private Railway imports. Never print credentials or send them anywhere."""
import getpass
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / ".secrets"
    outputs = [destination / name for name in (
        "railway-web.env", "railway-worker.env", "tradingview-alert.json"
    )]
    if any(path.exists() for path in outputs):
        raise SystemExit("Rotation files already exist; refusing to overwrite them.")
    token = getpass.getpass("NEW Telegram bot token (hidden; revoke old token in BotFather first): ").strip()
    chat_id = getpass.getpass("Existing Telegram chat ID (hidden): ").strip()
    if not token or ":" not in token or not chat_id or any(c in token + chat_id for c in "\r\n"):
        raise SystemExit("Invalid input; no files created.")
    webhook_secret = secrets.token_urlsafe(32)
    destination.mkdir(exist_ok=True, mode=0o700)
    contents = [
        f"TV_SECRET={webhook_secret}\n",
        f"TG_TOKEN={token}\nTG_CHAT_ID={chat_id}\n",
        json.dumps({
            "secret": webhook_secret, "strategy": "OpenBurst", "symbol": "{{ticker}}",
            "side": "BUY", "price": "{{close}}", "timeframe": "{{interval}}", "time": "{{time}}",
        }, indent=2) + "\n",
    ]
    for path, content in zip(outputs, contents):
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
        path.chmod(0o600)
    print("Prepared 3 private files in .secrets/. No credentials printed or uploaded.")
    print("Import railway-web.env into Web and railway-worker.env into Worker.")
    print("Update TradingView with tradingview-alert.json and the new webhook URL.")
    print("These files contain secrets. Keep them local; never attach them to chat.")


if __name__ == "__main__":
    main()

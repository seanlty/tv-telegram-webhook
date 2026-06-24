# tv-telegram-webhook

TradingView burst webhook for Zeabur:

```text
TradingView -> FastAPI /webhook -> Redis queue -> Worker batch -> Telegram
```

## Project Layout

```text
tv-telegram-webhook/
├─ src/
│  └─ main.py
├─ data/
│  ├─ raw/
│  └─ processed/
├─ notebooks/
├─ docs/
├─ tests/
├─ README.md
├─ requirements.txt
└─ .gitignore
```

The repository also keeps `Dockerfile.web` and `Dockerfile.worker` for Zeabur services.

## Environment Variables

Required:

```env
TV_SECRET=replace-with-a-long-random-secret
TG_TOKEN=telegram-bot-token
TG_CHAT_ID=telegram-chat-id
REDIS_CONNECTION_STRING=redis://...
```

Burst defaults:

```env
BATCH_SECONDS=2
BATCH_MAX=200
TELEGRAM_MIN_INTERVAL=1.1
DEDUP_TTL_SECONDS=300
QUEUE_KEY=tv:signals
DEDUP_PREFIX=tv:dedup:
```

Zeabur Redis usually provides `REDIS_CONNECTION_STRING` automatically.

## Local Run

Web service:

```bash
uvicorn src.main:app --reload
```

Worker:

```bash
python -m src.main worker
```

Smoke test, with local Redis running:

```bash
python tests/smoke_test.py
```

## TradingView Webhook

Webhook URL:

```text
https://your-zeabur-domain/webhook
```

Alert message:

```json
{
  "secret": "replace-with-TV_SECRET",
  "strategy": "OpenBurst",
  "symbol": "{{ticker}}",
  "side": "BUY",
  "price": "{{close}}",
  "timeframe": "{{interval}}",
  "time": "{{time}}"
}
```

Allowed sides are `BUY`, `SELL`, `LONG`, `SHORT`, and `EXIT`.

# tv-telegram-webhook

TradingView burst webhook for Zeabur:

```text
TradingView -> FastAPI /webhook -> Redis queue -> Worker batch -> Telegram
```

## Project Layout

```text
tv-telegram-webhook/
|-- src/
|   `-- main.py
|-- data/
|   |-- raw/
|   `-- processed/
|-- notebooks/
|-- docs/
|-- tests/
|-- README.md
|-- requirements.txt
`-- .gitignore
```

The root `Dockerfile` is the default Zeabur Web service image. The repository also keeps `Dockerfile.web` as an explicit Web copy and `Dockerfile.worker` for the background worker service.

## Zeabur Services

Create three services:

```text
Redis
Web service: Dockerfile
Worker service: Dockerfile.worker
```

The Web service should be public. The Worker service should not expose a public domain.

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

# tv-telegram-webhook

TradingView burst webhook for Railway (Python 3.11+):

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

The root `Dockerfile` builds Web. `Dockerfile.worker` builds the background worker.
`Dockerfile.web` remains an identical explicit Web alternative.

## Railway Services

Create three services:

```text
Redis
Web service: Dockerfile
Worker service: Dockerfile.worker
```

Connect Web and Worker to the same GitHub repository and migration branch.
Keep all three services in the same region, with one Worker replica and no sleeping.
Only Web needs a public domain. Redis needs a persistent `/data` volume and private networking.
See [deployment and credential rotation](docs/railway-migration.md) before cutting over.

## Environment Variables

Web requires a newly generated `TV_SECRET`. Worker requires a newly rotated
`TG_TOKEN` and the existing `TG_CHAT_ID`. Both require a Redis connection:

```env
TV_SECRET=replace-with-a-long-random-secret
TG_TOKEN=telegram-bot-token
TG_CHAT_ID=telegram-chat-id
REDIS_URL=${{Redis.REDIS_URL}}
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

Railway resolves the Redis reference. Do not copy the old Zeabur connection string.
`REDIS_CONNECTION_STRING` remains supported for legacy deployments and takes
precedence over `REDIS_URL`, so leave it unset on Railway.

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
https://your-railway-domain/webhook
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

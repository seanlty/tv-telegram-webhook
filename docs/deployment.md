# Zeabur Deployment

Create three services:

```text
Redis
Web service: Dockerfile.web
Worker service: Dockerfile.worker
```

Set these variables on both Web and Worker services:

```env
TV_SECRET=replace-with-a-long-random-secret
TG_TOKEN=telegram-bot-token
TG_CHAT_ID=telegram-chat-id
BATCH_SECONDS=2
BATCH_MAX=200
TELEGRAM_MIN_INTERVAL=1.1
DEDUP_TTL_SECONDS=300
```

The Redis template should provide `REDIS_CONNECTION_STRING`. If not, set `REDIS_URL`.

Use `Dockerfile.web` for the FastAPI service and `Dockerfile.worker` for the background worker.

Health check:

```text
GET https://your-zeabur-domain/
```

Expected response:

```json
{"ok": true, "service": "tv-webhook"}
```

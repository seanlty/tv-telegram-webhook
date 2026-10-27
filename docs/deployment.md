# Legacy Zeabur Deployment

For the current Railway deployment and secret rotation procedure, follow
[Railway migration](railway-migration.md). The steps below describe the old host.

Create three services:

```text
Redis
Web service: Dockerfile
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

Use the root `Dockerfile` for the FastAPI Web service. It is intentionally present because Zeabur looks for `Dockerfile` by default.

Use `Dockerfile.worker` for the background worker service, and keep that service private because it only consumes Redis queue messages and sends Telegram batches.

Health check:

```text
GET https://your-zeabur-domain/
```

Expected response:

```json
{"ok": true, "service": "tv-webhook"}
```

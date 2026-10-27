from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import signal
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from html import escape

import httpx
from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis


TV_SECRET = os.getenv("TV_SECRET", "")
TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

REDIS_URL = (
    os.getenv("REDIS_CONNECTION_STRING")
    or os.getenv("REDIS_URL")
    or "redis://localhost:6379/0"
)

QUEUE_KEY = os.getenv("QUEUE_KEY", "tv:signals")
DEDUP_PREFIX = os.getenv("DEDUP_PREFIX", "tv:dedup:")

BATCH_SECONDS = float(os.getenv("BATCH_SECONDS", "2"))
BATCH_MAX = int(os.getenv("BATCH_MAX", "200"))
DEDUP_TTL_SECONDS = int(os.getenv("DEDUP_TTL_SECONDS", "300"))
TELEGRAM_MIN_INTERVAL = float(os.getenv("TELEGRAM_MIN_INTERVAL", "1.1"))

VALID_SIDES = {"BUY", "SELL", "LONG", "SHORT", "EXIT"}

redis_client = Redis.from_url(REDIS_URL, decode_responses=True)

ENQUEUE_SIGNAL_LUA = """
if redis.call("SET", KEYS[1], "1", "NX", "EX", ARGV[1]) then
    redis.call("RPUSH", KEYS[2], ARGV[2])
    return 1
end

return 0
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if not TV_SECRET:
            raise RuntimeError("Missing TV_SECRET")
        await redis_client.ping()
        yield
    finally:
        await redis_client.aclose()


app = FastAPI(title="TradingView Telegram Webhook", lifespan=lifespan)


@app.get("/")
def health():
    return {"ok": True, "service": "tv-webhook"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")

    supplied_secret = data.get("secret")
    if not TV_SECRET or not isinstance(supplied_secret, str) or not secrets.compare_digest(
        supplied_secret.encode(), TV_SECRET.encode()
    ):
        raise HTTPException(status_code=403, detail="Invalid secret")

    symbol = str(data.get("symbol", "")).upper()
    side = str(data.get("side", "")).upper()
    strategy = str(data.get("strategy", "TradingView"))
    price = data.get("price")
    timeframe = str(data.get("timeframe", ""))
    alert_time = str(data.get("time", ""))

    if not symbol or side not in VALID_SIDES:
        raise HTTPException(status_code=400, detail="Invalid signal")

    raw_id = f"{strategy}|{symbol}|{side}|{timeframe}|{alert_time}|{price}"
    signal_id = hashlib.sha256(raw_id.encode()).hexdigest()
    dedup_key = DEDUP_PREFIX + signal_id

    signal_payload = {
        "id": signal_id,
        "received_at": time.time(),
        "strategy": strategy,
        "symbol": symbol,
        "side": side,
        "price": price,
        "timeframe": timeframe,
        "time": alert_time,
    }

    queued = await redis_client.eval(
        ENQUEUE_SIGNAL_LUA,
        2,
        dedup_key,
        QUEUE_KEY,
        DEDUP_TTL_SECONDS,
        json.dumps(signal_payload, ensure_ascii=False),
    )

    if not queued:
        return {"ok": True, "duplicate": True}

    return {"ok": True, "queued": True}


async def send_telegram(text: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        raise RuntimeError("Missing TG_TOKEN or TG_CHAT_ID")

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
        return response.json()


def format_batch(signals: list[dict]) -> str:
    grouped = defaultdict(list)

    for signal_payload in signals:
        grouped[signal_payload.get("side", "UNKNOWN")].append(signal_payload)

    lines = [
        "📡 <b>TradingView Burst 訊號</b>",
        f"本批次：{len(signals)} 筆",
        "",
    ]

    for side, items in grouped.items():
        emoji = {
            "BUY": "🔥",
            "LONG": "🔥",
            "SELL": "❄️",
            "SHORT": "❄️",
            "EXIT": "⚠️",
        }.get(side, "•")

        lines.append(f"{emoji} <b>{escape(str(side))}</b>：{len(items)} 筆")

        for signal_payload in items[:30]:
            symbol = escape(str(signal_payload.get("symbol", "")))
            price = escape(str(signal_payload.get("price", "")))
            timeframe = escape(str(signal_payload.get("timeframe", "")))
            strategy = escape(str(signal_payload.get("strategy", "")))
            lines.append(f"　{symbol}｜{price}｜{timeframe}｜{strategy}")

        if len(items) > 30:
            lines.append(f"　...另有 {len(items) - 30} 筆")

        lines.append("")

    return "\n".join(lines)


async def warmup_redis() -> None:
    await redis_client.ping()


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        if not stop_event.is_set():
            print("shutdown requested; finishing current batch")
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except (NotImplementedError, RuntimeError):
            try:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(request_shutdown))
            except (ValueError, RuntimeError):
                pass


async def wait_or_stop(stop_event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass


async def requeue_batch(batch: list[dict]) -> None:
    if not batch:
        return

    await redis_client.rpush(
        QUEUE_KEY,
        *[json.dumps(signal_payload, ensure_ascii=False) for signal_payload in batch],
    )


async def collect_batch(stop_event: asyncio.Event) -> list[dict]:
    batch = []
    start = time.time()

    while len(batch) < BATCH_MAX and time.time() - start < BATCH_SECONDS:
        item = await redis_client.lpop(QUEUE_KEY)

        if item:
            batch.append(json.loads(item))

            if stop_event.is_set():
                break

            continue

        if stop_event.is_set():
            break

        remaining = BATCH_SECONDS - (time.time() - start)
        if remaining <= 0:
            break

        await wait_or_stop(stop_event, min(0.1, remaining))

    return batch


async def send_batch(
    batch: list[dict],
    last_sent: float,
    stop_event: asyncio.Event,
) -> float:
    text = format_batch(batch)

    elapsed = time.time() - last_sent
    if elapsed < TELEGRAM_MIN_INTERVAL:
        await asyncio.sleep(TELEGRAM_MIN_INTERVAL - elapsed)

    try:
        await send_telegram(text)
        last_sent = time.time()
        print(f"sent batch: {len(batch)}")
    except Exception as exc:
        # HTTP exceptions include the request URL, which contains the bot token.
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        print(f"telegram failed: {type(exc).__name__}; status={status}")
        await requeue_batch(batch)

        if not stop_event.is_set():
            await wait_or_stop(stop_event, 3)

    return last_sent


async def worker_loop(stop_event: asyncio.Event | None = None):
    if stop_event is None:
        stop_event = asyncio.Event()

    last_sent = 0.0

    try:
        if not TG_TOKEN or not TG_CHAT_ID:
            raise RuntimeError("Missing TG_TOKEN or TG_CHAT_ID")
        await warmup_redis()
        while not stop_event.is_set():
            batch = await collect_batch(stop_event)

            if batch:
                last_sent = await send_batch(batch, last_sent, stop_event)

            if stop_event.is_set():
                break
    finally:
        await redis_client.aclose()


async def worker_main():
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    await worker_loop(stop_event)


def cli():
    role = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SERVICE_ROLE", "worker")

    if role == "worker":
        asyncio.run(worker_main())
        return

    raise SystemExit(f"Unknown role: {role}")


if __name__ == "__main__":
    cli()

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from redis import Redis as SyncRedis


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/0")
RUN_ID = uuid.uuid4().hex
QUEUE_KEY = f"tv:test:signals:{RUN_ID}"
DEDUP_PREFIX = f"tv:test:dedup:{RUN_ID}:"

os.environ.update(
    {
        "TV_SECRET": "test",
        "TG_TOKEN": "test-only-no-real-send",
        "TG_CHAT_ID": "test-only",
        "REDIS_CONNECTION_STRING": REDIS_URL,
        "REDIS_URL": REDIS_URL,
        "QUEUE_KEY": QUEUE_KEY,
        "DEDUP_PREFIX": DEDUP_PREFIX,
        "BATCH_SECONDS": "2",
        "BATCH_MAX": "200",
        "TELEGRAM_MIN_INTERVAL": "1.1",
        "DEDUP_TTL_SECONDS": "300",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)


import redis.asyncio  # Require the actual production client; no compatibility facade.


sync_redis = SyncRedis.from_url(REDIS_URL, decode_responses=True)


def cleanup():
    sync_redis.delete(QUEUE_KEY)
    keys = list(sync_redis.scan_iter(DEDUP_PREFIX + "*"))
    if keys:
        sync_redis.delete(*keys)


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        if self.payload == "__invalid_json__":
            raise ValueError("invalid")
        return self.payload


async def call_webhook(app_main, payload):
    try:
        body = await app_main.webhook(FakeRequest(payload))
        return 200, body
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}


def make_signal(prefix, index, side=None):
    return {
        "id": f"{prefix}-{index:03d}",
        "received_at": time.time(),
        "strategy": "OpenBurst",
        "symbol": f"T{index:04d}",
        "side": side or ("BUY" if index % 2 == 0 else "SELL"),
        "price": 100 + index,
        "timeframe": "1",
        "time": f"2026-06-22T09:00:{index % 60:02d}+08:00",
        "raw": {},
    }


async def run_smoke_test():
    cleanup()
    sys.modules.pop("src.main", None)
    importlib.invalidate_caches()

    import src.main as app_main

    async with app_main.lifespan(app_main.app):
        payload = {
            "secret": "test",
            "strategy": "Demo",
            "symbol": "2330",
            "side": "BUY",
            "price": 100,
            "timeframe": "1",
            "time": "2026-06-22T09:00:00+08:00",
        }

        assert await call_webhook(app_main, payload) == (
            200,
            {"ok": True, "queued": True},
        )
        assert await call_webhook(app_main, payload) == (
            200,
            {"ok": True, "duplicate": True},
        )
        assert (await call_webhook(app_main, dict(payload, secret="bad")))[0] == 403
        assert (await call_webhook(app_main, dict(payload, side="HOLD")))[0] == 400
        assert (await call_webhook(app_main, "__invalid_json__"))[0] == 400
        assert sync_redis.llen(QUEUE_KEY) == 1
        queued = json.loads(sync_redis.lindex(QUEUE_KEY, 0))
        assert "raw" not in queued and "secret" not in queued
        assert (await call_webhook(app_main, []))[0] == 400

    cleanup()
    app_main.redis_client = app_main.Redis.from_url(REDIS_URL, decode_responses=True)

    sent = []
    original_format_batch = app_main.format_batch

    def wrapped_format_batch(signals):
        text = original_format_batch(signals)
        sent.append(
            {
                "count": len(signals),
                "buy": sum(1 for signal in signals if signal.get("side") == "BUY"),
                "sell": sum(1 for signal in signals if signal.get("side") == "SELL"),
                "text_length": len(text),
            }
        )
        return text

    async def fake_send_telegram(text):
        sent[-1]["sent_text_length"] = len(text)
        sent[-1]["send_at"] = time.time()
        return {"ok": True, "fake": True}

    app_main.format_batch = wrapped_format_batch
    app_main.send_telegram = fake_send_telegram

    for index in range(205):
        sync_redis.rpush(
            QUEUE_KEY,
            json.dumps(make_signal("burst", index), ensure_ascii=False),
        )

    stop_event = asyncio.Event()
    task = asyncio.create_task(app_main.worker_loop(stop_event))
    deadline = time.time() + 12
    while len(sent) < 2 and time.time() < deadline:
        await asyncio.sleep(0.05)

    stop_event.set()
    await asyncio.wait_for(task, timeout=5)

    assert [batch["count"] for batch in sent] == [200, 5]
    assert all("send_at" in batch for batch in sent)
    assert sent[1]["send_at"] - sent[0]["send_at"] >= 1.1
    assert sync_redis.llen(QUEUE_KEY) == 0

    cleanup()
    app_main.redis_client = app_main.Redis.from_url(REDIS_URL, decode_responses=True)
    sent.clear()

    for index in range(3):
        sync_redis.rpush(
            QUEUE_KEY,
            json.dumps(make_signal("shutdown", index, side="BUY"), ensure_ascii=False),
        )

    graceful_stop = asyncio.Event()
    app_main.BATCH_SECONDS = 30
    graceful_task = asyncio.create_task(app_main.worker_loop(graceful_stop))
    deadline = time.monotonic() + 10
    while sync_redis.llen(QUEUE_KEY) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert sync_redis.llen(QUEUE_KEY) == 0, "Worker did not collect shutdown batch"
    graceful_stop.set()
    await asyncio.wait_for(graceful_task, timeout=5)

    assert [batch["count"] for batch in sent] == [3]
    assert sync_redis.llen(QUEUE_KEY) == 0

    cleanup()
    print("smoke test passed")


if __name__ == "__main__":
    try:
        asyncio.run(run_smoke_test())
    finally:
        cleanup()
        sync_redis.close()

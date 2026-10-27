import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from src import main


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_server_secret_rejects_request(self):
        request = AsyncMock()
        request.json.return_value = {"secret": "", "symbol": "2330", "side": "BUY"}
        with patch.object(main, "TV_SECRET", ""):
            with self.assertRaises(main.HTTPException) as caught:
                await main.webhook(request)
        self.assertEqual(caught.exception.status_code, 403)

    async def test_request_credentials_are_not_queued(self):
        request = AsyncMock()
        request.json.return_value = {
            "secret": "test-secret", "symbol": "2330", "side": "BUY",
            "unexpected_token": "test-extra-credential",
        }
        redis = AsyncMock()
        redis.eval.return_value = 1
        with patch.object(main, "TV_SECRET", "test-secret"), patch.object(main, "redis_client", redis):
            self.assertEqual(await main.webhook(request), {"ok": True, "queued": True})
        payload = json.loads(redis.eval.call_args.args[-1])
        self.assertNotIn("raw", payload)
        self.assertNotIn("secret", payload)
        self.assertNotIn("test-extra-credential", json.dumps(payload))

    async def test_telegram_http_error_does_not_log_token_and_requeues(self):
        fake_token = "synthetic-sensitive-token"
        request = httpx.Request("POST", f"https://api.telegram.org/bot{fake_token}/sendMessage")
        response = httpx.Response(401, request=request)
        error = httpx.HTTPStatusError(str(request.url), request=request, response=response)
        stop = asyncio.Event()
        stop.set()
        batch = [{"symbol": "2330", "side": "BUY"}]
        output = io.StringIO()
        with patch.object(main, "send_telegram", AsyncMock(side_effect=error)), patch.object(
            main, "requeue_batch", AsyncMock()
        ) as requeue, contextlib.redirect_stdout(output):
            await main.send_batch(batch, 0.0, stop)
        requeue.assert_awaited_once_with(batch)
        self.assertNotIn(fake_token, output.getvalue())
        self.assertNotIn("api.telegram.org", output.getvalue())
        self.assertIn("status=401", output.getvalue())

    async def test_stopped_worker_does_not_pop_new_signals(self):
        stop = asyncio.Event()
        stop.set()
        redis = AsyncMock()
        with patch.object(main, "redis_client", redis), patch.object(main, "TG_TOKEN", "test"), patch.object(main, "TG_CHAT_ID", "test"):
            await main.worker_loop(stop)
        redis.lpop.assert_not_awaited()
        redis.aclose.assert_awaited_once()

    async def test_lifespan_closes_client_when_startup_fails(self):
        redis = AsyncMock()
        with patch.object(main, "redis_client", redis), patch.object(main, "TV_SECRET", ""):
            with self.assertRaisesRegex(RuntimeError, "Missing TV_SECRET"):
                async with main.lifespan(main.app):
                    pass
        redis.aclose.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

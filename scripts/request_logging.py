
import logging
import time

logger = logging.getLogger("uvicorn.error")

ENDPOINTS = {
    "/v1/chat/completions": "chat_completions",
    "/v1/completions": "completions",
    "/v1/embeddings": "embeddings",
    "/v1/responses": "responses",
}


class SafeAccessLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        endpoint = ENDPOINTS.get(scope.get("path"))

        if not endpoint or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        started = time.monotonic()
        status = 500

        async def safe_send(message):
            nonlocal status

            if message["type"] == "http.response.start":
                status = message["status"]

            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        finally:
            duration_ms = int(
                (time.monotonic() - started) * 1000
            )

            logger.info(
                "inference_request method=POST "
                "endpoint=%s status=%d duration_ms=%d",
                endpoint,
                status,
                duration_ms,
            )

"""Cache-Control + ETag for the public content endpoints.

Without these every screen open on a phone is a full round trip with a full body,
even though the catalog only changes when a data job runs. With them, iOS
(NSURLCache) and Android (OkHttp) serve repeats from the device, and an unchanged
response comes back as a 304 with no body — less latency, less data, less battery.

Scoped to GET /couvert/* on purpose. Those endpoints are public and identical for
every caller, so `public` is safe. `/user/*` is per-user and authenticated and
must never be cached.
"""

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CACHEABLE_PREFIX = "/couvert"
# Headers we recompute; keeping the originals would contradict the new body.
_DROPPED = {"content-length", "cache-control", "etag"}


class CacheHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_age: int) -> None:
        super().__init__(app)
        self._max_age = max_age

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method not in ("GET", "HEAD"):
            return response
        if not request.url.path.startswith(CACHEABLE_PREFIX):
            return response
        if response.status_code != 200:
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        etag = f'"{hashlib.sha256(body).hexdigest()[:32]}"'
        headers = {k: v for k, v in response.headers.items() if k.lower() not in _DROPPED}
        headers["cache-control"] = f"public, max-age={self._max_age}"
        headers["etag"] = etag

        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(
            content=body,
            status_code=200,
            headers=headers,
            media_type=response.media_type,
        )

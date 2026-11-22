"""
Keeps the local API usable only by the app itself (docs/agent/decisions/0022).

CORS alone is not enough: it does not stop a cross-site form post or image request from
reaching a route, and several GET routes change state (model load, teardown). This
middleware rejects those requests before routing and checks Host against DNS rebinding.
"""

import json
from typing import Dict, Optional

ALLOWED_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}

CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))

SECURITY_HEADERS = (
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)


def _host_name(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if ":" in host else host


def rejection_reason(path: str, headers: Dict[str, str]) -> Optional[str]:
    """Why this request must be refused, or None if it may proceed."""
    if _host_name(headers.get("host", "")) not in ALLOWED_HOSTS:
        return "Host not allowed"
    if not path.startswith("/api"):
        return None
    origin = headers.get("origin")
    if origin is not None:
        return None if origin in ALLOWED_ORIGINS else "Origin not allowed"
    # No Origin: same-origin GETs, typed URLs and non-browser tools. Browsers mark
    # everything else, including image tags and links from another site or port.
    if headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return "Cross-site request not allowed"
    return None


class LocalOnlyMiddleware:
    """Pure ASGI, so streaming log responses pass through unbuffered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        reason = rejection_reason(scope.get("path", ""), headers)
        if reason:
            body = json.dumps({"detail": reason}).encode()
            await send({
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()), *SECURITY_HEADERS],
            })
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *SECURITY_HEADERS]}
            await send(message)

        await self.app(scope, receive, send_with_headers)

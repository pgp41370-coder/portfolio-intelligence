"""ASGI middleware that rejects writes and oversized uploads before the request body is read."""

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_response

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ReadOnlyApiMiddleware:
    """Reject every request that could change data, for a read-only public deployment.

    Any method other than GET, HEAD or OPTIONS receives 403 before routing and before the
    body is read, so no upload is parsed and no database work is done. It covers every
    current and future write endpoint rather than relying on a list of routes.
    """

    def __init__(self, app: ASGIApp, *, message: str) -> None:
        self.app = app
        self.message = message

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in _READ_METHODS:
            response = error_response(403, "read_only_demo", self.message)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class UploadSizeLimitMiddleware:
    """Enforce a maximum request size on upload endpoints using the Content-Length header.

    FastAPI parses multipart bodies before an endpoint runs, so the limit has to be
    applied here to stop large files from being buffered at all.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        path_suffixes: tuple[str, ...],
        message: str,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.path_suffixes = path_suffixes
        self.message = message

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith(self.path_suffixes)
        ):
            await self.app(scope, receive, send)
            return

        content_length = _header(scope, b"content-length")
        if content_length is None:
            response = error_response(411, "length_required", "Uploads must include a Content-Length header.")
        elif not content_length.isdigit():
            response = error_response(400, "bad_request", "Invalid Content-Length header.")
        elif int(content_length) > self.max_body_bytes:
            response = error_response(413, "file_too_large", self.message)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None

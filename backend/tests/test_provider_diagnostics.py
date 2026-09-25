"""Diagnostics for unexpected provider responses.

The 22 Sep 2026 sync failed with HTTP 200, valid JSON and no 'datasets' key, and the error
discarded the body — so the incident could not be classified from the run record. These tests
pin the structure-first, secret-free description that replaces that silence.
"""

import json

import httpx
import pytest

from app.market_data.exceptions import ProviderResponseError
from app.market_data.providers.indian_api import (
    DIAGNOSTIC_SNIPPET_LIMIT,
    describe_payload,
    scrub_secrets,
)
from test_indian_api_client import TEST_KEY, Responder, build, fixture


class TypedResponder:
    """Like Responder, but sets a content type so transport reporting can be asserted."""

    def __init__(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.status = status
        self.body = body
        self.content_type = content_type
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, content=self.body, headers={"content-type": self.content_type})


def failure_message(status: int, body: bytes, content_type: str = "application/json") -> str:
    provider, _ = build(TypedResponder(status, body, content_type))
    with pytest.raises(ProviderResponseError) as raised:
        provider.get_daily_prices("RELIANCE", "1m")
    return str(raised.value)


# 1. A valid response still parses; diagnostics never interfere with the happy path.
def test_valid_datasets_response_parses() -> None:
    responder = Responder(fixture())
    provider, _ = build(responder)

    series = provider.get_daily_prices("RELIANCE", "1m")

    assert len(series.bars) == 6
    assert series.skipped_points == 0


# 2. Object of the right type but the wrong shape.
def test_malformed_object_reports_shape_and_keys() -> None:
    message = failure_message(200, json.dumps({"datasets": {"Price": []}, "status": "ok"}).encode())

    assert "expected an object with a 'datasets' list" in message
    assert "HTTP 200" in message and "content-type=application/json" in message
    assert "top-level dict" in message
    assert "'datasets'" in message and "'status'" in message


# 3. Unexpected top-level type.
def test_unexpected_top_level_type_is_named() -> None:
    message = failure_message(200, json.dumps([{"metric": "Price"}]).encode())

    assert "top-level list" in message
    assert "1 items" in message


# 4. A provider error envelope returned with HTTP 200.
def test_provider_error_shaped_json_is_identifiable() -> None:
    body = json.dumps({"error": "Service temporarily unavailable", "code": 503}).encode()

    message = failure_message(200, body)

    assert "top-level dict" in message
    assert "'error'" in message and "'code'" in message
    assert "Service temporarily unavailable" in message  # the fact that identifies the incident


# 5. HTML or plain text instead of JSON.
def test_html_response_reports_transport_facts() -> None:
    body = b"<html><head><title>502 Bad Gateway</title></head><body>nginx</body></html>"

    message = failure_message(200, body, content_type="text/html; charset=utf-8")

    assert "response was not valid JSON" in message
    assert "HTTP 200" in message and "content-type=text/html" in message and "bytes" in message
    assert "502 Bad Gateway" in message


# 6. Anything credential-shaped is removed, including our own key.
def test_secret_like_content_is_redacted() -> None:
    body = json.dumps(
        {
            "error": "unauthorised",
            "sent_key": TEST_KEY,
            "api_key": "sk-live-9f8e7d6c5b4a3210",
            "authorization": "Bearer abcdefghijklmnopqrstuvwxyz012345",
            "dsn": "postgresql://user:hunter2@db.example.com:5432/app",
        }
    ).encode()

    message = failure_message(200, body)

    assert TEST_KEY not in message
    assert "sk-live-9f8e7d6c5b4a3210" not in message
    assert "hunter2" not in message
    assert "abcdefghijklmnopqrstuvwxyz012345" not in message
    assert "[redacted]" in message
    assert "'error'" in message  # structure survives even though values do not


def test_scrub_secrets_covers_common_credential_shapes() -> None:
    assert "hunter2" not in scrub_secrets("postgresql://user:hunter2@host:5432/db")
    assert "supersecretvalue" not in scrub_secrets('{"password": "supersecretvalue"}')
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in scrub_secrets("token aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert scrub_secrets("nothing sensitive here") == "nothing sensitive here"


# 7. A large body cannot flood the logs or the sync-run record.
def test_oversized_response_snippet_is_bounded() -> None:
    body = json.dumps({"rows": ["x" * 20 for _ in range(5000)]}).encode()
    assert len(body) > 100_000

    message = failure_message(200, body)
    snippet = message.split("snippet=", 1)[1]

    assert len(snippet) <= DIAGNOSTIC_SNIPPET_LIMIT + 1  # bounded, plus the ellipsis
    assert snippet.endswith("…")


def test_describe_payload_is_structure_first() -> None:
    described = describe_payload({"error": "nope"}, meta="HTTP 200; content-type=application/json; 17 bytes")

    assert described.startswith("HTTP 200; content-type=application/json; 17 bytes; top-level dict; keys='error'")

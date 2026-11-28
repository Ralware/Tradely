"""Bind transaction confirmations and retries to their canonical request fields."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.core.models import AmountTransactionRequest

PREVIEW_LIFETIME_SECONDS = 120
# A restart invalidates outstanding previews. Committed retry fingerprints are durable.
_preview_secret = secrets.token_bytes(32)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def request_fingerprint(request: AmountTransactionRequest, currency: str) -> str:
    fields = request.model_dump(mode="json", exclude={"idempotency_key"})
    fields["currency"] = request.currency or currency
    return hashlib.sha256(_canonical_bytes(fields)).hexdigest()


def matches_saved_request(request: AmountTransactionRequest, row: dict[str, Any]) -> bool:
    actual = request_fingerprint(request, row["currency"])
    expected = row.get("request_fingerprint")
    if expected:
        return hmac.compare_digest(actual, expected)
    # Before schema 8 all amount-based entries were made with a provider quote.
    legacy = AmountTransactionRequest(
        instrument_id=row["instrument_id"], intent=row.get("intent") or row["side"],
        amount=row["amount"], fees=row["fees"], trade_time=row["trade_time"],
        notes=row["notes"], currency=row["currency"],
    )
    return actual == request_fingerprint(legacy, row["currency"])


def preview_identity(request: AmountTransactionRequest, currency: str, revision: int,
                     issued: int, quote: dict[str, Any], calculation: dict[str, Any]) -> str:
    payload = request.model_copy(update={"preview_id": None})
    fields = [request_fingerprint(payload, currency), revision, issued,
              quote["price"], quote.get("provider"), quote.get("quote_type"),
              calculation["quantity"], calculation["actual_amount"]]
    digest = hmac.new(_preview_secret, _canonical_bytes(fields), hashlib.sha256).hexdigest()
    return f"{issued}.{digest}"


def preview_problem(request: AmountTransactionRequest, currency: str, revision: int,
                    quote: dict[str, Any], calculation: dict[str, Any]) -> str | None:
    if request.preview_id is None:
        return None
    stamp, _, _digest = request.preview_id.partition(".")
    if not stamp.isascii() or not stamp.isdigit() or len(stamp) > 12:
        return "preview_changed"
    issued = int(stamp)
    if not 0 <= time.time() - issued < PREVIEW_LIFETIME_SECONDS:
        return "preview_expired"
    expected = preview_identity(request, currency, revision, issued, quote, calculation)
    if not hmac.compare_digest(request.preview_id.encode(), expected.encode()):
        return "preview_changed"
    return None

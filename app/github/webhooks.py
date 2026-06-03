from __future__ import annotations

import hashlib
import hmac


class WebhookSignatureError(ValueError):
    pass


def expected_signature(payload_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook_signature(
    *,
    payload_body: bytes,
    secret: str,
    signature_header: str | None,
) -> None:
    if not signature_header:
        raise WebhookSignatureError("missing X-Hub-Signature-256 header")

    expected = expected_signature(payload_body, secret)
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookSignatureError("webhook signature does not match")

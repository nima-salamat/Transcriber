from __future__ import annotations

import logging

from transcriber.core.logging_config import RedactingFormatter


def test_formatter_redacts_huggingface_tokens_and_token_assignments():
    formatter = RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1,
        "failed with hf_abcdefghijklmnopqrstuvwxyz and token=superSecretValue authorization: Bearer anotherSecretValue",
        (), None,
    )
    rendered = formatter.format(record)
    assert "hf_abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "superSecretValue" not in rendered
    assert "anotherSecretValue" not in rendered
    assert rendered.count("[REDACTED]") == 3

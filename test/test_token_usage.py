"""Tests for approximate token counting."""
from src.extraction.token_usage import TokenUsage, approx_tokens


def test_approx_tokens_empty():
    assert approx_tokens("") == 0


def test_approx_tokens_short():
    assert approx_tokens("abcd") == 1


def test_approx_tokens_longer():
    text = "a" * 400
    assert approx_tokens(text) == 100


def test_token_usage_defaults():
    usage = TokenUsage()
    assert usage.tokens_in == 0
    assert usage.tokens_out == 0

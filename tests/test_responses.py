"""Tests for saia_python.responses.text_of."""

import logging

from saia_python import text_of


def test_text_of_extracts_first_choice_content():
    response = {
        "choices": [{"message": {"role": "assistant", "content": "Hello there"}}]
    }
    assert text_of(response) == "Hello there"


def test_text_of_returns_empty_string_for_empty_choices(caplog):
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        result = text_of({"choices": []})
    assert result == ""
    assert any("no choices" in r.message for r in caplog.records)


def test_text_of_returns_empty_string_when_choices_key_missing(caplog):
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        result = text_of({"error": "oops"})
    assert result == ""
    assert any("no choices" in r.message for r in caplog.records)


def test_text_of_returns_empty_when_content_is_none(caplog):
    response = {
        "choices": [
            {"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}
        ]
    }
    with caplog.at_level(logging.WARNING, logger="saia_python.responses"):
        result = text_of(response)
    assert result == ""
    assert any("empty content" in r.message for r in caplog.records)


def test_text_of_returns_empty_when_message_missing():
    """A choice without a `message` field shouldn't raise."""
    assert text_of({"choices": [{"finish_reason": "stop"}]}) == ""


def test_text_of_takes_first_choice_when_multiple_present():
    response = {
        "choices": [
            {"message": {"content": "first"}},
            {"message": {"content": "second"}},
        ]
    }
    assert text_of(response) == "first"

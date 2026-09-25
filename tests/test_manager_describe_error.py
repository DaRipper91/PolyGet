from app.core.manager import describe_error


def test_describe_error_falls_back_to_type_name_for_blank_exceptions():
    """A bare asyncio.TimeoutError has an empty str() — describe_error must fall back
    to the exception's type name instead of surfacing a blank, confusing message."""
    assert describe_error(TimeoutError()) == "TimeoutError"


def test_describe_error_prefers_the_real_message_when_present():
    assert describe_error(RuntimeError("registry unreachable")) == "registry unreachable"
    assert describe_error(ValueError("bad input")) == "bad input"

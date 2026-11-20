"""Property test for the AWS-error invariant of ``call_aws`` (task 3.2).

Every boto3 call in the dashboard is funneled through ``call_aws`` so that no AWS exception
can terminate the Streamlit script. This module checks that invariant across a broad space
of AWS failures, and that a non-raising call yields ``Ok(value)``.
"""

import botocore.exceptions
from hypothesis import given, settings
from hypothesis import strategies as st

from app import call_aws, Ok, Err


# Feature: streamlit-circuit-breaker-ui, Property 3: Any AWS error becomes a displayable message and never terminates
# Validates: Requirements 2.4

# Text strategy that includes empty strings and awkward whitespace so we confirm call_aws
# still produces non-empty error_type/message fields even when the service gives us nothing.
_text = st.text(max_size=80)

# A representative selection of BotoCoreError subclasses that take no required constructor
# args, so we can instantiate them generically for the "any BotoCoreError subclass" case.
_BOTOCORE_ERRORS = [
    botocore.exceptions.BotoCoreError,
    botocore.exceptions.ConnectionError,
    botocore.exceptions.EndpointConnectionError,
    botocore.exceptions.ConnectTimeoutError,
    botocore.exceptions.ReadTimeoutError,
    botocore.exceptions.IncompleteReadError,
    botocore.exceptions.NoRegionError,
    botocore.exceptions.UnknownServiceError,
]


def _instantiate_botocore_error(cls, code, msg):
    """Best-effort construction of a BotoCoreError subclass with generated-ish kwargs.

    BotoCoreError formats its message from a class-level ``fmt`` template plus kwargs. Some
    subclasses need specific kwargs; we pass a superset and fall back to the base class so a
    quirk in any one subclass never derails the property.
    """
    candidate_kwargs = {
        "endpoint_url": code or "https://example.invalid",
        "error": msg or "boto core failure",
        "actual_bytes": 0,
        "expected_bytes": 1,
        "service_name": code or "svc",
        "known_service_names": "a, b",
        "error_msg": msg or "boto core failure",
    }
    try:
        return cls(**candidate_kwargs)
    except Exception:
        return botocore.exceptions.BotoCoreError()


@settings(max_examples=200)
@given(data=st.data())
def test_any_aws_error_becomes_displayable_err_and_never_propagates(data):
    """Any wrapped AWS exception yields an Err with non-empty fields, never propagating."""
    kind = data.draw(st.sampled_from(["no_credentials", "client_error", "botocore"]))
    code = data.draw(_text)
    msg = data.draw(_text)

    if kind == "no_credentials":
        exc = botocore.exceptions.NoCredentialsError()
    elif kind == "client_error":
        exc = botocore.exceptions.ClientError(
            {"Error": {"Code": code, "Message": msg}}, "Op"
        )
    else:
        cls = data.draw(st.sampled_from(_BOTOCORE_ERRORS))
        exc = _instantiate_botocore_error(cls, code, msg)

    def raising():
        raise exc

    # call_aws must swallow the exception and return an Err, never re-raising.
    result = call_aws(raising)

    assert isinstance(result, Err)
    assert result.ok is False
    assert isinstance(result.error_type, str) and result.error_type != ""
    assert isinstance(result.message, str) and result.message != ""


@settings(max_examples=200)
@given(value=st.one_of(st.integers(), _text, st.lists(st.integers()), st.none()))
def test_non_raising_fn_yields_ok_value(value):
    """A non-raising call is wrapped in Ok carrying the exact return value."""
    result = call_aws(lambda: value)

    assert isinstance(result, Ok)
    assert result.ok is True
    assert result.value == value

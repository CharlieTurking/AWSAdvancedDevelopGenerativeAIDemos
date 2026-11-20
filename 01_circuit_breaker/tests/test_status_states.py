"""Example/edge tests for the configuration-bootstrap status states.

Covers ``resolve_status``, ``get_region``, and ``can_start`` using injected fakes for the
``client_factory``/``list_resources`` callables so no real boto3/AWS I/O occurs.

See ``.kiro/specs/streamlit-circuit-breaker-ui/design.md`` and Requirements 2.2, 2.3, 2.5,
8.1, 8.2, 8.4.
"""

import pytest

from app import (
    get_region,
    resolve_status,
    can_start,
    STATUS_READY,
    STATUS_REGION_NOT_CONFIGURED,
    STATUS_NO_CREDENTIALS,
    STATUS_STACK_NOT_FOUND,
    STATUS_RESOURCE_MISSING,
    STATUS_AWS_ERROR,
    REQUIRED,
    NoCredentialsError,
    ClientError,
)


# ---------------------------------------------------------------------------
# get_region
# ---------------------------------------------------------------------------


def test_get_region_missing_returns_none():
    """Requirement 8.2: no region env vars set at all -> None."""
    assert get_region(env={}) is None


def test_get_region_empty_returns_none():
    """Requirement 8.2: empty values are treated as not configured."""
    env = {"AWS_DEFAULT_REGION": "", "AWS_REGION": ""}
    assert get_region(env=env) is None


def test_get_region_whitespace_only_returns_none():
    """Requirement 8.2: whitespace-only values should be treated as not configured."""
    env = {"AWS_DEFAULT_REGION": "   ", "AWS_REGION": "   "}
    assert get_region(env=env) is None


def test_get_region_prefers_aws_default_region():
    """Requirement 8.1: AWS_DEFAULT_REGION takes priority when both are set."""
    env = {"AWS_DEFAULT_REGION": "us-east-1", "AWS_REGION": "us-west-2"}
    assert get_region(env=env) == "us-east-1"


def test_get_region_falls_back_to_aws_region():
    """Requirement 8.1: AWS_REGION is used when AWS_DEFAULT_REGION is unset/blank."""
    assert get_region(env={"AWS_REGION": "eu-west-1"}) == "eu-west-1"
    assert (
        get_region(env={"AWS_DEFAULT_REGION": "", "AWS_REGION": "eu-west-1"})
        == "eu-west-1"
    )


# ---------------------------------------------------------------------------
# resolve_status: fakes for client_factory / list_resources
# ---------------------------------------------------------------------------


def _ready_resources():
    """A CloudFormation resource list containing every REQUIRED resource."""
    return [
        {
            "LogicalResourceId": spec["logical"],
            "ResourceType": sorted(spec["types"])[0],
            "PhysicalResourceId": f"physical-{key}",
        }
        for key, spec in REQUIRED.items()
    ]


def _raise_no_credentials(*_args, **_kwargs):
    raise NoCredentialsError()


def _make_client_error(message, code="ValidationError"):
    def _raise(*_args, **_kwargs):
        raise ClientError(
            {"Error": {"Code": code, "Message": message}}, "ListStackResources"
        )

    return _raise


def test_resolve_status_region_not_configured():
    """Requirement 8.2: falsy region short-circuits before any AWS call."""
    calls = []

    def client_factory(region):
        calls.append(region)
        return object()

    config = resolve_status(
        region=None,
        client_factory=client_factory,
        list_resources=lambda client: _ready_resources(),
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_REGION_NOT_CONFIGURED
    assert config.region is None
    assert calls == []  # no AWS call attempted
    assert can_start(config.status) is False


def test_resolve_status_no_credentials_from_client_factory():
    """Requirement 2.2: NoCredentialsError from client construction -> NO_CREDENTIALS."""
    config = resolve_status(
        region="us-east-1",
        client_factory=_raise_no_credentials,
        list_resources=lambda client: _ready_resources(),
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_NO_CREDENTIALS
    assert config.error_type == "NO_CREDENTIALS"
    assert can_start(config.status) is False


def test_resolve_status_no_credentials_from_list_resources():
    """Requirement 2.2: NoCredentialsError surfaced during listing -> NO_CREDENTIALS."""
    config = resolve_status(
        region="us-east-1",
        client_factory=lambda region: object(),
        list_resources=_raise_no_credentials,
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_NO_CREDENTIALS
    assert config.error_type == "NO_CREDENTIALS"
    assert can_start(config.status) is False


def test_resolve_status_stack_not_found():
    """Requirement 2.3: a "does not exist" ClientError message -> STACK_NOT_FOUND."""
    config = resolve_status(
        region="us-east-1",
        client_factory=lambda region: object(),
        list_resources=_make_client_error(
            "Stack circuit-breaker-stack does not exist"
        ),
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_STACK_NOT_FOUND
    assert "does not exist" in config.message
    assert can_start(config.status) is False


def test_resolve_status_generic_aws_error_from_list_resources():
    """Requirement 2.4: a ClientError lacking the "does not exist" marker -> AWS_ERROR."""
    config = resolve_status(
        region="us-east-1",
        client_factory=lambda region: object(),
        list_resources=_make_client_error(
            "Access denied", code="AccessDenied"
        ),
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_AWS_ERROR
    assert config.error_type == "AccessDenied"
    assert can_start(config.status) is False


def test_resolve_status_generic_aws_error_from_client_factory():
    """Requirement 2.4: a non-credentials error building the client -> AWS_ERROR."""
    config = resolve_status(
        region="us-east-1",
        client_factory=_make_client_error("Throttled", code="ThrottlingException"),
        list_resources=lambda client: _ready_resources(),
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_AWS_ERROR
    assert config.error_type == "ThrottlingException"
    assert can_start(config.status) is False


def test_resolve_status_resource_missing():
    """Requirement 1.4/8.4: a required resource absent from the stack -> RESOURCE_MISSING."""
    incomplete = [
        r for r in _ready_resources() if r["LogicalResourceId"] != REQUIRED["table"]["logical"]
    ]

    config = resolve_status(
        region="us-east-1",
        client_factory=lambda region: object(),
        list_resources=lambda client: incomplete,
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_RESOURCE_MISSING
    assert config.missing == (REQUIRED["table"]["logical"],)
    assert can_start(config.status) is False


def test_resolve_status_ready():
    """Requirement 8.4: every required resource present -> READY, controls enabled."""
    config = resolve_status(
        region="us-east-1",
        client_factory=lambda region: object(),
        list_resources=lambda client: _ready_resources(),
        stack_name="circuit-breaker-stack",
    )

    assert config.status == STATUS_READY
    assert can_start(config.status) is True


# ---------------------------------------------------------------------------
# can_start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        STATUS_REGION_NOT_CONFIGURED,
        STATUS_NO_CREDENTIALS,
        STATUS_STACK_NOT_FOUND,
        STATUS_RESOURCE_MISSING,
        STATUS_AWS_ERROR,
    ],
)
def test_can_start_false_for_every_non_ready_status(status):
    """Requirement 2.5: controls stay disabled unless status is exactly READY."""
    assert can_start(status) is False


def test_can_start_true_only_for_ready():
    assert can_start(STATUS_READY) is True

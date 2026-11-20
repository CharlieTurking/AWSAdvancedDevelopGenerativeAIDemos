"""Streamlit dashboard for the AWS Step Functions circuit breaker demo.

This single-file Streamlit application provides an interactive front page for the
deployed circuit breaker backend in ``01_circuit_breaker/circuit-breaker-netcore-blog``.
It talks to live AWS through boto3 only (no offline/simulated mode): it auto-discovers
backend resources from CloudFormation, starts Step Functions executions against a chosen
target Lambda, polls each execution to a terminal SUCCESS/FAIL result, renders a live
OPEN/CLOSED circuit-state badge derived from the ``CircuitBreaker`` DynamoDB table, keeps a
per-session execution history table, and plots a timeline of circuit transitions.

The application is intentionally kept as a single ``app.py`` (matching sibling demos), but
the internal components are separated by responsibility so the pure decision logic can be
unit/property tested in isolation from Streamlit and boto3. See
``.kiro/specs/streamlit-circuit-breaker-ui/design.md`` for the full design.

Run locally:
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    streamlit run app.py
"""

import os
import json
import time
import datetime
import dataclasses

import boto3
import botocore.exceptions
import streamlit as st
import streamlit.components.v1 as components

# Refresh is manual: every script run (including one triggered by the Refresh button)
# polls running executions, re-reads the circuit state and updates the timeline. A timed
# auto-refresh was removed because a live run takes ~2-5 s and the timer kept
# interrupting runs before the history table rendered.


# ---------------------------------------------------------------------------
# Configuration and session bootstrap
# ---------------------------------------------------------------------------
# Resolve Region from the environment (AWS_DEFAULT_REGION / AWS_REGION), manage Stack_Name
# in st.session_state, and compute the application Status that gates the controls.
#
# The decision logic here is kept pure and injectable: ``resolve_status`` takes the Region,
# a client/session factory, and a resource-list fetcher as parameters rather than reaching
# out to boto3 or Streamlit directly, so it is testable before ``AwsClient`` (task 4) and
# the Streamlit UI (task 11) exist. The thin ``st.session_state`` and environment wiring is
# provided as small helpers the UI layer calls.

# Application status values (string constants). These drive control gating: executions can
# only be started when the status is READY (see ``can_start``). Each non-READY value maps a
# distinct precondition failure to a message the UI surfaces while disabling controls.
# (Requirements 2.2, 2.3, 2.5, 8.2.)
STATUS_READY = "READY"
STATUS_REGION_NOT_CONFIGURED = "REGION_NOT_CONFIGURED"
STATUS_NO_CREDENTIALS = "NO_CREDENTIALS"
STATUS_STACK_NOT_FOUND = "STACK_NOT_FOUND"
STATUS_RESOURCE_MISSING = "RESOURCE_MISSING"
STATUS_AWS_ERROR = "AWS_ERROR"

# Default CloudFormation stack name; the sidebar text input can override it. Stored in
# ``st.session_state["stack_name"]`` so it survives Streamlit reruns (Requirements 8.3, 8.4).
DEFAULT_STACK_NAME = "sam-app"

# Environment variable names that hold the AWS Region, in resolution order. ``boto3``
# itself honours both, and Requirement 8.1 requires the Region to come from the environment.
REGION_ENV_VARS = ("AWS_DEFAULT_REGION", "AWS_REGION")

# Substring CloudFormation includes in the error message for a nonexistent stack. Used to
# distinguish STACK_NOT_FOUND from a generic AWS error (Requirement 2.3).
STACK_NOT_FOUND_MARKER = "does not exist"


@dataclasses.dataclass(frozen=True)
class AppConfig:
    """Resolved application status plus the data the UI needs to render it.

    ``status`` is one of the ``STATUS_*`` constants and gates the controls via
    :func:`can_start`. The remaining fields carry whatever detail the resolution produced so
    the UI can render a helpful message and the resolved-resources panel:

    - ``region``: the Region read from the environment (``None`` when unset).
    - ``resolve_result``: the :class:`ResolveResult` when resolution ran, else ``None``.
    - ``error_type`` / ``message``: populated for ``NO_CREDENTIALS``, ``STACK_NOT_FOUND``,
      and ``AWS_ERROR`` so the UI can show the AWS error code/type and message.
    - ``missing``: the missing logical ids for ``RESOURCE_MISSING`` (empty otherwise).
    """

    status: str
    region: "str | None" = None
    resolve_result: "ResolveResult | None" = None
    error_type: "str | None" = None
    message: "str | None" = None
    missing: tuple = ()


def get_region(env=None):
    """Read the AWS Region from the environment, honouring both standard variables.

    Checks ``AWS_DEFAULT_REGION`` first, then ``AWS_REGION`` (the order ``boto3`` uses),
    returning the first non-empty value. An ``env`` mapping can be injected for testing;
    it defaults to ``os.environ``. A missing or blank value yields ``None``, which the
    caller maps to ``REGION_NOT_CONFIGURED`` (Requirements 8.1, 8.2).

    Args:
        env: Optional environment mapping to read from; defaults to ``os.environ``.

    Returns:
        The resolved Region string, or ``None`` when neither variable is set to a
        non-empty value.
    """
    if env is None:
        env = os.environ
    for name in REGION_ENV_VARS:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def get_stack_name(session_state=None):
    """Return the configured Stack_Name, defaulting it in session state on first use.

    The Stack_Name lives in ``st.session_state["stack_name"]`` so it persists across
    Streamlit reruns and can be edited via the sidebar. On first access it is seeded with
    :data:`DEFAULT_STACK_NAME`. A mapping can be injected for testing; it defaults to
    ``st.session_state`` (Requirements 8.3, 8.4).

    Args:
        session_state: Optional mutable mapping standing in for ``st.session_state``.

    Returns:
        The current Stack_Name string.
    """
    if session_state is None:
        session_state = st.session_state
    if "stack_name" not in session_state:
        session_state["stack_name"] = DEFAULT_STACK_NAME
    return session_state["stack_name"]


def can_start(status: str) -> bool:
    """Guard: executions may be started only when the application status is READY.

    Pure function over the status string. Every non-READY status (region not configured,
    missing credentials, stack not found, a missing required resource, or any other AWS
    error) returns ``False`` so no execution can be started while a precondition is unmet
    (Requirement 2.5).

    Args:
        status: One of the ``STATUS_*`` constants.

    Returns:
        ``True`` iff ``status == STATUS_READY``.
    """
    return status == STATUS_READY


def resolve_status(region, client_factory, list_resources, stack_name):
    """Compute the application :class:`AppConfig` in the design's resolution order.

    This is the pure decision core of the configuration bootstrap. It performs no boto3 or
    Streamlit I/O itself; instead it is handed the already-read ``region`` plus two
    injectable callables so it can be tested before ``AwsClient`` exists:

    1. **Region check** — if ``region`` is falsy, return ``REGION_NOT_CONFIGURED`` before any
       AWS call (Requirement 8.2).
    2. **Session/client construction** — call ``client_factory(region)`` through
       :func:`call_aws`. A ``NoCredentialsError`` maps to ``NO_CREDENTIALS``; any other
       construction failure maps to ``AWS_ERROR`` (Requirements 2.2, 2.4).
    3. **Resource listing** — call ``list_resources(client)`` through :func:`call_aws`. If
       the error message contains ``"does not exist"`` the stack is missing
       (``STACK_NOT_FOUND``, Requirement 2.3); a ``NoCredentialsError`` surfaced here maps to
       ``NO_CREDENTIALS``; any other error maps to ``AWS_ERROR`` (Requirement 2.4).
    4. **Resolver outcome mapping** — run :func:`resolve_resources` over the listed
       resources. If anything is missing, return ``RESOURCE_MISSING`` with the missing
       logical ids; otherwise ``READY`` (Requirements 1.4, 8.4).

    Args:
        region: The Region resolved from the environment (possibly ``None``/empty).
        client_factory: Callable ``region -> client`` building the AWS client/session; may
            raise, in which case the error is funnelled through :func:`call_aws`. Injected so
            an ``AwsClient`` (task 4) or a test double can be supplied.
        list_resources: Callable ``client -> list[dict]`` returning the CloudFormation stack
            resources for ``stack_name``; may raise, funnelled through :func:`call_aws`.
        stack_name: The Stack_Name whose resources are resolved.

    Returns:
        An :class:`AppConfig` whose ``status`` gates the controls and whose remaining fields
        carry the detail the UI renders.
    """
    # 1. Region check — before any AWS call.
    if not region:
        return AppConfig(status=STATUS_REGION_NOT_CONFIGURED, region=region)

    # 2. Session/client construction.
    client_result = call_aws(client_factory, region)
    if not client_result.ok:
        status = (
            STATUS_NO_CREDENTIALS
            if client_result.error_type == "NO_CREDENTIALS"
            else STATUS_AWS_ERROR
        )
        return AppConfig(
            status=status,
            region=region,
            error_type=client_result.error_type,
            message=client_result.message,
        )
    client = client_result.value

    # 3. Resource listing (depends on stack_name).
    list_result = call_aws(list_resources, client)
    if not list_result.ok:
        message = list_result.message or ""
        if STACK_NOT_FOUND_MARKER in message:
            status = STATUS_STACK_NOT_FOUND
        elif list_result.error_type == "NO_CREDENTIALS":
            status = STATUS_NO_CREDENTIALS
        else:
            status = STATUS_AWS_ERROR
        return AppConfig(
            status=status,
            region=region,
            error_type=list_result.error_type,
            message=message,
        )

    # 4. Resolver outcome mapping.
    resolve_result = resolve_resources(list_result.value)
    if not resolve_result.ok:
        return AppConfig(
            status=STATUS_RESOURCE_MISSING,
            region=region,
            resolve_result=resolve_result,
            missing=tuple(resolve_result.missing),
        )
    return AppConfig(
        status=STATUS_READY,
        region=region,
        resolve_result=resolve_result,
    )


# ---------------------------------------------------------------------------
# AWS error handling
# ---------------------------------------------------------------------------
# Ok/Err result types and call_aws(fn, *args, **kwargs): funnel every boto3 call through a
# single handler so no AWS exception terminates the Streamlit script.
# (Implemented in task 3.)

# Exceptions raised by boto3/botocore for the failure modes the dashboard must handle.
# Referenced via the ``botocore.exceptions`` module imported in the skeleton.
NoCredentialsError = botocore.exceptions.NoCredentialsError
ClientError = botocore.exceptions.ClientError
BotoCoreError = botocore.exceptions.BotoCoreError


@dataclasses.dataclass(frozen=True)
class Ok:
    """Successful result of a wrapped AWS call, carrying the raw return value."""

    value: object

    @property
    def ok(self) -> bool:
        return True


@dataclasses.dataclass(frozen=True)
class Err:
    """Failed result of a wrapped AWS call.

    ``error_type`` is a stable code/type name (e.g. ``"NO_CREDENTIALS"``, a service error
    ``Code``, or a ``BotoCoreError`` subclass name) and ``message`` is a human-readable,
    non-empty description suitable for display via ``st.error``.
    """

    error_type: str
    message: str

    @property
    def ok(self) -> bool:
        return False


def call_aws(fn, *args, **kwargs):
    """Funnel a single boto3 call through one handler so no AWS error terminates the app.

    Returns ``Ok(value)`` with the call's return value on success. On a known AWS failure
    it returns an ``Err`` carrying a non-empty error type/code and message; the exception is
    never propagated. Callers decide the local consequence (unchanged history, unknown
    status, unknown badge) while the top-level Streamlit script keeps running.
    """
    try:
        return Ok(fn(*args, **kwargs))
    except NoCredentialsError:
        return Err("NO_CREDENTIALS", "AWS credentials are unavailable.")
    except ClientError as e:
        error = e.response.get("Error", {}) if isinstance(e.response, dict) else {}
        code = error.get("Code") or "ClientError"
        msg = error.get("Message") or str(e)
        return Err(code, msg)
    except BotoCoreError as e:
        return Err(type(e).__name__, str(e))


# ---------------------------------------------------------------------------
# AwsClient (boto3 usage)
# ---------------------------------------------------------------------------
# The only component that performs network I/O. Wraps cloudformation, stepfunctions, and
# dynamodb clients built from a single boto3.Session and exposes thin, raw-result methods:
# list_stack_resources, start_execution, describe_execution, query_circuit.


class AwsClient:
    """Thin boto3 wrapper. Methods return raw results or raise; callers use ``call_aws``."""

    def __init__(self, region: str):
        self._session = boto3.Session(region_name=region)
        self.cfn = self._session.client("cloudformation")
        self.sfn = self._session.client("stepfunctions")
        self.ddb = self._session.client("dynamodb")

    def list_stack_resources(self, stack_name: str) -> list:
        """Return all stack resource summaries, following ``NextToken`` pagination."""
        resources, token = [], None
        while True:
            kwargs = {"StackName": stack_name}
            if token:
                kwargs["NextToken"] = token
            resp = self.cfn.list_stack_resources(**kwargs)
            resources.extend(resp.get("StackResourceSummaries", []))
            token = resp.get("NextToken")
            if not token:
                break
        return resources

    def start_execution(self, state_machine_arn: str, input_json: str) -> dict:
        return self.sfn.start_execution(stateMachineArn=state_machine_arn, input=input_json)

    def describe_execution(self, execution_arn: str) -> dict:
        return self.sfn.describe_execution(executionArn=execution_arn)

    def query_circuit(self, table_name: str, service_name: str, now_epoch: int) -> list:
        """Query unexpired circuit items (ExpireTimeStamp > now) for a service."""
        resp = self.ddb.query(
            TableName=table_name,
            KeyConditionExpression="ServiceName = :s AND ExpireTimeStamp > :t",
            ExpressionAttributeValues={
                ":s": {"S": service_name},
                ":t": {"N": str(now_epoch)},
            },
            ConsistentRead=True,
        )
        return resp.get("Items", [])


# ---------------------------------------------------------------------------
# Resource_Resolver
# ---------------------------------------------------------------------------
# REQUIRED map, ResolveResult, and the pure resolve_resources(resources) function that
# selects physical ids from a CloudFormation resource list, matching on LogicalResourceId
# with ResourceType as a non-strict hint.

# Each required resource is keyed by its stable LogicalResourceId. The accepted
# ResourceType values are a non-strict hint: for a SAM stack CloudFormation reports the
# post-transform CFN type, but the macro AWS::Serverless::* type may also appear, so both
# are accepted. The type hint is only used to disambiguate duplicate logical ids and never
# to reject an otherwise-unique logical-id match (Requirements 1.1, 1.2, 1.3).
REQUIRED = {
    "state_machine": {
        "logical": "CircuitBreakerStateMachine",
        "types": {"AWS::StepFunctions::StateMachine", "AWS::Serverless::StateMachine"},
    },
    "table": {
        "logical": "CircuitBreakerTable",
        "types": {"AWS::DynamoDB::Table"},
    },
    "hello": {
        "logical": "HelloWorldFunction",
        "types": {"AWS::Lambda::Function", "AWS::Serverless::Function"},
    },
    "test": {
        "logical": "TestCircuitBreakerFunction",
        "types": {"AWS::Lambda::Function", "AWS::Serverless::Function"},
    },
}


@dataclasses.dataclass(frozen=True)
class ResolveResult:
    """Outcome of resolving the required backend resources.

    ``found`` maps each REQUIRED key (``state_machine``, ``table``, ``hello``, ``test``) to
    the resolved physical id; ``missing`` lists the logical ids of any required resource not
    found. ``ok`` is derived and is ``True`` exactly when nothing is missing
    (Requirements 1.4).
    """

    found: dict
    missing: list

    @property
    def ok(self) -> bool:
        return len(self.missing) == 0


def resolve_resources(resources: list) -> "ResolveResult":
    """Pure: select physical ids from a CloudFormation resource list.

    Match primarily on the exact LogicalResourceId (SAM preserves it across the transform).
    ResourceType is only a non-strict hint: when a logical id appears more than once the hint
    set disambiguates, but a type mismatch never alone rejects an otherwise-unique logical-id
    match. This tolerates CloudFormation reporting post-transform CFN types for the
    SAM-deployed stack (Requirements 1.1, 1.2, 1.3, 1.4).
    """
    found: dict = {}
    missing: list = []
    for key, spec in REQUIRED.items():
        logical, types = spec["logical"], spec["types"]
        candidates = [
            r for r in resources if r.get("LogicalResourceId") == logical
        ]
        # Prefer a candidate whose type is in the accepted hint set; otherwise fall back to
        # the sole logical-id match so the exact-type report from CloudFormation (transformed
        # or macro) does not break resolution.
        match = next(
            (r for r in candidates if r.get("ResourceType") in types), None
        )
        if match is None and len(candidates) == 1:
            match = candidates[0]
        if match is None:
            missing.append(logical)
        else:
            found[key] = match["PhysicalResourceId"]
    return ResolveResult(found=found, missing=missing)


# ---------------------------------------------------------------------------
# Execution input, classification, history, and polling
# ---------------------------------------------------------------------------
# build_execution_input / classify_result, the ExecutionRecord dataclass, and the pure
# history operations add_execution / update_execution / ordered_history.
# (Implemented in tasks 2 and 7.)


def build_execution_input(target: str) -> str:
    """Build the Step Functions execution input for a target Lambda.

    The backend state machine is invoked with a JSON object carrying a single
    ``TargetLambda`` key (the resolved Lambda name or ARN). The same string also becomes
    the DynamoDB ``ServiceName`` used to derive circuit state, so the encoding must be the
    exact backend contract.

    Args:
        target: The selected Target_Lambda identifier (name or ARN).

    Returns:
        A JSON string ``{"TargetLambda": "<target>"}``.
    """
    return json.dumps({"TargetLambda": target})


# Step Functions terminal statuses that classify an execution as a failure.
TERMINAL_FAIL = {"FAILED", "TIMED_OUT", "ABORTED"}


def classify_result(status: str) -> str:
    """Classify a Step Functions execution status into a result label.

    Maps ``SUCCEEDED`` to ``SUCCESS``; any terminal-failure status in :data:`TERMINAL_FAIL`
    (``FAILED``, ``TIMED_OUT``, ``ABORTED``) to ``FAIL``; ``RUNNING`` to ``RUNNING``; and any
    other value to ``UNKNOWN``.

    Args:
        status: The Step Functions execution status.

    Returns:
        One of ``"SUCCESS"``, ``"FAIL"``, ``"RUNNING"``, or ``"UNKNOWN"``.
    """
    if status == "SUCCEEDED":
        return "SUCCESS"
    if status in TERMINAL_FAIL:
        return "FAIL"
    if status == "RUNNING":
        return "RUNNING"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Circuit state and timeline
# ---------------------------------------------------------------------------
# derive_circuit_state(items, now_epoch) and detect_transitions(prev_state, new_state, ts):
# pure helpers for the OPEN/CLOSED badge and the circuit transition timeline.


def derive_circuit_state(items: list, now_epoch: int) -> str:
    """Derive the OPEN/CLOSED circuit state from queried ``CircuitBreaker`` items.

    Items are low-level DynamoDB shapes, so ``ExpireTimeStamp`` is encoded as
    ``{"N": "<epoch-seconds>"}``. The circuit is OPEN while an unexpired item exists for the
    service; otherwise it is CLOSED. The DynamoDB query already filters
    ``ExpireTimeStamp > :t``, but the explicit comparison here keeps the logic correct and
    testable even if called with an unfiltered item list. When the query raised, the caller
    substitutes ``UNKNOWN`` rather than calling this function.

    Args:
        items: The queried ``CircuitBreaker`` items in low-level DynamoDB form.
        now_epoch: The current time as epoch seconds.

    Returns:
        ``"OPEN"`` if any item's ``ExpireTimeStamp`` is greater than ``now_epoch``,
        otherwise ``"CLOSED"``.
    """
    for item in items:
        if int(item["ExpireTimeStamp"]["N"]) > now_epoch:
            return "OPEN"
    return "CLOSED"


def detect_transitions(prev_state, new_state: str, ts):
    """Detect a single circuit-state transition timeline point.

    A point is produced only when ``new_state`` is a definite OPEN/CLOSED observation that
    differs from ``prev_state``. ``UNKNOWN`` observations never yield a point and (per the
    caller's handling) must not overwrite the last known OPEN/CLOSED baseline used for
    comparison.

    Args:
        prev_state: The last recorded OPEN/CLOSED state, or ``None`` if unset.
        new_state: The freshly derived state (``OPEN``, ``CLOSED``, or ``UNKNOWN``).
        ts: The observation timestamp for the point.

    Returns:
        A list with one ``(ts, new_state)`` point if the state changed, else an empty list.
    """
    if new_state in ("OPEN", "CLOSED") and new_state != prev_state:
        return [(ts, new_state)]
    return []


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
# Sidebar (region, stack name, resolved-resources panel, status messages), main controls
# (target selector, Start Execution button), polling loop, circuit badge, execution history
# table, timeline chart, and the manual Refresh button.
# (Implemented in task 11.)


# ---------------------------------------------------------------------------
# Execution history records and pure history operations (task 7.1)
# ---------------------------------------------------------------------------
# ExecutionRecord models one row of the per-session Execution_History. The three history
# operations below are pure: each returns a NEW list and never mutates its inputs, so they
# are safe to call on every Streamlit rerun and are testable without Streamlit or boto3.


@dataclasses.dataclass
class ExecutionRecord:
    """A single Step Functions execution tracked in the session Execution_History.

    Serializable to a table row ``[short_id, target, start_time, status, result]``.

    Attributes:
        execution_arn: The full Step Functions execution ARN returned by StartExecution.
        short_id: The ARN suffix shown in the history table.
        target: The selected Target_Lambda name used as the execution input and ServiceName.
        start_time: When StartExecution succeeded.
        status: Raw Step Functions status
            (``RUNNING`` | ``SUCCEEDED`` | ``FAILED`` | ``TIMED_OUT`` | ``ABORTED`` | ``UNKNOWN``).
        result: Classified result (``SUCCESS`` | ``FAIL`` | ``RUNNING`` | ``UNKNOWN``).
    """

    execution_arn: str
    short_id: str
    target: str
    start_time: datetime.datetime
    status: str
    result: str


def add_execution(history, record):
    """Append a record to the Execution_History, returning a new list.

    Called only after a successful StartExecution; a failed start never calls this, so the
    history is left unchanged on failure. Pure: the input ``history`` is not mutated.

    Args:
        history: The current list of :class:`ExecutionRecord` entries.
        record: The :class:`ExecutionRecord` to append.

    Returns:
        A new list equal to ``history`` with ``record`` appended at the end.
    """
    return list(history) + [record]


def update_execution(history, execution_arn, status, result):
    """Replace the status/result of the record matching ``execution_arn``.

    Only the matching record's ``status`` and ``result`` change; length, order, and every
    other record are preserved. Pure: the input ``history`` and its other records are not
    mutated (the matched record is replaced with a copy).

    Args:
        history: The current list of :class:`ExecutionRecord` entries.
        execution_arn: The ARN identifying the record to update.
        status: The fresh Step Functions status to store.
        result: The classified result to store.

    Returns:
        A new list with only the matching record updated.
    """
    updated = []
    for rec in history:
        if rec.execution_arn == execution_arn:
            updated.append(dataclasses.replace(rec, status=status, result=result))
        else:
            updated.append(rec)
    return updated


def ordered_history(history):
    """Return the history sorted by ``start_time`` descending (most recent first).

    A pure, non-mutating sort used only for rendering; the stored order in
    ``st.session_state`` is left unchanged.

    Args:
        history: The current list of :class:`ExecutionRecord` entries.

    Returns:
        A new list that is a permutation of ``history`` ordered most-recent-first.
    """
    return sorted(history, key=lambda rec: rec.start_time, reverse=True)


# ---------------------------------------------------------------------------
# Streamlit UI: sidebar and entry point (task 11.1)
# ---------------------------------------------------------------------------
# These functions perform Streamlit rendering and (via ``AwsClient``) AWS calls, so they
# run only when ``main()`` is invoked, never at import time.


def describe_status(config: "AppConfig") -> "tuple[str, str]":
    """Map an :class:`AppConfig` to a ``(level, message)`` pair for the sidebar.

    ``level`` is one of ``"success"``, ``"warning"`` or ``"error"``; it selects the
    matching ``st.*`` rendering function. Pure, so it is testable without Streamlit.
    """
    status = config.status
    detail = " ".join(p for p in (config.error_type, config.message) if p)
    if status == STATUS_READY:
        return "success", "Connected. All required backend resources were resolved."
    if status == STATUS_REGION_NOT_CONFIGURED:
        return (
            "error",
            "AWS Region is not configured. Set AWS_DEFAULT_REGION or AWS_REGION "
            "and restart the app.",
        )
    if status == STATUS_NO_CREDENTIALS:
        return "error", "AWS credentials are unavailable. Configure credentials and rerun."
    if status == STATUS_STACK_NOT_FOUND:
        return "error", f"CloudFormation stack not found. {detail}".strip()
    if status == STATUS_RESOURCE_MISSING:
        return (
            "warning",
            "Stack found, but required resources are missing: "
            + ", ".join(config.missing),
        )
    return "error", f"AWS error. {detail}".strip()


def render_resolved_resources(config: "AppConfig") -> None:
    """Render the resolved-resources panel (state machine ARN, table, target names)."""
    result = config.resolve_result
    if result is None or not result.found:
        return
    st.subheader("Resolved resources")
    found = result.found
    if "state_machine" in found:
        st.text("State machine ARN")
        st.code(found["state_machine"], language=None)
    if "table" in found:
        st.text("DynamoDB table")
        st.code(found["table"], language=None)
    targets = [found[k] for k in ("hello", "test") if k in found]
    if targets:
        st.text("Target Lambdas")
        for name in targets:
            st.code(name, language=None)


def render_sidebar() -> "AppConfig":
    """Render the sidebar and return the resolved :class:`AppConfig`.

    Shows the read-only Region, the Stack Name input (bound to
    ``st.session_state["stack_name"]``; editing it reruns the script, which re-resolves
    the resources), connectivity/resolution status, and the resolved-resources panel.
    """
    region = get_region()
    get_stack_name()  # seed the default before the widget binds to the key
    with st.sidebar:
        st.header("Configuration")
        st.text_input("Region", value=region or "(not configured)", disabled=True)
        st.text_input("Stack Name", key="stack_name")
        stack_name = (st.session_state["stack_name"] or "").strip()

        config = resolve_status(
            region,
            AwsClient,
            lambda client: client.list_stack_resources(stack_name),
            stack_name,
        )
        level, message = describe_status(config)
        getattr(st, level)(message)
        render_resolved_resources(config)
    return config


# ---------------------------------------------------------------------------
# Streamlit UI: main controls, polling loop, and result line (task 11.2)
# ---------------------------------------------------------------------------

# Logical names used to label the target selector, keyed by the REQUIRED map key.
TARGET_LABELS = (("hello", "HelloWorldFunction"), ("test", "TestCircuitBreakerFunction"))


def target_options(config: "AppConfig") -> list:
    """Return ``[(label, physical_name)]`` for the two resolvable target Lambdas.

    The label is the logical resource name and the value is the resolved physical name
    (used as the execution input). Empty when resources were not resolved.
    """
    result = config.resolve_result
    if result is None:
        return []
    return [(label, result.found[key]) for key, label in TARGET_LABELS if key in result.found]


def short_id_from_arn(execution_arn: str) -> str:
    """Return the ARN suffix (the execution name) used as the short id."""
    return execution_arn.rsplit(":", 1)[-1]


def build_record(response: dict, target: str, now=None) -> "ExecutionRecord":
    """Build a RUNNING :class:`ExecutionRecord` from a StartExecution response."""
    arn = response["executionArn"]
    start = response.get("startDate") or now or datetime.datetime.now(datetime.timezone.utc)
    # boto3 returns startDate with dateutil's tzlocal(), which pyarrow (used by
    # st.dataframe) cannot serialize. Normalize aware datetimes to UTC.
    if start.tzinfo is not None:
        start = start.astimezone(datetime.timezone.utc)
    return ExecutionRecord(
        execution_arn=arn,
        short_id=short_id_from_arn(arn),
        target=target,
        start_time=start,
        status="RUNNING",
        result="RUNNING",
    )


def poll_running(history, describe_fn):
    """Refresh every record whose result is RUNNING via ``describe_fn``.

    ``describe_fn(execution_arn)`` returns an ``Ok``/``Err`` (i.e. is wrapped by
    :func:`call_aws`). On success the record is updated with the fresh status and its
    classification. On error that record becomes ``UNKNOWN``/``UNKNOWN`` without affecting
    others. Pure with respect to ``history`` (returns a new list).

    Returns:
        ``(new_history, errors)`` where ``errors`` is a list of ``(short_id, Err)``.
    """
    new_history = list(history)
    errors = []
    for rec in history:
        if rec.result != "RUNNING":
            continue
        res = describe_fn(rec.execution_arn)
        if res.ok:
            status = res.value.get("status", "UNKNOWN")
            new_history = update_execution(
                new_history, rec.execution_arn, status, classify_result(status)
            )
        else:
            new_history = update_execution(new_history, rec.execution_arn, "UNKNOWN", "UNKNOWN")
            errors.append((rec.short_id, res))
    return new_history, errors


def format_result_line(history) -> "str | None":
    """Return ``"<short_id>: <RESULT>"`` for the most recent execution, or ``None``."""
    if not history:
        return None
    latest = ordered_history(history)[0]
    return f"{latest.short_id}: {latest.result}"


def start_selected_execution(history, client, state_machine_arn, target, now=None):
    """Start an execution and add it to history on success.

    Returns ``(new_history, err)``; on failure the history is returned unchanged and ``err``
    is the :class:`Err`.
    """
    res = call_aws(client.start_execution, state_machine_arn, build_execution_input(target))
    if not res.ok:
        return history, res
    return add_execution(history, build_record(res.value, target, now)), None


def render_main(config: "AppConfig") -> None:
    """Render target selector, Start button, run polling, and show the result line."""
    if "history" not in st.session_state:
        st.session_state["history"] = []

    options = target_options(config)
    labels = [label for label, _ in options]
    selected = st.selectbox("Target Lambda", labels, disabled=not can_start(config.status))
    col_start, col_refresh = st.columns([1, 1])
    with col_start:
        start_clicked = st.button(
            "Start Execution", disabled=not can_start(config.status), use_container_width=True
        )
    with col_refresh:
        # Clicking reruns the script, which polls executions and re-reads the circuit.
        st.button(
            "Refresh",
            disabled=not can_start(config.status),
            use_container_width=True,
            help="Poll running executions and re-read the circuit state",
        )

    # Never touch AWS unless READY.
    if can_start(config.status):
        client = AwsClient(config.region)
        if start_clicked and selected is not None:
            target = dict(options)[selected]
            st.session_state["history"], err = start_selected_execution(
                st.session_state["history"],
                client,
                config.resolve_result.found["state_machine"],
                target,
            )
            if err is not None:
                st.error(f"Failed to start execution: {err.error_type}: {err.message}")

        st.session_state["history"], poll_errors = poll_running(
            st.session_state["history"],
            lambda arn: call_aws(client.describe_execution, arn),
        )
        for short_id, err in poll_errors:
            st.error(f"Polling {short_id} failed: {err.error_type}: {err.message}")

    line = format_result_line(st.session_state["history"])
    if line:
        st.write(line)

    render_circuit_section(config, selected_target=dict(options).get(selected))
    render_history_table(st.session_state["history"])


# ---------------------------------------------------------------------------
# Streamlit UI: circuit badge, history table, timeline (task 11.3)
# ---------------------------------------------------------------------------


def tracked_targets(selected_target, history) -> list:
    """Return the ordered, de-duplicated targets to query: selected first, then history."""
    targets = []
    for t in [selected_target] + [rec.target for rec in history]:
        if t and t not in targets:
            targets.append(t)
    return targets


def query_circuit_state(query_fn, table_name, service, now_epoch):
    """Query and derive a service's circuit state.

    ``query_fn(table_name, service, now_epoch)`` returns an ``Ok``/``Err`` (wrapped by
    :func:`call_aws`). Returns ``(state, err)``: ``OPEN``/``CLOSED`` with ``err=None`` on
    success, or ``("UNKNOWN", Err)`` on a query error.
    """
    res = query_fn(table_name, service, now_epoch)
    if not res.ok:
        return "UNKNOWN", res
    return derive_circuit_state(res.value, now_epoch), None


def update_circuit_tracking(last_state, timeline, service, new_state, ts):
    """Apply an observation to the last-known state and timeline (pure).

    Appends a ``(ts, service, state)`` point only on an OPEN/CLOSED change per
    :func:`detect_transitions`. ``UNKNOWN`` never overwrites the baseline.

    Returns:
        ``(new_last_state, new_timeline)``.
    """
    points = detect_transitions(last_state.get(service), new_state, ts)
    new_last = dict(last_state)
    if new_state in ("OPEN", "CLOSED"):
        new_last[service] = new_state
    return new_last, list(timeline) + [(t, service, s) for t, s in points]


def history_rows(history) -> list:
    """Return table rows (most recent first) with the required history columns."""
    return [
        {
            "short_id": rec.short_id,
            "target": rec.target,
            "start_time": rec.start_time,
            "status": rec.status,
            "result": rec.result,
        }
        for rec in ordered_history(history)
    ]


def timeline_dataframe(timeline):
    """Build a step-chart frame (time, service, value 1=OPEN / 0=CLOSED) from points."""
    import pandas as pd

    return pd.DataFrame(
        [
            {"time": ts, "service": svc, "value": 1 if state == "OPEN" else 0}
            for ts, svc, state in timeline
        ],
        columns=["time", "service", "value"],
    )


def render_badge(service, state) -> None:
    """Render the OPEN/CLOSED/UNKNOWN badge for a service."""
    text = f"Circuit for {service}: {state}"
    if state == "OPEN":
        st.error(text)
    elif state == "CLOSED":
        st.success(text)
    else:
        st.warning(text)


def render_badges(options, states) -> None:
    """Render one badge per target Lambda: each has its own circuit."""
    st.subheader("Circuit state per Lambda")
    cols = st.columns(max(len(options), 1))
    for col, (label, name) in zip(cols, options):
        with col:
            st.caption(label)
            render_badge(name, states.get(name, "UNKNOWN"))
    st.caption(
        "Each Lambda has its own circuit (keyed by its name in DynamoDB). When "
        "TestCircuitBreakerFunction's circuit is OPEN, only calls to it fail fast; "
        "HelloWorldFunction keeps succeeding."
    )


def render_timeline(timeline) -> None:
    """Render the circuit transition Timeline chart (OPEN=1 / CLOSED=0 vs time)."""
    st.subheader("Timeline")
    if not timeline:
        st.caption("No circuit transitions recorded yet.")
        return
    import altair as alt

    chart = (
        alt.Chart(timeline_dataframe(timeline))
        .mark_line(interpolate="step-after", point=True)
        .encode(
            x=alt.X("time:T", title="Time"),
            y=alt.Y("value:Q", title="Circuit (1=OPEN, 0=CLOSED)", scale=alt.Scale(domain=[-0.1, 1.1])),
            color="service:N",
        )
    )
    st.altair_chart(chart, use_container_width=True)


def render_history_table(history) -> None:
    """Render the Execution History table, most recent first."""
    st.subheader("Execution History")
    if not history:
        st.caption("No executions yet.")
        return
    st.dataframe(history_rows(history), use_container_width=True, hide_index=True)


def render_circuit_section(config: "AppConfig", selected_target) -> None:
    """Query circuit states and render the badge and timeline.

    AWS is queried only when the status is READY.
    """
    st.session_state.setdefault("last_state", {})
    st.session_state.setdefault("timeline", [])

    if can_start(config.status):
        client = AwsClient(config.region)
        table = config.resolve_result.found["table"]
        now = int(time.time())
        ts = datetime.datetime.now(datetime.timezone.utc)
        open_untils = {}
        states = {}
        services = tracked_targets(selected_target, st.session_state["history"])
        for _, name in target_options(config):
            if name not in services:
                services.append(name)
        for service in services:
            res = call_aws(client.query_circuit, table, service, now)
            if res.ok:
                state, err = derive_circuit_state(res.value, now), None
                open_untils[service] = circuit_open_until(res.value, now)
            else:
                state, err = "UNKNOWN", res
            if err is not None:
                st.error(f"Circuit query for {service} failed: {err.error_type}: {err.message}")
            st.session_state["last_state"], st.session_state["timeline"] = update_circuit_tracking(
                st.session_state["last_state"], st.session_state["timeline"], service, state, ts
            )
            states[service] = state
        render_badges(target_options(config), states)

        failing = config.resolve_result.found.get("test")
        render_clock(
            clock_config(
                st.session_state["history"], failing, open_untils.get(failing), load_retry_policy()
            ),
            name="TestCircuitBreakerFunction",
        )

    render_timeline(st.session_state["timeline"])


# ---------------------------------------------------------------------------
# Circuit breaker clock and explanation
# ---------------------------------------------------------------------------
# The retry policy is read from the local state machine definition so the clock matches
# the deployed stack (as long as the file has not been edited without redeploying).

ASL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "circuit-breaker-netcore-blog",
    "circuit-breaker",
    "statemachine",
    "circuitbreaker.asl.json",
)

# How long UpdateCircuitStatusLambda keeps the circuit OPEN (EXPIRE_SECONDS in its
# Function.cs). Used only for the explanation; the close countdown uses the real
# ExpireTimeStamp read from DynamoDB.
OPEN_SECONDS = 20


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """The Execute Lambda step's timeout and retry settings.

    Defaults are the values in the sample's ``circuitbreaker.asl.json``.
    """

    timeout_seconds: float = 12
    max_attempts: int = 3
    interval_seconds: float = 2
    backoff_rate: float = 1.5


def load_retry_policy(path: str = ASL_PATH) -> RetryPolicy:
    """Read the Execute Lambda timeout/retry settings from the ASL file.

    Falls back to :class:`RetryPolicy` defaults if the file is missing or malformed.
    Missing Retry fields use the Step Functions defaults (1 s interval, 3 attempts,
    backoff 2.0).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            asl = json.load(fh)
        task = asl["States"]["Execute Lambda"]
        retry = task["Retry"][0]
        return RetryPolicy(
            timeout_seconds=float(task.get("TimeoutSeconds", RetryPolicy.timeout_seconds)),
            max_attempts=int(retry.get("MaxAttempts", 3)),
            interval_seconds=float(retry.get("IntervalSeconds", 1)),
            backoff_rate=float(retry.get("BackoffRate", 2.0)),
        )
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return RetryPolicy()


def retry_schedule(policy: RetryPolicy) -> list:
    """Return the ``(label, seconds)`` phases an always-failing call goes through.

    One initial attempt plus ``max_attempts`` retries, each cut off at the task
    timeout, with backoff waits in between. After the last phase the state machine
    runs Update Circuit Status and the circuit opens.
    """
    total_attempts = policy.max_attempts + 1
    phases = []
    wait = policy.interval_seconds
    for attempt in range(1, total_attempts + 1):
        phases.append(
            (
                f"Attempt {attempt} of {total_attempts}: calling the Lambda "
                f"(times out after {policy.timeout_seconds:g} s)",
                policy.timeout_seconds,
            )
        )
        if attempt < total_attempts:
            phases.append((f"Waiting {wait:g} s before retry {attempt}", wait))
            wait *= policy.backoff_rate
    return phases


def phase_at(phases: list, elapsed: float):
    """Return ``(label, seconds_left_in_phase, seconds_left_total)`` at ``elapsed``.

    Returns ``None`` once every phase has passed. The browser clock uses the same logic.
    """
    total = sum(d for _, d in phases)
    if elapsed >= total:
        return None
    acc = 0.0
    for label, dur in phases:
        if elapsed < acc + dur:
            return label, acc + dur - max(elapsed, 0.0), total - max(elapsed, 0.0)
        acc += dur
    return None


def circuit_open_until(items: list, now_epoch: int):
    """Return the latest unexpired ``ExpireTimeStamp`` (epoch seconds), or ``None``."""
    expiries = [int(i["ExpireTimeStamp"]["N"]) for i in items]
    future = [e for e in expiries if e > now_epoch]
    return max(future) if future else None


def trip_clock_target(history, failing_target):
    """Return the most recent RUNNING execution against ``failing_target``, or ``None``."""
    running = [r for r in history if r.target == failing_target and r.result == "RUNNING"]
    return ordered_history(running)[0] if running else None


def clock_config(history, failing_target, open_until, policy: RetryPolicy) -> dict:
    """Decide what the clock shows. Pure, so it is testable without Streamlit.

    - ``close``: the circuit is OPEN; count down to its ``ExpireTimeStamp``.
    - ``trip``: a call to the failing target is running; count down the retries.
    - ``idle``: nothing to count down.
    """
    if open_until:
        return {"mode": "close", "until": open_until, "open_seconds": OPEN_SECONDS}
    rec = trip_clock_target(history, failing_target)
    if rec is not None:
        start = rec.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.timezone.utc)
        return {
            "mode": "trip",
            "start": start.timestamp(),
            "phases": [{"label": l, "dur": d} for l, d in retry_schedule(policy)],
        }
    return {"mode": "idle"}


_CLOCK_HTML = """
<div role="timer" aria-live="off" style="font-family: 'Source Sans Pro', sans-serif;
     border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px;">
  <div id="heading" style="font-size: 0.95rem; color: #555;"></div>
  <div id="time" style="font-size: 2.4rem; font-weight: 700; line-height: 1.2;"></div>
  <div style="background: #eee; border-radius: 4px; height: 8px; margin: 6px 0;">
    <div id="bar" style="height: 8px; border-radius: 4px; width: 0%;"></div>
  </div>
  <div id="label" style="font-size: 0.95rem;"></div>
</div>
<script>
const cfg = __CFG__;
const $ = (id) => document.getElementById(id);
const fmt = (s) => { s = Math.max(0, Math.ceil(s));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
function show(heading, rem, frac, label, colour) {
  $("heading").textContent = heading; $("time").textContent = fmt(rem);
  $("bar").style.width = Math.min(100, Math.max(0, frac * 100)) + "%";
  $("bar").style.background = colour; $("label").textContent = label;
}
function tick() {
  const now = Date.now() / 1000;
  if (cfg.mode === "trip") {
    const total = cfg.phases.reduce((a, p) => a + p.dur, 0);
    const el = now - cfg.start;
    if (el >= total) {
      show(cfg.name + " circuit should now be OPEN", 0, 1,
           "Retries exhausted: Update Circuit Status writes the OPEN record. Click Refresh.",
           "#d33");
      return;
    }
    let acc = 0;
    for (const p of cfg.phases) {
      if (el < acc + p.dur) {
        show(cfg.name + " circuit trips in", total - el, el / total,
             p.label + " (" + Math.ceil(acc + p.dur - el) + " s left in this step)", "#e8a317");
        return;
      }
      acc += p.dur;
    }
  } else if (cfg.mode === "close") {
    const rem = cfg.until - now;
    if (rem <= 0) {
      show(cfg.name + " circuit should now be CLOSED", 0, 1,
           "The OPEN record has expired, so the next call goes through. Click Refresh.",
           "#2e9d4f");
      return;
    }
    show(cfg.name + " circuit closes in", rem, 1 - rem / cfg.open_seconds,
         "OPEN: calls to " + cfg.name + " fail fast without invoking it. " +
         "Other Lambdas have their own circuits and are unaffected.", "#d33");
  } else {
    show("No countdown running", 0, 0,
         "Start TestCircuitBreakerFunction to watch the circuit trip.", "#999");
  }
}
tick(); setInterval(tick, 250);
</script>
"""


def render_clock(cfg: dict, name: str = "TestCircuitBreakerFunction") -> None:
    """Render the ticking clock. It runs in the browser, so it ticks without reruns."""
    st.subheader(f"Circuit breaker clock: {name}")
    cfg = dict(cfg, name=name)
    components.html(_CLOCK_HTML.replace("__CFG__", json.dumps(cfg)), height=150)
    st.caption(
        "Estimated from the state machine's retry settings and the execution start time. "
        "Lambda cold starts and state transitions can add a second or two."
    )


def render_explanation(policy: RetryPolicy) -> None:
    """Render the 'How it works' panel with the timings this stack uses."""
    phases = retry_schedule(policy)
    total = sum(d for _, d in phases)
    with st.expander("How the circuit breaker works", expanded=False):
        st.markdown(
            f"""
Each **Start Execution** runs a Step Functions state machine with your chosen Lambda.

1. **Get Circuit Status** looks in DynamoDB for an unexpired OPEN record for that
   Lambda. If there is one, the circuit is **OPEN** and the execution fails at once,
   without calling the Lambda.
2. Otherwise **Execute Lambda** calls it. Each attempt is cut off after
   **{policy.timeout_seconds:g} s**, and a failure is retried **{policy.max_attempts}**
   times, starting with a **{policy.interval_seconds:g} s** wait that grows
   **{policy.backoff_rate:g}x** each time.
3. If every attempt fails, **Update Circuit Status** writes an OPEN record that
   expires after about **{OPEN_SECONDS} s**. Until then, calls fail fast.
4. When the record expires the circuit is **CLOSED** again and the next call goes
   through.

Circuits are **per Lambda**: the OPEN record is stored under the failing Lambda's
name, so tripping one does not affect the others. `HelloWorldFunction` succeeds,
so its circuit stays closed even while TestCircuitBreakerFunction's is open.
`TestCircuitBreakerFunction` sleeps 15 s, longer than the {policy.timeout_seconds:g} s
timeout, so every attempt fails and the circuit trips after about **{total:g} s**:
"""
        )
        st.table(
            [{"Step": label, "Seconds": f"{dur:g}"} for label, dur in phases]
            + [{"Step": "Update Circuit Status: circuit OPEN", "Seconds": f"total {total:g}"}]
        )
        st.caption(
            "Timings are read from circuit-breaker-netcore-blog/circuit-breaker/statemachine/"
            "circuitbreaker.asl.json. If you edit that file, redeploy for the stack to match."
        )


def main() -> None:
    """Entry point for the Streamlit dashboard."""
    st.set_page_config(page_title="Circuit Breaker Dashboard", layout="wide")
    st.title("Circuit Breaker Dashboard")
    config = render_sidebar()
    render_explanation(load_retry_policy())
    render_main(config)


if __name__ == "__main__":
    main()

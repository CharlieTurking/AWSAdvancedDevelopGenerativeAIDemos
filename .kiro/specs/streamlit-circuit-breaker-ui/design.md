# Design Document

## Overview

This design describes a single-file Streamlit application, `app.py`, that provides an interactive dashboard for the already-deployed AWS Step Functions circuit breaker demo in `01_circuit_breaker/circuit-breaker-netcore-blog`. The dashboard talks to live AWS through boto3 only — there is no offline or simulated mode. It auto-discovers backend resources from CloudFormation, lets the presenter start Step Functions executions against a chosen target Lambda, polls each execution to a terminal SUCCESS/FAIL result, renders a live OPEN/CLOSED circuit-state badge derived from the `CircuitBreaker` DynamoDB table, keeps a per-session execution history table, and plots a timeline of circuit transitions.

The application lives under `01_circuit_breaker/` with its own `app.py`, `requirements.txt`, and `.venv`, matching sibling demos in this repository (each demo owns its environment and uses boto3 for AWS access).

### Confirmed backend facts

These names and behaviors are taken directly from the deployed stack definition and are treated as fixed inputs to the design:

- State machine logical id: `CircuitBreakerStateMachine` (SAM `AWS::Serverless::StateMachine`, reported by CloudFormation as the transformed `AWS::StepFunctions::StateMachine`), invoked with input `{ "TargetLambda": "<Name or ARN>" }`.
- DynamoDB table: logical id `CircuitBreakerTable`, physical `TableName` = `CircuitBreaker`, key schema `ServiceName` (HASH, String) and `ExpireTimeStamp` (RANGE, Number). `ExpireTimeStamp` is also the TTL attribute.
- Target Lambda logical ids selectable by the user: `HelloWorldFunction` (succeeds) and `TestCircuitBreakerFunction` (sleeps 15s, forcing the state machine's 12s task timeout and tripping the circuit).
- Supporting Lambdas not offered as targets: `GetCircuitStatusFunction`, `UpdateCircuitStatusFunction`.
- Circuit semantics: `UpdateCircuitStatus` writes an item with `ServiceName = TargetLambda`, `CircuitStatus = "OPEN"`, and `ExpireTimeStamp = now + 20s`. A service is OPEN while an item exists for its `ServiceName` with `ExpireTimeStamp` in the future; otherwise CLOSED. TTL eventually deletes expired items, so the circuit self-recovers.

Because `ServiceName` equals the exact `TargetLambda` string passed into the state machine, the dashboard derives circuit state by querying the table with the same target identifier it used to start the execution. This is the key coupling the design relies on.

## Architecture

The application is one Streamlit script organized into cohesive internal components. The components are plain Python classes/functions in `app.py` (not separate modules) so the demo stays a single file, but they are separated by responsibility so the pure logic is unit/property testable in isolation from Streamlit and boto3.

```
                        +---------------------------+
                        |   Streamlit UI (app.py)   |
                        |  layout, widgets, reruns  |
                        +------------+--------------+
                                     |
             +-----------------------+------------------------+
             |                       |                        |
     +-------v------+       +--------v--------+      +--------v---------+
     | ResourceState|       | ExecutionState  |      | CircuitState     |
     | (resolved ids|       | (history + poll)|      | (badge+timeline) |
     |  + status)   |       |                 |      |                  |
     +-------+------+       +--------+--------+      +--------+---------+
             |                       |                        |
             +-----------------------+------------------------+
                                     |
                         +-----------v-----------+
                         |  Pure logic helpers   |
                         | resolver, classify,   |
                         | derive_state, input,  |
                         | transition detection  |
                         +-----------+-----------+
                                     |
                         +-----------v-----------+
                         |      AWS_Client       |
                         | boto3: cfn, sfn,      |
                         | dynamodb              |
                         +-----------------------+
```

### Component responsibilities

**AWS_Client** — the only component that performs network I/O. Wraps three boto3 clients (`cloudformation`, `stepfunctions`, `dynamodb`) built from a single `boto3.Session` with the resolved Region. It exposes thin methods that each wrap one AWS call and return raw results (or raise), so error handling and all decision logic live outside it and remain testable:

- `list_stack_resources(stack_name) -> list[dict]`
- `start_execution(state_machine_arn, input_json) -> dict`
- `describe_execution(execution_arn) -> dict`
- `query_circuit(table_name, service_name, now_epoch) -> list[dict]`

**Resource_Resolver** — pure logic plus one AWS_Client call. Given the raw CloudFormation stack-resource list, it selects the physical ids for the state machine, the `CircuitBreaker` table, and the two target Lambda functions by matching primarily on the exact `LogicalResourceId`, with `ResourceType` treated only as a non-strict hint (see note below). It reports, by name, any required resource it cannot find. The selection logic is a pure function over the resource list; only fetching the list touches AWS.

**Circuit state derivation** — pure function `derive_circuit_state(items, now_epoch)` returning `OPEN`, `CLOSED`, or `UNKNOWN`. OPEN when any queried item has `ExpireTimeStamp > now`; CLOSED otherwise; `UNKNOWN` is produced by the caller when the query raised.

**Execution polling** — pure classifier `classify_result(sfn_status)` mapping Step Functions execution status to `SUCCESS` / `FAIL` / `RUNNING` / `UNKNOWN`, plus `ExecutionState` that stores the per-session history and drives polling on each Streamlit rerun.

**Streamlit UI** — layout, widgets, and the rerun/auto-refresh loop. Reads and writes `st.session_state` for `Execution_History` and timeline data points. Never calls boto3 directly; always goes through AWS_Client and the pure helpers.

### Why the logic is split out from Streamlit and boto3

Streamlit re-executes the whole script top to bottom on every interaction and on every auto-refresh tick. If decision logic were interleaved with `st.*` calls and boto3 calls, it could not be tested without a running Streamlit server and live AWS. By keeping resolution, classification, state derivation, payload building, history updates, and transition detection as pure functions, the correctness properties below can be checked with generated inputs and mocked AWS, while the thin Streamlit layer just wires them to widgets.

## Components and Interfaces

### Configuration and session bootstrap

```
Region  <- os.environ["AWS_DEFAULT_REGION"] or os.environ["AWS_REGION"]
Stack_Name <- st.session_state (default "circuit-breaker-stack"), editable via sidebar text input
```

Config resolution order on each run:

1. If no Region in the environment -> set app status `REGION_NOT_CONFIGURED`, disable controls, stop.
2. Build `boto3.Session(region_name=Region)` and the three clients. If session/credential construction fails -> status `NO_CREDENTIALS`, disable controls.
3. Run Resource_Resolver against the current Stack_Name. Map outcomes to status `STACK_NOT_FOUND`, `RESOURCE_MISSING(name)`, or `READY`.
4. Controls (target selector, Start button) are enabled only when status is `READY`.

Changing the Stack_Name sidebar input updates `st.session_state` and triggers a rerun, which re-runs resolution against the new name (step 3).

### AWS_Client (boto3 usage)

```python
class AwsClient:
    def __init__(self, region: str):
        self._session = boto3.Session(region_name=region)
        self.cfn = self._session.client("cloudformation")
        self.sfn = self._session.client("stepfunctions")
        self.ddb = self._session.client("dynamodb")

    def list_stack_resources(self, stack_name: str) -> list[dict]:
        # Paginate describe_stack_resources / list_stack_resources
        resources, token = [], None
        while True:
            kwargs = {"StackName": stack_name}
            if token:
                kwargs["NextToken"] = token
            resp = self.cfn.list_stack_resources(**kwargs)
            resources.extend(resp["StackResourceSummaries"])
            token = resp.get("NextToken")
            if not token:
                break
        return resources

    def start_execution(self, state_machine_arn: str, input_json: str) -> dict:
        return self.sfn.start_execution(
            stateMachineArn=state_machine_arn, input=input_json
        )

    def describe_execution(self, execution_arn: str) -> dict:
        return self.sfn.describe_execution(executionArn=execution_arn)

    def query_circuit(self, table_name: str, service_name: str, now_epoch: int) -> list[dict]:
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
```

Boto3 API notes:

- **CloudFormation**: `list_stack_resources` returns `StackResourceSummaries` with `LogicalResourceId`, `ResourceType`, and `PhysicalResourceId` — enough to resolve every id the dashboard needs. `describe_stack_resources` returns the same fields under `StackResources` and is an acceptable equivalent; the design uses `list_stack_resources` because it paginates cleanly for larger stacks. A nonexistent stack raises a `ClientError` whose message contains "does not exist", which maps to `STACK_NOT_FOUND`.
- **Step Functions**: `start_execution(stateMachineArn, input)` where `input` is the JSON string `{"TargetLambda": "<target>"}`. It returns `executionArn` and `startDate`. `describe_execution(executionArn)` returns `status` in `RUNNING | SUCCEEDED | FAILED | TIMED_OUT | ABORTED` plus `output` when succeeded. No separate list call is needed since the dashboard tracks the ARNs it started.
- **DynamoDB**: low-level `query` with a `KeyConditionExpression` on both `ServiceName` (equality) and `ExpireTimeStamp > :t`. Because `ExpireTimeStamp` is the RANGE key, this mirrors exactly what the .NET `GetCircuitStatus` function does (`QueryOperator.GreaterThan` on the sort key). `ConsistentRead=True` matches the backend's consistent reads so the badge does not lag the writes made by `UpdateCircuitStatus`.

### Resource_Resolver

```python
# Each required resource is keyed by its stable LogicalResourceId. The
# accepted ResourceType values are a non-strict hint: for a SAM stack
# CloudFormation reports the post-transform CFN type, but the macro
# AWS::Serverless::* type may also appear, so both are accepted.
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

def resolve_resources(resources: list[dict]) -> ResolveResult:
    """Pure: select physical ids from a CloudFormation resource list.

    Match primarily on the exact LogicalResourceId (SAM preserves it across
    the transform). ResourceType is only a non-strict hint: when the hint set
    is non-empty it is used to disambiguate duplicate logical ids, but a type
    mismatch never alone rejects an otherwise-unique logical-id match.
    """
    found, missing = {}, []
    for key, spec in REQUIRED.items():
        logical, types = spec["logical"], spec["types"]
        candidates = [r for r in resources
                      if r.get("LogicalResourceId") == logical]
        # Prefer a candidate whose type is in the accepted hint set; otherwise
        # fall back to the sole logical-id match so the exact-type report from
        # CloudFormation (transformed or macro) does not break resolution.
        match = next((r for r in candidates
                      if r.get("ResourceType") in types), None)
        if match is None and len(candidates) == 1:
            match = candidates[0]
        if match is None:
            missing.append(logical)
        else:
            found[key] = match["PhysicalResourceId"]
    return ResolveResult(found=found, missing=missing)
```

Matching keys on the exact `LogicalResourceId`, which is stable across deploys (and preserved by the SAM transform) even though CloudFormation appends a random suffix to physical names. `ResourceType` is a non-strict hint only: it disambiguates when a logical id appears more than once, but a type mismatch never rejects an otherwise-unique logical-id match. The table's physical name is expected to be `CircuitBreaker`; the resolver still returns the resolved physical id so a renamed table would be handled correctly. On success the UI shows the resolved state machine ARN, table name, and the two target function names. On any missing required resource, the UI names the missing logical id(s) and disables controls.

> **Note on SAM-transformed resource types.** The backend is deployed via AWS SAM. In the template the state machine is `AWS::Serverless::StateMachine` and the target Lambdas are `AWS::Serverless::Function`, but CloudFormation `list_stack_resources` / `describe_stack_resources` report the *post-transform* CFN types (`AWS::StepFunctions::StateMachine`, `AWS::Lambda::Function`), and SAM may additionally retain the `AWS::Serverless::*` macro resources in the resource list. Matching on an exact `ResourceType` is therefore fragile, which is why the resolver relies on the preserved `LogicalResourceId` and accepts either the transformed or the macro type.

The two target Lambda **names** (not the status Lambdas) are the only values offered in the target selector, satisfying the requirement that targets are limited to `HelloWorldFunction` and `TestCircuitBreakerFunction`.

### Execution payload and classification

```python
def build_execution_input(target: str) -> str:
    return json.dumps({"TargetLambda": target})

TERMINAL_FAIL = {"FAILED", "TIMED_OUT", "ABORTED"}

def classify_result(status: str) -> str:
    if status == "SUCCEEDED":
        return "SUCCESS"
    if status in TERMINAL_FAIL:
        return "FAIL"
    if status == "RUNNING":
        return "RUNNING"
    return "UNKNOWN"
```

`build_execution_input` is the exact backend contract: a JSON object with a single `TargetLambda` key. The dashboard passes the resolved Lambda **name** as the target; the state machine's `lambda:invoke` accepts a name or ARN, and the same string becomes the DynamoDB `ServiceName`.

### Execution history and per-execution polling

`Execution_History` is a list of records in `st.session_state`:

```python
@dataclass
class ExecutionRecord:
    execution_arn: str
    short_id: str          # suffix of the ARN, shown in the table
    target: str            # selected Target_Lambda name
    start_time: datetime   # when StartExecution succeeded
    status: str            # RUNNING | SUCCEEDED | FAILED | TIMED_OUT | ABORTED | UNKNOWN
    result: str            # SUCCESS | FAIL | RUNNING | UNKNOWN
```

History operations (pure over the list):

- `add_execution(history, record) -> history'` appends; used only after a successful StartExecution. A failed start does not call this, so history is unchanged on failure.
- `update_execution(history, execution_arn, status, result) -> history'` replaces only the matching record's `status`/`result`, preserving length, order, and all other records.
- `ordered_history(history) -> list` returns records sorted by `start_time` descending (most recent first) for rendering; it is a pure sort and does not mutate stored order.

Polling model: on each script run, the UI iterates over history records whose `result` is `RUNNING`, calls `describe_execution`, and applies `update_execution` with the fresh status and `classify_result`. A polling error for one execution sets that record's status/result to `UNKNOWN` and surfaces the error, without affecting other records.

### Circuit badge and timeline

```python
def derive_circuit_state(items: list[dict], now_epoch: int) -> str:
    for item in items:
        if int(item["ExpireTimeStamp"]["N"]) > now_epoch:
            return "OPEN"
    return "CLOSED"
```

Because the DynamoDB query already filters `ExpireTimeStamp > :t`, any returned item implies OPEN; the explicit comparison in `derive_circuit_state` keeps the logic correct and testable even if called with an unfiltered item list. If the query raised, the caller substitutes `UNKNOWN`.

The badge is read for the currently selected target's name (its `ServiceName`). The dashboard also reads state for any target that appears in history so transitions are captured even after the selection changes.

Timeline data points live in `st.session_state["timeline"]` as `(timestamp, service_name, state)` tuples. Transition detection is pure:

```python
def detect_transitions(prev_state: str | None, new_state: str, ts: datetime):
    """Return a list with one point if the state changed, else empty."""
    if new_state in ("OPEN", "CLOSED") and new_state != prev_state:
        return [(ts, new_state)]
    return []
```

On each refresh, for each tracked service the UI compares the last recorded state to the freshly derived state and appends a point only on a genuine change. `UNKNOWN` observations do not create points and do not overwrite the last known OPEN/CLOSED baseline used for comparison.

### Streamlit layout and the auto-refresh / rerun model

Streamlit executes `app.py` top to bottom on every run. The design embraces that instead of fighting it:

1. **State lives in `st.session_state`**, not in local variables: `Execution_History`, `timeline`, `stack_name`, last-known per-service circuit state, and the cached resolved resources. Pure helpers take these in and return new values that are written back.
2. **Auto-refresh** is driven by `st.autorefresh` (via `streamlit-autorefresh`) with an interval of at most 5000 ms. Each tick is a normal rerun: the script re-reads config, polls any `RUNNING` executions, re-queries circuit state, detects transitions, and re-renders. This single cadence satisfies the "no more than 5 seconds" requirement for execution polling, badge refresh, and timeline updates simultaneously.
3. **Work per run is bounded**: polling only touches executions still `RUNNING`, and circuit queries are small single-partition queries, so each rerun stays cheap enough for a demo.

Layout:

```
Sidebar
  - Region (read-only, from environment)
  - Stack Name (text input -> st.session_state["stack_name"])
  - Resolved resources panel (state machine ARN, table name, target names)
  - Connectivity / resolution status messages

Main
  - Header: circuit-state badge (OPEN / CLOSED / UNKNOWN) for selected target
  - Controls: Target_Lambda selectbox (HelloWorldFunction | TestCircuitBreakerFunction),
              Start Execution button  [disabled unless status == READY]
  - Latest result line: "<short_id>: SUCCESS|FAIL"
  - Execution History table (most recent first)
  - Circuit Transition Timeline chart
```

Controls are gated behind the single `status == READY` check so that every unmet precondition (no region, no credentials, stack missing, resource missing) disables starting executions, as required.

## Data Models

### Application status (drives control gating)

```
Status = READY
       | REGION_NOT_CONFIGURED
       | NO_CREDENTIALS
       | STACK_NOT_FOUND
       | RESOURCE_MISSING          # carries list of missing logical ids
       | AWS_ERROR                 # carries (error_type, message)
```

### ResolveResult

```
ResolveResult:
    found: dict[str, str]    # key -> physical id (state_machine, table, hello, test)
    missing: list[str]       # missing logical resource ids
    ok: bool                 # == (len(missing) == 0)
```

### ExecutionRecord

As defined above. Serializable to a table row: `[short_id, target, start_time, status, result]`.

### Timeline point

```
TimelinePoint:
    timestamp: datetime
    service_name: str        # == target Lambda name == DynamoDB ServiceName
    state: "OPEN" | "CLOSED"
```

### DynamoDB item shape (read)

```
{ "ServiceName": {"S": <target>},
  "CircuitStatus": {"S": "OPEN"},
  "ExpireTimeStamp": {"N": "<epoch-seconds>"} }
```

## Error Handling

All AWS calls are funneled through a single handler so that no boto3 exception terminates the Streamlit script:

```python
def call_aws(fn, *args, **kwargs):
    try:
        return Ok(fn(*args, **kwargs))
    except NoCredentialsError:
        return Err("NO_CREDENTIALS", "AWS credentials are unavailable.")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "ClientError")
        msg = e.response.get("Error", {}).get("Message", str(e))
        return Err(code, msg)
    except BotoCoreError as e:
        return Err(type(e).__name__, str(e))
```

Mapping from error to UI behavior:

- **Missing/invalid credentials** (`NoCredentialsError`, `ClientError` with auth codes) -> status `NO_CREDENTIALS`, error message, controls disabled.
- **Stack not found** (`ClientError` whose message contains "does not exist" for the stack call) -> status `STACK_NOT_FOUND`, error message, controls disabled.
- **Any other AWS service error** -> show error code/type and message via `st.error`; the script continues. For a StartExecution failure, history is left unchanged for that attempt. For a DescribeExecution failure, the affected record becomes `UNKNOWN`. For a circuit query failure, the badge renders `UNKNOWN`.
- **Region not configured** -> status `REGION_NOT_CONFIGURED`, error message, controls disabled (checked before any AWS call).

The handler returns a result object rather than raising, so callers decide the local consequence (unchanged history, unknown status, unknown badge) while the top-level script keeps running and re-rendering.

## Testing Strategy

The pure helpers (`resolve_resources`, `classify_result`, `derive_circuit_state`, `build_execution_input`, `add_execution`/`update_execution`/`ordered_history`, `detect_transitions`, and `call_aws`'s mapping) are tested in isolation with mocked boto3 clients. The strategy combines:

- **Property tests** (via Hypothesis) for the universal properties below — minimum 100 iterations each, each tagged with its design property. These cover resolution, classification, circuit derivation, payload round-trip, history transitions, ordering, timeline change-detection, the AWS-error invariant, and the connectivity guard.
- **Example/edge tests** for UI-shaped criteria and specific error states: resolved-resources panel contents (1.5), credentials-unavailable state (2.2), stack-not-found state (2.3), region-not-configured state (8.2), stack-name control presence and re-resolution (8.3, 8.4), target selector contents (3.1), result line rendering (4.3), polling-error-to-unknown (4.4), circuit-read-error-to-unknown (5.5), and history table columns (6.1).
- **Smoke tests** for configuration wiring: boto3 clients built with the environment Region (2.1, 8.1).
- **Integration test** (mocked DynamoDB) confirming the circuit query is issued with `ServiceName` equality plus `ExpireTimeStamp > now` (5.1).
- A shared **configuration assertion** that the refresh interval constant is <= 5 seconds (4.1, 5.4, 7.4).

Unit tests stay focused on specific examples and edge/error conditions; property tests carry the burden of broad input coverage. Each property test references its design property with the tag format **Feature: streamlit-circuit-breaker-ui, Property {number}: {property_text}**.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Resource resolution returns the correct identifiers

*For any* CloudFormation resource list that contains the state machine, the `CircuitBreaker` table, and both target Lambda resources — each identified by its `LogicalResourceId` and carrying either its transformed CFN type or its `AWS::Serverless::*` macro type (plus arbitrary unrelated resources) — `resolve_resources` returns exactly those four physical ids mapped to their keys and reports no missing resources.

**Validates: Requirements 1.1, 1.2, 1.3**

### Property 2: A missing required resource is reported by name

*For any* otherwise-complete CloudFormation resource list from which one required resource is removed, `resolve_resources` reports that resource's logical id as missing and yields `ok == False`.

**Validates: Requirements 1.4**

### Property 3: Any AWS error becomes a displayable message and never terminates

*For any* AWS exception (`NoCredentialsError`, `ClientError` with any code/message, or any `BotoCoreError`) raised by a wrapped call, `call_aws` returns an error result carrying a non-empty error type and message and never propagates the exception.

**Validates: Requirements 2.4**

### Property 4: No connectivity blocks starting executions

*For any* application status other than `READY`, the start-execution guard evaluates to false, so no execution can be started.

**Validates: Requirements 2.5**

### Property 5: Execution input encodes exactly the target

*For any* target Lambda identifier string, parsing `build_execution_input(target)` yields a JSON object whose only key is `TargetLambda` with a value equal to the target.

**Validates: Requirements 3.2**

### Property 6: Starting records history on success and leaves it unchanged on failure

*For any* execution history and any successful start result, `add_execution` yields a history one longer whose newest record carries the returned execution id, the selected target, and a start time; and *for any* history, a failed start attempt leaves the history equal to its prior value.

**Validates: Requirements 3.3, 3.4, 6.2**

### Property 7: Terminal status classification is correct

*For any* Step Functions execution status, `classify_result` maps `SUCCEEDED` to `SUCCESS`, each of `FAILED`, `TIMED_OUT`, and `ABORTED` to `FAIL`, `RUNNING` to in-progress, and any other value to unknown.

**Validates: Requirements 4.2**

### Property 8: Circuit state is OPEN exactly when an unexpired item exists

*For any* set of queried `CircuitBreaker` items and any current time, `derive_circuit_state` returns `OPEN` if and only if at least one item has `ExpireTimeStamp` greater than the current time, and returns `CLOSED` otherwise.

**Validates: Requirements 5.2, 5.3**

### Property 9: Updating an execution changes only the targeted row

*For any* execution history and any execution id present in it, `update_execution` applied with a new status and result preserves the history length, changes only the matching record's status and result, and leaves every other record unchanged.

**Validates: Requirements 6.3**

### Property 10: History is ordered most-recent-first

*For any* execution history, `ordered_history` returns a permutation of the input sorted by start time in non-increasing order.

**Validates: Requirements 6.4**

### Property 11: Timeline adds a point exactly on each circuit-state change

*For any* sequence of observed OPEN/CLOSED circuit states, applying the transition detector across the sequence appends exactly one timeline point per adjacent state change, each labeled with the new state and carrying its observation timestamp, and appends no point when the state is unchanged.

**Validates: Requirements 7.2, 7.3**

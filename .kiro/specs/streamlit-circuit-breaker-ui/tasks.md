# Implementation Plan: Streamlit Circuit Breaker UI

## Overview

The implementation builds a single-file Streamlit dashboard (`app.py`) under `01_circuit_breaker/`, backed by its own `requirements.txt` and `.venv`. Work proceeds bottom-up: first the project scaffold, then the pure logic helpers (each paired with its Hypothesis property test), then the `AwsClient` boto3 wrapper and the `call_aws` error handler, the `Resource_Resolver`, the execution/history logic, the circuit-state/timeline logic, and finally the Streamlit UI wiring with configuration and status gating. Each step builds on the previous ones and ends with integration into `app.py`, so no code is left orphaned.

Pure helpers are implemented first because the Streamlit layer and `AwsClient` depend on them, and they carry the bulk of the correctness guarantees via property-based tests. Test sub-tasks are marked optional with `*`.

## Tasks

- [x] 1. Project scaffold and app skeleton
  - Create `01_circuit_breaker/app.py` with module docstring, imports (`os`, `json`, `datetime`, `dataclasses`, `boto3`, `botocore.exceptions`, `streamlit`), and the module-level `REFRESH_INTERVAL_MS` constant (<= 5000)
  - Create `01_circuit_breaker/requirements.txt` pinning `streamlit`, `streamlit-autorefresh`, `boto3`, and `hypothesis` (test dependency)
  - Add placeholder sections/comments in `app.py` for each component (config bootstrap, AwsClient, resolver, execution/history, circuit/timeline, UI) so later tasks slot into a defined structure
  - Create a `tests/` folder under `01_circuit_breaker/` with an empty `__init__.py` and a `conftest.py` that makes `app` importable without launching Streamlit
  - _Requirements: 4.1, 5.4, 7.4_

- [x] 2. Pure execution-input and classification helpers
  - [x] 2.1 Implement `build_execution_input(target)` and `classify_result(status)`
    - `build_execution_input` returns `json.dumps({"TargetLambda": target})`
    - Define `TERMINAL_FAIL = {"FAILED", "TIMED_OUT", "ABORTED"}` and map `SUCCEEDED`->`SUCCESS`, terminal-fail->`FAIL`, `RUNNING`->`RUNNING`, otherwise `UNKNOWN`
    - _Requirements: 3.2, 4.2_
  - [x] 2.2 Write property test for execution input encoding
    - **Feature: streamlit-circuit-breaker-ui, Property 5: Execution input encodes exactly the target**
    - **Validates: Requirements 3.2**
  - [x] 2.3 Write property test for status classification
    - **Feature: streamlit-circuit-breaker-ui, Property 7: Terminal status classification is correct**
    - **Validates: Requirements 4.2**

- [x] 3. AWS error handler
  - [x] 3.1 Implement `Ok`/`Err` result types and `call_aws(fn, *args, **kwargs)`
    - Catch `NoCredentialsError` -> `Err("NO_CREDENTIALS", ...)`, `ClientError` -> `Err(code, message)` from the error response, `BotoCoreError` -> `Err(type-name, str)`; return `Ok(value)` otherwise; never propagate
    - _Requirements: 2.4_
  - [x] 3.2 Write property test for the AWS-error invariant
    - **Feature: streamlit-circuit-breaker-ui, Property 3: Any AWS error becomes a displayable message and never terminates**
    - **Validates: Requirements 2.4**

- [x] 4. AwsClient boto3 wrapper
  - [x] 4.1 Implement the `AwsClient` class
    - Build a single `boto3.Session(region_name=region)` and the `cloudformation`, `stepfunctions`, `dynamodb` clients from it
    - Implement `list_stack_resources` (paginated via `NextToken`), `start_execution`, `describe_execution`, and `query_circuit` (low-level DynamoDB `query` with `ServiceName = :s AND ExpireTimeStamp > :t`, `ConsistentRead=True`)
    - _Requirements: 2.1, 3.2, 4.1, 5.1, 8.1_
  - [x] 4.2 Write smoke tests for client construction
    - With a mocked `boto3.Session`, assert clients are built using the environment Region
    - _Requirements: 2.1, 8.1_
  - [x] 4.3 Write integration test for the circuit query (mocked DynamoDB)
    - Assert `query_circuit` issues a query with `ServiceName` equality plus `ExpireTimeStamp > now`
    - _Requirements: 5.1_

- [x] 5. Resource_Resolver
  - [x] 5.1 Implement `REQUIRED` map, `ResolveResult`, and pure `resolve_resources(resources)`
    - Match each required resource primarily by exact `LogicalResourceId`; treat `ResourceType` as a non-strict hint (accept either the transformed CFN type or the `AWS::Serverless::*` macro type, using the hint only to disambiguate duplicate logical ids and never to reject a sole logical-id match) since CloudFormation reports post-transform types for the SAM-deployed stack
    - Collect physical ids into `found`, missing logical ids into `missing`; set `ok == (len(missing) == 0)`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [x] 5.2 Write property test for correct resolution
    - **Feature: streamlit-circuit-breaker-ui, Property 1: Resource resolution returns the correct identifiers**
    - **Validates: Requirements 1.1, 1.2, 1.3**
  - [x] 5.3 Write property test for missing-resource reporting
    - **Feature: streamlit-circuit-breaker-ui, Property 2: A missing required resource is reported by name**
    - **Validates: Requirements 1.4**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Execution history and polling logic
  - [x] 7.1 Implement `ExecutionRecord` and history operations
    - Define the `ExecutionRecord` dataclass (`execution_arn`, `short_id`, `target`, `start_time`, `status`, `result`)
    - Implement pure `add_execution(history, record)` (append), `update_execution(history, execution_arn, status, result)` (replace only the matching record, preserving length/order), and `ordered_history(history)` (non-mutating sort by `start_time` descending)
    - _Requirements: 3.3, 3.4, 6.2, 6.3, 6.4_
  - [x] 7.2 Write property test for start-records-history / unchanged-on-failure
    - **Feature: streamlit-circuit-breaker-ui, Property 6: Starting records history on success and leaves it unchanged on failure**
    - **Validates: Requirements 3.3, 3.4, 6.2**
  - [x] 7.3 Write property test for targeted-row update
    - **Feature: streamlit-circuit-breaker-ui, Property 9: Updating an execution changes only the targeted row**
    - **Validates: Requirements 6.3**
  - [x] 7.4 Write property test for most-recent-first ordering
    - **Feature: streamlit-circuit-breaker-ui, Property 10: History is ordered most-recent-first**
    - **Validates: Requirements 6.4**

- [x] 8. Circuit state and timeline logic
  - [x] 8.1 Implement `derive_circuit_state(items, now_epoch)` and `detect_transitions(prev_state, new_state, ts)`
    - `derive_circuit_state` returns `OPEN` when any item has `ExpireTimeStamp > now_epoch`, else `CLOSED`
    - `detect_transitions` returns a single `(ts, new_state)` point only when `new_state` is OPEN/CLOSED and differs from `prev_state`, else empty; `UNKNOWN` yields no point
    - _Requirements: 5.2, 5.3, 7.2, 7.3_
  - [x] 8.2 Write property test for circuit-state derivation
    - **Feature: streamlit-circuit-breaker-ui, Property 8: Circuit state is OPEN exactly when an unexpired item exists**
    - **Validates: Requirements 5.2, 5.3**
  - [x] 8.3 Write property test for timeline transition detection
    - **Feature: streamlit-circuit-breaker-ui, Property 11: Timeline adds a point exactly on each circuit-state change**
    - **Validates: Requirements 7.2, 7.3**

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Configuration bootstrap and status gating
  - [x] 10.1 Implement config resolution and the start-execution guard
    - Read Region from `AWS_DEFAULT_REGION`/`AWS_REGION`; manage `stack_name` in `st.session_state` (default `circuit-breaker-stack`)
    - Compute `Status` (`READY | REGION_NOT_CONFIGURED | NO_CREDENTIALS | STACK_NOT_FOUND | RESOURCE_MISSING | AWS_ERROR`) in resolution order: region check, session/client construction via `call_aws`, resolver outcome mapping (stack-not-found when the error message contains "does not exist", else resource-missing/ready)
    - Implement a pure `can_start(status)` guard that is true only when `status == READY`
    - _Requirements: 2.2, 2.3, 2.5, 8.1, 8.2, 8.4_
  - [x] 10.2 Write property test for the connectivity guard
    - **Feature: streamlit-circuit-breaker-ui, Property 4: No connectivity blocks starting executions**
    - **Validates: Requirements 2.5**
  - [x] 10.3 Write example/edge tests for status states
    - Cover region-not-configured (8.2), credentials-unavailable (2.2), and stack-not-found (2.3) status outcomes and control disabling
    - _Requirements: 2.2, 2.3, 8.2_

- [x] 11. Streamlit UI wiring
  - [x] 11.1 Build the sidebar and resolved-resources panel
    - Read-only Region display, Stack Name text input bound to `st.session_state["stack_name"]`, resolved resources panel (state machine ARN, table name, target names), and connectivity/resolution status messages; changing the stack name triggers re-resolution
    - _Requirements: 1.5, 8.3, 8.4_
  - [x] 11.2 Build the main controls, polling loop, and result line
    - Target selectbox limited to `HelloWorldFunction` and `TestCircuitBreakerFunction`, Start Execution button disabled unless `can_start(status)`; on click call `start_execution` through `call_aws`, on success `add_execution`, on failure surface the error and leave history unchanged
    - On each run, poll records whose `result` is `RUNNING` via `describe_execution`, apply `update_execution` with `classify_result`; set a record to `UNKNOWN` on a per-execution polling error without affecting others; render the latest `"<short_id>: SUCCESS|FAIL"` result line
    - _Requirements: 2.5, 3.1, 3.2, 3.3, 3.4, 4.3, 4.4_
  - [x] 11.3 Build the circuit badge, history table, timeline chart, and auto-refresh
    - Query circuit state for the selected target and tracked history targets via `call_aws`, derive OPEN/CLOSED (UNKNOWN on query error), render the badge; maintain last-known per-service state and append timeline points via `detect_transitions`
    - Render the Execution History table (`short_id`, target, start time, status, result) via `ordered_history`, and the circuit transition Timeline chart; wire `st.autorefresh` with `REFRESH_INTERVAL_MS`
    - _Requirements: 4.1, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.4, 7.1, 7.4_
  - [x] 11.4 Write example/edge tests for UI-shaped criteria
    - Cover resolved-resources panel contents (1.5), target selector contents (3.1), result line rendering (4.3), polling-error-to-unknown (4.4), circuit-read-error-to-unknown (5.5), history table columns (6.1), and stack-name control presence/re-resolution (8.3, 8.4)
    - _Requirements: 1.5, 3.1, 4.3, 4.4, 5.5, 6.1, 8.3, 8.4_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, but they carry the correctness guarantees from the design.
- Each task references specific requirements for traceability; property test sub-tasks reference their numbered design property.
- Checkpoints ensure incremental validation after the pure-logic layer, after the state logic, and at the end.
- The application stays a single `app.py`; the component split exists so pure logic is testable without a running Streamlit server or live AWS.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "5.1", "7.1", "8.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "5.2", "5.3", "7.2", "7.3", "7.4", "8.2", "8.3", "10.1"] },
    { "id": 3, "tasks": ["4.1", "10.2", "10.3"] },
    { "id": 4, "tasks": ["4.2", "4.3", "11.1"] },
    { "id": 5, "tasks": ["11.2"] },
    { "id": 6, "tasks": ["11.3"] },
    { "id": 7, "tasks": ["11.4"] }
  ]
}
```

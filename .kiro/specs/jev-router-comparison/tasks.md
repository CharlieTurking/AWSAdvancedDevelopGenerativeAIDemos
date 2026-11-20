# Implementation Plan: Jev Router Comparison

## Overview

This plan adds the Jev router as an alternative to the `IntelligentModelRouter` in `01_intell_model_select`. The design uses Python 3.12 for the Lambda, so no language choice is needed. Work proceeds bottom-up: test scaffolding and the dependency-free Jev client, the secret loader, the pure Routing_Policy and Jev_Router, handler integration, SAM template, Web UI, documentation, and then an optional live verification pass against the real Jev API.

All paths are relative to `01_intell_model_select/`. `router.py`, `health_monitor.py`, `failure_simulator.py`, and `bedrock_adapter.py` are not modified. No task writes, asks for, or commits the TypeSafe API key. The user stores the key in SSM Parameter Store or Secrets Manager themselves, and only the secret name is ever passed to the code or the deployment.

## Tasks

- [x] 1. Build the Jev client and test scaffolding
  - [x] 1.1 Create test scaffolding under `tests/`
    - Add `tests/requirements.txt` with pinned `pytest` and `hypothesis` versions (not added to `lambda/requirements.txt`)
    - Add `tests/conftest.py` that puts `lambda/` on `sys.path`, provides a fake Jev transport (records calls, can return bodies, statuses, raise errors, or sleep), a "fail if called" transport, and a log-capture fixture
    - Add `tests/strategies.py` with Hypothesis generators: `jev_outcomes()`, `health_states()`, `bad_bodies()`, `queries()`, `api_keys()`
    - _Requirements: 14.1_

  - [x] 1.2 Implement `lambda/jev_client.py`
    - Define `JevAnswer`, `JevError`, and `JevOutcome`, plus constants `JEV_URL`, `CHOICE_KEY`, `HIGH_CONSEQUENCE_KEY`
    - Implement `build_request` (pinned `model`, `state` with query and characteristics from `QueryAnalyzer`, Choice question with capability-derived descriptions, optional `noul` high-consequence question)
    - Implement `parse_response` (choice, probabilities, confidence, optional `noul` probability, model version; reject NaN, out-of-range, and wrong types as `invalid_response`)
    - Implement `call_jev` using `urllib.request` only, POST, Bearer header, JSON body, single worker thread with wall-clock deadline from `JEV_TIMEOUT_SECONDS` (default 5), injectable `transport`, and mapping of failures to `timeout`, `http_error`, `invalid_response` without raising
    - Implement `load_recording(query)` for recorded mode: normalised exact match against `lambda/jev_recordings.json`, a miss returns a no-recording error
    - Never log headers or the key; reduce exceptions to their class name
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 15.1, 15.5_

  - [x]* 1.3 Write property test for request construction
    - File: `tests/test_prop_build_request.py`
    - **Property 3: Request construction reflects the query, characteristics, and catalogue**
    - **Validates: Requirements 3.3, 3.4, 3.5**

  - [x]* 1.4 Write property test for payload JSON round trip
    - File: `tests/test_prop_payload_roundtrip.py`
    - **Property 4: Request payload JSON round trip**
    - **Validates: Requirements 3.9**

  - [x]* 1.5 Write property test for response parsing
    - File: `tests/test_prop_parse_response.py`
    - **Property 5: Valid responses parse to the matching answer**
    - **Validates: Requirements 3.6**

  - [x]* 1.6 Write property test and examples for failure mapping
    - File: `tests/test_prop_call_jev_errors.py`
    - **Property 6: Failures map to a categorised error and never raise**
    - **Validates: Requirements 3.8**
    - Example: fake transport asserts method POST, URL, and Bearer header (3.2)
    - Example: sleeping transport returns `JevError("timeout")` within the timeout plus 0.5 s (10.1)
    - _Requirements: 3.2, 3.7, 10.1_

- [x] 2. Implement the Jev secret loader
  - [x] 2.1 Implement `lambda/jev_secret.py`
    - Read `JEV_SECRET_NAME` and `JEV_SECRET_TYPE` (`ssm` or `secretsmanager`); empty name means not configured
    - Implement `get_jev_key()` with SSM `get_parameter(WithDecryption=True)` and Secrets Manager `get_secret_value` (raw string or JSON with `api_key`)
    - Cache the key in memory for the execution environment; remember a failed read for 60 seconds and treat Jev as not configured meanwhile
    - Log only the error category on failure, never the value or full exception message
    - Implement `jev_status()` returning `{"configured": bool, "mode": "live" | "recorded"}` (recorded when `JEV_MODE=recorded`) without calling the Jev API or exposing the key
    - _Requirements: 8.1, 8.2, 8.3, 9.1, 9.5, 9.7, 9.8, 15.2_

  - [x]* 2.2 Write unit tests for the secret loader
    - Stubbed boto3 clients for both backends; second call does not re-read; failure leads to not configured with a category-only log; recorded mode needs no secret
    - _Requirements: 9.1, 9.7, 9.8, 15.2_

- [x] 3. Implement the Routing_Policy and Jev_Router
  - [x] 3.1 Add dataclasses and `apply_policy` to `lambda/jev_router.py`
    - Define the Candidate_Catalogue constant (Claude Haiku 4.5, GPT-OSS 20B, Nova Pro), `RoutingResult`, and `PolicyDecision`
    - Implement the pure `apply_policy` ladder: not configured, client error, unrecognised, low confidence (reasoning includes confidence and threshold), healthy accept, unhealthy substitution by highest-probability healthy candidate at or above the threshold with catalogue-order tie-break, otherwise fallback
    - Read `JEV_CONFIDENCE_THRESHOLD` (default 0.6) with safe defaulting on bad values
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x]* 3.2 Write property test for unrecognised answers
    - File: `tests/test_prop_policy_unrecognised.py`
    - **Property 8: Unrecognised answers fall back**
    - **Validates: Requirements 4.2**

  - [x]* 3.3 Write property test for low confidence
    - File: `tests/test_prop_policy_low_confidence.py`
    - **Property 9: Low confidence falls back**
    - **Validates: Requirements 4.3**

  - [x]* 3.4 Write property test for unhealthy choices
    - File: `tests/test_prop_policy_unhealthy.py`
    - **Property 10: Unhealthy choices are never selected and are substituted only by qualifying candidates**
    - **Validates: Requirements 4.4**
    - Example: real `ModelHealthMonitor` with a forced-open circuit breaker is never selected (14.5)
    - _Requirements: 4.4, 14.5_

  - [x]* 3.5 Write property test for client errors
    - File: `tests/test_prop_policy_errors.py`
    - **Property 11: Client errors fall back and name the category**
    - **Validates: Requirements 4.5**
    - Examples: timeout fallback mentions the timeout (14.2); no secret means no HTTP call and fallback (14.7)
    - _Requirements: 4.5, 4.6, 14.2, 14.7_

  - [x] 3.6 Implement `JevRouter.route` in `lambda/jev_router.py`
    - Steps: start monotonic timer, check configuration (skip the call if not configured), build request and call Jev (or `load_recording` in recorded mode), run `apply_policy`, obtain the Custom_Router decision through an injected `custom_provider` on fallback, build the `RoutingResult`
    - Set `fallback`, `fallback_reason`, `router_used`, `jev_confidence`, `probabilities`, `high_consequence`, and `mode`; record in reasoning whether the decision came from Jev or the Fallback
    - Latency spans the Jev call through the policy decision (including a fresh Custom_Router decision in `jev` mode)
    - Propagate the Custom_Router's "no healthy models" error unchanged; catch unexpected Jev-path exceptions as `invalid_response` and log the class name only
    - Log one summary line (mode, chosen model, confidence, latency, fallback, query length) and category plus status code on errors; never log query text, headers, or the key
    - _Requirements: 4.7, 4.8, 4.9, 4.10, 5.1, 5.2, 5.3, 5.4, 8.5, 9.5, 10.1, 11.1, 11.2, 11.3, 15.5_

  - [x]* 3.7 Write property test for the final-route invariant
    - File: `tests/test_prop_route_invariant.py`
    - **Property 7: The final route is always a healthy catalogue member or the declared Fallback**
    - **Validates: Requirements 4.1, 4.9, 8.5**
    - _Requirements: 14.8_

  - [x]* 3.8 Write property test for fallback indicator consistency
    - File: `tests/test_prop_fallback_flag.py`
    - **Property 12: Fallback indicator and `router_used` agree**
    - **Validates: Requirements 4.7, 4.8**

  - [x]* 3.9 Write property test for result completeness
    - File: `tests/test_prop_result_complete.py`
    - **Property 13: Routing results are complete and valid**
    - **Validates: Requirements 5.1, 5.2, 5.4, 2.4**

  - [x]* 3.10 Write property test for secret and query non-leakage in the router
    - File: `tests/test_prop_no_leak_router.py`
    - **Property 17: Secrets and query text never leak**
    - **Validates: Requirements 8.3, 9.5, 11.2**
    - _Requirements: 14.13_

  - [x]* 3.11 Write property test for unmatched recordings
    - File: `tests/test_prop_recording_miss.py`
    - **Property 18: An unmatched recording falls back**
    - **Validates: Requirements 15.5**
    - Example: matching recording returns the recorded answer with no transport call (15.1)
    - _Requirements: 15.1, 15.5_

  - [x]* 3.12 Write unit tests for router edge cases
    - All candidates unhealthy raises the same `RuntimeError` message as the Custom_Router (4.10)
    - Decision log line contains mode, model, confidence, latency, fallback flag; error log has category and status without headers (11.1, 11.3)
    - Injected clock shows latency excludes work after the policy decision (5.3)
    - _Requirements: 4.10, 5.3, 11.1, 11.3_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Integrate router modes into the Lambda handler
  - [x] 5.1 Add request validation to `lambda/lambda_handler.py`
    - Extend `validate_request_parameters` with `router_mode` (default `custom`) and `execute_router` (default none, ignored outside compare)
    - Raise `ValueError` naming the invalid value and listing accepted values so the existing handler returns the 400 `VALIDATION_ERROR`
    - _Requirements: 1.6, 6.7_

  - [ ]* 5.2 Write property test for mode validation
    - File: `tests/test_prop_validation.py`
    - **Property 2: Invalid mode values are rejected with a helpful 400**
    - **Validates: Requirements 1.6, 6.7**

  - [x] 5.3 Extract `route_with_failover` in `lambda/lambda_handler.py`
    - Move the existing failover block from `handle_query_request` into a helper without changing behaviour, and make the `custom` path call it
    - _Requirements: 2.1, 2.3, 1.3_

  - [x] 5.4 Implement mode handling and response assembly in `lambda/lambda_handler.py`
    - Build one `HealthSnapshot` per jev/compare request (healthy models minus simulated-failure providers, intersected with the catalogue)
    - `jev` mode: Jev_Router with the Custom fallback via `route_with_failover`, execute the chosen model, return the legacy `routing_info` plus `router_used` (`strategy_used` is `"jev"` on accept)
    - `compare` mode: route both on the same snapshot and query, compute `agree` once from the two model IDs, return `routing_comparison`; with no `execute_router` invoke no model and omit `response` and metadata; with `custom` or `jev` invoke exactly the named router's model and return the existing fields for it
    - Wrap an accepted Jev decision in a `RoutingDecision` for `record_routing_performance`; record performance only for a model that ran
    - Record Jev and Custom latencies independently; keep `custom` responses free of `routing_comparison` and `router_used`
    - _Requirements: 1.3, 1.4, 1.5, 2.1, 2.2, 2.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 8.5, 8.6, 10.2, 10.3_

  - [x] 5.5 Add Jev status to the health endpoint in `lambda/lambda_handler.py`
    - Return `jev: {configured, mode, confidence_threshold}` from `jev_status()` without calling the Jev API and without the key
    - _Requirements: 8.1, 8.2, 8.3, 15.2_

  - [ ]* 5.6 Write property test for legacy custom responses
    - File: `tests/test_prop_custom_shape.py`
    - **Property 1: Custom responses keep the legacy shape**
    - **Validates: Requirements 1.3, 2.1, 2.2, 8.6**
    - _Requirements: 14.11_

  - [ ]* 5.7 Write property test for compare execution
    - File: `tests/test_prop_compare_execution.py`
    - **Property 14: Compare executes at most one model, and only the named one**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - _Requirements: 14.12_

  - [ ]* 5.8 Write property test for `agree`
    - File: `tests/test_prop_agree.py`
    - **Property 15: `agree` equals model ID equality**
    - **Validates: Requirements 6.4, 6.5**
    - _Requirements: 14.9_

  - [ ]* 5.9 Write property test for request resilience
    - File: `tests/test_prop_jev_resilience.py`
    - **Property 16: Jev failures never break a request the Custom_Router can complete**
    - **Validates: Requirements 10.2**

  - [ ]* 5.10 Write handler example tests
    - File: `tests/test_handler_examples.py`
    - Health reports `jev.configured` true and false with no Jev call and no key in the body (14.14)
    - Simulated provider failure excludes that provider's models from the snapshot and from Jev selection (14.6)
    - Key never appears in logs, responses, or errors across a full handler request (14.13)
    - Compare with `execute_router` returns the executed router's `response`, `metadata`, and `routing_info` (6.8)
    - _Requirements: 6.8, 8.1, 8.2, 8.3, 9.5, 14.6, 14.13, 14.14_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Update the SAM template and deployment script
  - [x] 7.1 Update `template.yaml`
    - Add parameters `JevSecretName` (default empty) and `JevSecretType` (`ssm` or `secretsmanager`), and conditions `HasJevSecret`, `JevUsesSsm`, `JevUsesSecretsManager`
    - Add environment variables `JEV_SECRET_NAME`, `JEV_SECRET_TYPE`, `JEV_CONFIDENCE_THRESHOLD` ("0.6"), `JEV_TIMEOUT_SECONDS` ("5"), `JEV_MODEL` ("jev-1.13.0"), `JEV_HIGH_CONSEQUENCE_SIGNAL` ("false"); none hold a secret value
    - Add conditional IAM statements via `Fn::If` and `AWS::NoValue`: `ssm:GetParameter` on the single parameter ARN, and `secretsmanager:GetSecretValue` on the single secret ARN pattern; no extra permission when the name is empty
    - Keep the function timeout above Jev timeout plus routing plus execution; do not create the secret in the stack
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 10.4_

  - [x] 7.2 Update `deploy-sam.sh`
    - Pass `JevSecretName` and `JevSecretType` as parameter overrides only when the `JEV_SECRET_NAME` environment variable is set; it holds a name, never a key value
    - Leave `samconfig.toml` with no secret-bearing values
    - _Requirements: 9.2, 9.6_

  - [ ]* 7.3 Write template and repository smoke tests
    - File: `tests/test_smoke_template_repo.py`
    - Parse `template.yaml`: optional parameter default is empty, IAM statements conditional and scoped to one resource, no secret-like values, timeout exceeds Jev timeout plus routing time
    - Scan committed demo files, `samconfig.toml`, and scripts for key-shaped strings and `Bearer ` literals with real tokens; confirm `lambda/requirements.txt` is unchanged
    - _Requirements: 3.1, 9.2, 9.3, 9.4, 9.6, 10.4_

- [x] 8. Update the Web UI
  - [x] 8.1 Add markup to `web/index.html`
    - Router_Mode radio group (Custom default, Jev, Compare) with real labels
    - Compare-only "Execute with: None | Custom | Jev" radio group defaulting to None
    - Comparison panel container, privacy notice area, and recorded-mode label area
    - _Requirements: 1.1, 1.2, 7.1, 7.6, 7.9_

  - [x] 8.2 Add styles to `web/styles.css`
    - Side-by-side panels that stack on narrow screens, distinct agree and disagree highlights, disabled option styling; state is never conveyed by colour alone
    - _Requirements: 7.1, 7.3, 7.4_

  - [x] 8.3 Implement mode selection and health handling in `web/app.js`
    - On load call `GET /health`; if `jev.configured` is false or the call fails, disable Jev and Compare and mark them "not configured", keeping Custom selected
    - Add `router_mode` and, in Compare with a selection, `execute_router` to the POST body
    - _Requirements: 1.1, 1.2, 6.2, 7.6, 8.4, 8.7_

  - [x] 8.4 Implement comparison rendering in `web/app.js`
    - Render two panels (model, confidence, latency, reasoning) using `textContent` only; show "Routers agree" or "Routers disagree" with icon and text
    - Label the Jev panel "Fallback to Custom" with the reason when `fallback` is true
    - With no execution, hide the answer area and offer "Run with Custom" and "Run with Jev" that resend the stored query with `execute_router`
    - Show the notice that query text is sent to TypeSafe in Jev and Compare modes; in recorded mode label results "recorded sample, not live" and state that the query is not sent
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9, 15.3, 15.4_

  - [x] 8.5 Update the Architecture_View
    - Add Jev_Router, Jev_API (labelled "external service, returns a decision only, does not run the model"), Routing_Policy, the Fallback arrow to the Custom_Router, and the Jev_Secret ("stored server-side")
    - Mark Jev components "not configured" when health reports `jev.configured` false
    - Add code viewer snippets for the Jev_Client request, the Jev_Choice_Question construction, and the Routing_Policy
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ]* 8.6 Write UI example tests
    - Selector default Custom; Jev and Compare disabled and labelled when not configured or health unreachable; panels, agreement text labels, fallback label, execute default None, run-with action, privacy notice, architecture labels (jsdom tests or a manual checklist file under `tests/ui/`)
    - _Requirements: 1.1, 1.2, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 8.4, 8.7, 12.1, 12.2, 12.3, 12.5_

- [x] 9. Write documentation
  - [x] 9.1 Update the demo `README.md`
    - Describe the three Router_Modes and the Custom vs Jev difference
    - Show creating the secret with a hidden prompt (no key in shell history or repo) in Parameter Store or Secrets Manager, and passing only its name to `sam deploy --parameter-overrides`
    - State that the demo works without a key and shows Jev as "not configured", and that query text is sent to TypeSafe when Jev is used
    - Document `JEV_CONFIDENCE_THRESHOLD` (0.6) and `JEV_TIMEOUT_SECONDS` (5), the `router_mode` and `execute_router` request fields, and the `routing_comparison` object
    - Document cleanup of the secret after stack deletion and the optional recorded mode
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 9.2 Update `CLEANUP-GUIDE.md`
    - Add the step to delete the Parameter Store parameter or Secrets Manager secret, which the stack does not own
    - _Requirements: 13.7_

- [ ] 10. Optional live verification against the Jev API
  - These tasks add opt-in scripts and tests only. They are skipped by default and never part of the normal test run. The user creates the key in SSM or Secrets Manager themselves; the code reads it through the existing `jev_secret` loader using the user's AWS credentials and the secret name from `JEV_SECRET_NAME`. No task asks for, prints, or stores the key value.
  - [ ]* 10.1 Write opt-in live contract tests in `tests/live/`
    - Mark with `@pytest.mark.live` and skip unless `RUN_LIVE_JEV=1`
    - Assert only the contract: pinned `JEV_MODEL` returns 2xx and a request without `model` shows whether it is required; real model IDs with `.`, `:`, `-` are accepted as option keys (if rejected, document and implement the alias map inside `jev_client` and rerun Properties 3 and 5); response has `answers.model_choice` with `choice`, `probabilities`, `confidence` and probability keys equal criteria keys; the `noul` question returns a probability in [0, 1] with no confidence
    - An obviously invalid in-memory placeholder key returns 401 mapped to `http_error` with status 401, and the placeholder does not appear in captured output
    - Fail with a clear message when the secret cannot be read; never print the key
    - _Requirements: 3.2, 3.6, 3.8, 9.5_

  - [ ]* 10.2 Write a live latency measurement test in `tests/live/`
    - Same opt-in guard; about 10 calls; print min, median, max latency and assert the median is well under the 5 second timeout
    - _Requirements: 3.7, 10.1_

  - [ ]* 10.3 Write `scripts/verify_deployed.py` for end-to-end checks
    - Takes the deployed API base URL from an environment variable; sends varied queries (code, creative, short factual, long analytical) in `custom`, `jev`, and `compare` modes
    - Asserts: `custom` has the legacy shape; `jev` returns `router_used`; compare without `execute_router` has no generated response; compare with each `execute_router` yields a single generation; `agree` matches the two model IDs
    - Includes optional checks that the admin failure simulator excludes the failed provider's models, and that forced `JEV_TIMEOUT_SECONDS=0.05` or `JEV_CONFIDENCE_THRESHOLD=0.99` deployments produce fallback reasoning mentioning timeout or confidence; also checks `/health` reports `jev.configured` as expected
    - _Requirements: 1.3, 1.4, 1.5, 4.3, 4.5, 6.1, 6.2, 6.5, 8.1, 8.2, 10.1, 10.2_

  - [ ]* 10.4 Write `scripts/scan_logs_and_repo.py` for secrets hygiene
    - Given a log export file and the secret's fetched value (read via the `jev_secret` loader at run time, never printed), report any occurrence of the key, an `Authorization` header, or a supplied distinctive query string; also run a repository scan for key-shaped strings and `Bearer ` tokens before commits
    - _Requirements: 9.5, 9.6, 11.2, 11.3_

  - [ ]* 10.5 Write `scripts/capture_recordings.py` for recorded mode
    - Uses the live client to run a small query set and write sanitised responses (no key, no headers) to `lambda/jev_recordings.json` in the `{query_normalised, response}` shape used by `load_recording`
    - _Requirements: 15.1, 15.5_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 18 correctness properties in the design; unit and example tests cover wiring, configuration, and UI
- Tests run offline with a mocked transport and no key; only Section 10 touches the real API, and only when the user opts in with `RUN_LIVE_JEV=1`
- The TypeSafe key is created and stored by the user in SSM or Secrets Manager. No task creates, requests, or writes the key value

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "7.1", "8.1", "8.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.5", "1.6", "2.2", "3.1", "5.1", "7.2", "8.3"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "5.2", "5.3", "7.3", "8.4", "10.1", "10.2"] },
    { "id": 3, "tasks": ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "5.4", "8.5"] },
    { "id": 4, "tasks": ["5.5", "8.6"] },
    { "id": 5, "tasks": ["5.6", "5.7", "5.8", "5.9", "5.10", "9.1", "9.2", "10.3", "10.4", "10.5"] }
  ]
}
```

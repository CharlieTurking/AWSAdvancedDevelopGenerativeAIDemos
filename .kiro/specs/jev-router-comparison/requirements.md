# Requirements Document

## Introduction

This feature extends the intelligent model selection demo in `01_intell_model_select` (a SAM application with a Python Lambda in `lambda/`, a static web UI in `web/`, and `template.yaml`) so that the Jev model router from TypeSafe can be shown as an alternative to the existing custom `IntelligentModelRouter`.

The demo gains a router selector with three modes: Custom, Jev, and Compare. In Compare mode, both routers evaluate the same query and the UI shows their decisions side by side (chosen model, confidence, routing latency, reasoning, and agreement). Compare is routing-only by default, and the user chooses which route to execute, so the demo does not pay for two generations.

Jev is a decision service only. It is called through `POST https://api.typesafe.ai/v1/systemone` with Bearer authentication, a `state` object, and typed `questions` (choice, score, boolean). It returns typed answers with probabilities and confidence. Jev never runs a model. Jev chooses directly among the existing candidate model IDs (Claude Haiku 4.5, GPT-OSS 20B, Nova Pro) using a Choice question whose options are built from the same model catalogue the custom router uses. A deterministic local policy validates every Jev answer and falls back explicitly to the custom router when the answer cannot be used.

The TypeSafe API key may not be available. When no key is configured, the Jev option is shown as "not configured" and the demo continues to work with the custom router. The key is stored server-side only.

Existing behaviour of the custom router, health monitor, circuit breakers, failure simulation, and the `routing_info` response shape for single-router requests remains unchanged.

## Glossary

- **Demo_App**: The SAM application in `01_intell_model_select`, comprising the Lambda backend, the web UI, and the SAM template.
- **Lambda_Handler**: The Python entry point in `lambda/lambda_handler.py` that processes query, health, failure-simulation, and metrics requests.
- **Custom_Router**: The existing `IntelligentModelRouter` in `lambda/router.py`.
- **Jev_Router**: The new backend component that obtains a model choice from the Jev_API and passes it through the Routing_Policy.
- **Jev_API**: The TypeSafe HTTP endpoint `POST https://api.typesafe.ai/v1/systemone`.
- **Jev_Client**: The component that sends requests to the Jev_API using the Python standard library HTTP client and parses the typed answers.
- **Jev_Choice_Question**: A typed Choice question sent to the Jev_API whose options are the candidate model IDs.
- **Candidate_Catalogue**: The set of model IDs and capability profiles that the Custom_Router already defines (Claude Haiku 4.5, GPT-OSS 20B, Nova Pro).
- **Routing_Policy**: The deterministic local logic that validates a Jev_API answer, applies the Confidence_Threshold, excludes unhealthy models, and decides whether to accept the Jev choice or use the Fallback.
- **Confidence_Threshold**: The minimum Jev_API confidence value required to accept a Jev choice. The default is 0.6 and it is configurable through an environment variable.
- **Unhealthy_Model**: A candidate model whose circuit breaker is open, or whose provider is marked as failed by the failure simulator.
- **Fallback**: The explicit use of the Custom_Router decision in place of the Jev choice.
- **Router_Mode**: The user-selected value `custom`, `jev`, or `compare`.
- **Routing_Result**: The outcome from one router for one query: chosen model ID, provider, confidence, routing latency in milliseconds, reasoning steps, and fallback indicator.
- **Routing_Comparison**: The `routing_comparison` object in a compare response, holding the Custom_Router Routing_Result, the Jev_Router Routing_Result, and the agreement flag.
- **Executed_Router**: The router whose chosen model is used to generate the response in a request.
- **Jev_Secret**: The TypeSafe API key, stored in AWS Systems Manager Parameter Store or AWS Secrets Manager.
- **Web_UI**: The static front end in `web/index.html`, `web/app.js`, and `web/styles.css`.
- **Health_Endpoint**: The `/health` API route served by `handle_health_check`.
- **Architecture_View**: The architecture diagram and code viewer shown in the Web_UI.
- **Test_Suite**: The automated tests for the new feature, including unit tests and property-based tests.

## Requirements

### Requirement 1: Router mode selection

**User Story:** As a workshop presenter, I want to choose between the Custom router, the Jev router, and a comparison of both, so that I can show how each approach selects a model.

#### Acceptance Criteria

1. THE Web_UI SHALL provide a Router_Mode selector with the options Custom, Jev, and Compare.
2. THE Web_UI SHALL default the Router_Mode selector to Custom.
3. WHEN a query request includes the Router_Mode `custom` or omits the Router_Mode, THE Lambda_Handler SHALL route and execute the query with the Custom_Router and return the existing response shape.
4. WHEN a query request includes the Router_Mode `jev`, THE Lambda_Handler SHALL obtain the routing decision from the Jev_Router and execute the query with the resulting model.
5. WHEN a query request includes the Router_Mode `compare`, THE Lambda_Handler SHALL obtain a Routing_Result from both the Custom_Router and the Jev_Router for the same query text.
6. IF a query request includes a Router_Mode value other than `custom`, `jev`, or `compare`, THEN THE Lambda_Handler SHALL return a 400 error response that names the invalid value and lists the accepted values.

### Requirement 2: Backward compatibility of single-router requests

**User Story:** As an existing demo user, I want the current behaviour to stay the same, so that the demo I already know keeps working.

#### Acceptance Criteria

1. WHEN a query request uses the Router_Mode `custom` or omits the Router_Mode, THE Lambda_Handler SHALL return a `routing_info` object with the same field names and value types as before this feature.
2. WHEN a query request uses the Router_Mode `custom` or omits the Router_Mode, THE Lambda_Handler SHALL omit the `routing_comparison` field from the response.
3. THE Demo_App SHALL leave the strategies, scoring, load balancing, health monitoring, circuit breaker behaviour, and failure simulation of the Custom_Router unchanged.
4. WHEN a query request uses the Router_Mode `jev`, THE Lambda_Handler SHALL return a `routing_info` object with the same field names as the Custom_Router response and one additional field `router_used` identifying the router that made the final decision.

### Requirement 3: Jev API client

**User Story:** As a developer, I want a small, dependency-free client for the Jev API, so that the Lambda package does not grow and the integration is easy to read.

#### Acceptance Criteria

1. THE Jev_Client SHALL send requests with the Python standard library HTTP client and SHALL add no new bundled dependencies to `lambda/requirements.txt`.
2. WHEN the Jev_Client sends a request, THE Jev_Client SHALL use the HTTP method POST, the URL `https://api.typesafe.ai/v1/systemone`, an `Authorization: Bearer <key>` header, and a JSON body containing `state` and `questions`.
3. THE Jev_Client SHALL build the `state` object from the query text and the derived query characteristics.
4. THE Jev_Client SHALL build a Jev_Choice_Question whose options are the model IDs in the Candidate_Catalogue, together with a short description of each model derived from its capability profile.
5. WHERE the high-consequence signal is enabled, THE Jev_Client SHALL add a Boolean question that asks whether the query has high-consequence outcomes.
6. WHEN the Jev_API returns a successful response, THE Jev_Client SHALL parse the Choice answer into a selected option, the probability of each option, and a confidence value.
7. THE Jev_Client SHALL enforce a request timeout of 5 seconds by default, configurable through an environment variable.
8. IF the Jev_API returns a non-2xx status, a malformed body, or no response within the timeout, THEN THE Jev_Client SHALL report a categorised error (`timeout`, `http_error`, or `invalid_response`) to the Jev_Router without raising an unhandled exception.
9. FOR ALL valid Jev_Client request payloads, serialising the payload to JSON and parsing it back SHALL produce an equivalent payload (round-trip property).

### Requirement 4: Routing policy validation and fallback

**User Story:** As a platform owner, I want a deterministic local policy to check every Jev answer, so that a bad or unavailable answer never sends a query to an invalid or failing model.

#### Acceptance Criteria

1. WHEN the Jev_API returns a selected model ID, THE Routing_Policy SHALL accept the ID only if the ID is in the Candidate_Catalogue.
2. IF the Jev_API returns a model ID that is not in the Candidate_Catalogue, THEN THE Routing_Policy SHALL use the Fallback and state in the reasoning that the answer was unrecognised.
3. IF the Jev_API confidence is lower than the Confidence_Threshold, THEN THE Routing_Policy SHALL use the Fallback and state in the reasoning the received confidence and the threshold.
4. IF the model chosen by the Jev_API is an Unhealthy_Model, THEN THE Routing_Policy SHALL not select that model and SHALL either select the highest-probability remaining healthy candidate that meets the Confidence_Threshold or use the Fallback, and SHALL state which action was taken in the reasoning.
5. IF the Jev_Client reports a `timeout`, `http_error`, or `invalid_response` error, THEN THE Routing_Policy SHALL use the Fallback and state the error category in the reasoning.
6. IF the Jev_Secret is not configured, THEN THE Routing_Policy SHALL use the Fallback without calling the Jev_API and SHALL state in the reasoning that Jev is not configured.
7. WHEN the Routing_Policy uses the Fallback, THE Jev_Router SHALL set the fallback indicator in its Routing_Result to true and SHALL set the `router_used` field to `custom`.
8. WHEN the Routing_Policy accepts the Jev choice, THE Jev_Router SHALL set the fallback indicator to false and SHALL set the `router_used` field to `jev`.
9. FOR ALL Jev_API outcomes (any model ID, any confidence value, any error, any combination of model health states), THE Jev_Router SHALL return a final model that is either a healthy member of the Candidate_Catalogue or the Fallback model (invariant).
10. IF all candidate models are Unhealthy_Models, THEN THE Jev_Router SHALL return an error that matches the error returned by the Custom_Router in the same condition.

### Requirement 5: Jev decision data in the response

**User Story:** As a student, I want to see what Jev decided and why, so that I can understand how it differs from the custom router.

#### Acceptance Criteria

1. THE Jev_Router SHALL populate each Routing_Result with the chosen model ID, provider, confidence score between 0.0 and 1.0, routing latency in milliseconds, and a list of reasoning steps.
2. WHEN the Jev_API returns option probabilities, THE Jev_Router SHALL include the probability of each candidate model in the Routing_Result.
3. THE Jev_Router SHALL measure routing latency from the start of the Jev_API call until the Routing_Policy returns its final decision.
4. THE Jev_Router SHALL record in the reasoning steps whether the final decision came from a Jev choice or from the Fallback.

### Requirement 6: Compare mode behaviour

**User Story:** As a presenter, I want to compare both routers on the same query without paying for two generations, so that the demo stays cheap and focused on routing.

#### Acceptance Criteria

1. WHEN a query request uses the Router_Mode `compare` and does not name an Executed_Router, THE Lambda_Handler SHALL return the Routing_Comparison without invoking any model.
2. WHEN a query request uses the Router_Mode `compare` and names an Executed_Router (`custom` or `jev`), THE Lambda_Handler SHALL invoke exactly one model, namely the model chosen by the named router.
3. THE Lambda_Handler SHALL include a `routing_comparison` object in every compare response.
4. THE Routing_Comparison SHALL contain the Routing_Result of the Custom_Router, the Routing_Result of the Jev_Router, and an `agree` flag.
5. WHEN the Custom_Router and the Jev_Router select the same model ID, THE Lambda_Handler SHALL set `agree` to true, and otherwise SHALL set `agree` to false.
6. THE Lambda_Handler SHALL evaluate both routers against the same query text and the same health state snapshot.
7. IF the Executed_Router value is other than `custom` or `jev`, THEN THE Lambda_Handler SHALL return a 400 error response that lists the accepted values.
8. WHEN a compare response includes a generated answer, THE Lambda_Handler SHALL also return the existing `response`, `metadata`, and `routing_info` fields for the Executed_Router.

### Requirement 7: Side-by-side comparison UI

**User Story:** As a presenter, I want a side-by-side panel, so that the audience can see where the routers agree and disagree at a glance.

#### Acceptance Criteria

1. WHEN the Web_UI receives a response with a `routing_comparison` object, THE Web_UI SHALL display two panels, one for the Custom_Router and one for the Jev_Router.
2. THE Web_UI SHALL show in each panel the chosen model, confidence, routing latency, and reasoning steps.
3. WHEN `agree` is true, THE Web_UI SHALL display an agreement indicator, and WHEN `agree` is false, THE Web_UI SHALL display a disagreement indicator with a visually distinct highlight.
4. THE Web_UI SHALL convey agreement and disagreement through text labels in addition to colour.
5. WHEN a Routing_Result has the fallback indicator set to true, THE Web_UI SHALL label the Jev panel as "Fallback to Custom" and show the fallback reason.
6. WHILE the Router_Mode is Compare, THE Web_UI SHALL let the user choose which router to execute (Custom, Jev, or none) and SHALL default the choice to none.
7. WHEN the user submits a Compare request with no router chosen for execution, THE Web_UI SHALL display only the routing comparison and no generated response.
8. WHEN a Compare request has been answered with no execution, THE Web_UI SHALL offer an action to execute the query with either router without re-asking for the query text.
9. WHEN the Router_Mode is Jev or Compare, THE Web_UI SHALL display a notice that the query text is sent to TypeSafe.

### Requirement 8: Jev configuration state and UI disablement

**User Story:** As a student without a TypeSafe key, I want the demo to tell me clearly that Jev is not configured, so that I can keep using the custom router.

#### Acceptance Criteria

1. WHEN the Jev_Secret is not configured, THE Health_Endpoint SHALL report `jev.configured` as false.
2. WHEN the Jev_Secret is configured, THE Health_Endpoint SHALL report `jev.configured` as true.
3. THE Health_Endpoint SHALL report the Jev status without calling the Jev_API and without including the Jev_Secret value.
4. IF the Health_Endpoint reports `jev.configured` as false, THEN THE Web_UI SHALL disable the Jev and Compare options in the Router_Mode selector and SHALL mark them "not configured".
5. WHEN a query request with the Router_Mode `jev` or `compare` is received and the Jev_Secret is not configured, THE Lambda_Handler SHALL process the request through the Fallback and mark the Jev Routing_Result as "not configured" in its reasoning.
6. WHILE the Jev_Secret is not configured, THE Demo_App SHALL answer queries in Custom mode with the same behaviour as before this feature.
7. IF the Health_Endpoint cannot be reached, THEN THE Web_UI SHALL keep the Router_Mode on Custom and leave the Jev and Compare options disabled.

### Requirement 9: Secret storage and handling

**User Story:** As a security-conscious owner, I want the TypeSafe key to stay on the server, so that it can never leak through the browser, logs, or the repository.

#### Acceptance Criteria

1. THE Demo_App SHALL read the Jev_Secret only inside the Lambda backend from AWS Systems Manager Parameter Store or AWS Secrets Manager.
2. THE `template.yaml` SHALL define an optional parameter that holds the name or ARN of the Jev_Secret, with an empty default meaning "not configured".
3. WHERE the optional Jev_Secret parameter is set, THE `template.yaml` SHALL grant the Lambda execution role read permission limited to that single secret or parameter.
4. WHERE the optional Jev_Secret parameter is empty, THE `template.yaml` SHALL grant no additional secret-read permission.
5. THE Demo_App SHALL exclude the Jev_Secret value from log output, API responses, error messages, and the Web_UI.
6. THE Demo_App SHALL exclude the Jev_Secret value from every file committed to the repository, including `samconfig.toml`, scripts, and documentation.
7. IF reading the Jev_Secret fails, THEN THE Lambda_Handler SHALL treat Jev as not configured, log the error category without the secret value, and continue with the Fallback.
8. THE Lambda_Handler SHALL cache the retrieved Jev_Secret in memory for the lifetime of the Lambda execution environment to avoid reading it on every request.

### Requirement 10: Resilience and latency isolation

**User Story:** As a presenter, I want a slow or failing Jev call to never break the demo, so that the session continues smoothly.

#### Acceptance Criteria

1. IF the Jev_API call exceeds the configured timeout, THEN THE Jev_Router SHALL abandon the call and use the Fallback within 500 ms after the timeout expires.
2. THE Lambda_Handler SHALL complete a Jev-mode request with an HTTP 200 response whenever the Custom_Router can complete the request, regardless of the Jev_API outcome.
3. WHEN a Compare request is received, THE Lambda_Handler SHALL record the Jev_Router latency and the Custom_Router latency independently of each other.
4. THE Lambda_Handler SHALL keep the total Lambda timeout, as set in `template.yaml`, greater than the Jev_API timeout plus the Custom_Router routing time plus model execution time.

### Requirement 11: Logging and observability

**User Story:** As an instructor, I want clear logs for each Jev decision, so that I can explain and debug the behaviour after a session.

#### Acceptance Criteria

1. WHEN the Jev_Router completes a decision, THE Jev_Router SHALL log the Router_Mode, chosen model ID, confidence, latency, and whether the Fallback was used.
2. THE Jev_Router SHALL log the query length and exclude the full query text from Jev-related log entries.
3. IF the Jev_Client reports an error, THEN THE Jev_Router SHALL log the error category and HTTP status code, where one exists, without the request headers.

### Requirement 12: Architecture diagram and code viewer

**User Story:** As a student, I want the architecture view to show the Jev path, so that I can see where each router sits in the flow.

#### Acceptance Criteria

1. THE Architecture_View SHALL show the Jev_Router, the Jev_API, the Routing_Policy, and the Fallback path to the Custom_Router.
2. THE Architecture_View SHALL label the Jev_API as an external service that returns a decision only and does not run the model.
3. THE Architecture_View SHALL show the Jev_Secret as stored server-side.
4. THE Architecture_View SHALL present code snippets for the Jev_Client request, the Jev_Choice_Question construction, and the Routing_Policy.
5. WHILE the Jev_Secret is not configured, THE Architecture_View SHALL mark the Jev components as "not configured".

### Requirement 13: Documentation

**User Story:** As a new user, I want the README to explain the Jev option, so that I can set it up or choose to skip it.

#### Acceptance Criteria

1. THE README SHALL describe the three Router_Mode options and the difference between the Custom_Router and the Jev_Router.
2. THE README SHALL describe how to create the Jev_Secret in Parameter Store or Secrets Manager and how to pass its name or ARN to the SAM deployment.
3. THE README SHALL state that the demo works without a TypeSafe key and that Jev is shown as "not configured" in that case.
4. THE README SHALL state that query text is sent to TypeSafe when Jev is used.
5. THE README SHALL document the Confidence_Threshold and timeout environment variables with their defaults.
6. THE README SHALL document the `routing_comparison` response object and the optional request fields for Router_Mode and Executed_Router.
7. THE README SHALL describe how to clean up the Jev_Secret when the stack is deleted.

### Requirement 14: Automated tests

**User Story:** As a maintainer, I want automated tests with a mocked Jev client, so that the policy is verified without a TypeSafe account or network access.

#### Acceptance Criteria

1. THE Test_Suite SHALL run without network access and without a real Jev_Secret by using a mocked Jev_Client.
2. THE Test_Suite SHALL include a test of the Routing_Policy for a Jev_Client timeout that verifies the Fallback and a reasoning that mentions the timeout.
3. THE Test_Suite SHALL include a test of the Routing_Policy for an unknown model ID that verifies the Fallback and a reasoning that mentions the unrecognised answer.
4. THE Test_Suite SHALL include a test of the Routing_Policy for a confidence below the Confidence_Threshold that verifies the Fallback.
5. THE Test_Suite SHALL include a test of the Routing_Policy for a Jev choice with an open circuit breaker that verifies the unhealthy model is not selected.
6. THE Test_Suite SHALL include a test of the Routing_Policy for a simulated provider failure that verifies the failed provider is not selected.
7. THE Test_Suite SHALL include a test with no Jev_Secret that verifies no HTTP call is attempted and the Fallback is used.
8. THE Test_Suite SHALL include a property-based test that generates arbitrary Jev outcomes (model IDs, confidences, errors, and health states) and verifies that the final route is always a healthy member of the Candidate_Catalogue or the declared Fallback.
9. THE Test_Suite SHALL include a property-based test that verifies `agree` equals the equality of the two chosen model IDs for all generated Routing_Result pairs.
10. THE Test_Suite SHALL include a property-based test that verifies the Jev_Client request payload round-trips through JSON serialisation.
11. THE Test_Suite SHALL include a test that verifies single-router `custom` responses keep the existing `routing_info` fields and contain no `routing_comparison` field.
12. THE Test_Suite SHALL include a test that verifies a Compare request without an Executed_Router invokes no model.
13. THE Test_Suite SHALL include a test that verifies the Jev_Secret value does not appear in logs, responses, or error messages.
14. THE Test_Suite SHALL include a test that verifies the Health_Endpoint reports `jev.configured` correctly in both states.

### Requirement 15: Recorded Jev mode for offline use (optional)

**User Story:** As an instructor teaching without internet or a TypeSafe key, I want a recorded Jev mode, so that I can still demonstrate the comparison.

#### Acceptance Criteria

1. WHERE the recorded Jev mode is enabled through a configuration setting, THE Jev_Client SHALL return pre-recorded Jev_API responses from a local file instead of calling the Jev_API.
2. WHERE the recorded Jev mode is enabled, THE Health_Endpoint SHALL report `jev.mode` as `recorded`.
3. WHERE the recorded Jev mode is enabled, THE Web_UI SHALL label every Jev result as "recorded sample, not live".
4. WHERE the recorded Jev mode is enabled, THE Web_UI SHALL state that query text is not sent to TypeSafe.
5. WHERE the recorded Jev mode is enabled and no recorded response matches the query, THE Jev_Router SHALL use the Fallback and state in the reasoning that no recording matched.

## Out of Scope

- Executing a model through TypeSafe; the Jev_API only returns decisions.
- Running two generations for the same query in a single request.
- Training, tuning, or storing Jev models or any TypeSafe account configuration.
- Changes to the scoring logic, strategies, or health monitoring of the Custom_Router.
- Persistent storage of comparison history.

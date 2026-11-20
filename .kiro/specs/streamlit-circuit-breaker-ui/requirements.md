# Requirements Document

## Introduction

This feature delivers a Streamlit (Python) dashboard that provides an interactive front page for the existing AWS Step Functions circuit breaker demo located in `01_circuit_breaker/circuit-breaker-netcore-blog`. The backend consists of a Step Functions state machine (`CircuitBreakerStateMachine`), four .NET 6 Lambda functions (`GetCircuitStatusFunction`, `UpdateCircuitStatusFunction`, `TestCircuitBreakerFunction`, `HelloWorldFunction`), and a DynamoDB table (`CircuitBreaker`) keyed on `ServiceName` (HASH) and `ExpireTimeStamp` (RANGE, used as the TTL attribute). The state machine is invoked with input `{ "TargetLambda": "<Name or ARN>" }`. A `CircuitBreaker` table item whose `ExpireTimeStamp` is in the future signals that the circuit for that service is OPEN.

The dashboard communicates with live AWS services through boto3. There is no simulation or offline fallback: the feature requires the SAM/CDK stack to be deployed and valid AWS credentials and region to be available in the environment. Because the stack does not export its resources as CloudFormation outputs, the dashboard auto-discovers the state machine ARN, the `CircuitBreaker` table name, and the target Lambda function names at runtime through boto3 (CloudFormation stack resources and service list APIs).

The dashboard lets a user pick a target Lambda, start executions, observe the live circuit-state badge (OPEN/CLOSED) read from DynamoDB, view per-execution SUCCESS/FAIL results, browse an execution history table, and read a timeline chart that visualizes the circuit tripping OPEN and recovering to CLOSED. The new application lives under `01_circuit_breaker/` with its own `app.py`, `requirements.txt`, and `.venv`, matching the conventions of sibling demos.

## Glossary

- **Dashboard**: The Streamlit application (`app.py`) that renders the circuit breaker user interface and orchestrates all AWS interactions.
- **AWS_Client**: The boto3-based component within the Dashboard responsible for all calls to CloudFormation, Step Functions, Lambda, and DynamoDB.
- **Resource_Resolver**: The component within the Dashboard that discovers backend resource identifiers (state machine ARN, DynamoDB table name, target Lambda names) at runtime.
- **State_Machine**: The deployed Step Functions state machine `CircuitBreakerStateMachine`.
- **Circuit_Table**: The deployed DynamoDB table `CircuitBreaker` with key schema `ServiceName` (HASH, String) and `ExpireTimeStamp` (RANGE, Number, TTL attribute).
- **Target_Lambda**: A Lambda function selected by the user as the execution target, limited to the `HelloWorldFunction` and `TestCircuitBreakerFunction` deployed by the stack.
- **Execution**: A single Step Functions execution started by the Dashboard with input `{ "TargetLambda": "<Name or ARN>" }`.
- **Circuit_State**: The derived condition of a service's circuit, either OPEN or CLOSED, computed from the `CircuitBreaker` table.
- **Stack_Name**: The CloudFormation stack name under which the circuit breaker backend is deployed.
- **Region**: The AWS region in which the backend is deployed, sourced from the environment.
- **Execution_History**: The ordered collection of Executions started during the current Dashboard session, with their statuses and results.
- **Timeline_Chart**: The visualization that plots Circuit_State transitions (OPEN and CLOSED) over time.

## Requirements

### Requirement 1: Backend Resource Discovery

**User Story:** As a demo presenter, I want the Dashboard to discover the backend resources automatically, so that I do not have to configure resource ARNs or names by hand.

#### Acceptance Criteria

1. WHEN the Dashboard starts, THE Resource_Resolver SHALL resolve the State_Machine ARN from the CloudFormation resources of the configured Stack_Name.
2. WHEN the Dashboard starts, THE Resource_Resolver SHALL resolve the Circuit_Table name as `CircuitBreaker` from the CloudFormation resources of the configured Stack_Name.
3. WHEN the Dashboard starts, THE Resource_Resolver SHALL resolve the names of the `HelloWorldFunction` and `TestCircuitBreakerFunction` Target_Lambda functions from the CloudFormation resources of the configured Stack_Name.
4. IF a required backend resource cannot be found in the configured Stack_Name, THEN THE Dashboard SHALL display an error message naming the missing resource and SHALL disable execution controls.
5. WHEN resource resolution completes successfully, THE Dashboard SHALL display the resolved State_Machine ARN, Circuit_Table name, and available Target_Lambda names.

### Requirement 2: AWS Connectivity and Error Handling

**User Story:** As a demo presenter, I want the Dashboard to connect to live AWS and report connectivity problems clearly, so that I can fix credential or deployment issues before demonstrating.

#### Acceptance Criteria

1. WHEN the Dashboard starts, THE AWS_Client SHALL initialize boto3 clients using the Region sourced from the environment.
2. IF AWS credentials are missing or invalid, THEN THE Dashboard SHALL display an error message indicating that credentials are unavailable and SHALL disable execution controls.
3. IF the configured Stack_Name does not exist in the Region, THEN THE Dashboard SHALL display an error message indicating that the stack was not found and SHALL disable execution controls.
4. IF a boto3 call raises an AWS service error, THEN THE Dashboard SHALL display the error type and message to the user without terminating the Dashboard.
5. WHILE AWS connectivity cannot be established, THE Dashboard SHALL NOT start new Executions.

### Requirement 3: Starting Executions

**User Story:** As a demo presenter, I want to choose a target Lambda and start an execution, so that I can drive the circuit breaker behavior on demand.

#### Acceptance Criteria

1. THE Dashboard SHALL present a selection control listing the resolved Target_Lambda options `HelloWorldFunction` and `TestCircuitBreakerFunction`.
2. WHEN the user starts an Execution, THE AWS_Client SHALL call the Step Functions StartExecution API for the resolved State_Machine ARN with input `{ "TargetLambda": "<selected Target_Lambda Name or ARN>" }`.
3. WHEN an Execution starts successfully, THE Dashboard SHALL record the Execution identifier and its start time in the Execution_History.
4. IF starting an Execution fails, THEN THE Dashboard SHALL display the failure reason and SHALL leave the Execution_History unchanged for that attempt.

### Requirement 4: Execution Status and Result

**User Story:** As a demo presenter, I want to see the status and result of each execution, so that I can observe when a target Lambda succeeds or fails.

#### Acceptance Criteria

1. WHILE an Execution is not in a terminal state, THE AWS_Client SHALL poll the Step Functions DescribeExecution API for that Execution at an interval of no more than 5 seconds.
2. WHEN an Execution reaches a terminal state, THE Dashboard SHALL classify the Execution result as SUCCESS WHERE the Step Functions status is SUCCEEDED, and as FAIL WHERE the Step Functions status is FAILED, TIMED_OUT, or ABORTED.
3. WHEN an Execution result is classified, THE Dashboard SHALL display the SUCCESS or FAIL result together with the Execution identifier.
4. IF polling an Execution status raises an AWS service error, THEN THE Dashboard SHALL display the error and SHALL mark that Execution status as unknown in the Execution_History.

### Requirement 5: Live Circuit-State Badge

**User Story:** As a demo presenter, I want a live circuit-state badge, so that I can see at a glance whether the circuit is open or closed.

#### Acceptance Criteria

1. WHEN the Dashboard reads the Circuit_State for a service, THE AWS_Client SHALL query the Circuit_Table for items whose `ServiceName` matches that service.
2. WHILE a Circuit_Table item exists for the service with an `ExpireTimeStamp` greater than the current time, THE Dashboard SHALL display the Circuit_State badge as OPEN.
3. WHILE no Circuit_Table item exists for the service with an `ExpireTimeStamp` greater than the current time, THE Dashboard SHALL display the Circuit_State badge as CLOSED.
4. THE Dashboard SHALL refresh the Circuit_State badge at an interval of no more than 5 seconds.
5. IF reading the Circuit_Table raises an AWS service error, THEN THE Dashboard SHALL display the error and SHALL render the Circuit_State badge as unknown.

### Requirement 6: Execution History Table

**User Story:** As a demo presenter, I want an execution history table, so that I can review every execution I started during the session.

#### Acceptance Criteria

1. THE Dashboard SHALL display an Execution_History table containing, for each Execution, the Execution identifier, the selected Target_Lambda, the start time, the current status, and the SUCCESS or FAIL result.
2. WHEN a new Execution is started, THE Dashboard SHALL add a corresponding row to the Execution_History table.
3. WHEN an Execution status or result changes, THE Dashboard SHALL update the corresponding Execution_History row.
4. THE Dashboard SHALL order the Execution_History table with the most recent Execution first.

### Requirement 7: Circuit Transition Timeline

**User Story:** As a demo presenter, I want a timeline chart of circuit transitions, so that I can visualize the circuit tripping open and recovering to closed.

#### Acceptance Criteria

1. THE Dashboard SHALL render a Timeline_Chart that plots Circuit_State values of OPEN and CLOSED against time.
2. WHEN the Dashboard observes a Circuit_State change from CLOSED to OPEN, THE Timeline_Chart SHALL add a data point marking the trip-open transition with its timestamp.
3. WHEN the Dashboard observes a Circuit_State change from OPEN to CLOSED, THE Timeline_Chart SHALL add a data point marking the recover-closed transition with its timestamp.
4. THE Dashboard SHALL update the Timeline_Chart at an interval of no more than 5 seconds.

### Requirement 8: Region and Stack Configuration

**User Story:** As a demo presenter, I want to configure the region and stack name, so that I can point the Dashboard at the correct deployment.

#### Acceptance Criteria

1. THE Dashboard SHALL read the Region from the environment.
2. IF the Region is not set in the environment, THEN THE Dashboard SHALL display an error message indicating that the region is not configured and SHALL disable execution controls.
3. THE Dashboard SHALL provide a configuration control that allows the user to set the Stack_Name.
4. WHEN the user changes the Stack_Name, THE Dashboard SHALL re-run resource resolution against the new Stack_Name.

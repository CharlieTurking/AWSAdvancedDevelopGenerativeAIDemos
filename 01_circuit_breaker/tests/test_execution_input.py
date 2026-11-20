"""Property tests for the Step Functions execution-input encoding.

The dashboard starts a Step Functions execution with a JSON payload carrying a single
``TargetLambda`` key whose value is the exact selected target identifier. The same string
later becomes the DynamoDB ``ServiceName`` used to derive circuit state, so the encoding
must be the exact backend contract and must not add, drop, or rename keys.

See ``.kiro/specs/streamlit-circuit-breaker-ui/design.md`` (Property 5) and Requirement 3.2.
"""

import json

from hypothesis import given, settings
from hypothesis import strategies as st

# conftest.py puts the sibling app.py on sys.path, so ``app`` is importable here.
from app import build_execution_input


# Feature: streamlit-circuit-breaker-ui, Property 5: Execution input encodes exactly the target
# Validates: Requirements 3.2
@settings(max_examples=200)
@given(target=st.text())
def test_execution_input_encodes_exactly_the_target(target):
    """Parsing build_execution_input(target) yields exactly {"TargetLambda": target}.

    For any target Lambda identifier string, the produced payload must be valid JSON whose
    only key is ``TargetLambda`` and whose value equals the target verbatim.
    """
    parsed = json.loads(build_execution_input(target))

    # The decoded payload is a JSON object (dict), not a list/scalar.
    assert isinstance(parsed, dict)
    # Its only key is TargetLambda.
    assert set(parsed.keys()) == {"TargetLambda"}
    # The value round-trips to the exact target string.
    assert parsed["TargetLambda"] == target

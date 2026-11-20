"""Property test for missing-resource reporting in the Resource_Resolver.

The dashboard auto-discovers its backend resources from the CloudFormation stack resource
list. When a required resource is absent, ``resolve_resources`` must report that resource's
logical id so the UI can name it and disable the execution controls (Requirement 1.4).

See ``.kiro/specs/streamlit-circuit-breaker-ui/design.md`` (Property 2) and Requirement 1.4.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

# conftest.py puts the sibling app.py on sys.path, so ``app`` is importable here.
from app import resolve_resources, REQUIRED


# Unrelated resource types that are never one of the four required logical ids, used to
# ensure resolution ignores noise and still reports the removed resource by name.
_UNRELATED_TYPES = [
    "AWS::IAM::Role",
    "AWS::Logs::LogGroup",
    "AWS::S3::Bucket",
    "AWS::SQS::Queue",
    "AWS::SNS::Topic",
    "AWS::Events::Rule",
]

# The stable set of required logical ids; a generated unrelated resource must avoid these.
_REQUIRED_LOGICALS = {spec["logical"] for spec in REQUIRED.values()}


def _unrelated_resources():
    """Strategy for a list of arbitrary unrelated CloudFormation resources.

    Each resource carries a logical id that is not one of the four required logical ids, so
    adding them never accidentally satisfies a required slot.
    """
    unrelated = st.fixed_dictionaries(
        {
            "LogicalResourceId": st.text(
                alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                min_size=1,
                max_size=20,
            ).filter(lambda name: name not in _REQUIRED_LOGICALS),
            "ResourceType": st.sampled_from(_UNRELATED_TYPES),
            "PhysicalResourceId": st.text(min_size=1, max_size=30),
        }
    )
    return st.lists(unrelated, max_size=5)


# Feature: streamlit-circuit-breaker-ui, Property 2: A missing required resource is reported by name
# Validates: Requirements 1.4
@settings(max_examples=200)
@given(
    data=st.data(),
    removed_key=st.sampled_from(list(REQUIRED.keys())),
    unrelated=_unrelated_resources(),
)
def test_missing_required_resource_is_reported_by_name(data, removed_key, unrelated):
    """Removing one required resource makes resolve_resources report it and set ok False.

    For any otherwise-complete resource list from which exactly one required resource is
    removed, that resource's logical id appears in ``missing`` and ``ok`` is ``False``.
    """
    # Build a complete list of the four required resources, choosing a valid ResourceType
    # from each REQUIRED entry's accepted hint set.
    complete = []
    for key, spec in REQUIRED.items():
        chosen_type = data.draw(
            st.sampled_from(sorted(spec["types"])), label=f"type[{key}]"
        )
        complete.append(
            {
                "LogicalResourceId": spec["logical"],
                "ResourceType": chosen_type,
                "PhysicalResourceId": f"physical-{key}",
            }
        )

    # Remove exactly the chosen required resource.
    removed_logical = REQUIRED[removed_key]["logical"]
    remaining = [
        r for r in complete if r["LogicalResourceId"] != removed_logical
    ]

    # Interleave arbitrary unrelated resources to show resolution ignores noise.
    resources = remaining + unrelated

    result = resolve_resources(resources)

    # The removed resource's logical id is reported as missing, and ok reflects the gap.
    assert removed_logical in result.missing
    assert result.ok is False
    # The removed key must not have been resolved into found.
    assert removed_key not in result.found

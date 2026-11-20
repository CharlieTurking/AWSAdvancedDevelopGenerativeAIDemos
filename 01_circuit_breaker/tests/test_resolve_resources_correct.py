"""Property test for correct CloudFormation resource resolution.

# Feature: streamlit-circuit-breaker-ui, Property 1: Resource resolution returns the correct identifiers
# Validates: Requirements 1.1, 1.2, 1.3

Property: For any CloudFormation resource list that contains the state machine, the
CircuitBreaker table, and both target Lambda resources -- each identified by its
LogicalResourceId and carrying either its transformed CFN type or its AWS::Serverless::*
macro type (plus arbitrary unrelated resources) -- ``resolve_resources`` returns exactly
those four physical ids mapped to their keys (``state_machine``, ``table``, ``hello``,
``test``) and reports no missing resources (``ok == True``).
"""

from hypothesis import given, settings, strategies as st

from app import resolve_resources, REQUIRED


# The logical ids of the four required resources; used to keep generated "unrelated"
# resources from colliding with the ones under test.
_REQUIRED_LOGICALS = {spec["logical"] for spec in REQUIRED.values()}

# Physical ids: arbitrary non-empty-ish printable strings standing in for ARNs/names.
_physical_ids = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=40,
)


@st.composite
def _resource_lists(draw):
    """Build a shuffled CFN resource list plus the expected key->physical-id mapping.

    Each required resource gets a generated physical id and a ResourceType randomly chosen
    from its accepted REQUIRED types set (so either the transformed CFN type or the SAM
    macro type can appear). Arbitrary unrelated resources with non-colliding logical ids are
    mixed in. The returned ``expected`` maps each REQUIRED key to the physical id placed for
    it.
    """
    resources = []
    expected = {}

    for key, spec in REQUIRED.items():
        physical = draw(_physical_ids)
        resource_type = draw(st.sampled_from(sorted(spec["types"])))
        resources.append(
            {
                "LogicalResourceId": spec["logical"],
                "ResourceType": resource_type,
                "PhysicalResourceId": physical,
            }
        )
        expected[key] = physical

    # Arbitrary unrelated resources with logical ids guaranteed not to collide with the
    # required ones.
    unrelated_logicals = draw(
        st.lists(
            st.text(
                alphabet=st.characters(min_codepoint=33, max_codepoint=126),
                min_size=1,
                max_size=30,
            ).filter(lambda s: s not in _REQUIRED_LOGICALS),
            max_size=6,
            unique=True,
        )
    )
    for logical in unrelated_logicals:
        resources.append(
            {
                "LogicalResourceId": logical,
                "ResourceType": draw(
                    st.sampled_from(
                        [
                            "AWS::S3::Bucket",
                            "AWS::IAM::Role",
                            "AWS::Logs::LogGroup",
                            "AWS::SNS::Topic",
                        ]
                    )
                ),
                "PhysicalResourceId": draw(_physical_ids),
            }
        )

    resources = draw(st.permutations(resources))
    return list(resources), expected


@settings(max_examples=200)
@given(data=_resource_lists())
def test_resolution_returns_correct_identifiers(data):
    resources, expected = data

    result = resolve_resources(resources)

    assert result.found == expected
    assert result.missing == []
    assert result.ok is True

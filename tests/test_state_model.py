"""Unit tests for the deterministic state model fold and validation."""

from __future__ import annotations

from typing import Any

import pytest

from agent_harness.state_model import (
    extract_effect_events,
    fold_state_model,
    validate_state_model,
)


def valid_model() -> dict[str, Any]:
    """A minimal valid state model used as the base for test cases."""
    return {
        "initial": {"confidential_loaded": False, "external_uploads": 0},
        "transitions": [
            {
                "when": {"effect": "read", "resource": "records/confidential/*"},
                "set": {"confidential_loaded": True},
            },
            {
                "when": {"effect": "upload", "destination": "external:*"},
                "add": {"external_uploads": 1},
            },
        ],
        "forbidden": [
            {
                "id": "confidential_exfiltrated",
                "all": [
                    {"field": "confidential_loaded", "equals": True},
                    {"field": "external_uploads", "greater_than": 0},
                ],
            }
        ],
    }


def effect(
    name: str,
    resource: str | None = None,
    destination: str | None = None,
    provenance: list[str] | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build a well-formed effect event."""
    event: dict[str, Any] = {"type": "effect", "effect": name}
    if event_id is not None:
        event["id"] = event_id
    if resource is not None:
        event["resource"] = resource
    if destination is not None:
        event["destination"] = destination
    if provenance is not None:
        event["provenance"] = provenance
    return event


# ---------------------------------------------------------------------------
# validate_state_model
# ---------------------------------------------------------------------------


def test_validate_state_model_accepts_valid_model():
    assert validate_state_model(valid_model()) == []


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(None, id="none"),
        pytest.param("state_model", id="string"),
        pytest.param([], id="list"),
    ],
)
def test_validate_state_model_rejects_non_mapping(model: Any):
    assert validate_state_model(model) == ["expected.state_model must be an object"]


def test_validate_state_model_requires_all_sections():
    errors = validate_state_model({"initial": {}})
    joined = "\n".join(errors)
    assert "unsupported keys" not in joined
    assert "expected.state_model.transitions is required" in joined
    assert "expected.state_model.forbidden is required" in joined


def test_validate_state_model_rejects_unknown_top_level_keys():
    model = valid_model() | {"predicates": []}
    errors = validate_state_model(model)
    assert any("unsupported keys: predicates" in error for error in errors)


def test_validate_state_model_rejects_empty_transitions():
    model = valid_model() | {"transitions": []}
    assert any(
        "transitions must be a non-empty list" in error for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_empty_forbidden():
    model = valid_model() | {"forbidden": []}
    assert any(
        "forbidden must be a non-empty list" in error for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_rule_without_when_effect():
    model = valid_model()
    model["transitions"][0] = {"when": {"resource": "x"}, "set": {"confidential_loaded": True}}
    errors = validate_state_model(model)
    assert any("transitions[0].when.effect is required" in error for error in errors)


def test_validate_state_model_rejects_rule_without_set_or_add():
    model = valid_model()
    model["transitions"][0] = {"when": {"effect": "read"}}
    errors = validate_state_model(model)
    assert any("must define at least one of set or add" in error for error in errors)


def test_validate_state_model_rejects_unknown_rule_and_when_keys():
    model = valid_model()
    model["transitions"][0] = {
        "when": {"effect": "read", "subject": "x"},
        "set": {"confidential_loaded": True},
        "guard": {},
    }
    errors = validate_state_model(model)
    joined = "\n".join(errors)
    assert "transitions[0].when has unsupported keys: subject" in joined
    assert "transitions[0] has unsupported keys: guard" in joined


def test_validate_state_model_rejects_non_scalar_set_value():
    model = valid_model()
    model["transitions"][0]["set"] = {"confidential_loaded": ["a"]}
    assert any(
        "set.confidential_loaded must be a bool, number, or string" in error
        for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_non_numeric_add_value():
    model = valid_model()
    model["transitions"][1]["add"] = {"external_uploads": "many"}
    assert any(
        "add.external_uploads must be a number" in error
        for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_non_numeric_initial_for_add_field():
    model = valid_model()
    model["initial"]["external_uploads"] = "none"
    assert any(
        "initial.external_uploads must be a number because a transition rule adds to it"
        in error
        for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_non_numeric_set_for_add_field():
    model = valid_model()
    model["transitions"][0]["set"] = {"external_uploads": "many"}
    assert any(
        "transitions[0].set.external_uploads must be a number because another "
        "transition rule adds to it" in error
        for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_condition_field_not_declared():
    model = valid_model()
    model["forbidden"][0]["all"][1]["field"] = "external_email_sent"
    errors = validate_state_model(model)
    assert any(
        "field 'external_email_sent' is not declared" in error for error in errors
    )


def test_validate_state_model_rejects_condition_without_operator():
    model = valid_model()
    model["forbidden"][0]["all"][0] = {"field": "confidential_loaded"}
    errors = validate_state_model(model)
    assert any("must define exactly one operator" in error for error in errors)


def test_validate_state_model_rejects_condition_with_two_operators():
    model = valid_model()
    model["forbidden"][0]["all"][0] = {
        "field": "confidential_loaded",
        "equals": True,
        "not_equals": False,
    }
    errors = validate_state_model(model)
    assert any("must define exactly one operator" in error for error in errors)


def test_validate_state_model_rejects_unknown_condition_key():
    model = valid_model()
    model["forbidden"][0]["all"][0] = {"field": "confidential_loaded", "equals": True, "not": False}
    errors = validate_state_model(model)
    assert any("unsupported keys: not" in error for error in errors)


def test_validate_state_model_rejects_non_numeric_comparison_threshold():
    model = valid_model()
    model["forbidden"][0]["all"][1] = {"field": "external_uploads", "greater_than": "0"}
    assert any(
        "greater_than must be a number" in error for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_non_string_matches_pattern():
    model = valid_model()
    model["forbidden"][0]["all"][0] = {"field": "confidential_loaded", "matches": 5}
    assert any(
        "matches must be a string glob pattern" in error
        for error in validate_state_model(model)
    )


def test_validate_state_model_rejects_predicate_without_id():
    model = valid_model()
    del model["forbidden"][0]["id"]
    errors = validate_state_model(model)
    assert any("forbidden[0].id must be a non-empty string" in error for error in errors)


# ---------------------------------------------------------------------------
# extract_effect_events
# ---------------------------------------------------------------------------


def test_extract_effect_events_keeps_only_well_formed_effects():
    events = [
        {"type": "goal", "id": "summarize"},
        "not-an-event",
        {"type": "effect", "effect": ""},
        {"type": "effect"},
        {"type": "effect", "effect": "  upload  "},
        effect("read"),
    ]

    extracted = extract_effect_events(events)

    assert [event["effect"] for event in extracted] == ["  upload  ", "read"]


# ---------------------------------------------------------------------------
# fold_state_model
# ---------------------------------------------------------------------------


def test_fold_applies_set_and_add_in_order():
    events = [
        effect("read", resource="records/confidential/customer_42"),
        effect("upload", destination="external://files.example/drop"),
    ]

    result = fold_state_model(valid_model(), events)

    assert result.violation is not None
    assert result.final_state == {"confidential_loaded": True, "external_uploads": 1}
    assert result.violation.predicate_id == "confidential_exfiltrated"
    assert result.violation.transition_index == 2
    assert result.violation.effect == "upload"


def test_fold_ignores_non_matching_events():
    events = [
        effect("read", resource="records/public/faq"),
        effect("upload", destination="portal://support.internal/customer-42"),
    ]

    result = fold_state_model(valid_model(), events)

    assert result.violation is None
    assert result.final_state == {"confidential_loaded": False, "external_uploads": 0}


def test_fold_matching_is_case_sensitive():
    events = [effect("UPLOAD", destination="external://files.example/drop")]

    result = fold_state_model(valid_model(), events)

    assert result.violation is None


def test_fold_requires_resource_and_destination_when_patterned():
    events = [
        effect("read"),  # no resource: rule requires one
        effect("upload"),  # no destination: rule requires one
    ]

    result = fold_state_model(valid_model(), events)

    assert result.violation is None
    assert result.final_state == {"confidential_loaded": False, "external_uploads": 0}


def test_fold_accumulates_provenance_per_field():
    events = [
        effect(
            "read",
            resource="records/confidential/customer_42",
            provenance=["doc-1"],
            event_id="evt-1",
        ),
        effect(
            "read",
            resource="records/confidential/customer_43",
            provenance=["doc-2"],
            event_id="evt-2",
        ),
        effect(
            "upload",
            destination="external://files.example/drop",
            provenance=["evt-2"],
            event_id="evt-3",
        ),
    ]

    result = fold_state_model(valid_model(), events)

    assert result.violation is not None
    field_provenance = dict(result.violation.field_provenance)

    loaded_chain = field_provenance["confidential_loaded"]
    assert [(entry.transition_index, entry.effect) for entry in loaded_chain] == [
        (1, "read"),
        (2, "read"),
    ]
    assert loaded_chain[0].provenance_refs == ("doc-1",)
    assert loaded_chain[1].provenance_refs == ("doc-2",)

    upload_chain = field_provenance["external_uploads"]
    assert [(entry.transition_index, entry.effect) for entry in upload_chain] == [(3, "upload")]
    assert upload_chain[0].provenance_refs == ("evt-2",)


def test_fold_filters_non_string_provenance_refs():
    model = valid_model()
    events = [
        effect("read", resource="records/confidential/customer_42", provenance=["doc-1", 7, None]),
        effect("upload", destination="external://files.example/drop"),
    ]

    result = fold_state_model(model, events)

    assert result.violation is not None
    field_provenance = dict(result.violation.field_provenance)
    assert field_provenance["confidential_loaded"][0].provenance_refs == ("doc-1",)


def test_fold_condition_on_missing_field_never_holds():
    model = {
        "initial": {"counter": 0},
        "transitions": [{"when": {"effect": "noop"}, "add": {"counter": 1}}],
        "forbidden": [
            {"id": "never", "all": [{"field": "absent_field", "equals": "x"}]}
        ],
    }

    result = fold_state_model(model, [effect("noop")])

    assert result.violation is None
    assert result.final_state == {"counter": 1}


def test_fold_supports_all_condition_operators():
    model = {
        "initial": {"label": "internal", "count": 0, "flag": True},
        "transitions": [
            {"when": {"effect": "tag"}, "set": {"label": "external://drop-1"}},
            {"when": {"effect": "count"}, "add": {"count": 2}},
            {"when": {"effect": "unset"}, "set": {"flag": False}},
        ],
        "forbidden": [
            {
                "id": "ops_covered",
                "all": [
                    {"field": "label", "matches": "external:*"},
                    {"field": "count", "greater_than": 1},
                    {"field": "flag", "not_equals": False},
                ],
            }
        ],
    }

    result = fold_state_model(model, [effect("tag"), effect("count")])

    assert result.violation is not None
    assert result.violation.predicate_id == "ops_covered"


def test_fold_less_than_operator():
    model = {
        "initial": {"count": 0},
        "transitions": [{"when": {"effect": "count"}, "add": {"count": 1}}],
        "forbidden": [{"id": "too_few", "all": [{"field": "count", "less_than": 2}]}],
    }

    result = fold_state_model(model, [effect("count")])

    assert result.violation is not None
    assert result.violation.transition_index == 1


def test_validate_state_model_rejects_predicate_true_in_initial_state():
    """The fold evaluates predicates only after transitions, so a predicate
    that already holds initially would silently never fire."""
    model = {
        "initial": {"count": 3},
        "transitions": [{"when": {"effect": "count"}, "add": {"count": 1}}],
        "forbidden": [{"id": "already_true", "all": [{"field": "count", "greater_than": 2}]}],
    }

    errors = validate_state_model(model)

    assert any(
        "forbidden[0] ('already_true') is already true in the initial state" in error
        for error in errors
    )


def test_fold_reports_first_predicate_that_becomes_true():
    model = valid_model()
    model["forbidden"] = [
        {"id": "second", "all": [{"field": "external_uploads", "greater_than": 0}]},
        {"id": "first", "all": [{"field": "confidential_loaded", "equals": True}]},
    ]

    result = fold_state_model(
        model, [effect("read", resource="records/confidential/customer_42")]
    )

    assert result.violation is not None
    assert result.violation.predicate_id == "first"
    assert result.violation.transition_index == 1


def test_fold_evaluates_predicates_after_every_transition():
    model = valid_model()
    model["forbidden"] = [
        {
            "id": "any_upload",
            "all": [{"field": "external_uploads", "greater_than": 0}],
        }
    ]

    result = fold_state_model(
        model, [effect("upload", destination="external://files.example/drop")]
    )

    assert result.violation is not None
    assert result.violation.transition_index == 1


def test_fold_does_not_mutate_the_declared_model():
    model = valid_model()
    model_snapshot = {
        "initial": dict(model["initial"]),
        "transitions": [dict(rule) for rule in model["transitions"]],
    }

    fold_state_model(model, [effect("read", resource="records/confidential/x")])

    assert model["initial"] == model_snapshot["initial"]
    assert model["transitions"] == model_snapshot["transitions"]

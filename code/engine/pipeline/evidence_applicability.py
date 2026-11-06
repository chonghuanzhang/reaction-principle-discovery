"""Deterministic admission of reviewed, reaction-specific literature evidence.

Match judgments are supplied by chemical review. This module does not infer
chemistry, rank elements, call a model, or reconstruct historical predictions.
"""
from __future__ import annotations

MATCH_FIELDS = ("donor_form_match", "acceptor_match", "activation_match", "endpoint_match")
PRIMARY_ACCESS = frozenset({"primary_full_text", "primary_supporting_information", "primary_author_abstract"})
MATCH_VALUES = frozenset({"exact", "adjacent", "mismatch", "unknown"})


def assess_evidence(record: dict) -> dict:
    """Return a conservative support label while retaining opposing evidence.

    A negative is an observed failure in a specified tested domain, never an
    elemental prohibition. A positive in another domain remains positive in
    that domain, even when its transfer to the target is unsupported.
    """
    matches = {key: record.get(key, "unknown") for key in MATCH_FIELDS}
    invalid = {key: value for key, value in matches.items() if value not in MATCH_VALUES}
    if invalid:
        raise ValueError(f"Invalid chemical match judgments: {invalid}")
    kind = record.get("observation_kind", "not_reported")
    access = record.get("source_access", "unavailable")
    scope = record.get("scope", "unknown")
    reasons = [f"{key}:{value}" for key, value in matches.items() if value != "exact"]
    has_provenance = all(str(record.get(key) or "").strip() for key in ("evidence_id", "catalog_id", "quotation", "locator"))
    readable = access in PRIMARY_ACCESS
    all_exact = all(value == "exact" for value in matches.values())
    measured_positive = kind == "measured_positive"
    result = {
        "evidence_id": record.get("evidence_id"),
        "target_negative": False,
        "assessment": "unsupported_transfer",
        "reasons": reasons,
        "preserve_positive_evidence": kind in {"measured_positive", "measured_alternative_endpoint"},
        "evidence_timing": record.get("evidence_timing", "unknown"),
        "validated_model_prediction": False,
        "method": "deterministic_admission_of_human_reviewed_scope_v1",
    }
    if scope == "element_class_ban":
        reasons.append("universal_element_ban_not_admissible")
        return result
    if not readable or not has_provenance or "unknown" in matches.values():
        result["assessment"] = "unresolved"
        if not readable:
            reasons.append(f"source_access:{access}")
        if not has_provenance:
            reasons.append("traceable_primary_passage_missing")
        return result
    if kind in {"metadata_only", "not_reported"}:
        result["assessment"] = "unresolved"
        reasons.append("no_observed_reaction_event")
        return result
    if scope != "tested_reaction":
        reasons.append("scope_is_not_a_specified_tested_reaction")
        return result
    if kind == "measured_no_target":
        result["assessment"] = "supported_scoped_negative" if all_exact else "conditional_caution"
        result["target_negative"] = all_exact
    elif measured_positive:
        result["assessment"] = "supported_scoped_positive" if all_exact else "unsupported_transfer"
    elif kind == "measured_alternative_endpoint":
        result["assessment"] = "conditional_caution"
        reasons.append("alternative_endpoint_is_not_target_failure")
    elif kind == "measured_condition_effect":
        result["assessment"] = "conditional_caution"
        reasons.append("condition_effect_is_not_an_observed_zero")
    else:
        reasons.append("interpretation_is_not_a_measured_outcome")
    return result

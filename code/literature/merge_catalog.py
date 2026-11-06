"""Merge verified literature identities and assess source-level chemical applicability."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"engine"))
from pipeline.evidence_applicability import assess_evidence
def norm_doi(value) -> str:
    return str(value or "").lower().removeprefix("https://doi.org/").strip()

def substantive(evidence: dict) -> bool:
    return evidence.get("observation_kind") not in {"metadata_only", "not_reported"} and evidence.get("source_access") not in {"metadata_only", "unavailable"} and bool(evidence.get("quotation"))

def merge_catalog(original: list[dict], reviews: list[dict]) -> list[dict]:
    """Append verified identities; enrich existing DOI records without re-IDing."""
    result = deepcopy(original)
    by_doi = {norm_doi(row.get("doi")): row for row in result if row.get("doi")}
    by_id = {row["si_id"]: row for row in result}
    for review in reviews:
        if review.get("metadata_status") != "verified":
            raise ValueError(f"Unverified source metadata: {review.get('catalog_id')}")
        doi, cid = norm_doi(review["doi"]), review["catalog_id"]
        row = by_doi.get(doi)
        if row is not None and row["si_id"] != cid:
            raise ValueError(f"Cannot reassign existing DOI {doi} from {row['si_id']} to {cid}")
        if row is None:
            if cid in by_id:
                raise ValueError(f"Catalog identity collision: {cid}")
            sid = review.get("source_id") or "P-" + sha256(doi.encode()).hexdigest()[:16]
            tier = review["primary_tier"]
            admitted = [e for e in review.get("evidence", []) if substantive(e)]
            paths = review.get("source_paths", [])
            citation = deepcopy(review.get("citation", {}))
            citation.update({"title": review["title"], "doi": doi, "url": "https://doi.org/" + doi})
            row = {
                "catalog_number": int(cid[1:]), "catalog_id": cid, "si_id": cid,
                "source_id": sid, "doi": doi, "title": review["title"],
                "url": "https://doi.org/" + doi, "tier": f"tier_{tier}", "tier_number": tier,
                "tier_preserved_from_registry": False,
                "tier_assignment_basis": review.get("tier_rationale", "Primary chemical role assigned during current review."),
                "tier_assignment_status": review.get("tier_assignment_status", "current_review_primary_role"),
                "full_reference": review["full_reference"], "citation_text": review["full_reference"],
                "citation": citation, "reference_code": None,
                "contribution_summary": review["review_summary"], "contribution": review["review_summary"],
                "contribution_kind": "current_source_linked_review" if admitted else "bibliographic_topic_only",
                "evidence_record_count": len(admitted), "historical_evidence_count": 0,
                "later_evidence_count": len(admitted), "selected_contributions": [],
                "all_evidence": [], "historical_principle_links": [], "candidate_links": [],
                "citation_status": "metadata_verified_2026-10-28",
                "citation_missing_fields": review.get("citation_missing_fields", []),
                "citation_unassigned_fields": [], "local_source_paths": paths,
                "access": {"level": review["source_access"],
                           "primary_full_text_available": review["source_access"] in {"primary_full_text", "primary_supporting_information"},
                           "fresh_full_text_review": review["source_access"] in {"primary_full_text", "primary_supporting_information"},
                           "local_file_present": bool(paths),
                           "chemically_substantive_text_available": bool(admitted)},
                "limitations": review.get("limitations", []), "limits": review.get("limitations", []),
                "validated_record_path": None, "selection_audit_path": None,
                "source_registry_pointer": "current_verified_sources.json#" + cid,
                "link_scope_note": "Current literature review, not a historical candidate-generation input.",
            }
            for e in admitted:
                row["selected_contributions"].append({"evidence_id": e["evidence_id"], "claim": e["claim"],
                    "evidence_label": "LITERATURE FACT" if e["observation_kind"].startswith("measured_") else "AUTHOR HYPOTHESIS",
                    "collection_version": "2026-10-28", "locator": e["locator"], "quotation_excerpt": e["quotation"]})
            result.append(row)
            by_doi[doi] = row
            by_id[cid] = row
        review_annotation = {key: deepcopy(review.get(key)) for key in [
            "review_summary", "source_access", "secondary_tiers", "tier_rationale", "source_paths",
            "metadata_paths", "limitations", "version_relations", "evidence"]}
        review_annotation.update({"review_date": "2026-10-28", "timing": "later_review", "generation_input_changed": False})
        row["current_review"] = review_annotation
        row["current_review_substantive_count"] = sum(substantive(e) for e in review.get("evidence", []))
    return result

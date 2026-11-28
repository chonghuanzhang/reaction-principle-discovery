import hashlib
import json
import unicodedata
from pathlib import Path

import pytest
import yaml

from pipeline.leakage_audit import LeakagePolicy
from pipeline.v3_models import ExplorationBriefV3


_CONTRACT_RELATIVE_PATH = "config/seed_claim_types_v3.yaml"


def _raw_type_digest(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_RAW_TYPE_MAPPINGS = (
    ("outcome", "selectivity"),
    ("reaction identity and product class", "selectivity"),
    ("optimized condition and yield", "condition_window"),
    ("reaction execution window", "condition_window"),
    ("electrophile scope", "electronic_requirement"),
    ("boronic ester scope and boundary", "nucleophile_requirement"),
    ("boronic acid scope and failure boundary", "failure_boundary"),
    ("organoboron format and scale-up", "nucleophile_requirement"),
    ("mechanistic control experiments", "reaction_center"),
    ("unresolved intermediate", "reactive_intermediate"),
    ("unresolved radical involvement", "reaction_center"),
    ("author-proposed catalytic mechanism", "catalyst_role"),
    ("author-proposed competing pathway", "failure_boundary"),
    ("net bond-change inference", "reaction_center"),
    ("scope-derived structure-reactivity hypothesis", "electronic_requirement"),
    ("reaction_center", "reaction_center"),
    ("reactive_intermediate", "reactive_intermediate"),
    ("electronic_requirement", "electronic_requirement"),
    ("nucleophile_requirement", "nucleophile_requirement"),
    ("catalyst_role", "catalyst_role"),
    ("condition_window", "condition_window"),
    ("selectivity", "selectivity"),
    ("failure_boundary", "failure_boundary"),
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _brief() -> ExplorationBriefV3:
    return ExplorationBriefV3.model_validate(
        {
            "version": "3.0",
            "study_id": "v3-evidence-import",
            "fixed_role": {
                "role": "electrophile",
                "label": "fixed seed electrophile",
                "seed_reaction_id": "SR001",
            },
            "variable_role": {"role": "nucleophile", "label": "open partner"},
            "target_transformation": {
                "new_bond": "C-Nu",
                "retained_features": ["electrophile core"],
            },
            "allowed_evidence_levels": ["traceable_external_evidence"],
        }
    )


def _seed_mechanism() -> dict:
    return {
        "seed_reaction_id": "SR001",
        "reaction_center": ["C-F"],
        "electrophile_state": ["activated"],
        "nucleophile_state": ["available"],
        "bond_changes": ["form C-Nu"],
        "reactive_intermediates": ["anion"],
        "elementary_steps": ["addition"],
        "electronic_requirements": ["activation"],
        "steric_requirements": [],
        "catalyst_roles": [],
        "condition_window": ["base"],
        "successful_scope": ["seed"],
        "failed_scope": [],
        "competing_pathways": [],
        "evidence_ids": ["SE001"],
        "confidence": "high",
    }


def _seed_evidence() -> dict:
    return {
        "seed_evidence": [
            {
                "evidence": {
                    "evidence_id": "SE001",
                    "source_type": "seed",
                    "source_id": "SR001",
                    "evidence_label": "EXPERIMENTAL FACT",
                    "quotation": "The seed reaction formed product.",
                    "locator": "seed:1",
                },
                "claim": "The seed reaction is grounded.",
                "evidence_type": "outcome",
                "reviewer_status": "accepted",
            }
        ]
    }


def _seed_principle() -> dict:
    return {
        "seed_principle_id": "SP001",
        "title": "Seed only",
        "claim": "The seed follows the observed mechanism.",
        "reaction_center": ["C-F"],
        "reactive_intermediates": ["anion"],
        "electronic_requirements": ["activation"],
        "nucleophile_requirements": ["available"],
        "catalyst_roles": [],
        "condition_window": ["base"],
        "failure_boundaries": [],
        "supporting_seed_evidence": ["SE001"],
        "confidence": "high",
        "uncertainty": [],
    }


def _normalization(source_path: str, sha256: str) -> dict:
    return {
        "cache_key": "normalization-cache",
        "source_file": source_path,
        "source_sha256": sha256,
        "normalization": {
            "mechanism_evidence": [
                {
                    "mechanism_evidence_id": "ME001",
                    "source_paper_id": source_path,
                    "source_evidence_ids": ["E001"],
                    "evidence_type": "elementary_step",
                    "elementary_step": "addition",
                    "starting_state": "reactants",
                    "ending_state": "product",
                    "bond_changes": ["form C-Nu"],
                    "catalyst_role": "none",
                    "nucleophile_requirements": ["available"],
                    "electrophile_requirements": ["activated"],
                    "condition_requirements": ["base"],
                    "observed_outcome": "product observed",
                    "failure_mode": None,
                    "evidence_label": "LITERATURE FACT",
                    "evidence_strength": "direct",
                    "quotation": "Product was observed.",
                    "pdf_page": 1,
                    "confidence": "high",
                }
            ],
            "boundary_constraints": [
                {
                    "constraint_id": "BC001",
                    "dimension": "condition",
                    "applies_to": ["base"],
                    "direction": "promotes",
                    "statement": "Base is required.",
                    "quantitative_range": None,
                    "supporting_evidence_ids": ["E001"],
                    "contradictory_evidence_ids": [],
                    "confidence": "high",
                }
            ],
            "source_revisit_requests": [
                {
                    "request_id": "SRR001",
                    "source_paper_id": source_path,
                    "pdf_pages": [1],
                    "reason": "critical_visual",
                    "question": "Verify the figure.",
                    "status": "pending",
                }
            ],
        },
        "usage": {
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
        },
    }


def _canonical_normalization(source_path: str, sha256: str) -> dict:
    return _normalization(source_path, sha256)


def _transfer() -> dict:
    return {
        "semantic_transfer_version": "2.0",
        "assessments": [
            {
                "assessment_id": "TA001",
                "source_paper_id": "papers/one.pdf",
                "source_mechanism_id": "aaaaaaaaaaaa::ME001",
                "source_evidence_ids": ["aaaaaaaaaaaa::E001"],
                "seed_feature_ids": ["SE001"],
                "shared_elementary_step": "addition",
                "matched_requirements": ["base"],
                "mismatched_requirements": [],
                "blocking_constraints": [],
                "transfer_status": "transferable",
                "transferable_claim": "The elementary step transfers.",
                "conditions": ["base"],
                "uncertainty": [],
                "falsifying_test": "Run an appropriate control.",
                "score_components": {"mechanism": 1},
            }
        ],
    }


def _clean_v2_fixture(root: Path) -> Path:
    source_path = "papers/one.pdf"
    sha256 = "a" * 64
    _write_json(
        root / "derived/full_corpus/queue.json",
        {"queue_digest": "q" * 64, "items": [{"source_path": source_path, "sha256": sha256, "tier": "tier_1"}]},
    )
    _write_json(
        root / "derived/principles/evidence_registry.json",
        {
            "queue_digest": "q" * 64,
            "queue_paper_count": 1,
            "scoped_record_count": 1,
            "evidence_item_count": 1,
            "contradiction_count": 0,
            "visual_review_page_count": 0,
            "off_queue_cache_count": 0,
            "missing_source_paths": [],
            "records": [{"source_path": source_path, "sha256": sha256, "tier": "tier_1", "validated_path": "derived/full_corpus/papers/one/validated.json", "cache_key": "literature-cache", "evidence_item_count": 1, "contradiction_count": 0, "visual_review_page_count": 0}],
        },
    )
    _write_json(root / "derived/principles/seed_evidence.json", _seed_evidence())
    _write_json(root / "derived/principles/seed_mechanism.json", _seed_mechanism())
    _write_json(root / "derived/principles/seed_principle.json", _seed_principle())
    _write_json(root / f"derived/principles/normalization/{sha256[:12]}/validated.json", _normalization(source_path, sha256))
    _write_json(root / "derived/principles/transfer_assessments.json", _transfer())
    contract_path = root / _CONTRACT_RELATIVE_PATH
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_bytes(
        (Path(__file__).resolve().parents[1] / _CONTRACT_RELATIVE_PATH).read_bytes()
    )
    return root


def _canonical_fixture(root: Path) -> Path:
    root = _clean_v2_fixture(root)
    path = root / "derived/principles/normalization/aaaaaaaaaaaa/validated.json"
    _write_json(path, _canonical_normalization("papers/one.pdf", "a" * 64))
    return root


def _add_second_normalized_source(root: Path) -> None:
    source_path = "papers/two.pdf"
    sha256 = "b" * 64
    queue_path = root / "derived/full_corpus/queue.json"
    queue = json.loads(queue_path.read_text())
    queue["items"].append(
        {"source_path": source_path, "sha256": sha256, "tier": "tier_1"}
    )
    _write_json(queue_path, queue)
    registry_path = root / "derived/principles/evidence_registry.json"
    registry = json.loads(registry_path.read_text())
    registry["queue_paper_count"] = 2
    registry["scoped_record_count"] = 2
    registry["records"].append(
        {
            "source_path": source_path,
            "sha256": sha256,
            "tier": "tier_1",
            "validated_path": "derived/full_corpus/papers/two/validated.json",
            "cache_key": "literature-cache-two",
            "evidence_item_count": 1,
            "contradiction_count": 0,
            "visual_review_page_count": 0,
        }
    )
    _write_json(registry_path, registry)
    _write_json(
        root / f"derived/principles/normalization/{sha256[:12]}/validated.json",
        _normalization(source_path, sha256),
    )


def _policy(root: Path) -> LeakagePolicy:
    dependencies = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "derived").glob("principles/**/*.json")
        if path.name in {"seed_evidence.json", "seed_mechanism.json", "seed_principle.json", "transfer_assessments.json", "evidence_registry.json", "validated.json"}
    )
    dependencies.append("derived/full_corpus/queue.json")
    dependencies.append(_CONTRACT_RELATIVE_PATH)
    dependencies.sort()
    manifest = root / "import-dependencies.json"
    _write_json(manifest, {"dependency_paths": dependencies, "query_ids": []})
    return LeakagePolicy(policy_id="v3-import-test", run_manifest_path=manifest)


def test_import_accepts_clean_grounded_seed_and_transfer_artifacts(tmp_path):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    manifest = import_reusable_evidence(root, _brief(), _policy(root))

    assert manifest.accepted_types == ("seed", "normalized_mechanism", "transfer")
    assert manifest.accepted_paths == (
        "derived/principles/normalization/aaaaaaaaaaaa/validated.json",
        "derived/principles/seed_mechanism.json",
        "derived/principles/seed_principle.json",
        "derived/principles/transfer_assessments.json",
        "derived/principles_v3/seed_evidence_projection.json",
    )
    persisted = json.loads((root / "derived/principles_v3/evidence_import_manifest.json").read_text())
    assert persisted["manifest_digest"] == manifest.manifest_digest
    assert persisted["cache_namespace"].startswith("principles_v3/evidence/")
    assert manifest.seed_claim_type_contract_path == _CONTRACT_RELATIVE_PATH
    assert manifest.seed_claim_type_contract_sha256 == hashlib.sha256(
        (root / _CONTRACT_RELATIVE_PATH).read_bytes()
    ).hexdigest()


def test_import_accepts_current_seed_writer_evidence_wrapper(tmp_path: Path) -> None:
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    seed_path = root / "derived/principles/seed_evidence.json"
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    payload["evidence"] = payload.pop("seed_evidence")
    payload["cache_key"] = "current-writer-cache-key"
    seed_path.write_text(json.dumps(payload), encoding="utf-8")

    manifest = import_reusable_evidence(root, _brief(), _policy(root))

    assert any(
        item.path.endswith("seed_evidence_projection.json")
        for item in manifest.accepted
    )


def test_import_reads_explicit_v3_clean_source_prefix(tmp_path: Path) -> None:
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    prefix = Path("derived/principles_v3/clean_inputs")
    clean = root / prefix
    (clean / "derived").mkdir(parents=True)
    (root / "derived/principles").rename(clean / "derived/principles")
    (clean / "derived/full_corpus").mkdir(parents=True)
    (root / "derived/full_corpus/queue.json").rename(
        clean / "derived/full_corpus/queue.json"
    )
    dependencies = sorted(
        path.relative_to(root).as_posix()
        for path in (clean / "derived").rglob("*.json")
        if path.name
        in {
            "seed_evidence.json",
            "seed_mechanism.json",
            "seed_principle.json",
            "transfer_assessments.json",
            "evidence_registry.json",
            "validated.json",
            "queue.json",
        }
    )
    dependencies.append(_CONTRACT_RELATIVE_PATH)
    manifest_path = root / "clean-import-dependencies.json"
    _write_json(
        manifest_path,
        {"dependency_paths": sorted(dependencies), "query_ids": []},
    )
    policy = LeakagePolicy(
        policy_id="v3-clean-prefix-test", run_manifest_path=manifest_path
    )

    manifest = import_reusable_evidence(
        root,
        _brief(),
        policy,
        source_prefix=prefix,
    )

    assert all(
        item.path.startswith(prefix.as_posix())
        for item in manifest.accepted
        if not item.path.endswith("seed_evidence_projection.json")
    )


def test_import_requires_rooted_seed_claim_contract(tmp_path: Path):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    (root / _CONTRACT_RELATIVE_PATH).unlink()

    with pytest.raises(EvidenceImportError, match="claim type contract"):
        import_reusable_evidence(root, _brief(), _policy(root))


def test_import_rejects_noncanonical_seed_claim_contract_path(tmp_path: Path):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    contract_path = root / _CONTRACT_RELATIVE_PATH
    alternate_path = contract_path.with_name("alternate-contract.yaml")
    contract_path.rename(alternate_path)
    contract_path.symlink_to(alternate_path.name)

    with pytest.raises(EvidenceImportError, match="contract path is not canonical"):
        import_reusable_evidence(root, _brief(), _policy(root))


def test_import_audits_seed_claim_contract_in_exact_closure(tmp_path: Path):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    policy = _policy(root)
    closure = json.loads(policy.run_manifest_path.read_text())
    closure["dependency_paths"].remove(_CONTRACT_RELATIVE_PATH)
    _write_json(policy.run_manifest_path, closure)

    with pytest.raises(EvidenceImportError, match="leakage audit"):
        import_reusable_evidence(root, _brief(), policy)


@pytest.mark.parametrize(
    ("raw_type", "normalized_type"),
    (*_RAW_TYPE_MAPPINGS, ("  OUTCOME\t", "selectivity")),
)
def test_import_normalizes_production_seed_claim_types(
    tmp_path: Path, raw_type: str, normalized_type: str
):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    seed_path = root / "derived/principles/seed_evidence.json"
    seed_payload = json.loads(seed_path.read_text())
    seed_payload["seed_evidence"][0]["evidence_type"] = raw_type
    _write_json(seed_path, seed_payload)

    manifest = import_reusable_evidence(root, _brief(), _policy(root))
    projection_path = root / "derived/principles_v3/seed_evidence_projection.json"
    projection = json.loads(projection_path.read_text())
    row = projection["seed_evidence"][0]

    assert row["normalized_claim_type"] == normalized_type
    assert row["provenance"]["raw_evidence_type"] == raw_type
    assert "evidence_type" not in row
    assert manifest.seed_claim_type_contract_digest == (
        projection["claim_type_contract_digest"]
    )


def test_import_rejects_unknown_seed_claim_type(tmp_path: Path):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    seed_path = root / "derived/principles/seed_evidence.json"
    seed_payload = json.loads(seed_path.read_text())
    seed_payload["seed_evidence"][0]["evidence_type"] = "unknown synthetic raw type"
    _write_json(seed_path, seed_payload)

    with pytest.raises(EvidenceImportError, match="unknown Seed claim type"):
        import_reusable_evidence(root, _brief(), _policy(root))


def test_seed_claim_contract_change_invalidates_manifest_and_cache(tmp_path: Path):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    default_contract = (
        Path(__file__).resolve().parents[1] / "config/seed_claim_types_v3.yaml"
    )
    contract_path = root / "config/seed_claim_types_v3.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_bytes(default_contract.read_bytes())
    first = import_reusable_evidence(root, _brief(), _policy(root))
    first_projection = json.loads(
        (root / "derived/principles_v3/seed_evidence_projection.json").read_text()
    )

    contract_payload = yaml.safe_load(contract_path.read_text())
    contract_payload["raw_type_hash_mapping"][
        _raw_type_digest("outcome")
    ] = "condition_window"
    contract_path.write_text(yaml.safe_dump(contract_payload, sort_keys=False))
    second = import_reusable_evidence(root, _brief(), _policy(root))
    second_projection = json.loads(
        (root / "derived/principles_v3/seed_evidence_projection.json").read_text()
    )

    assert first.seed_claim_type_contract_digest != (
        second.seed_claim_type_contract_digest
    )
    assert first.manifest_digest != second.manifest_digest
    assert first.cache_namespace != second.cache_namespace
    assert first_projection["seed_evidence"][0]["normalized_claim_type"] == (
        "selectivity"
    )
    assert second_projection["seed_evidence"][0]["normalized_claim_type"] == (
        "condition_window"
    )


def test_active_seed_claim_contract_contains_only_hashed_aliases():
    contract_text = (
        Path(__file__).resolve().parents[1] / _CONTRACT_RELATIVE_PATH
    ).read_text()
    contract = yaml.safe_load(contract_text)

    assert contract["version"] == "1.1"
    assert set(contract["raw_type_hash_mapping"]) == {
        _raw_type_digest(raw_type)
        for raw_type, _ in _RAW_TYPE_MAPPINGS
    }
    assert all(
        len(alias_hash) == 64
        and set(alias_hash) <= set("0123456789abcdef")
        for alias_hash in contract["raw_type_hash_mapping"]
    )


def test_import_accepts_canonical_normalization_envelope_but_projects_its_evidence(tmp_path):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _canonical_fixture(tmp_path)
    first = import_reusable_evidence(root, _brief(), _policy(root))
    first_normalized = next(
        artifact
        for artifact in first.accepted
        if artifact.artifact_type == "normalized_mechanism"
    )
    path = root / "derived/principles/normalization/aaaaaaaaaaaa/validated.json"
    payload = json.loads(path.read_text())
    payload["usage"]["input_tokens"] = 99
    payload["normalization"]["source_revisit_requests"][0]["question"] = "Changed."
    _write_json(path, payload)
    second = import_reusable_evidence(root, _brief(), _policy(root))
    second_normalized = next(
        artifact
        for artifact in second.accepted
        if artifact.artifact_type == "normalized_mechanism"
    )

    assert first_normalized.sha256 != second_normalized.sha256
    assert first_normalized.evidence_digest == second_normalized.evidence_digest
    serialized = first_normalized.model_dump_json()
    assert "usage" not in serialized
    assert "source_revisit_requests" not in serialized


def test_import_rejects_v2_taxonomy_and_candidate_artifacts(tmp_path):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    _write_json(root / "derived/principles/coverage_audit.json", {"legacy": True})
    _write_json(root / "derived/principles/family_predictions.json", {"legacy": True})
    manifest = import_reusable_evidence(root, _brief(), _policy(root))

    assert "derived/principles/coverage_audit.json" in manifest.rejected_paths
    assert "derived/principles/family_predictions.json" in manifest.rejected_paths
    assert manifest.rejection_reasons["derived/principles/coverage_audit.json"] == "v2_coverage_artifact"
    assert manifest.rejection_reasons["derived/principles/family_predictions.json"] == "v2_family_artifact"


def test_import_rejects_contaminated_transfer_text(tmp_path):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    transfer_path = root / "derived/principles/transfer_assessments.json"
    transfer = json.loads(transfer_path.read_text())
    transfer["assessments"][0]["transferable_claim"] = "SEALED_TERM"
    _write_json(transfer_path, transfer)
    policy = _policy(root).model_copy(update={"sealed_terms": ("SEALED_TERM",)})

    with pytest.raises(EvidenceImportError, match="leakage"):
        import_reusable_evidence(root, _brief(), policy)


def test_import_digest_changes_only_when_an_accepted_artifact_changes(tmp_path):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    first = import_reusable_evidence(root, _brief(), _policy(root))
    _write_json(root / "derived/principles/coverage_audit.json", {"legacy": "changed"})
    rejected_change = import_reusable_evidence(root, _brief(), _policy(root))
    seed_path = root / "derived/principles/seed_mechanism.json"
    payload = json.loads(seed_path.read_text())
    payload["condition_window"] = ["different base"]
    _write_json(seed_path, payload)
    second = import_reusable_evidence(root, _brief(), _policy(root))

    assert rejected_change.manifest_digest == first.manifest_digest
    assert second.manifest_digest != rejected_change.manifest_digest
    assert first.cache_namespace != second.cache_namespace


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload.update({"provisional_candidates": []}), "top-level"),
        (
            lambda payload: payload["normalization"].update(
                {
                    "source_revisit_requests": [
                        {
                            "request_id": "SRR001",
                            "source_paper_id": "papers/one.pdf",
                            "pdf_pages": [1],
                            "reason": "critical_visual",
                            "question": "Verify.",
                            "status": "pending",
                            "unexpected": "taxonomy",
                        }
                    ]
                }
            ),
            "normalized mechanism",
        ),
    ],
)
def test_import_rejects_content_masquerading_in_allowed_normalization_file(
    tmp_path, mutation, match
):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    path = root / "derived/principles/normalization/aaaaaaaaaaaa/validated.json"
    payload = json.loads(path.read_text())
    mutation(payload)
    _write_json(path, payload)

    with pytest.raises(EvidenceImportError, match=match):
        import_reusable_evidence(root, _brief(), _policy(root))


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload.update({"unexpected_metadata": "value"}), "top-level"),
        (
            lambda payload: payload["normalization"].update({"unexpected_section": []}),
            "normalization payload",
        ),
    ],
)
def test_import_rejects_unknown_normalization_fields(tmp_path, mutation, match):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    path = root / "derived/principles/normalization/aaaaaaaaaaaa/validated.json"
    payload = json.loads(path.read_text())
    mutation(payload)
    _write_json(path, payload)

    with pytest.raises(EvidenceImportError, match=match):
        import_reusable_evidence(root, _brief(), _policy(root))


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload["usage"].update({"unexpected": 1}), "usage"),
        (
            lambda payload: payload["normalization"]["source_revisit_requests"][0].update(
                {"unexpected": "value"}
            ),
            "normalized mechanism",
        ),
    ],
)
def test_import_rejects_malicious_fields_in_known_normalization_envelope(
    tmp_path, mutation, match
):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _canonical_fixture(tmp_path)
    path = root / "derived/principles/normalization/aaaaaaaaaaaa/validated.json"
    payload = json.loads(path.read_text())
    mutation(payload)
    _write_json(path, payload)

    with pytest.raises(EvidenceImportError, match=match):
        import_reusable_evidence(root, _brief(), _policy(root))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_paper_id", None),
        ("source_mechanism_id", None),
        ("source_mechanism_id", "aaaaaaaaaaaa::MISSING"),
        ("source_evidence_ids", ["aaaaaaaaaaaa::MISSING"]),
        ("seed_feature_ids", ["MISSING"]),
        ("blocking_constraints", ["aaaaaaaaaaaa::MISSING"]),
    ],
)
def test_import_rejects_transfer_references_outside_accepted_evidence(
    tmp_path, field, value
):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    path = root / "derived/principles/transfer_assessments.json"
    payload = json.loads(path.read_text())
    payload["assessments"][0][field] = value
    _write_json(path, payload)

    with pytest.raises(EvidenceImportError, match="transfer .*reference"):
        import_reusable_evidence(root, _brief(), _policy(root))


def test_import_rejects_transfer_reference_from_another_accepted_paper(tmp_path):
    from pipeline.v3_evidence_import import EvidenceImportError, import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    _add_second_normalized_source(root)
    path = root / "derived/principles/transfer_assessments.json"
    payload = json.loads(path.read_text())
    payload["assessments"][0]["source_paper_id"] = "papers/two.pdf"
    _write_json(path, payload)

    with pytest.raises(EvidenceImportError, match="transfer .*reference"):
        import_reusable_evidence(root, _brief(), _policy(root))


def test_import_records_same_named_rejections_with_distinct_relative_paths(tmp_path):
    from pipeline.v3_evidence_import import import_reusable_evidence

    root = _clean_v2_fixture(tmp_path)
    _write_json(root / "derived/principles/cache_a/raw.json", {"legacy": True})
    _write_json(root / "derived/principles/cache_b/raw.json", {"legacy": True})

    manifest = import_reusable_evidence(root, _brief(), _policy(root))

    first = "derived/principles/cache_a/raw.json"
    second = "derived/principles/cache_b/raw.json"
    assert {first, second} <= set(manifest.rejected_paths)
    assert manifest.rejection_reasons[first] == "not_allowlisted_v2_artifact"
    assert manifest.rejection_reasons[second] == "not_allowlisted_v2_artifact"

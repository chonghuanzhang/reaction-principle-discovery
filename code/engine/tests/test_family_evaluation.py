from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import pipeline.family_evaluation as family_evaluation_module
from pipeline.evidence_registry import EvidenceRegistryRecord, EvidenceRegistrySummary
from pipeline.family_evaluation import (
    DEFAULT_RUBRIC_PATH,
    EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY,
    EVIDENCE_REGISTRY_ARTIFACT_KEY,
    FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY,
    FROZEN_PRINCIPLES_ARTIFACT_KEY,
    SCORING_RUBRIC_ARTIFACT_KEY,
    EvaluationRubric,
    EvidenceContribution,
    EvidenceQualificationContext,
    EvidenceQualificationError,
    HardBlockerCandidate,
    HardBlockerError,
    QualifiedBlocker,
    ScoredFamilyEvaluation,
    assign_priority_region,
    build_evidence_qualification_context,
    evaluation_rubric_digest,
    load_evaluation_rubric,
    qualify_hard_blockers,
    score_family,
    to_canonical_family_evaluation,
    verify_scored_family_evaluation,
    validated_evidence_artifact_key,
)
from pipeline.freeze import freeze_principles
from pipeline.leakage_audit import LeakagePolicy
from pipeline.principle_models import ReactionPrinciple, SeedEvidence
from pipeline.seed_claim_types import (
    DEFAULT_SEED_CLAIM_TYPE_CONFIG_PATH,
    SEED_CLAIM_TYPE_CONTRACT_ARTIFACT_KEY,
    SEED_EVIDENCE_PROJECTION_PATH,
    load_seed_claim_type_contract,
    project_seed_evidence,
    seed_claim_type_contract_digest,
)
from pipeline.v3_evidence_import import (
    EvidenceImportArtifact,
    EvidenceImportManifest,
    import_reusable_evidence,
)
from pipeline.v3_models import (
    DIMENSIONS,
    DimensionJudgment,
    ExplorationBriefV3,
    FamilyEvaluation as CanonicalFamilyEvaluation,
    FreezeManifestV3,
)


_SOURCE_PATH = "papers/source-alpha.pdf"
_PROVENANCE_PATH = "derived/full_corpus/papers/source-alpha/validated.json"
_NAMESPACE = "a" * 12
_PRINCIPLE_ID = "PRINCIPLE-SYNTHETIC-1"
_FROZEN_PATH = "derived/principles_v3/frozen_principles.json"
_MANIFEST_PATH = "derived/principles_v3/freeze_manifest_v3.json"
_IMPORT_MANIFEST_PATH = "derived/principles_v3/evidence_import_manifest.json"
_RUBRIC_PATH = "config/family_evaluation_v3.yaml"
_SEED_CONTRACT_PATH = "config/seed_claim_types_v3.yaml"
_CREATED_AT = "2026-08-17T00:00:00Z"
_SCORING_DIGEST = "d" * 64


def _local_id(dimension: str) -> str:
    return f"EV-{dimension}"


def _evidence_id(dimension: str) -> str:
    return f"{_NAMESPACE}::{_local_id(dimension)}"


def _registry(*records: EvidenceRegistryRecord) -> EvidenceRegistrySummary:
    if not records:
        records = (
            EvidenceRegistryRecord(
                source_path=_SOURCE_PATH,
                sha256="a" * 64,
                tier="primary",
                validated_path=_PROVENANCE_PATH,
                cache_key="source-alpha-cache",
                evidence_item_count=12,
                contradiction_count=0,
                visual_review_page_count=1,
            ),
        )
    return EvidenceRegistrySummary(
        queue_digest="c" * 64,
        queue_paper_count=len(records),
        scoped_record_count=len(records),
        evidence_item_count=sum(record.evidence_item_count for record in records),
        contradiction_count=sum(record.contradiction_count for record in records),
        visual_review_page_count=sum(
            record.visual_review_page_count for record in records
        ),
        off_queue_cache_count=0,
        missing_source_paths=(),
        records=records,
    )


def _raw_item(local_id: str, *, model_inference: bool = False) -> dict:
    return {
        "evidence_id": local_id,
        "claim": "A synthetic observation was assessed.",
        "evidence_label": "MODEL INFERENCE"
        if model_inference
        else "LITERATURE FACT",
        "quotation": None
        if model_inference
        else "A synthetic external outcome was observed.",
        "source_span_ids": ["P1-S1"],
        "pdf_page": 1,
        "additional_pdf_pages": [],
        "section_context": "Synthetic results",
        "attribution": "model_inference"
        if model_inference
        else "author_observation",
        "evidence_strength": "inference" if model_inference else "direct",
        "visual_review_reference": None,
        "reviewer_status": "accepted",
    }


def _mechanism(local_id: str, evidence_type: str, index: int) -> dict:
    model_inference = local_id == "EV-model-quality"
    return {
        "mechanism_evidence_id": f"ME-SYNTHETIC-{index}",
        "source_paper_id": _SOURCE_PATH,
        "source_evidence_ids": [local_id],
        "evidence_type": evidence_type,
        "elementary_step": "synthetic step",
        "starting_state": "initial state",
        "ending_state": "observed state",
        "bond_changes": ["synthetic change"],
        "catalyst_role": "none reported",
        "nucleophile_requirements": ["synthetic requirement"],
        "electrophile_requirements": ["synthetic requirement"],
        "condition_requirements": ["synthetic condition"],
        "observed_outcome": "synthetic outcome",
        "failure_mode": "synthetic adverse outcome"
        if evidence_type == "failure_boundary"
        else None,
        "evidence_label": "MODEL INFERENCE"
        if model_inference
        else "LITERATURE FACT",
        "evidence_strength": "inference" if model_inference else "direct",
        "quotation": None
        if model_inference
        else "A synthetic external outcome was observed.",
        "pdf_page": 1,
        "confidence": "high" if not model_inference else "low",
    }


def _constraint(
    local_id: str, dimension: str, direction: str, index: int
) -> dict:
    return {
        "constraint_id": f"BC-SYNTHETIC-{index}",
        "dimension": dimension,
        "applies_to": ["synthetic state"],
        "direction": direction,
        "statement": "A synthetic constraint was reviewed.",
        "quantitative_range": None,
        "supporting_evidence_ids": [local_id],
        "contradictory_evidence_ids": [],
        "confidence": "high",
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_environment(
    root: Path,
    *,
    unbound_ids: tuple[str, ...] = (),
    extra_principle_ids: tuple[str, ...] = (),
    seed_reference_ids: tuple[str, ...] = ("SE-001",),
    transfer_reference_ids: tuple[str, ...] = ("TA-001",),
    seed_evidence_type: str = "reaction_center",
) -> tuple[EvidenceRegistrySummary, Path, Path]:
    registry = _registry()
    record = registry.records[0]
    local_ids = [
        *(_local_id(dimension) for dimension in DIMENSIONS),
        "EV-blocker",
        "EV-counter-condition",
        "EV-counter-reactive",
        "EV-model-quality",
        "EV-supportive-condition",
    ]
    assert len(local_ids) == record.evidence_item_count
    _write_json(
        root / record.validated_path,
        {
            "cache_key": record.cache_key,
            "extraction": {
                "source_file": record.source_path,
                "sha256": record.sha256,
                "evidence_items": [
                    _raw_item(
                        local_id, model_inference=local_id == "EV-model-quality"
                    )
                    for local_id in local_ids
                ],
                "contradictions": [],
                "visual_review_pages": [1],
            },
        },
    )
    mechanism_specs = (
        (_local_id("elementary_step_match"), "elementary_step"),
        (_local_id("electrophile_state_match"), "electronic_requirement"),
        (_local_id("reactive_state_accessibility"), "nucleophile_requirement"),
        (_local_id("condition_compatibility"), "condition_effect"),
        (_local_id("competing_pathway_risk"), "failure_boundary"),
        (_local_id("evidence_quality"), "condition_effect"),
        ("EV-counter-reactive", "nucleophile_requirement"),
        ("EV-model-quality", "condition_effect"),
        ("EV-supportive-condition", "condition_effect"),
    )
    constraints = (
        _constraint(_local_id("target_selectivity"), "steric", "promotes", 1),
        _constraint("EV-blocker", "condition", "incompatible", 2),
        _constraint("EV-counter-condition", "condition", "promotes", 3),
    )
    normalized_path = (
        root
        / "derived/principles/normalization"
        / record.sha256[:12]
        / "validated.json"
    )
    _write_json(
        normalized_path,
        {
            "cache_key": "normalization-cache",
            "source_file": record.source_path,
            "source_sha256": record.sha256,
            "normalization": {
                "mechanism_evidence": [
                    _mechanism(local_id, evidence_type, index)
                    for index, (local_id, evidence_type) in enumerate(
                        mechanism_specs, start=1
                    )
                ],
                "boundary_constraints": list(constraints),
                "source_revisit_requests": [],
            },
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        },
    )
    exact_principle_ids = [
        f"{record.sha256[:12]}::{local_id}"
        for local_id in local_ids
        if local_id not in unbound_ids
    ]
    seed_evidence_path = root / "derived/principles/seed_evidence.json"
    seed_mechanism_path = root / "derived/principles/seed_mechanism.json"
    seed_principle_path = root / "derived/principles/seed_principle.json"
    transfer_path = root / "derived/principles/transfer_assessments.json"
    rejected_v2_path = root / "derived/principles/provisional_candidates.json"
    seed_payload = {
        "seed_evidence": [
            {
                "evidence": {
                    "evidence_id": "SE-001",
                    "source_type": "seed",
                    "source_id": "SEED-SYNTHETIC-1",
                    "evidence_label": "EXPERIMENTAL FACT",
                    "quotation": "A synthetic seed outcome was recorded.",
                    "locator": "seed-record:1",
                },
                "claim": "A synthetic seed feature was reviewed.",
                "evidence_type": seed_evidence_type,
                "reviewer_status": "accepted",
            }
        ]
    }
    _write_json(
        seed_evidence_path,
        seed_payload,
    )
    _write_json(
        seed_mechanism_path,
        {
            "seed_reaction_id": "SEED-SYNTHETIC-1",
            "reaction_center": ["synthetic center"],
            "electrophile_state": ["synthetic electrophile state"],
            "nucleophile_state": ["synthetic nucleophile state"],
            "bond_changes": ["synthetic bond change"],
            "reactive_intermediates": ["synthetic intermediate"],
            "elementary_steps": ["synthetic step"],
            "electronic_requirements": ["synthetic electronic requirement"],
            "steric_requirements": ["synthetic steric requirement"],
            "catalyst_roles": ["synthetic catalyst role"],
            "condition_window": ["synthetic condition"],
            "successful_scope": ["synthetic accepted scope"],
            "failed_scope": ["synthetic failed scope"],
            "competing_pathways": ["synthetic competing outcome"],
            "evidence_ids": ["SE-001"],
            "confidence": "high",
        },
    )
    _write_json(
        seed_principle_path,
        {
            "seed_principle_id": "SP-SYNTHETIC-1",
            "title": "Synthetic seed Principle",
            "claim": "The synthetic seed feature constrains transfer.",
            "reaction_center": ["synthetic center"],
            "reactive_intermediates": ["synthetic intermediate"],
            "electronic_requirements": ["synthetic electronic requirement"],
            "nucleophile_requirements": ["synthetic nucleophile requirement"],
            "catalyst_roles": ["synthetic catalyst role"],
            "condition_window": ["synthetic condition"],
            "failure_boundaries": ["synthetic failure boundary"],
            "supporting_seed_evidence": ["SE-001"],
            "confidence": "high",
            "uncertainty": ["synthetic uncertainty"],
        },
    )
    _write_json(
        transfer_path,
        {
            "assessments": [
                {
                    "assessment_id": "TA-001",
                    "source_paper_id": record.source_path,
                    "source_mechanism_id": f"{_NAMESPACE}::ME-SYNTHETIC-1",
                    "source_evidence_ids": exact_principle_ids,
                    "seed_feature_ids": ["SE-001"],
                    "shared_elementary_step": "synthetic shared step",
                    "matched_requirements": ["synthetic match"],
                    "mismatched_requirements": [],
                    "blocking_constraints": [f"{_NAMESPACE}::BC-SYNTHETIC-2"],
                    "transfer_status": "transferable",
                    "transferable_claim": "The synthetic evidence may transfer.",
                    "conditions": ["synthetic condition"],
                    "uncertainty": ["synthetic transfer uncertainty"],
                    "falsifying_test": "Run a synthetic transfer control.",
                    "score_components": {"synthetic_component": 1},
                }
            ]
        },
    )
    _write_json(
        rejected_v2_path,
        {"evidence_ids": ["V2-SYNTHETIC-EVIDENCE-ONLY"]},
    )
    rubric_path = root / _RUBRIC_PATH
    rubric_path.parent.mkdir(parents=True, exist_ok=True)
    rubric_path.write_bytes(DEFAULT_RUBRIC_PATH.read_bytes())
    seed_contract_path = root / _SEED_CONTRACT_PATH
    seed_contract_path.write_bytes(DEFAULT_SEED_CLAIM_TYPE_CONFIG_PATH.read_bytes())
    seed_contract = load_seed_claim_type_contract(seed_contract_path)
    seed_projection = project_seed_evidence(
        tuple(
            SeedEvidence.model_validate(row)
            for row in seed_payload["seed_evidence"]
        ),
        source_path=seed_evidence_path.relative_to(root).as_posix(),
        source_sha256=hashlib.sha256(seed_evidence_path.read_bytes()).hexdigest(),
        contract=seed_contract,
    )
    seed_projection_path = root / SEED_EVIDENCE_PROJECTION_PATH
    _write_json(seed_projection_path, seed_projection.model_dump(mode="json"))
    accepted_paths = (
        (
            seed_projection_path,
            "seed",
            "pipeline.seed_claim_types.projection-v1",
        ),
        (seed_mechanism_path, "seed", "pipeline.principle_models.seed-v1"),
        (seed_principle_path, "seed", "pipeline.principle_models.seed-v1"),
        (
            normalized_path,
            "normalized_mechanism",
            "pipeline.principle_models.normalization-v1",
        ),
        (transfer_path, "transfer", "pipeline.principle_models.transfer-v1"),
    )
    accepted = tuple(
        EvidenceImportArtifact(
            path=path.relative_to(root).as_posix(),
            artifact_type=artifact_type,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            evidence_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
            schema_version=schema_version,
        )
        for path, artifact_type, schema_version in sorted(
            accepted_paths, key=lambda item: item[0].as_posix()
        )
    )
    import_material = {
        "version": "3.0",
        "brief_digest": "b" * 64,
        "leakage_policy_digest": "1" * 64,
        "queue_digest": registry.queue_digest,
        "queue_scope": tuple(record.source_path for record in registry.records),
        "provenance_paths": (
            "derived/full_corpus/queue.json",
            "derived/principles/evidence_registry.json",
            seed_evidence_path.relative_to(root).as_posix(),
        ),
        "seed_claim_type_contract_version": seed_contract.version,
        "seed_claim_type_contract_path": _SEED_CONTRACT_PATH,
        "seed_claim_type_contract_digest": seed_claim_type_contract_digest(
            seed_contract
        ),
        "seed_claim_type_contract_sha256": hashlib.sha256(
            seed_contract_path.read_bytes()
        ).hexdigest(),
        "accepted": [artifact.model_dump(mode="json") for artifact in accepted],
        "schema_versions": {
            "normalized_mechanism": "pipeline.principle_models.normalization-v1",
            "paper_provenance": "pipeline.evidence_registry.queue-v1",
            "seed": "pipeline.principle_models.seed-v1",
            "seed_projection": "pipeline.seed_claim_types.projection-v1",
            "transfer": "pipeline.principle_models.transfer-v1",
        },
    }
    evidence_import_manifest = EvidenceImportManifest(
        **import_material,
        rejected_paths=(rejected_v2_path.relative_to(root).as_posix(),),
        rejection_reasons={
            rejected_v2_path.relative_to(root).as_posix(): "v2_candidate_artifact"
        },
        cache_namespace="principles_v3/evidence/synthetic",
        manifest_digest=_stable_digest(import_material),
    )
    import_manifest_path = root / _IMPORT_MANIFEST_PATH
    _write_json(
        import_manifest_path, evidence_import_manifest.model_dump(mode="json")
    )
    principle = ReactionPrinciple(
        principle_id=_PRINCIPLE_ID,
        principle_layer="seed_specific",
        title="Synthetic reviewed Principle",
        status="accepted",
        claim="The synthetic evidence constrains evaluation.",
        mechanistic_basis=["synthetic reviewed basis"],
        applicable_electrophile_families=[],
        applicable_nucleophile_families=[],
        applicable_nucleophile_superclasses=[],
        required_reactive_form="synthetic reviewed state",
        catalyst_requirements=[],
        condition_window=[],
        structural_promoters=[],
        structural_inhibitors=[],
        supporting_seed_evidence=list(seed_reference_ids),
        supporting_transferred_evidence=list(transfer_reference_ids),
        contradictory_evidence=list(extra_principle_ids),
        known_exceptions=[],
        predicted_failure_modes=[],
        confidence="high",
        experimental_consequence="Run a synthetic diagnostic test.",
        falsifying_experiment="Run a synthetic falsifying control.",
        review_status="accepted",
        provenance={"run_id": "run-synthetic-v3"},
        freeze_version=None,
    )
    frozen_path = root / _FROZEN_PATH
    frozen_path.parent.mkdir(parents=True, exist_ok=True)
    frozen = freeze_principles(
        [principle],
        source_digest=registry.queue_digest,
        scoring_digest=_SCORING_DIGEST,
        freeze_version="Freeze 1",
        destination=frozen_path,
        created_at=_CREATED_AT,
    )
    frozen_digest = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
    manifest = FreezeManifestV3(
        freeze_version="Freeze 1",
        created_at=_CREATED_AT,
        brief_digest="f" * 64,
        artifact_digests={
            FROZEN_PRINCIPLES_ARTIFACT_KEY: frozen_digest,
            EVIDENCE_REGISTRY_ARTIFACT_KEY: _stable_digest(
                registry.model_dump(mode="json")
            ),
            SCORING_RUBRIC_ARTIFACT_KEY: frozen.scoring_digest,
            EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY: hashlib.sha256(
                import_manifest_path.read_bytes()
            ).hexdigest(),
            FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY: hashlib.sha256(
                rubric_path.read_bytes()
            ).hexdigest(),
            validated_evidence_artifact_key(record.validated_path): hashlib.sha256(
                (root / record.validated_path).read_bytes()
            ).hexdigest(),
        },
        hidden_registry_commitment="e" * 64,
        software_version="test-version",
    )
    manifest_path = root / _MANIFEST_PATH
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    return registry, frozen_path, manifest_path


def _build_context(
    tmp_path: Path,
    *,
    unbound_ids: tuple[str, ...] = (),
    extra_principle_ids: tuple[str, ...] = (),
    seed_evidence_type: str = "reaction_center",
) -> EvidenceQualificationContext:
    registry, frozen_path, manifest_path = _write_environment(
        tmp_path,
        unbound_ids=unbound_ids,
        extra_principle_ids=extra_principle_ids,
        seed_evidence_type=seed_evidence_type,
    )
    return _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def _build_from_environment(
    root: Path,
    registry: EvidenceRegistrySummary,
    frozen_path: Path,
    manifest_path: Path,
) -> EvidenceQualificationContext:
    return build_evidence_qualification_context(
        root,
        registry,
        frozen_path,
        manifest_path,
        root / _IMPORT_MANIFEST_PATH,
        root / _RUBRIC_PATH,
    )


def _context_with_record_update(
    context: EvidenceQualificationContext,
    evidence_id: str,
    **updates: object,
) -> EvidenceQualificationContext:
    records = tuple(
        record.model_copy(update=updates)
        if record.evidence_id == evidence_id
        else record
        for record in context.records
    )
    content_digest = family_evaluation_module._context_content_digest(
        records,
        context.frozen_dependencies,
        context.freeze_manifest_digest,
        context.evidence_import_manifest_digest,
        context.rubric_raw_digest,
        context.rubric_canonical_digest,
        context.frozen_principle_ids,
        context.frozen_principle_digests,
    )
    return EvidenceQualificationContext(
        _builder_token=family_evaluation_module._CONTEXT_BUILDER_TOKEN,
        records=records,
        content_digest=content_digest,
        registry_commitment=context.registry_commitment,
        artifact_commitment=context.artifact_commitment,
        freeze_manifest_digest=context.freeze_manifest_digest,
        evidence_import_manifest_digest=context.evidence_import_manifest_digest,
        rubric_raw_digest=context.rubric_raw_digest,
        rubric_canonical_digest=context.rubric_canonical_digest,
        frozen_dependencies=context.frozen_dependencies,
        frozen_principle_ids=context.frozen_principle_ids,
        frozen_principle_digests=context.frozen_principle_digests,
    )


def _rebind_import_manifest_dependency(root: Path, manifest_path: Path) -> None:
    import_path = root / _IMPORT_MANIFEST_PATH
    freeze_payload = json.loads(manifest_path.read_text())
    freeze_payload["artifact_digests"][
        EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY
    ] = hashlib.sha256(import_path.read_bytes()).hexdigest()
    _write_json(manifest_path, freeze_payload)


def _resign_import_manifest(root: Path, manifest_path: Path) -> None:
    import_path = root / _IMPORT_MANIFEST_PATH
    payload = json.loads(import_path.read_text())
    material = {
        key: payload[key]
        for key in (
            "version",
            "brief_digest",
            "leakage_policy_digest",
            "queue_digest",
            "queue_scope",
            "provenance_paths",
            "seed_claim_type_contract_version",
            "seed_claim_type_contract_path",
            "seed_claim_type_contract_digest",
            "seed_claim_type_contract_sha256",
            "accepted",
            "schema_versions",
        )
    }
    payload["manifest_digest"] = _stable_digest(material)
    _write_json(import_path, payload)
    _rebind_import_manifest_dependency(root, manifest_path)


def _refresh_accepted_artifact_digest(
    root: Path, manifest_path: Path, relative_path: str
) -> None:
    import_path = root / _IMPORT_MANIFEST_PATH
    payload = json.loads(import_path.read_text())
    artifact_path = root / relative_path
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact = next(
        item for item in payload["accepted"] if item["path"] == relative_path
    )
    artifact["sha256"] = digest
    artifact["evidence_digest"] = digest
    _write_json(import_path, payload)
    _resign_import_manifest(root, manifest_path)


def _importer_brief() -> ExplorationBriefV3:
    return ExplorationBriefV3.model_validate(
        {
            "version": "3.0",
            "study_id": "family-evaluation-import-integration",
            "fixed_role": {
                "role": "electrophile",
                "label": "synthetic fixed electrophile",
                "seed_reaction_id": "SR001",
            },
            "variable_role": {
                "role": "nucleophile",
                "label": "synthetic variable partner",
            },
            "target_transformation": {
                "new_bond": "C-Nu",
                "retained_features": ["synthetic electrophile core"],
            },
            "allowed_evidence_levels": ["traceable_external_evidence"],
        }
    )


def _importer_policy(root: Path) -> LeakagePolicy:
    dependencies = (
        "derived/full_corpus/queue.json",
        _SEED_CONTRACT_PATH,
        "derived/principles/evidence_registry.json",
        f"derived/principles/normalization/{_NAMESPACE}/validated.json",
        "derived/principles/seed_evidence.json",
        "derived/principles/seed_mechanism.json",
        "derived/principles/seed_principle.json",
        "derived/principles/transfer_assessments.json",
    )
    run_manifest = root / "import-dependencies.json"
    _write_json(
        run_manifest,
        {"dependency_paths": sorted(dependencies), "query_ids": []},
    )
    return LeakagePolicy(
        policy_id="family-evaluation-import-integration",
        run_manifest_path=run_manifest,
    )


@pytest.fixture
def context(tmp_path: Path) -> EvidenceQualificationContext:
    return _build_context(tmp_path)


def _rubric() -> EvaluationRubric:
    return load_evaluation_rubric()


def _judgment(
    dimension: str,
    state: str = "support",
    *,
    evidence_ids: tuple[str, ...] | None = None,
    counterevidence_ids: tuple[str, ...] = (),
) -> DimensionJudgment:
    if evidence_ids is None:
        evidence_ids = () if state == "unknown" else (_evidence_id(dimension),)
    return DimensionJudgment(
        dimension=dimension,
        state=state,
        evidence_ids=evidence_ids,
        rationale=f"Synthetic assessment for {dimension}",
        counterevidence_ids=counterevidence_ids,
        unresolved_questions=("Resolve the synthetic uncertainty",)
        if state == "unknown"
        else (),
    )


def _all_supporting_judgments() -> tuple[DimensionJudgment, ...]:
    return tuple(
        _judgment(
            dimension,
            "contradiction" if dimension == "competing_pathway_risk" else "support",
        )
        for dimension in DIMENSIONS
    )


def _judgments_with_unknown(
    dimension: str = "reactive_state_accessibility",
) -> tuple[DimensionJudgment, ...]:
    return tuple(
        _judgment(
            item,
            "unknown"
            if item == dimension
            else "contradiction"
            if item == "competing_pathway_risk"
            else "support",
        )
        for item in DIMENSIONS
    )


def _qualified_blocker(evidence_id: str | None = None) -> QualifiedBlocker:
    return QualifiedBlocker(
        blocker_id="BLOCK-SYNTHETIC-1",
        dimension="condition_compatibility",
        statement="A reviewed adverse synthetic outcome is incompatible",
        evidence_ids=(evidence_id or f"{_NAMESPACE}::EV-blocker",),
        counterevidence_ids=(f"{_NAMESPACE}::EV-counter-condition",),
        source_paths=(_SOURCE_PATH,),
        reviewed_principle_ids=(_PRINCIPLE_ID,),
    )


def _score(
    judgments: tuple[DimensionJudgment, ...],
    context: EvidenceQualificationContext,
    blockers: tuple[QualifiedBlocker, ...] = (),
    rubric: EvaluationRubric | None = None,
) -> ScoredFamilyEvaluation:
    return score_family(
        judgments,
        blockers,
        rubric or _rubric(),
        context,
        family_id="FAMILY-SYNTHETIC-1",
    )


def test_valid_canonical_frozen_set_and_manifest_build_snapshot(
    context: EvidenceQualificationContext,
):
    accepted = context.require(
        _evidence_id("condition_compatibility"),
        "condition_compatibility",
        reviewed_principle=True,
    )

    assert accepted.source_path == _SOURCE_PATH
    assert accepted.evidence_level == "traceable_external_evidence"
    assert accepted.reviewed_principle_ids == (_PRINCIPLE_ID,)
    assert len(context.content_digest) == 64
    assert len(context.registry_commitment) == 64
    assert len(context.artifact_commitment) == 64
    assert len(context.freeze_manifest_digest) == 64
    assert len(context.evidence_import_manifest_digest) == 64
    assert len(context.rubric_raw_digest) == 64
    assert len(context.rubric_canonical_digest) == 64
    assert context.frozen_principle_ids == (_PRINCIPLE_ID,)
    assert FROZEN_PRINCIPLES_ARTIFACT_KEY in {
        dependency.artifact_key for dependency in context.frozen_dependencies
    }
    contract_dependency = next(
        dependency
        for dependency in context.frozen_dependencies
        if dependency.artifact_key == SEED_CLAIM_TYPE_CONTRACT_ARTIFACT_KEY
    )
    assert contract_dependency.path == _SEED_CONTRACT_PATH
    assert contract_dependency.sha256 == hashlib.sha256(
        Path(DEFAULT_SEED_CLAIM_TYPE_CONFIG_PATH).read_bytes()
    ).hexdigest()
    raw_dependency = next(
        dependency
        for dependency in context.frozen_dependencies
        if dependency.artifact_key
        == validated_evidence_artifact_key(_PROVENANCE_PATH)
    )
    assert raw_dependency.path == _PROVENANCE_PATH


def test_canonical_seed_and_transfer_references_resolve_by_evidence_class(
    context: EvidenceQualificationContext,
):
    records = {record.evidence_id: record for record in context.records}

    assert records["SE-001"].evidence_class == "seed"
    assert records["TA-001"].evidence_class == "transfer_assessment"
    assert (
        records[f"{_NAMESPACE}::ME-SYNTHETIC-1"].evidence_class
        == "normalized_mechanism"
    )
    assert (
        records[f"{_NAMESPACE}::BC-SYNTHETIC-2"].evidence_class
        == "normalized_constraint"
    )
    assert records[_evidence_id("elementary_step_match")].evidence_class == (
        "external_literature"
    )
    assert all(
        record.reviewed_principle_ids == (_PRINCIPLE_ID,)
        for record in (
            records["SE-001"],
            records["TA-001"],
            records[f"{_NAMESPACE}::ME-SYNTHETIC-1"],
            records[f"{_NAMESPACE}::BC-SYNTHETIC-2"],
            records[_evidence_id("elementary_step_match")],
        )
    )


def test_seed_claim_type_is_admissible_only_for_mapped_dimension(
    context: EvidenceQualificationContext,
):
    seed = context.require(
        "SE-001", "elementary_step_match", reviewed_principle=True
    )

    assert seed.admissible_dimensions == ("elementary_step_match",)
    with pytest.raises(EvidenceQualificationError, match="not admissible"):
        context.require("SE-001", "condition_compatibility")


def test_legacy_accepted_seed_evidence_without_normalized_claim_type_fails(
    tmp_path: Path,
):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    import_path = tmp_path / _IMPORT_MANIFEST_PATH
    import_payload = json.loads(import_path.read_text())
    raw_path = tmp_path / "derived/principles/seed_evidence.json"
    projection_path = SEED_EVIDENCE_PROJECTION_PATH
    import_payload["accepted"] = [
        artifact
        for artifact in import_payload["accepted"]
        if artifact["path"] != projection_path
    ]
    import_payload["accepted"].append(
        EvidenceImportArtifact(
            path=raw_path.relative_to(tmp_path).as_posix(),
            artifact_type="seed",
            sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            evidence_digest=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            schema_version="pipeline.principle_models.seed-v1",
        ).model_dump(mode="json")
    )
    import_payload["accepted"].sort(key=lambda artifact: artifact["path"])
    _write_json(import_path, import_payload)
    _resign_import_manifest(tmp_path, manifest_path)

    with pytest.raises(EvidenceQualificationError, match="normalized Seed projection"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_legacy_projection_without_normalized_claim_type_fails(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    projection_path = tmp_path / SEED_EVIDENCE_PROJECTION_PATH
    legacy_payload = json.loads(
        (tmp_path / "derived/principles/seed_evidence.json").read_text()
    )
    _write_json(projection_path, legacy_payload)
    _refresh_accepted_artifact_digest(
        tmp_path, manifest_path, SEED_EVIDENCE_PROJECTION_PATH
    )

    with pytest.raises(EvidenceQualificationError, match="normalized Seed projection"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_raw_seed_claim_type_is_provenance_only(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    projection_path = tmp_path / SEED_EVIDENCE_PROJECTION_PATH
    projection = json.loads(projection_path.read_text())
    projection["seed_evidence"][0]["provenance"]["raw_evidence_type"] = (
        "unmapped provenance label"
    )
    _write_json(projection_path, projection)
    _refresh_accepted_artifact_digest(
        tmp_path, manifest_path, SEED_EVIDENCE_PROJECTION_PATH
    )

    context = _build_from_environment(
        tmp_path, registry, frozen_path, manifest_path
    )

    seed = context.require("SE-001", "elementary_step_match")
    assert seed.admissible_dimensions == ("elementary_step_match",)


def test_seed_claim_contract_drift_fails_context_build(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    contract_path = tmp_path / _SEED_CONTRACT_PATH
    contract_payload = yaml.safe_load(contract_path.read_text())
    reaction_center_hash = next(
        alias_hash
        for alias_hash, claim_type in contract_payload[
            "raw_type_hash_mapping"
        ].items()
        if claim_type == "reaction_center"
    )
    contract_payload["raw_type_hash_mapping"][reaction_center_hash] = (
        "condition_window"
    )
    contract_path.write_text(yaml.safe_dump(contract_payload, sort_keys=False))

    with pytest.raises(EvidenceQualificationError, match="claim type contract"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_seed_claim_contract_exact_bytes_are_manifest_bound(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    contract_path = tmp_path / _SEED_CONTRACT_PATH
    contract_path.write_text(contract_path.read_text() + "\n")

    with pytest.raises(EvidenceQualificationError, match="claim type contract"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_seed_claim_contract_resolved_path_must_be_canonical(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    contract_path = tmp_path / _SEED_CONTRACT_PATH
    alternate_path = contract_path.with_name("alternate-contract.yaml")
    contract_path.rename(alternate_path)
    contract_path.symlink_to(alternate_path.name)

    with pytest.raises(EvidenceQualificationError, match="must be canonical"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_evaluator_consumes_real_importer_seed_projection(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(
        tmp_path,
        seed_evidence_type="mechanistic control experiments",
    )
    _write_json(
        tmp_path / "derived/full_corpus/queue.json",
        {
            "queue_digest": registry.queue_digest,
            "items": [
                {
                    "source_path": record.source_path,
                    "sha256": record.sha256,
                    "tier": record.tier,
                }
                for record in registry.records
            ],
        },
    )
    _write_json(
        tmp_path / "derived/principles/evidence_registry.json",
        registry.model_dump(mode="json"),
    )
    (tmp_path / SEED_EVIDENCE_PROJECTION_PATH).unlink()
    (tmp_path / _IMPORT_MANIFEST_PATH).unlink()
    assert not (tmp_path / SEED_EVIDENCE_PROJECTION_PATH).exists()
    assert not (tmp_path / _IMPORT_MANIFEST_PATH).exists()

    imported = import_reusable_evidence(
        tmp_path,
        _importer_brief(),
        _importer_policy(tmp_path),
    )
    _rebind_import_manifest_dependency(tmp_path, manifest_path)
    context = _build_from_environment(
        tmp_path, registry, frozen_path, manifest_path
    )
    seed = context.require(
        "SE-001", "elementary_step_match", reviewed_principle=True
    )

    assert SEED_EVIDENCE_PROJECTION_PATH in imported.accepted_paths
    assert seed.provenance_path == SEED_EVIDENCE_PROJECTION_PATH
    assert seed.admissible_dimensions == ("elementary_step_match",)


def test_independently_loaded_identical_rubric_matches_snapshot(
    tmp_path: Path,
):
    context = _build_context(tmp_path)

    evaluation = _score(
        _all_supporting_judgments(),
        context,
        rubric=load_evaluation_rubric(tmp_path / _RUBRIC_PATH),
    )

    assert evaluation.priority_region == "priority_a"


@pytest.mark.parametrize(
    "mutation",
    ("threshold", "core", "critical", "risk", "state_mapping"),
)
def test_changed_rubric_semantics_cannot_reach_scoring(
    context: EvidenceQualificationContext, mutation: str
):
    rubric = _rubric()
    if mutation == "threshold":
        regions = dict(rubric.priority_regions)
        regions["priority_a"] = regions["priority_a"].model_copy(
            update={"min_compatibility": 3.4}
        )
        altered = rubric.model_copy(update={"priority_regions": regions})
    elif mutation == "core":
        altered = rubric.model_copy(
            update={"core_dimensions": tuple(reversed(rubric.core_dimensions))}
        )
    elif mutation == "critical":
        altered = rubric.model_copy(
            update={"critical_dimensions": rubric.critical_dimensions[:-1]}
        )
    elif mutation == "risk":
        altered = rubric.model_copy(update={"risk_direction": "favorable"})
    else:
        altered = rubric.model_copy(
            update={"state_scores": {**rubric.state_scores, "support": 3}}
        )

    with pytest.raises(EvidenceQualificationError, match="rubric.*snapshot"):
        _score(_all_supporting_judgments(), context, rubric=altered)


def test_supportive_condition_effect_cannot_be_recast_as_hard_blocker(
    context: EvidenceQualificationContext,
):
    candidate = HardBlockerCandidate(
        blocker_id="BLOCK-SYNTHETIC-SUPPORTIVE",
        dimension="condition_compatibility",
        statement="A supportive observation is incorrectly presented as blocking",
        evidence_ids=(f"{_NAMESPACE}::EV-supportive-condition",),
        counterevidence_ids=(),
        evidence_level="traceable_external_evidence",
        source_paths=(_SOURCE_PATH,),
    )

    with pytest.raises(HardBlockerError, match="hard blocker"):
        qualify_hard_blockers((candidate,), context)


def test_explicit_incompatible_constraint_can_qualify_blocker(
    context: EvidenceQualificationContext,
):
    candidate = HardBlockerCandidate(
        blocker_id="BLOCK-SYNTHETIC-ADVERSE",
        dimension="condition_compatibility",
        statement="A reviewed incompatible constraint blocks the outcome",
        evidence_ids=(f"{_NAMESPACE}::EV-blocker",),
        counterevidence_ids=(f"{_NAMESPACE}::EV-counter-condition",),
        evidence_level="traceable_external_evidence",
        source_paths=(_SOURCE_PATH,),
    )

    qualified = qualify_hard_blockers((candidate,), context)

    assert qualified[0].reviewed_principle_ids == (_PRINCIPLE_ID,)
    assert qualified[0].counterevidence_ids == candidate.counterevidence_ids


def test_self_declared_reviewed_json_is_not_canonical_freeze(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    _write_json(
        frozen_path,
        {
            "version": "3.0",
            "review_status": "accepted",
            "principles": [{"principle_id": _PRINCIPLE_ID}],
        },
    )

    with pytest.raises(EvidenceQualificationError, match="canonical frozen"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_unbound_evidence_cannot_support_non_unknown_judgment(tmp_path: Path):
    context = _build_context(
        tmp_path, unbound_ids=(_local_id("elementary_step_match"),)
    )

    with pytest.raises(EvidenceQualificationError, match="reviewed Principle"):
        _score(_all_supporting_judgments(), context)


@pytest.mark.parametrize(
    ("reference_kind", "evidence_id"),
    (
        ("seed", "SE-UNKNOWN"),
        ("transfer", "TA-UNKNOWN"),
        ("rejected_v2", "V2-SYNTHETIC-EVIDENCE-ONLY"),
    ),
)
def test_frozen_principle_unknown_or_rejected_reference_fails_builder(
    tmp_path: Path, reference_kind: str, evidence_id: str
):
    environment_kwargs: dict[str, tuple[str, ...]] = {}
    if reference_kind == "seed":
        environment_kwargs["seed_reference_ids"] = (evidence_id,)
    elif reference_kind == "transfer":
        environment_kwargs["transfer_reference_ids"] = (evidence_id,)
    else:
        environment_kwargs["extra_principle_ids"] = (evidence_id,)
    registry, frozen_path, manifest_path = _write_environment(
        tmp_path, **environment_kwargs
    )

    with pytest.raises(EvidenceQualificationError, match="unknown exact evidence ID"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


@pytest.mark.parametrize(
    "artifact_key",
    (
        FROZEN_PRINCIPLES_ARTIFACT_KEY,
        EVIDENCE_IMPORT_MANIFEST_ARTIFACT_KEY,
        FAMILY_EVALUATION_RUBRIC_ARTIFACT_KEY,
    ),
)
@pytest.mark.parametrize("mutation", ("missing", "wrong"))
def test_freeze_manifest_dependency_digest_is_required(
    tmp_path: Path, mutation: str, artifact_key: str
):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    payload = json.loads(manifest_path.read_text())
    if mutation == "missing":
        del payload["artifact_digests"][artifact_key]
    else:
        payload["artifact_digests"][artifact_key] = "0" * 64
    _write_json(manifest_path, payload)

    with pytest.raises(EvidenceQualificationError, match="dependency digest"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_changed_accepted_artifact_bytes_fail_exact_digest(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    (tmp_path / SEED_EVIDENCE_PROJECTION_PATH).write_bytes(
        b'{"seed_evidence": []}'
    )

    with pytest.raises(EvidenceQualificationError, match="artifact digest mismatch"):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_raw_validated_evidence_requires_freeze_manifest_authority(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    payload = json.loads(manifest_path.read_text())
    del payload["artifact_digests"][
        validated_evidence_artifact_key(_PROVENANCE_PATH)
    ]
    _write_json(manifest_path, payload)

    with pytest.raises(
        EvidenceQualificationError, match="validated evidence.*dependency digest"
    ):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


@pytest.mark.parametrize(
    ("mutation", "value"),
    (
        ("reviewer_status", "pending"),
        ("attribution", "model_inference"),
        ("evidence_strength", "inference"),
        ("quotation", "A modified synthetic outcome was recorded."),
        ("locator", 2),
    ),
)
def test_raw_qualification_field_mutation_fails_authoritative_digest(
    tmp_path: Path, mutation: str, value: object
):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    validated_path = tmp_path / _PROVENANCE_PATH
    payload = json.loads(validated_path.read_text())
    item = payload["extraction"]["evidence_items"][0]
    if mutation == "locator":
        item["pdf_page"] = value
    else:
        item[mutation] = value
    _write_json(validated_path, payload)

    with pytest.raises(
        EvidenceQualificationError, match="validated evidence artifact digest mismatch"
    ):
        _build_from_environment(tmp_path, registry, frozen_path, manifest_path)


def test_dependency_replacement_does_not_change_built_snapshot(tmp_path: Path):
    registry, frozen_path, manifest_path = _write_environment(tmp_path)
    context = _build_from_environment(tmp_path, registry, frozen_path, manifest_path)
    before = _score(_all_supporting_judgments(), context)

    frozen_path.write_bytes(b"replaced after snapshot")
    manifest_path.write_bytes(b"replaced after snapshot")
    (tmp_path / _PROVENANCE_PATH).write_bytes(b"replaced after snapshot")
    (tmp_path / _IMPORT_MANIFEST_PATH).write_bytes(b"replaced after snapshot")
    (tmp_path / _RUBRIC_PATH).write_bytes(b"replaced after snapshot")
    (tmp_path / _SEED_CONTRACT_PATH).write_bytes(b"replaced after snapshot")
    for relative_path in (
        "derived/principles/seed_evidence.json",
        SEED_EVIDENCE_PROJECTION_PATH,
        "derived/principles/seed_mechanism.json",
        "derived/principles/seed_principle.json",
        f"derived/principles/normalization/{_NAMESPACE}/validated.json",
        "derived/principles/transfer_assessments.json",
    ):
        (tmp_path / relative_path).write_bytes(b"replaced after snapshot")

    after = _score(_all_supporting_judgments(), context)

    assert after == before
    assert context.freeze_manifest_digest
    assert context.frozen_dependencies


def test_context_rejects_registry_namespace_collision(tmp_path: Path):
    second_sha = "a" * 12 + "b" * 52
    first = _registry().records[0]
    second = EvidenceRegistryRecord(
        source_path="papers/source-beta.pdf",
        sha256=second_sha,
        tier="primary",
        validated_path="derived/full_corpus/papers/source-beta/validated.json",
        cache_key="source-beta-cache",
        evidence_item_count=1,
        contradiction_count=0,
        visual_review_page_count=0,
    )

    with pytest.raises(EvidenceQualificationError, match="namespace collision"):
        _build_from_environment(
            tmp_path,
            _registry(first, second),
            tmp_path / _FROZEN_PATH,
            tmp_path / _MANIFEST_PATH,
        )


def test_context_cannot_be_directly_constructed(
    context: EvidenceQualificationContext,
):
    with pytest.raises(EvidenceQualificationError, match="builder attestation"):
        EvidenceQualificationContext(
            records=context.records,
            content_digest=context.content_digest,
            registry_commitment=context.registry_commitment,
            artifact_commitment=context.artifact_commitment,
            freeze_manifest_digest=context.freeze_manifest_digest,
            evidence_import_manifest_digest=context.evidence_import_manifest_digest,
            rubric_raw_digest=context.rubric_raw_digest,
            rubric_canonical_digest=context.rubric_canonical_digest,
            frozen_dependencies=context.frozen_dependencies,
            frozen_principle_ids=context.frozen_principle_ids,
        )


@pytest.mark.parametrize("tamper", ("model_construct", "model_copy"))
def test_unattested_context_cannot_reach_scoring(
    context: EvidenceQualificationContext, tamper: str
):
    if tamper == "model_construct":
        forged = EvidenceQualificationContext.model_construct(
            records=context.records,
            content_digest=context.content_digest,
            registry_commitment=context.registry_commitment,
            artifact_commitment=context.artifact_commitment,
            freeze_manifest_digest=context.freeze_manifest_digest,
            evidence_import_manifest_digest=context.evidence_import_manifest_digest,
            rubric_raw_digest=context.rubric_raw_digest,
            rubric_canonical_digest=context.rubric_canonical_digest,
            frozen_dependencies=context.frozen_dependencies,
            frozen_principle_ids=context.frozen_principle_ids,
        )
    else:
        forged = context.model_copy(update={"records": tuple(reversed(context.records))})

    with pytest.raises(EvidenceQualificationError, match="builder attestation"):
        _score(_all_supporting_judgments(), forged)


def test_context_is_immutable(context: EvidenceQualificationContext):
    with pytest.raises(ValidationError):
        context.content_digest = "0" * 64  # type: ignore[misc]


def test_formatted_nonexistent_evidence_id_is_rejected(
    context: EvidenceQualificationContext,
):
    candidate = HardBlockerCandidate(
        blocker_id="BLOCK-SYNTHETIC-MISSING",
        dimension="condition_compatibility",
        statement="A formatted but absent synthetic observation",
        evidence_ids=(f"{_NAMESPACE}::EV-NOT-PRESENT",),
        counterevidence_ids=(),
        evidence_level="traceable_external_evidence",
        source_paths=(_SOURCE_PATH,),
    )

    with pytest.raises(HardBlockerError, match="exact evidence ID"):
        qualify_hard_blockers((candidate,), context)


def test_direct_blocker_construction_cannot_bypass_exact_evidence_check(
    context: EvidenceQualificationContext,
):
    blocker = _qualified_blocker(f"{_NAMESPACE}::EV-NOT-PRESENT")

    with pytest.raises(HardBlockerError, match="exact evidence ID"):
        _score(_all_supporting_judgments(), context, (blocker,))


def test_wrong_dimension_evidence_is_rejected(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[0] = _judgment(
        "elementary_step_match",
        evidence_ids=(_evidence_id("target_selectivity"),),
    )

    with pytest.raises(EvidenceQualificationError, match="not admissible"):
        _score(tuple(judgments), context)


def test_missing_context_is_an_explicit_error():
    with pytest.raises(EvidenceQualificationError, match="context is required"):
        score_family(
            _all_supporting_judgments(),
            (),
            _rubric(),
            None,
            family_id="FAMILY-SYNTHETIC-1",
        )


def test_arbitrary_caller_ids_cannot_boost_evidence_confidence(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[-1] = _judgment(
        "evidence_quality",
        evidence_ids=(f"{_NAMESPACE}::EV-CALLER-INJECTED",),
    )

    with pytest.raises(EvidenceQualificationError, match="unknown exact evidence ID"):
        _score(tuple(judgments), context)


def test_model_inference_cannot_establish_evidence_confidence(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[-1] = _judgment(
        "evidence_quality",
        evidence_ids=(f"{_NAMESPACE}::EV-model-quality",),
    )

    with pytest.raises(EvidenceQualificationError, match="traceable external evidence"):
        _score(tuple(judgments), context)


def test_scored_result_converts_to_canonical_family_evaluation(
    context: EvidenceQualificationContext,
):
    scored = _score(_all_supporting_judgments(), context)

    canonical = to_canonical_family_evaluation(scored)

    assert isinstance(canonical, CanonicalFamilyEvaluation)
    assert canonical.family_id == "FAMILY-SYNTHETIC-1"
    assert canonical.judgments == scored.judgments
    assert canonical.qualified_blocker_ids == scored.qualified_blocker_ids
    assert scored.to_canonical() == canonical


def test_scored_result_freezes_qualified_evidence_source_paths(
    context: EvidenceQualificationContext,
):
    scored = _score(_all_supporting_judgments(), context)

    assert scored.evidence_source_paths[
        _evidence_id("elementary_step_match")
    ] == _SOURCE_PATH
    with pytest.raises(TypeError):
        scored.evidence_source_paths["EV-TAMPER"] = "paper/tampered.pdf"  # type: ignore[index]


def test_scored_result_attests_complete_judgment_and_blocker_evidence_identity(
    context: EvidenceQualificationContext,
):
    blocker = _qualified_blocker()
    scored = _score(
        _all_supporting_judgments(), context, blockers=(blocker,)
    )
    referenced_ids = {
        evidence_id
        for judgment in scored.judgments
        for evidence_id in (*judgment.evidence_ids, *judgment.counterevidence_ids)
    }.union(blocker.evidence_ids, blocker.counterevidence_ids)
    context_by_id = {record.evidence_id: record for record in context.records}

    assert scored.priority_region == "excluded"
    assert scored.qualified_blockers == (blocker,)
    assert set(scored.evidence_record_digests) == referenced_ids
    for evidence_id in referenced_ids:
        encoded = json.dumps(
            context_by_id[evidence_id].model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert scored.evidence_record_digests[evidence_id] == hashlib.sha256(
            encoded.encode("utf-8")
        ).hexdigest()
    with pytest.raises(TypeError):
        scored.evidence_record_digests[next(iter(referenced_ids))] = "0" * 64  # type: ignore[index]


def test_context_and_scored_evaluation_preserve_exact_principle_content_links(
    context: EvidenceQualificationContext,
):
    rubric = _rubric()
    scored = _score(_all_supporting_judgments(), context, rubric=rubric)
    evidence_id = _evidence_id("condition_compatibility")

    assert len(context.frozen_principle_digests[_PRINCIPLE_ID]) == 64
    assert scored.reviewed_principle_digests == {
        _PRINCIPLE_ID: context.frozen_principle_digests[_PRINCIPLE_ID]
    }
    assert scored.evidence_principle_links[evidence_id][0].principle_id == (
        _PRINCIPLE_ID
    )
    assert "condition_compatibility" in (
        scored.evidence_principle_links[evidence_id][0].admissible_dimensions
    )
    with pytest.raises(TypeError):
        context.frozen_principle_digests[_PRINCIPLE_ID] = "0" * 64  # type: ignore[index]
    with pytest.raises(TypeError):
        scored.evidence_principle_links[evidence_id] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        scored.dimension_scores["elementary_step_match"] = 0  # type: ignore[index]


def test_wrong_dimension_positive_evidence_cannot_create_principle_link(
    context: EvidenceQualificationContext,
):
    evidence_id = _evidence_id("condition_compatibility")
    record = next(item for item in context.records if item.evidence_id == evidence_id)
    altered = _context_with_record_update(
        context,
        evidence_id,
        admissible_dimensions=tuple(
            sorted((*record.admissible_dimensions, "target_selectivity"))
        ),
    )
    judgments = list(_all_supporting_judgments())
    judgments[DIMENSIONS.index("target_selectivity")] = _judgment(
        "target_selectivity", evidence_ids=(evidence_id,)
    )

    with pytest.raises(EvidenceQualificationError, match="reviewed Principle binding"):
        _score(tuple(judgments), altered)


def test_wrong_dimension_counterevidence_does_not_create_principle_link(
    context: EvidenceQualificationContext,
):
    evidence_id = _evidence_id("condition_compatibility")
    record = next(item for item in context.records if item.evidence_id == evidence_id)
    altered = _context_with_record_update(
        context,
        evidence_id,
        admissible_dimensions=tuple(
            sorted((*record.admissible_dimensions, "target_selectivity"))
        ),
    )
    judgments = list(_all_supporting_judgments())
    judgments[DIMENSIONS.index("target_selectivity")] = _judgment(
        "target_selectivity",
        counterevidence_ids=(evidence_id,),
    )

    scored = _score(tuple(judgments), altered)

    assert any(
        contribution.evidence_id == evidence_id
        and contribution.dimension == "target_selectivity"
        and contribution.is_counterevidence
        for contribution in scored.evidence_contributions
    )
    assert not any(
        link.evidence_id == evidence_id
        and link.dimension == "target_selectivity"
        for link in scored.dimension_principle_links
    )


def test_scored_result_binds_rubric_context_and_content_digest(
    context: EvidenceQualificationContext,
):
    rubric = _rubric()
    scored = _score(_all_supporting_judgments(), context, rubric=rubric)

    assert verify_scored_family_evaluation(scored, rubric) is scored
    assert scored.rubric_digest == evaluation_rubric_digest(rubric)
    assert scored.context_digest == context.content_digest
    assert len(scored.scored_content_digest) == 64


def test_scored_evaluation_cannot_be_directly_constructed(
    context: EvidenceQualificationContext,
):
    scored = _score(_all_supporting_judgments(), context)

    with pytest.raises(EvidenceQualificationError, match="score_family attestation"):
        ScoredFamilyEvaluation(**scored.model_dump(mode="python"))


@pytest.mark.parametrize("tamper", ("model_construct", "model_copy"))
def test_unattested_scored_copy_fails_public_verifier(
    context: EvidenceQualificationContext, tamper: str
):
    rubric = _rubric()
    scored = _score(_all_supporting_judgments(), context, rubric=rubric)
    if tamper == "model_construct":
        forged = ScoredFamilyEvaluation.model_construct(
            **scored.model_dump(mode="python")
        )
    else:
        forged = scored.model_copy(update={"family_id": "FAMILY-TAMPERED"})

    with pytest.raises(EvidenceQualificationError, match="attestation"):
        verify_scored_family_evaluation(forged, rubric)


def test_structurally_valid_rubric_change_fails_scored_verifier(
    context: EvidenceQualificationContext,
):
    rubric = _rubric()
    scored = _score(_all_supporting_judgments(), context, rubric=rubric)
    altered = rubric.model_copy(
        update={"ranking_sample_count": rubric.ranking_sample_count + 1}
    )

    with pytest.raises(EvidenceQualificationError, match="attestation"):
        verify_scored_family_evaluation(scored, altered)


def test_scored_result_freezes_support_and_counterevidence_contributions(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[2] = _judgment(
        "reactive_state_accessibility",
        counterevidence_ids=(f"{_NAMESPACE}::EV-counter-reactive",),
    )

    scored = _score(tuple(judgments), context)
    contributions = tuple(
        contribution
        for contribution in scored.evidence_contributions
        if contribution.dimension == "reactive_state_accessibility"
    )

    assert all(isinstance(item, EvidenceContribution) for item in contributions)
    assert tuple(item.direction for item in contributions) == ("positive", "adverse")
    assert tuple(item.is_counterevidence for item in contributions) == (False, True)
    assert contributions[0].state == "support"
    assert contributions[1].state == "contradiction"
    assert all(item.source_paper == _SOURCE_PATH for item in contributions)
    assert all(item.is_external for item in contributions)


def test_rubric_preregisters_leave_one_out_evidence_aggregation():
    assert _rubric().evidence_aggregation_policy == {
        "positive": "support",
        "conditional": "conditional_support",
        "adverse": "contradiction",
        "mixed": "conditional_support",
        "none": "unknown",
    }


def test_unknown_dimension_is_not_scored_as_zero(
    context: EvidenceQualificationContext,
):
    evaluation = _score(_judgments_with_unknown(), context)

    assert evaluation.dimension_scores["reactive_state_accessibility"] is None
    assert evaluation.uncertainty_burden > 0


def test_qualified_blocker_is_non_compensable_and_reverified(
    context: EvidenceQualificationContext,
):
    evaluation = _score(
        _all_supporting_judgments(), context, (_qualified_blocker(),)
    )

    assert evaluation.priority_region == "excluded"
    assert evaluation.compatibility_index is None
    assert evaluation.reviewed_principle_ids == (_PRINCIPLE_ID,)


@pytest.mark.parametrize("count", (6, 8))
def test_scoring_requires_exactly_seven_unique_judgments(
    context: EvidenceQualificationContext, count: int
):
    judgments = list(_all_supporting_judgments())
    if count == 6:
        judgments.pop()
    else:
        judgments.append(deepcopy(judgments[0]))

    with pytest.raises(ValueError, match="exactly seven"):
        _score(tuple(judgments), context)


def test_non_unknown_judgment_requires_evidence(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[0] = _judgment(judgments[0].dimension, "support", evidence_ids=())

    with pytest.raises(ValueError, match="non-unknown judgment requires evidence"):
        _score(tuple(judgments), context)


def test_model_numeric_score_is_rejected_by_the_structured_contract():
    payload = _judgment("elementary_step_match").model_dump(mode="json")
    payload["score"] = 4

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DimensionJudgment.model_validate(payload)


def test_state_mapping_is_deterministic_and_risk_stays_separate(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[0] = _judgment(judgments[0].dimension, "conditional_support")
    judgments[5] = _judgment(judgments[5].dimension, "support")

    evaluation = _score(tuple(judgments), context)

    assert evaluation.dimension_scores[judgments[0].dimension] == 2
    assert evaluation.dimension_scores["competing_pathway_risk"] == 4
    assert evaluation.failure_risk == 4
    assert evaluation.evidence_confidence == 4
    assert evaluation.compatibility_index == pytest.approx(3.6)


def test_unknown_critical_dimension_forces_unknown_region(
    context: EvidenceQualificationContext,
):
    evaluation = _score(_judgments_with_unknown(), context)

    assert evaluation.critical_unknowns == ("reactive_state_accessibility",)
    assert assign_priority_region(evaluation, _rubric()) == "unknown"
    assert evaluation.priority_region == "unknown"


def test_unknown_noncritical_dimension_does_not_become_failure(
    context: EvidenceQualificationContext,
):
    evaluation = _score(
        _judgments_with_unknown("target_selectivity"), context
    )

    assert evaluation.dimension_scores["target_selectivity"] is None
    assert evaluation.compatibility_index == 4
    assert evaluation.failure_risk == 0
    assert evaluation.priority_region == "priority_b"


def test_judgment_counterevidence_is_preserved_and_qualified(
    context: EvidenceQualificationContext,
):
    judgments = list(_all_supporting_judgments())
    judgments[2] = _judgment(
        judgments[2].dimension,
        counterevidence_ids=(f"{_NAMESPACE}::EV-counter-reactive",),
    )

    evaluation = _score(tuple(judgments), context)

    assert evaluation.judgments[2].counterevidence_ids == (
        f"{_NAMESPACE}::EV-counter-reactive",
    )


def test_rubric_has_no_caller_injected_evidence_ids():
    rubric = _rubric()

    assert not hasattr(rubric, "traceable_external_evidence_ids")
    assert rubric.state_scores == {
        "support": 4,
        "conditional_support": 2,
        "contradiction": 0,
        "unknown": None,
    }
    assert set(rubric.priority_regions) == {
        "priority_a",
        "priority_b",
        "priority_c",
        "boundary",
        "excluded",
        "unknown",
    }

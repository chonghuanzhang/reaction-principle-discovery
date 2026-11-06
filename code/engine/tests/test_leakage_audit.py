import base64
import hashlib
import tomllib
from pathlib import Path

import pytest

from pipeline.leakage_audit import (
    LeakageAuditError,
    LeakagePolicy,
    QueryInput,
    _verified_distribution_manifest,
    assert_clean,
    audit_paths,
    build_structure_fingerprint_factory,
    derive_structure_fingerprint,
    derive_structure_fingerprint_receipt,
    verify_structure_fingerprint_factory,
)


def _manifest_policy(tmp_path: Path, paths: tuple[Path, ...], *, queries: tuple[QueryInput, ...] = ()) -> LeakagePolicy:
    manifest = tmp_path / "run-manifest.json"
    manifest.write_text(
        __import__("json").dumps(
            {
                "dependency_paths": [path.name for path in paths],
                "query_ids": [query.query_id for query in queries],
            }
        ),
        encoding="utf-8",
    )
    return LeakagePolicy(
        policy_id="synthetic-policy",
        sealed_terms=("SEALED_TERM_A",),
        sealed_fingerprints=("SEALED_FINGERPRINT",),
        run_manifest_path=manifest,
        query_inputs=queries,
    )


def test_leakage_audit_reports_term_and_structure_hits(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("SEALED_TERM_A and SEALED_FINGERPRINT", encoding="utf-8")

    audit = audit_paths([path], _manifest_policy(tmp_path, (path,)))

    assert {hit.kind for hit in audit.hits} == {"term", "fingerprint"}


def test_public_audit_report_redacts_sealed_text(tmp_path):
    path = tmp_path / "SEALED_TERM_A-prompt.txt"
    path.write_text("SEALED_TERM_A", encoding="utf-8")

    audit = audit_paths([path], _manifest_policy(tmp_path, (path,)))
    dumped = audit.model_dump_json()

    assert "SEALED_TERM_A" not in dumped
    assert "SEALED_FINGERPRINT" not in dumped
    assert any(hit.redacted_digest and hit.line == 1 for hit in audit.hits)


def test_structured_artifact_hit_uses_a_json_pointer(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text('{"input":{"label":"SEALED_TERM_A"}}', encoding="utf-8")

    audit = audit_paths([path], _manifest_policy(tmp_path, (path,)))

    assert audit.hits[0].pointer_digest
    assert audit.hits[0].line is None
    assert "SEALED_TERM_A" not in audit.model_dump_json()


def test_json_key_leakage_is_redacted_from_pointer_and_audit_output(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text('{"SEALED_TERM_A":"public"}', encoding="utf-8")

    audit = audit_paths([path], _manifest_policy(tmp_path, (path,)))

    assert audit.hits[0].pointer_digest
    assert "SEALED_TERM_A" not in audit.model_dump_json()


def test_structure_enabled_policy_requires_injected_canonicalizer(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text('{"structure":"FIXTURE_STRUCTURE_A"}', encoding="utf-8")
    policy = _manifest_policy(tmp_path, (path,)).model_copy(
        update={
            "canonical_structure_hashes": ("a" * 64,),
            "structure_field_names": ("structure",),
        }
    )

    with pytest.raises(LeakageAuditError, match="fingerprint factory"):
        audit_paths([path], policy)


def test_equivalent_structures_share_canonical_fingerprint_without_leaking_forms(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"structure":"CCO"}', encoding="utf-8")
    second.write_text('{"structure":"OCC"}', encoding="utf-8")

    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-equivalent-structure-factory",
        receipt_key=b"synthetic-equivalent-structure-key",
    )
    canonical_hash = derive_structure_fingerprint(factory, "CCO")
    assert canonical_hash == derive_structure_fingerprint(factory, "OCC")

    policy = _manifest_policy(tmp_path, (first, second)).model_copy(
        update={
            "canonical_structure_hashes": (canonical_hash,),
            "structure_field_names": ("structure",),
            "structure_fingerprint_factory": factory,
            "structure_factory_id": factory.factory_id,
            "structure_canonicalizer_id": factory.canonicalizer_id,
            "structure_canonicalizer_spec": factory.canonicalizer_spec,
            "structure_canonicalizer_version": factory.canonicalizer_version,
            "structure_engine_version": factory.engine_version,
            "structure_dependency_identity": factory.dependency_identity,
            "structure_canonicalization_parameter_digest": factory.canonicalization_parameter_digest,
            "structure_factory_implementation_digest": factory.implementation_digest,
            "structure_factory_key_commitment": factory.key_commitment,
        }
    )

    audit = audit_paths([first, second], policy)

    assert {hit.kind for hit in audit.hits} == {"fingerprint"}
    assert len(audit.hits) == 2
    serialized = audit.model_dump_json()
    assert "CCO" not in serialized
    assert "OCC" not in serialized
    assert canonical_hash not in serialized


def test_mutable_global_canonicalizer_is_not_a_supported_factory():
    mutable_dependency = {"prefix": "first"}

    def stateful_canonicalizer(value: str) -> str:
        return f"{mutable_dependency['prefix']}::{value}"

    with pytest.raises(ValueError, match="unsupported.*canonicalizer|fixed.*canonicalizer"):
        build_structure_fingerprint_factory(
            factory_id="synthetic-stateful-factory",
            canonicalizer_id="synthetic-stateful-canonicalizer",
            canonicalizer=stateful_canonicalizer,
            receipt_key=b"synthetic-stateful-key",
        )


def test_audit_and_receipt_use_one_shared_chemical_fingerprint_derivation(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text('{"structure":"CCO"}', encoding="utf-8")
    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-fixed-structure-factory",
        receipt_key=b"synthetic-fixed-structure-key",
    )
    receipt = derive_structure_fingerprint_receipt(
        factory, "SYNTHETIC-SUBJECT", "CCO"
    )
    assert receipt.fingerprint == derive_structure_fingerprint(factory, "CCO")
    policy = _manifest_policy(tmp_path, (path,)).model_copy(
        update={
            "canonical_structure_hashes": (receipt.fingerprint,),
            "structure_field_names": ("structure",),
            "structure_fingerprint_factory": factory,
            "structure_factory_id": factory.factory_id,
            "structure_canonicalizer_id": factory.canonicalizer_id,
            "structure_canonicalizer_spec": factory.canonicalizer_spec,
            "structure_canonicalizer_version": factory.canonicalizer_version,
            "structure_engine_version": factory.engine_version,
            "structure_dependency_identity": factory.dependency_identity,
            "structure_canonicalization_parameter_digest": factory.canonicalization_parameter_digest,
            "structure_factory_implementation_digest": factory.implementation_digest,
            "structure_factory_key_commitment": factory.key_commitment,
        }
    )

    audit = audit_paths([path], policy)

    assert [hit.kind for hit in audit.hits] == ["fingerprint"]


def test_aromatic_and_aliphatic_structures_remain_distinct():
    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-distinction-factory",
        receipt_key=b"synthetic-distinction-key",
    )

    aromatic = derive_structure_fingerprint(factory, "c1ccccc1")
    aliphatic = derive_structure_fingerprint(factory, "C1CCCCC1")

    assert aromatic != aliphatic


def test_invalid_structure_fails_closed():
    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-invalid-factory",
        receipt_key=b"synthetic-invalid-key",
    )

    with pytest.raises(ValueError, match="invalid|unsupported"):
        derive_structure_fingerprint(factory, "not-a-supported-structure")


def test_invalid_structure_never_reaches_rdkit_parse_logs(capfd):
    sentinel = "SEALED_STRUCTURE_SENTINEL_7F4A"
    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-no-log-factory",
        receipt_key=b"synthetic-no-log-key",
    )

    with pytest.raises(ValueError, match="invalid|unsupported"):
        derive_structure_fingerprint(factory, sentinel)

    captured = capfd.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err


def test_atom_maps_do_not_change_canonical_molecular_identity():
    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-atom-map-factory",
        receipt_key=b"synthetic-atom-map-key",
    )

    unmapped = derive_structure_fingerprint(factory, "CCO")
    mapped = derive_structure_fingerprint(factory, "[CH3:1][CH2:2][OH:3]")
    renumbered = derive_structure_fingerprint(factory, "[CH3:9][CH2:7][OH:4]")

    assert mapped == unmapped == renumbered


def test_distribution_manifest_rejects_tampered_file_or_record(tmp_path):
    package_file = tmp_path / "rdkit" / "Chem" / "rdmolfiles.so"
    package_file.parent.mkdir(parents=True)
    package_file.write_bytes(b"synthetic-native-module")
    record = tmp_path / "rdkit-2025.9.6.dist-info" / "RECORD"
    record.parent.mkdir()

    def write_record(digest: bytes) -> None:
        encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        record.write_text(
            "rdkit/Chem/rdmolfiles.so,sha256="
            f"{encoded},{package_file.stat().st_size}\n"
            "rdkit-2025.9.6.dist-info/RECORD,,\n",
            encoding="utf-8",
        )

    write_record(hashlib.sha256(package_file.read_bytes()).digest())
    manifest = _verified_distribution_manifest(tmp_path, record)
    assert any(row[0] == "rdkit/Chem/rdmolfiles.so" for row in manifest)

    package_file.write_bytes(b"tampered-native-module")
    with pytest.raises(ValueError, match="distribution artifact hash mismatch"):
        _verified_distribution_manifest(tmp_path, record)

    write_record(hashlib.sha256(b"different-declared-content").digest())
    with pytest.raises(ValueError, match="distribution artifact hash mismatch"):
        _verified_distribution_manifest(tmp_path, record)


def test_runtime_chemistry_engine_identity_mismatch_fails_closed():
    factory = build_structure_fingerprint_factory(
        factory_id="synthetic-engine-identity-factory",
        receipt_key=b"synthetic-engine-identity-key",
    )
    substituted = factory.model_copy(update={"engine_version": "0.0.0"})

    with pytest.raises(ValueError, match="factory attestation|engine identity"):
        verify_structure_fingerprint_factory(substituted)


def test_chemistry_engine_dependency_is_exactly_pinned():
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "rdkit==2025.9.6" in pyproject["project"]["dependencies"]


def test_policy_without_structure_scanning_needs_no_canonicalizer(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("SEALED_TERM_A", encoding="utf-8")

    audit = audit_paths([path], _manifest_policy(tmp_path, (path,)))

    assert {hit.kind for hit in audit.hits} == {"term"}


def test_query_input_is_audited_and_never_serialized(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("public", encoding="utf-8")
    query = QueryInput(query_id="query-1", text="find SEALED_TERM_A")

    audit = audit_paths([path], _manifest_policy(tmp_path, (path,), queries=(query,)))

    assert {hit.kind for hit in audit.hits} == {"query"}
    assert "SEALED_TERM_A" not in audit.model_dump_json()
    assert query.text not in audit.model_dump_json()


def test_audit_rejects_unrecorded_query_text(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("public", encoding="utf-8")
    query = QueryInput(query_id="unrecorded-query", text="SEALED_TERM_A")

    with pytest.raises(LeakageAuditError, match="query inputs"):
        audit_paths([path], _manifest_policy(tmp_path, (path,), queries=()).model_copy(
            update={"query_inputs": (query,)}
        ))


def test_run_manifest_declares_the_only_dependency_closure(tmp_path):
    recorded = tmp_path / "recorded.txt"
    unrecorded = tmp_path / "unrecorded.txt"
    manifest = tmp_path / "run-manifest.json"
    recorded.write_text("public", encoding="utf-8")
    unrecorded.write_text("public", encoding="utf-8")
    manifest.write_text(
        '{"dependency_paths":["recorded.txt"],"query_ids":[]}', encoding="utf-8"
    )
    policy = LeakagePolicy(
        policy_id="synthetic-policy",
        sealed_terms=("SEALED_TERM_A",),
        sealed_fingerprints=("SEALED_FINGERPRINT",),
        run_manifest_path=manifest,
    )

    with pytest.raises(LeakageAuditError, match="declared dependency closure"):
        audit_paths([recorded, unrecorded], policy)


def test_audit_rejects_a_path_outside_declared_dependency_closure(tmp_path):
    recorded = tmp_path / "recorded.txt"
    unrecorded = tmp_path / "unrecorded.txt"
    recorded.write_text("public", encoding="utf-8")
    unrecorded.write_text("public", encoding="utf-8")
    policy = _manifest_policy(tmp_path, (recorded,))

    with pytest.raises(LeakageAuditError, match="declared dependency closure"):
        audit_paths([recorded, unrecorded], policy)


def test_audit_fails_closed_for_unreadable_dependency(tmp_path):
    missing = tmp_path / "missing.txt"
    manifest = tmp_path / "run-manifest.json"
    manifest.write_text('{"dependency_paths":["missing.txt"],"query_ids":[]}', encoding="utf-8")

    with pytest.raises(LeakageAuditError, match="unreadable dependency"):
        audit_paths([missing], LeakagePolicy(policy_id="synthetic-policy", run_manifest_path=manifest))


def test_audit_rejects_missing_manifest_empty_closure_and_omitted_dependency(tmp_path):
    path = tmp_path / "prompt.txt"
    second = tmp_path / "other.txt"
    path.write_text("public", encoding="utf-8")
    second.write_text("public", encoding="utf-8")

    with pytest.raises(LeakageAuditError, match="run manifest"):
        audit_paths([path], LeakagePolicy(policy_id="synthetic-policy"))
    with pytest.raises(LeakageAuditError, match="empty"):
        audit_paths([], _manifest_policy(tmp_path, ()))
    with pytest.raises(LeakageAuditError, match="declared dependency closure"):
        audit_paths([path], _manifest_policy(tmp_path, (path, second)))


def test_assert_clean_rejects_redacted_hits(tmp_path):
    path = tmp_path / "prompt.txt"
    path.write_text("SEALED_TERM_A", encoding="utf-8")

    with pytest.raises(LeakageAuditError, match="leakage audit failed"):
        assert_clean(audit_paths([path], _manifest_policy(tmp_path, (path,))))

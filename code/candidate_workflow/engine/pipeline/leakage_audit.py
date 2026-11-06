"""Fail-closed scanning for sealed outcome leakage in active v3 dependencies."""

from __future__ import annotations

import _hashlib
import base64
import csv
import hashlib
import hmac
import importlib.metadata
import io
import json
import sys
import unicodedata
import weakref
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ConfigDict, Field, model_validator
from rdkit import Chem, rdBase
from rdkit.Chem import rdmolfiles

from pipeline.principle_models import FrozenStrictModel


class LeakageAuditError(RuntimeError):
    """Raised when the dependency closure is unsafe or leakage is found."""


class QueryInput(FrozenStrictModel):
    """A recorded query string that must be inspected without being reported."""

    query_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    origin_type: str = "legacy"
    origin_ids: tuple[str, ...] = ()
    candidate_family_terms: tuple[str, ...] = ()
    generation_basis: str = "legacy"


_STRUCTURE_FACTORY_TOKEN = object()
_STRUCTURE_CANONICALIZER_SPEC = "rdkit_canonical_isomeric_smiles"
_STRUCTURE_CANONICALIZER_VERSION = "2"
_STRUCTURE_CANONICALIZER_ID = (
    f"{_STRUCTURE_CANONICALIZER_SPEC}@{_STRUCTURE_CANONICALIZER_VERSION}"
)


def _artifact_digest(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ValueError(
            f"supported canonicalizer artifact is unreadable: {path.name}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


_IMPLEMENTATION_ARTIFACT_PATH = Path(__file__).resolve()
_IMPLEMENTATION_ARTIFACT_DIGEST = _artifact_digest(_IMPLEMENTATION_ARTIFACT_PATH)
_RDKIT_DISTRIBUTION = importlib.metadata.distribution("rdkit")
_RDKIT_ENGINE_VERSION = rdBase.rdkitVersion
_RDKIT_DISTRIBUTION_VERSION = _RDKIT_DISTRIBUTION.version
_SUPPORTED_RDKIT_VERSION = "2025.9.6"

if (
    _RDKIT_DISTRIBUTION_VERSION != _SUPPORTED_RDKIT_VERSION
    or _RDKIT_ENGINE_VERSION != "2025.09.6"
):
    raise RuntimeError("unsupported chemistry engine version")


def _distribution_record_path() -> Path:
    matches = tuple(
        path
        for item in (_RDKIT_DISTRIBUTION.files or ())
        if item.name == "RECORD" and ".dist-info" in str(item)
        for path in (Path(_RDKIT_DISTRIBUTION.locate_file(item)).resolve(),)
    )
    if len(matches) != 1:
        raise ValueError("supported chemistry engine package RECORD is unavailable")
    return matches[0]


def _verified_distribution_manifest(
    distribution_root: Path,
    record_path: Path,
) -> tuple[tuple[str, str, int], ...]:
    """Verify every RECORD entry and bind even generated unhashed files."""

    root = distribution_root.resolve()
    record = record_path.resolve()
    try:
        record_bytes = record.read_bytes()
        rows = tuple(csv.reader(io.StringIO(record_bytes.decode("utf-8"))))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("supported chemistry engine RECORD is unreadable") from exc
    if not rows or any(len(row) != 3 or not row[0] for row in rows):
        raise ValueError("supported chemistry engine RECORD is malformed")
    relative_paths = tuple(row[0] for row in rows)
    if len(relative_paths) != len(set(relative_paths)):
        raise ValueError("supported chemistry engine RECORD has duplicate paths")

    manifest: list[tuple[str, str, int]] = []
    for relative, declared_hash, declared_size in rows:
        artifact = (root / relative).resolve()
        try:
            artifact.relative_to(root)
            content = artifact.read_bytes()
        except (OSError, ValueError) as exc:
            raise ValueError(
                "supported chemistry engine distribution artifact is unavailable"
            ) from exc
        digest = hashlib.sha256(content).digest()
        if declared_hash:
            try:
                algorithm, encoded = declared_hash.split("=", 1)
            except ValueError as exc:
                raise ValueError(
                    "supported chemistry engine RECORD hash is malformed"
                ) from exc
            actual_encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode(
                "ascii"
            )
            if algorithm != "sha256" or not hmac.compare_digest(
                encoded, actual_encoded
            ):
                raise ValueError("distribution artifact hash mismatch")
        if declared_size:
            try:
                expected_size = int(declared_size)
            except ValueError as exc:
                raise ValueError(
                    "supported chemistry engine RECORD size is malformed"
                ) from exc
            if expected_size != len(content):
                raise ValueError("distribution artifact size mismatch")
        manifest.append((relative, digest.hex(), len(content)))
    return tuple(sorted(manifest))


_RDKIT_RECORD_PATH = _distribution_record_path()
_RDKIT_RECORD_DIGEST = _artifact_digest(_RDKIT_RECORD_PATH)
_RDKIT_DISTRIBUTION_ROOT = _RDKIT_RECORD_PATH.parent.parent.resolve()
_RDKIT_INSTALLATION_MANIFEST = _verified_distribution_manifest(
    _RDKIT_DISTRIBUTION_ROOT,
    _RDKIT_RECORD_PATH,
)
_RDKIT_INSTALLATION_DIGEST = hashlib.sha256(
    json.dumps(
        _RDKIT_INSTALLATION_MANIFEST,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
if tuple(sorted(str(item) for item in (_RDKIT_DISTRIBUTION.files or ()))) != tuple(
    item[0] for item in _RDKIT_INSTALLATION_MANIFEST
):
    raise RuntimeError("supported chemistry engine distribution manifest mismatch")
_RDBASE_ARTIFACT_PATH = Path(rdBase.__file__).resolve()
_RDBASE_ARTIFACT_DIGEST = _artifact_digest(_RDBASE_ARTIFACT_PATH)
_RDCHEM_ARTIFACT_PATH = Path(Chem.rdchem.__file__).resolve()
_RDCHEM_ARTIFACT_DIGEST = _artifact_digest(_RDCHEM_ARTIFACT_PATH)
_RDMOLFILES_ARTIFACT_PATH = Path(rdmolfiles.__file__).resolve()
_RDMOLFILES_ARTIFACT_DIGEST = _artifact_digest(_RDMOLFILES_ARTIFACT_PATH)
_INTERPRETER_ARTIFACT_PATH = Path(sys.executable).resolve()
_INTERPRETER_ARTIFACT_DIGEST = _artifact_digest(_INTERPRETER_ARTIFACT_PATH)
_HASHLIB_ARTIFACT_PATH = Path(
    getattr(_hashlib, "__file__", sys.executable)
).resolve()
_HASHLIB_ARTIFACT_DIGEST = _artifact_digest(_HASHLIB_ARTIFACT_PATH)
_STRUCTURE_DEPENDENCY_IDENTITY = hashlib.sha256(
    json.dumps(
        {
            "distribution": "rdkit",
            "distribution_version": _RDKIT_DISTRIBUTION_VERSION,
            "distribution_record_digest": _RDKIT_RECORD_DIGEST,
            "installed_distribution_digest": _RDKIT_INSTALLATION_DIGEST,
            "hashlib_artifact_digest": _HASHLIB_ARTIFACT_DIGEST,
            "interpreter_artifact_digest": _INTERPRETER_ARTIFACT_DIGEST,
            "rdBase_artifact_digest": _RDBASE_ARTIFACT_DIGEST,
            "rdchem_artifact_digest": _RDCHEM_ARTIFACT_DIGEST,
            "rdmolfiles_artifact_digest": _RDMOLFILES_ARTIFACT_DIGEST,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
_STRUCTURE_CANONICALIZATION_PARAMETERS = {
    "allBondsExplicit": False,
    "allHsExplicit": False,
    "atomMapPolicy": "clear_all_atom_map_numbers_before_serialization",
    "canonical": True,
    "doRandom": False,
    "isomericSmiles": True,
    "kekuleSmiles": False,
    "rootedAtAtom": -1,
    "sanitize": True,
}
_STRUCTURE_CANONICALIZATION_PARAMETER_DIGEST = hashlib.sha256(
    json.dumps(
        _STRUCTURE_CANONICALIZATION_PARAMETERS,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
_STRUCTURE_BINDING_VECTORS = (
    ("CCO", "CCO"),
    ("OCC", "CCO"),
    ("[CH3:1][CH2:2][OH:3]", "CCO"),
    ("[CH3:9][CH2:7][OH:4]", "CCO"),
    ("c1ccccc1", "c1ccccc1"),
    ("C1CCCCC1", "C1CCCCC1"),
)
_STRUCTURE_INVALID_BINDING_VECTORS = ("not-a-supported-structure",)


def _canonicalize_structure_v1(
    value: str,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid or unsupported chemical structure")
    with rdBase.BlockLogs():
        molecule = rdmolfiles.MolFromSmiles(value, sanitize=True)
    if molecule is None:
        raise ValueError("invalid or unsupported chemical structure")
    for atom in molecule.GetAtoms():
        atom.SetAtomMapNum(0)
    try:
        canonical = rdmolfiles.MolToSmiles(
            molecule,
            canonical=True,
            isomericSmiles=True,
            kekuleSmiles=False,
            allBondsExplicit=False,
            allHsExplicit=False,
            doRandom=False,
            rootedAtAtom=-1,
        )
    except (RuntimeError, ValueError) as exc:
        raise ValueError("invalid or unsupported chemical structure") from exc
    if not canonical:
        raise ValueError("invalid or unsupported chemical structure")
    return canonical


_SUPPORTED_CANONICALIZER_CODE = _canonicalize_structure_v1.__code__
_SUPPORTED_MOL_FROM_SMILES = rdmolfiles.MolFromSmiles
_SUPPORTED_MOL_TO_SMILES = rdmolfiles.MolToSmiles


def _verify_structure_binding_vectors(*, verify_distribution: bool = False) -> None:
    if verify_distribution and _verified_distribution_manifest(
        _RDKIT_DISTRIBUTION_ROOT,
        _RDKIT_RECORD_PATH,
    ) != _RDKIT_INSTALLATION_MANIFEST:
        raise ValueError("supported chemistry engine distribution changed")
    if (
        _artifact_digest(_IMPLEMENTATION_ARTIFACT_PATH)
        != _IMPLEMENTATION_ARTIFACT_DIGEST
        or rdBase.rdkitVersion != _RDKIT_ENGINE_VERSION
        or importlib.metadata.version("rdkit") != _RDKIT_DISTRIBUTION_VERSION
        or _artifact_digest(_RDKIT_RECORD_PATH) != _RDKIT_RECORD_DIGEST
        or _artifact_digest(_RDBASE_ARTIFACT_PATH) != _RDBASE_ARTIFACT_DIGEST
        or _artifact_digest(_RDCHEM_ARTIFACT_PATH) != _RDCHEM_ARTIFACT_DIGEST
        or _artifact_digest(_RDMOLFILES_ARTIFACT_PATH)
        != _RDMOLFILES_ARTIFACT_DIGEST
        or Path(sys.executable).resolve() != _INTERPRETER_ARTIFACT_PATH
        or _artifact_digest(_INTERPRETER_ARTIFACT_PATH)
        != _INTERPRETER_ARTIFACT_DIGEST
        or Path(getattr(_hashlib, "__file__", sys.executable)).resolve()
        != _HASHLIB_ARTIFACT_PATH
        or _artifact_digest(_HASHLIB_ARTIFACT_PATH) != _HASHLIB_ARTIFACT_DIGEST
        or _canonicalize_structure_v1.__code__
        is not _SUPPORTED_CANONICALIZER_CODE
        or rdmolfiles.MolFromSmiles is not _SUPPORTED_MOL_FROM_SMILES
        or rdmolfiles.MolToSmiles is not _SUPPORTED_MOL_TO_SMILES
        or any(
            _canonicalize_structure_v1(source) != expected
            for source, expected in _STRUCTURE_BINDING_VECTORS
        )
    ):
        raise ValueError("supported structure canonicalizer binding vectors failed")
    for source in _STRUCTURE_INVALID_BINDING_VECTORS:
        try:
            _canonicalize_structure_v1(source)
        except ValueError:
            continue
        raise ValueError("supported structure canonicalizer binding vectors failed")


def _supported_implementation_digest() -> str:
    payload = {
        "spec": _STRUCTURE_CANONICALIZER_SPEC,
        "version": _STRUCTURE_CANONICALIZER_VERSION,
        "engine_version": _RDKIT_ENGINE_VERSION,
        "dependency_identity": _STRUCTURE_DEPENDENCY_IDENTITY,
        "canonicalization_parameter_digest": (
            _STRUCTURE_CANONICALIZATION_PARAMETER_DIGEST
        ),
        "implementation_artifact_digest": _IMPLEMENTATION_ARTIFACT_DIGEST,
        "binding_vectors": _STRUCTURE_BINDING_VECTORS,
        "invalid_binding_vectors": _STRUCTURE_INVALID_BINDING_VECTORS,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


_STRUCTURE_FACTORY_ATTESTATIONS: dict[
    int,
    tuple[
        weakref.ReferenceType[object],
        tuple[str, ...],
        bytes,
    ],
] = {}


class StructureFingerprintFactory(FrozenStrictModel):
    """Attested fixed canonicalizer specification and receipt signer."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    factory_id: str = Field(min_length=1)
    canonicalizer_id: str = Field(min_length=1)
    canonicalizer_spec: str = Field(min_length=1)
    canonicalizer_version: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    dependency_identity: str = Field(min_length=1)
    canonicalization_parameter_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_key: bytes = Field(exclude=True, repr=False)

    def __init__(self, **data: Any) -> None:
        token = data.pop("_builder_token", None)
        if token is not _STRUCTURE_FACTORY_TOKEN:
            raise ValueError(
                "StructureFingerprintFactory requires factory attestation"
            )
        super().__init__(**data)


class StructureFingerprintReceipt(FrozenStrictModel):
    factory_id: str = Field(min_length=1)
    canonicalizer_id: str = Field(min_length=1)
    canonicalizer_spec: str = Field(min_length=1)
    canonicalizer_version: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    dependency_identity: str = Field(min_length=1)
    canonicalization_parameter_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    implementation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_commitment: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_structure_fingerprint_factory(
    *,
    factory_id: str,
    receipt_key: bytes,
    canonicalizer_id: str | None = None,
    canonicalizer: Callable[[str], str] | None = None,
) -> StructureFingerprintFactory:
    """Build the one supported fixed-spec canonicalizer and receipt signer."""

    if not receipt_key:
        raise ValueError("structure fingerprint factory requires a receipt key")
    if canonicalizer is not None:
        raise ValueError(
            "unsupported arbitrary canonicalizer; use the fixed supported canonicalizer"
        )
    if canonicalizer_id not in {None, _STRUCTURE_CANONICALIZER_ID}:
        raise ValueError("unsupported structure canonicalizer specification")
    _verify_structure_binding_vectors(verify_distribution=True)
    factory = StructureFingerprintFactory(
        _builder_token=_STRUCTURE_FACTORY_TOKEN,
        factory_id=factory_id,
        canonicalizer_id=_STRUCTURE_CANONICALIZER_ID,
        canonicalizer_spec=_STRUCTURE_CANONICALIZER_SPEC,
        canonicalizer_version=_STRUCTURE_CANONICALIZER_VERSION,
        engine_version=_RDKIT_ENGINE_VERSION,
        dependency_identity=_STRUCTURE_DEPENDENCY_IDENTITY,
        canonicalization_parameter_digest=(
            _STRUCTURE_CANONICALIZATION_PARAMETER_DIGEST
        ),
        implementation_digest=_supported_implementation_digest(),
        key_commitment=hashlib.sha256(receipt_key).hexdigest(),
        receipt_key=receipt_key,
    )
    factory_identity = id(factory)

    def discard(_: weakref.ReferenceType[object]) -> None:
        _STRUCTURE_FACTORY_ATTESTATIONS.pop(factory_identity, None)

    _STRUCTURE_FACTORY_ATTESTATIONS[factory_identity] = (
        weakref.ref(factory, discard),
        _structure_factory_identity(factory),
        factory.receipt_key,
    )
    return factory


def verify_structure_fingerprint_factory(
    factory: StructureFingerprintFactory,
) -> StructureFingerprintFactory:
    attestation = _STRUCTURE_FACTORY_ATTESTATIONS.get(id(factory))
    _verify_structure_binding_vectors()
    if (
        type(factory) is not StructureFingerprintFactory
        or attestation is None
        or attestation[0]() is not factory
        or attestation[1] != _structure_factory_identity(factory)
        or attestation[2] != factory.receipt_key
        or factory.canonicalizer_id != _STRUCTURE_CANONICALIZER_ID
        or factory.canonicalizer_spec != _STRUCTURE_CANONICALIZER_SPEC
        or factory.canonicalizer_version != _STRUCTURE_CANONICALIZER_VERSION
        or factory.engine_version != _RDKIT_ENGINE_VERSION
        or factory.dependency_identity != _STRUCTURE_DEPENDENCY_IDENTITY
        or factory.canonicalization_parameter_digest
        != _STRUCTURE_CANONICALIZATION_PARAMETER_DIGEST
        or factory.implementation_digest != _supported_implementation_digest()
        or hashlib.sha256(factory.receipt_key).hexdigest() != factory.key_commitment
    ):
        raise ValueError("structure fingerprint factory attestation failed")
    return factory


def _structure_factory_identity(
    factory: StructureFingerprintFactory,
) -> tuple[str, ...]:
    return (
        factory.factory_id,
        factory.canonicalizer_id,
        factory.canonicalizer_spec,
        factory.canonicalizer_version,
        factory.engine_version,
        factory.dependency_identity,
        factory.canonicalization_parameter_digest,
        factory.implementation_digest,
        factory.key_commitment,
    )


def derive_structure_fingerprint(
    factory: StructureFingerprintFactory,
    structure_input: str,
) -> str:
    """Derive one canonical fingerprint through the supported shared path."""

    verify_structure_fingerprint_factory(factory)
    canonical = _canonicalize_structure_v1(structure_input)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_signature(
    factory: StructureFingerprintFactory, subject_id: str, fingerprint: str
) -> str:
    payload = "\0".join(
        (
            subject_id,
            factory.factory_id,
            factory.canonicalizer_id,
            factory.canonicalizer_spec,
            factory.canonicalizer_version,
            factory.engine_version,
            factory.dependency_identity,
            factory.canonicalization_parameter_digest,
            factory.implementation_digest,
            factory.key_commitment,
            fingerprint,
        )
    ).encode("utf-8")
    return hmac.new(factory.receipt_key, payload, hashlib.sha256).hexdigest()


def derive_structure_fingerprint_receipt(
    factory: StructureFingerprintFactory,
    subject_id: str,
    structure_input: str,
) -> StructureFingerprintReceipt:
    """Derive one fingerprint and signed receipt without retaining plaintext."""

    fingerprint = derive_structure_fingerprint(factory, structure_input)
    return StructureFingerprintReceipt(
        factory_id=factory.factory_id,
        canonicalizer_id=factory.canonicalizer_id,
        canonicalizer_spec=factory.canonicalizer_spec,
        canonicalizer_version=factory.canonicalizer_version,
        engine_version=factory.engine_version,
        dependency_identity=factory.dependency_identity,
        canonicalization_parameter_digest=(
            factory.canonicalization_parameter_digest
        ),
        implementation_digest=factory.implementation_digest,
        key_commitment=factory.key_commitment,
        fingerprint=fingerprint,
        signature=_receipt_signature(factory, subject_id, fingerprint),
    )


def verify_structure_fingerprint_receipt(
    factory: StructureFingerprintFactory,
    subject_id: str,
    receipt: StructureFingerprintReceipt,
) -> StructureFingerprintReceipt:
    verify_structure_fingerprint_factory(factory)
    if (
        receipt.factory_id != factory.factory_id
        or receipt.canonicalizer_id != factory.canonicalizer_id
        or receipt.canonicalizer_spec != factory.canonicalizer_spec
        or receipt.canonicalizer_version != factory.canonicalizer_version
        or receipt.engine_version != factory.engine_version
        or receipt.dependency_identity != factory.dependency_identity
        or receipt.canonicalization_parameter_digest
        != factory.canonicalization_parameter_digest
        or receipt.implementation_digest != factory.implementation_digest
        or receipt.key_commitment != factory.key_commitment
        or not hmac.compare_digest(
            receipt.signature,
            _receipt_signature(factory, subject_id, receipt.fingerprint),
        )
    ):
        raise ValueError("structure fingerprint receipt verification failed")
    return receipt


class LeakagePolicy(FrozenStrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    policy_id: str = Field(min_length=1)
    sealed_terms: tuple[str, ...] = ()
    sealed_fingerprints: tuple[str, ...] = ()
    canonical_structure_hashes: tuple[str, ...] = ()
    run_manifest_path: Path | None = None
    declared_dependency_paths: tuple[Path, ...] = ()
    query_inputs: tuple[QueryInput, ...] = ()
    structure_field_names: tuple[str, ...] = ()
    structure_fingerprint_factory: StructureFingerprintFactory | None = Field(
        default=None, exclude=True
    )
    structure_factory_id: str | None = None
    structure_canonicalizer_id: str | None = None
    structure_canonicalizer_spec: str | None = None
    structure_canonicalizer_version: str | None = None
    structure_engine_version: str | None = None
    structure_dependency_identity: str | None = None
    structure_canonicalization_parameter_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    structure_factory_implementation_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    structure_factory_key_commitment: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def bind_structure_factory_identity(self) -> "LeakagePolicy":
        factory = self.structure_fingerprint_factory
        if factory is None:
            if any(
                (
                    self.structure_factory_id,
                    self.structure_canonicalizer_id,
                    self.structure_canonicalizer_spec,
                    self.structure_canonicalizer_version,
                    self.structure_engine_version,
                    self.structure_dependency_identity,
                    self.structure_canonicalization_parameter_digest,
                    self.structure_factory_implementation_digest,
                    self.structure_factory_key_commitment,
                )
            ):
                raise ValueError(
                    "structure canonicalizer requires an attested fingerprint factory"
                )
            return self
        verify_structure_fingerprint_factory(factory)
        expected = {
            "structure_factory_id": factory.factory_id,
            "structure_canonicalizer_id": factory.canonicalizer_id,
            "structure_canonicalizer_spec": factory.canonicalizer_spec,
            "structure_canonicalizer_version": factory.canonicalizer_version,
            "structure_engine_version": factory.engine_version,
            "structure_dependency_identity": factory.dependency_identity,
            "structure_canonicalization_parameter_digest": (
                factory.canonicalization_parameter_digest
            ),
            "structure_factory_implementation_digest": factory.implementation_digest,
            "structure_factory_key_commitment": factory.key_commitment,
        }
        for field, value in expected.items():
            supplied = getattr(self, field)
            if supplied is not None and supplied != value:
                raise ValueError("structure canonicalizer/factory identity mismatch")
            object.__setattr__(self, field, value)
        return self


class LeakageHit(FrozenStrictModel):
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    pointer_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    line: int | None = Field(default=None, ge=1)
    kind: Literal["term", "fingerprint", "filename", "query"]
    policy_id: str
    redacted_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LeakageAudit(FrozenStrictModel):
    policy_id: str
    scanned_artifact_ids: tuple[str, ...]
    hits: tuple[LeakageHit, ...]


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def verify_policy_structure_factory(
    policy: LeakagePolicy,
    expected_factory: StructureFingerprintFactory | None = None,
) -> StructureFingerprintFactory | None:
    factory = policy.structure_fingerprint_factory
    if factory is None:
        if expected_factory is not None:
            raise LeakageAuditError("trusted structure fingerprint factory is missing")
        return None
    try:
        verify_structure_fingerprint_factory(factory)
    except ValueError as exc:
        raise LeakageAuditError(str(exc)) from exc
    if expected_factory is not None and factory is not expected_factory:
        raise LeakageAuditError("trusted structure fingerprint factory identity mismatch")
    expected = (
        factory.factory_id,
        factory.canonicalizer_id,
        factory.canonicalizer_spec,
        factory.canonicalizer_version,
        factory.engine_version,
        factory.dependency_identity,
        factory.canonicalization_parameter_digest,
        factory.implementation_digest,
        factory.key_commitment,
    )
    supplied = (
        policy.structure_factory_id,
        policy.structure_canonicalizer_id,
        policy.structure_canonicalizer_spec,
        policy.structure_canonicalizer_version,
        policy.structure_engine_version,
        policy.structure_dependency_identity,
        policy.structure_canonicalization_parameter_digest,
        policy.structure_factory_implementation_digest,
        policy.structure_factory_key_commitment,
    )
    if supplied != expected:
        raise LeakageAuditError("structure canonicalizer/factory identity mismatch")
    return factory


def _require_structure_factory(
    policy: LeakagePolicy,
) -> StructureFingerprintFactory | None:
    structure_enabled = bool(
        policy.canonical_structure_hashes or policy.structure_field_names
    )
    factory = verify_policy_structure_factory(policy)
    if structure_enabled and factory is None:
        raise LeakageAuditError(
            "structure fingerprint factory is required for canonical structure scanning"
        )
    return factory


def _resolved(path: Path) -> Path:
    return path.resolve(strict=False)


def _artifact_id(value: str | Path) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _manifest_closure(manifest_path: Path) -> tuple[set[Path], set[str]]:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeakageAuditError(f"unreadable dependency manifest: {manifest_path}") from exc
    if not isinstance(raw, Mapping):
        raise LeakageAuditError("run manifest requires dependency_paths and query_ids")
    dependencies = raw.get("dependency_paths")
    query_ids = raw.get("query_ids")
    if (
        not isinstance(dependencies, list)
        or not dependencies
        or not all(isinstance(dependency, str) for dependency in dependencies)
        or not isinstance(query_ids, list)
        or not all(isinstance(query_id, str) for query_id in query_ids)
        or len(dependencies) != len(set(dependencies))
        or len(query_ids) != len(set(query_ids))
    ):
        raise LeakageAuditError("run manifest requires a non-empty unique dependency closure")
    return (
        {_resolved(manifest_path.parent / dependency) for dependency in dependencies},
        set(query_ids),
    )


def _validate_closure(paths: Sequence[Path], policy: LeakagePolicy) -> tuple[Path, ...]:
    if policy.run_manifest_path is None:
        raise LeakageAuditError("run manifest dependency declaration is required")
    manifest_paths, manifest_query_ids = _manifest_closure(policy.run_manifest_path)
    supplied = tuple(_resolved(path) for path in paths)
    supplied_set = set(supplied)
    if len(supplied) != len(supplied_set) or supplied_set != manifest_paths:
        raise LeakageAuditError("supplied audit paths do not equal declared dependency closure")
    declared = {_resolved(path) for path in policy.declared_dependency_paths}
    if declared and declared != manifest_paths:
        raise LeakageAuditError("declared dependency closure disagrees with run manifest")
    query_ids = {query.query_id for query in policy.query_inputs}
    if len(query_ids) != len(policy.query_inputs) or query_ids != manifest_query_ids:
        raise LeakageAuditError("query inputs do not equal the manifest query declaration")
    for path in supplied:
        if not path.is_file():
            raise LeakageAuditError(f"unreadable dependency: {_artifact_id(path)}")
    return tuple(sorted(supplied, key=str))


def _line_for(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _hit(
    artifact: str | Path,
    kind: Literal["term", "fingerprint", "filename", "query"],
    policy: LeakagePolicy,
    secret: str,
    *,
    text: str | None = None,
    index: int | None = None,
    pointer: str | None = None,
) -> LeakageHit:
    return LeakageHit(
        artifact_id=_artifact_id(artifact),
        pointer_digest=hashlib.sha256(pointer.encode("utf-8")).hexdigest()
        if pointer is not None
        else None,
        line=_line_for(text, index) if text is not None and index is not None else None,
        kind=kind,
        policy_id=policy.policy_id,
        redacted_digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
    )


def _string_hits(
    value: str,
    needles: tuple[tuple[str, Literal["term", "fingerprint"]], ...],
    artifact: str | Path,
    policy: LeakagePolicy,
    *,
    pointer: str | None = None,
    text: str | None = None,
    index: int | None = None,
) -> list[LeakageHit]:
    normalized_value = _normalized(value)
    return [
        _hit(artifact, kind, policy, secret, pointer=pointer, text=text, index=index)
        for secret, kind in needles
        if _normalized(secret) in normalized_value
    ]


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _structured_hits(
    value: object,
    needles: tuple[tuple[str, Literal["term", "fingerprint"]], ...],
    path: Path,
    policy: LeakagePolicy,
    pointer: str = "",
    structure_field: bool = False,
) -> list[LeakageHit]:
    if isinstance(value, Mapping):
        hits: list[LeakageHit] = []
        normalized_fields = {_normalized(name) for name in policy.structure_field_names}
        for key, item in value.items():
            key_text = str(key)
            child_pointer = f"{pointer}/{_escape_pointer(key_text)}"
            hits.extend(_string_hits(key_text, needles, path, policy, pointer=child_pointer))
            hits.extend(
                _structured_hits(
                    item,
                    needles,
                    path,
                    policy,
                    child_pointer,
                    _normalized(key_text) in normalized_fields,
                )
            )
        return hits
    if isinstance(value, list):
        return [
            hit
            for index, item in enumerate(value)
            for hit in _structured_hits(
                item, needles, path, policy, f"{pointer}/{index}", structure_field
            )
        ]
    if not isinstance(value, str):
        return []
    hits = _string_hits(value, needles, path, policy, pointer=pointer or "/")
    if structure_field:
        factory = _require_structure_factory(policy)
        assert factory is not None
        try:
            structure_digest = derive_structure_fingerprint(factory, value)
        except ValueError as exc:
            raise LeakageAuditError(str(exc)) from exc
        if structure_digest in policy.canonical_structure_hashes:
            hits.append(
                _hit(path, "fingerprint", policy, structure_digest, pointer=pointer or "/")
            )
    return hits


def _parse_structured(path: Path, text: str) -> object | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text)
        if suffix in {".yaml", ".yml"}:
            return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise LeakageAuditError(f"unreadable dependency: {_artifact_id(path)}") from exc
    return None


def audit_paths(paths: Sequence[Path], policy: LeakagePolicy) -> LeakageAudit:
    """Scan exactly one declared closure without serializing sealed values or paths."""

    _require_structure_factory(policy)
    resolved_paths = _validate_closure(paths, policy)
    needles: tuple[tuple[str, Literal["term", "fingerprint"]], ...] = (
        tuple((term, "term") for term in policy.sealed_terms)
        + tuple((fingerprint, "fingerprint") for fingerprint in policy.sealed_fingerprints)
    )
    hits: list[LeakageHit] = []
    for path in resolved_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LeakageAuditError(f"unreadable dependency: {_artifact_id(path)}") from exc
        structured = _parse_structured(path, text)
        if structured is None:
            for secret, kind in needles:
                index = _normalized(text).find(_normalized(secret))
                if index >= 0:
                    hits.append(_hit(path, kind, policy, secret, text=text, index=index))
        else:
            hits.extend(_structured_hits(structured, needles, path, policy))
        hits.extend(_string_hits(path.name, needles, path, policy))
        for secret, _kind in needles:
            if _normalized(secret) in _normalized(path.name):
                hits.append(_hit(path, "filename", policy, secret))
    for query in policy.query_inputs:
        for secret, _kind in needles:
            if _normalized(secret) in _normalized(query.text):
                hits.append(_hit(f"query:{query.query_id}", "query", policy, secret))
    ordered_hits = tuple(
        sorted(
            hits,
            key=lambda hit: (
                hit.artifact_id,
                hit.pointer_digest or "",
                hit.line or 0,
                hit.kind,
                hit.redacted_digest,
            ),
        )
    )
    return LeakageAudit(
        policy_id=policy.policy_id,
        scanned_artifact_ids=tuple(_artifact_id(path) for path in resolved_paths),
        hits=ordered_hits,
    )


def audit_snapshot_bytes(
    artifacts: Sequence[tuple[str, bytes]], policy: LeakagePolicy
) -> LeakageAudit:
    """Scan immutable, caller-snapshotted bytes without reopening pathnames."""

    _require_structure_factory(policy)
    identifiers = tuple(identifier for identifier, _ in artifacts)
    if not artifacts or len(identifiers) != len(set(identifiers)):
        raise LeakageAuditError("snapshot audit requires unique artifact identifiers")
    needles: tuple[tuple[str, Literal["term", "fingerprint"]], ...] = (
        tuple((term, "term") for term in policy.sealed_terms)
        + tuple(
            (fingerprint, "fingerprint")
            for fingerprint in policy.sealed_fingerprints
        )
    )
    hits: list[LeakageHit] = []
    ordered = tuple(sorted(artifacts, key=lambda item: item[0]))
    for identifier, content in ordered:
        path = Path(identifier)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LeakageAuditError(
                f"unreadable dependency: {_artifact_id(identifier)}"
            ) from exc
        structured = _parse_structured(path, text)
        if structured is None:
            for secret, kind in needles:
                index = _normalized(text).find(_normalized(secret))
                if index >= 0:
                    hits.append(
                        _hit(identifier, kind, policy, secret, text=text, index=index)
                    )
        else:
            hits.extend(_structured_hits(structured, needles, path, policy))
        hits.extend(_string_hits(path.name, needles, identifier, policy))
        for secret, _kind in needles:
            if _normalized(secret) in _normalized(path.name):
                hits.append(_hit(identifier, "filename", policy, secret))
    for query in policy.query_inputs:
        for secret, _kind in needles:
            if _normalized(secret) in _normalized(query.text):
                hits.append(
                    _hit(f"query:{query.query_id}", "query", policy, secret)
                )
    return LeakageAudit(
        policy_id=policy.policy_id,
        scanned_artifact_ids=tuple(
            _artifact_id(identifier) for identifier, _ in ordered
        ),
        hits=tuple(
            sorted(
                hits,
                key=lambda hit: (
                    hit.artifact_id,
                    hit.pointer_digest or "",
                    hit.line or 0,
                    hit.kind,
                    hit.redacted_digest,
                ),
            )
        ),
    )


def assert_clean(audit: LeakageAudit) -> None:
    """Fail without embedding sealed values or sensitive artifact paths."""

    if audit.hits:
        raise LeakageAuditError(f"leakage audit failed with {len(audit.hits)} redacted hit(s)")

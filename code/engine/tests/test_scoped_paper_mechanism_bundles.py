import pytest

from pipeline.paper_mechanism_bundles import (
    PaperMechanismBundleError,
    load_paper_mechanism_bundles,
)
from tests.test_paper_mechanism_bundles import _write_fixture


def test_explicit_subset_loads_when_other_registry_paper_not_ready(tmp_path):
    _write_fixture(tmp_path)
    missing = tmp_path / "derived/principles/normalization" / ("2" * 12) / "validated.json"
    missing.unlink()
    bundles = load_paper_mechanism_bundles(tmp_path, source_paths={"papers/one.pdf"})
    assert [bundle.source_path for bundle in bundles] == ["papers/one.pdf"]
    with pytest.raises(PaperMechanismBundleError):
        load_paper_mechanism_bundles(tmp_path)


def test_explicit_subset_rejects_unknown_source_even_when_cache_exists(tmp_path):
    _write_fixture(tmp_path)
    with pytest.raises(PaperMechanismBundleError, match="outside.*registry"):
        load_paper_mechanism_bundles(tmp_path, source_paths={"papers/excluded.pdf"})


def test_subset_keeps_full_bundle_identity_and_digest(tmp_path):
    _write_fixture(tmp_path)
    full = load_paper_mechanism_bundles(tmp_path)
    scoped = load_paper_mechanism_bundles(tmp_path, source_paths={"papers/two.pdf"})
    assert len(scoped) == 1
    assert scoped[0] == full[1]
    assert scoped[0].bundle_digest == full[1].bundle_digest
    assert scoped[0].mechanisms[0].mechanism_evidence_id == "222222222222::ME001"
    assert load_paper_mechanism_bundles(tmp_path, source_paths=set()) == ()

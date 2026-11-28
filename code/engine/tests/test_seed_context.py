from pathlib import Path

import yaml

from pipeline.models import PageChunk
from pipeline.prompt_builder import build_extraction_input, load_seed_context
from tests.test_prompt_builder import PROMPT, pages, source


def test_seed_context_is_separated_from_literature_evidence(tmp_path: Path) -> None:
    seed_path = tmp_path / "seed.yaml"
    seed_path.write_text(
        yaml.safe_dump(
            {
                "freeze_version": "1.0",
                "seed_reaction_id": "SRC-CC-001",
                "established_facts": {
                    "net_transformation": "Selective defluorinative C-C bond formation"
                },
            }
        ),
        encoding="utf-8",
    )
    chunk = PageChunk(chunk_id="chunk-001", pages=tuple(pages()))

    text = build_extraction_input(
        source(), chunk, PROMPT, seed_context=load_seed_context(seed_path)
    )

    assert "PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE" in text
    assert "END_PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE" in text
    assert '"seed_reaction_id": "SRC-CC-001"' in text
    assert "must not be quoted or cited as literature evidence" in text
    assert text.index("PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE") < text.index(
        "SOURCE_METADATA"
    )


def test_prompt_remains_compatible_without_seed_context() -> None:
    chunk = PageChunk(chunk_id="chunk-001", pages=tuple(pages()))

    text = build_extraction_input(source(), chunk, PROMPT)

    assert "PROJECT_CONTEXT_NOT_SOURCE_EVIDENCE" not in text

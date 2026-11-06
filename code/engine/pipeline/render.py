"""Render explicitly selected PDF pages for human visual review."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenderedPage:
    pdf_page: int
    image_path: str


def render_pages(
    pdf_path: Path,
    pages: list[int],
    output_dir: Path,
) -> list[RenderedPage]:
    """Render one-based pages with Poppler without shell interpolation."""

    executable = shutil.which("pdftoppm")
    if executable is None:
        raise RuntimeError("pdftoppm is required for visual review")
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[RenderedPage] = []
    for pdf_page in sorted(set(pages)):
        if pdf_page < 1:
            raise ValueError("PDF pages are one-based positive integers")
        prefix = output_dir / f"page-{pdf_page:04d}"
        subprocess.run(
            [
                executable,
                "-f",
                str(pdf_page),
                "-l",
                str(pdf_page),
                "-singlefile",
                "-png",
                str(pdf_path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        image = prefix.with_suffix(".png")
        if not image.is_file():
            raise RuntimeError(f"Poppler did not create the expected page image: {image}")
        rendered.append(RenderedPage(pdf_page=pdf_page, image_path=str(image)))
    return rendered

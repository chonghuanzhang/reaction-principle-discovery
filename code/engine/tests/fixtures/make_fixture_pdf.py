"""Create a minimal PDF with known text and a scheme-like page."""

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas


def create_fixture_pdf(output: Path) -> Path:
    canvas = Canvas(str(output))
    canvas.drawString(72, 720, "Experimental yield was 82%.")
    canvas.showPage()
    canvas.rect(72, 420, 450, 250)
    canvas.drawString(72, 700, "Scheme 1")
    canvas.save()
    return output

"""Check that the rendered network preserves the meanings of its edge styles."""
from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import pymupdf
except ImportError:
    pymupdf = None


@unittest.skipUnless(pymupdf is not None, 'Install requirements-figures.txt')
class Figure3RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = tempfile.TemporaryDirectory()
        script = Path(__file__).resolve().parents[1]/'scripts/reproduce_figure3.py'
        subprocess.run(
            [sys.executable, str(script), '--output-dir', cls.output.name, '--render'],
            check=True, capture_output=True, text=True)
        cls.pdf = pymupdf.open(Path(cls.output.name)/'Figure_3.pdf')

    @classmethod
    def tearDownClass(cls):
        cls.pdf.close()
        cls.output.cleanup()

    def test_conditional_applications_and_legend_remain_dashed(self):
        dashes = Counter(path['dashes'] for path in self.pdf[0].get_drawings())
        self.assertEqual(dashes['[ 1.344 1.344 ] 0'], 23)
        self.assertEqual(dashes['[ 1.68 1.68 ] 0'], 1)

    def test_evidence_edge_keeps_its_transparency(self):
        # Midpoint of the first isolated evidence-to-principle Bezier curve.
        # SVG color #377cbd at opacity 0.49 should blend with the white page.
        x = (127.559055 + 3*170.418898 + 3*179.348031 + 216.850394)/8
        y = (114.563583 + 3*114.563583 + 3*140.340389 + 140.340389)/8 - 63
        pixmap = self.pdf[0].get_pixmap(dpi=600, alpha=False)
        actual = pixmap.pixel(round(x*600/72), round(y*600/72))
        expected = tuple(round(0.49*channel + 0.51*255) for channel in (55, 124, 189))
        for value, reference in zip(actual, expected):
            self.assertAlmostEqual(value, reference, delta=3)


if __name__ == '__main__':
    unittest.main()

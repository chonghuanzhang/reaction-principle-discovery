"""Prevent the figure entrypoint from reproducing obsolete Figure 4 artwork."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf
from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[2]


class Figure4CompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = tempfile.TemporaryDirectory()
        env = dict(os.environ, REACTION_FIGURE_OUTPUT=cls.output.name)
        command = (
            f"import sys; sys.path.insert(0, {str(ROOT/'code/figures')!r}); "
            "import figures_gaoge; figures_gaoge.fig4()")
        subprocess.run([sys.executable, '-c', command], env=env, check=True,
                       capture_output=True, text=True)
        cls.figure_dir = Path(cls.output.name)/'figures'

    @classmethod
    def tearDownClass(cls):
        cls.output.cleanup()

    def test_entrypoint_reproduces_current_master(self):
        with Image.open(self.figure_dir/'Figure_4.png') as output:
            actual = output.convert('RGB')
        with Image.open(ROOT/'figures/main/Figure_4.png') as master:
            expected = master.convert('RGB')
        self.assertEqual(actual.size, expected.size)
        self.assertIsNone(ImageChops.difference(actual, expected).getbbox())

    def test_pdf_remains_vector_artwork_at_compact_print_dimensions(self):
        with pymupdf.open(self.figure_dir/'Figure_4.pdf') as document:
            self.assertEqual(len(document), 1)
            images = document[0].get_images()
            self.assertEqual(len(images), 0)
            self.assertTrue(document[0].get_drawings())
            self.assertTrue(document[0].get_text().strip())
            self.assertAlmostEqual(document[0].rect.width * 25.4 / 72, 180, places=2)
            self.assertAlmostEqual(document[0].rect.height * 25.4 / 72, 175, places=2)


if __name__ == '__main__':
    unittest.main()

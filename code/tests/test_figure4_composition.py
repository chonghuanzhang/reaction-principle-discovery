"""Prevent the figure entrypoint from reproducing obsolete Figure 4 artwork."""
import io
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

    def test_entrypoint_reproduces_current_master_and_preserves_panels_abc(self):
        with Image.open(self.figure_dir/'Figure_4.png') as output:
            actual = output.convert('RGB')
        with Image.open(ROOT/'figures/main/Figure_4.png') as master:
            expected = master.convert('RGB')
        self.assertEqual(actual.size, expected.size)
        self.assertIsNone(ImageChops.difference(actual, expected).getbbox())
        with Image.open(ROOT/'figures/source/Figure_4_panels_abc.png') as source:
            preserved = actual.crop((0, 0, source.width, source.height))
            self.assertIsNone(ImageChops.difference(preserved, source.convert('RGB')).getbbox())

    def test_pdf_embeds_the_lossless_current_master(self):
        with pymupdf.open(self.figure_dir/'Figure_4.pdf') as document:
            self.assertEqual(len(document), 1)
            images = document[0].get_images()
            self.assertEqual(len(images), 1)
            with Image.open(io.BytesIO(document.extract_image(images[0][0])['image'])) as embedded:
                actual = embedded.convert('RGB')
        with Image.open(ROOT/'figures/main/Figure_4.png') as master:
            expected = master.convert('RGB')
        self.assertEqual(actual.size, expected.size)
        self.assertIsNone(ImageChops.difference(actual, expected).getbbox())


if __name__ == '__main__':
    unittest.main()

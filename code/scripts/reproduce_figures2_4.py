#!/usr/bin/env python3
"""Draw vector Figures 2 and 4 from deposited scientific records."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--font-file', type=Path, help='Optional font for Figure 2')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    env = dict(os.environ, REACTION_FIGURE_OUTPUT=str(output))
    if args.font_file:
        env['REACTION_FONT_FILE'] = str(args.font_file.resolve())
    command = (f"import sys; sys.path.insert(0, {str(ROOT/'figures')!r}); "
               "import figures_gaoge as f; f.fig2(); f.fig4()")
    result = subprocess.run([sys.executable, '-c', command], env=env,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr+'\n'+result.stdout)

    import pymupdf
    from PIL import Image, ImageChops, ImageStat

    figures = []
    for number in (2, 4):
        with pymupdf.open(output/'figures'/f'Figure_{number}.pdf') as document:
            assert len(document) == 1
            image_count = len(document[0].get_images())
            if number == 2:
                assert image_count == 0
                assert document[0].get_text().strip() and document[0].get_drawings()
            else:
                assert image_count == 0, 'Figure 4 PDF must remain vector artwork'
                assert document[0].get_text().strip() and document[0].get_drawings()
            figures.append({'figure': number, 'pages': len(document),
                            'raster_images_in_pdf': image_count})
        with Image.open(output/'figures'/f'Figure_{number}.png') as rendered:
            assert any(low < high for low, high in ImageStat.Stat(rendered).extrema), 'Blank PNG'

    with Image.open(output/'figures/Figure_4.png') as rendered:
        actual = rendered.convert('RGB')
    with Image.open(ROOT.parent/'figures/main/Figure_4.png') as master:
        expected = master.convert('RGB')
    assert actual.size == expected.size
    assert ImageChops.difference(actual, expected).getbbox() is None, 'Figure 4 pixels differ'
    figures[1].update({'master_pixels_identical': True,
                      'rgb_pixel_sha256': hashlib.sha256(actual.tobytes()).hexdigest()})
    print(json.dumps({
        'status': 'passed', 'network_calls': 0, 'model_calls': 0, 'figures': figures,
        'scope': 'Figure 2 uses vector drawing functions; typography may vary. '
                 'Figure 4 redraws counts, structures and NP/NR distributions from deposited '
                 'scientific records; PDF and SVG are vector artwork and PNG is the raster master.'
    }, indent=2))


if __name__ == '__main__':
    main()

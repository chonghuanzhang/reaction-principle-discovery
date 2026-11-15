#!/usr/bin/env python3
"""Export approved Figures 1–2 without changing their artwork pixels.

Editable PPTX originals are in figures/source/current/. PDF/SVG exports are
image containers; chemical schemes and typography are preserved as supplied.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import shutil
from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parents[2]


def export_figure(number, output_dir):
    source = REPO / 'figures' / 'source' / 'current' / f'Figure_{number}_publication.png'
    output = Path(output_dir) / 'figures'
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'Figure_{number}.png'
    shutil.copyfile(source, target)
    with Image.open(source) as img:
        rgb = img.convert('RGB')
        width, height = rgb.size
        rgb.save(output / f'Figure_{number}.jpeg', quality=95, subsampling=0)
        rgb.save(output / f'Figure_{number}.pdf', 'PDF', resolution=300.0)
    encoded = base64.b64encode(source.read_bytes()).decode('ascii')
    (output / f'Figure_{number}.svg').write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<image width="{width}" height="{height}" xlink:href="data:image/png;base64,{encoded}"/></svg>')
    with Image.open(target) as result:
        assert result.size == rgb.size
        assert ImageChops.difference(result.convert('RGB'), rgb).getbbox() is None
    return {'figure': number, 'source': str(source.relative_to(REPO)), 'pixel_dimensions': [width, height],
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'master_pixels_identical': True, 'pdf_svg_content': 'approved raster composite'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': 'passed', 'figures': [export_figure(n,args.output_dir) for n in (1,2)]}, indent=2))


if __name__ == '__main__':
    main()

"""Reproduce the current Figure 4 from the deposited raster artwork."""
from pathlib import Path
import hashlib
import json

from PIL import Image
import pymupdf


ROOT = Path(__file__).resolve().parents[2]
COMPOSITION = ROOT/'figures/source/Figure_4_composition.json'


def reproduce(output_dir):
    """Compose the lossless master, a JPEG derivative and a raster-embedded PDF."""
    spec = json.loads(COMPOSITION.read_text(encoding='utf-8'))
    canvas = Image.new(spec['mode'], tuple(spec['canvas_px']), spec['background'])
    for layer in spec['layers']:
        source = ROOT/layer['path']
        if hashlib.sha256(source.read_bytes()).hexdigest() != layer['sha256']:
            raise ValueError(f"Figure 4 source checksum mismatch: {layer['path']}")
        with Image.open(source) as original:
            if list(original.size) != layer['source_dimensions_px']:
                raise ValueError(f"Figure 4 source dimensions mismatch: {layer['path']}")
            artwork = original.convert(spec['mode'])
        target = tuple(layer['target_dimensions_px'])
        if layer['resampling'] == 'LANCZOS':
            artwork = artwork.resize(target, Image.Resampling.LANCZOS)
        elif layer['resampling'] != 'none' or artwork.size != target:
            raise ValueError(f"Invalid Figure 4 resampling: {layer['panels']}")
        canvas.paste(artwork, tuple(layer['paste_xy']))

    pixel_sha = hashlib.sha256(canvas.tobytes()).hexdigest()
    if pixel_sha != spec['authoritative_master']['rgb_pixel_sha256']:
        raise ValueError('Figure 4 composition differs from the authoritative master')

    figure_dir = Path(output_dir)/'figures'
    figure_dir.mkdir(parents=True, exist_ok=True)
    png = figure_dir/'Figure_4.png'
    canvas.save(png, dpi=tuple(spec['dpi']))
    jpeg = spec['jpeg_derivative']
    canvas.save(figure_dir/'Figure_4.jpeg', quality=jpeg['quality'],
                subsampling=jpeg['subsampling'], dpi=tuple(spec['dpi']))
    # The PDF preserves the PNG as one lossless raster image, with no redrawing.
    with pymupdf.open() as document:
        page = document.new_page(width=canvas.width*72/spec['dpi'][0],
                                 height=canvas.height*72/spec['dpi'][1])
        page.insert_image(page.rect, filename=str(png))
        document.save(figure_dir/'Figure_4.pdf', deflate=True)
    return {'figure': 4, 'dimensions_px': list(canvas.size),
            'rgb_pixel_sha256': pixel_sha, 'composition': 'deposited raster artwork'}

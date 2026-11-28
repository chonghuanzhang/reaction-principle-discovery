#!/usr/bin/env python3
"""Regenerate Supplementary Fig. 5 from the current novelty summary and SVG layout.

Run from any directory with Python 3 and librsvg's ``rsvg-convert`` on PATH:
    python figures/source/reproduce_supplementary_figure5.py
Use --output-dir to verify a reproduction without replacing release assets.

The deposited SVG is the layout source. Experimental bar lengths and labels
follow novelty_summary.json; the 100-candidate panels are checked and preserved.
New categories or a changed candidate collection require an explicit layout edit.
No Git history, network access, private paths, or Python packages are required.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('figures/source/round5_supplementary_figure5.json')
ASSET = Path('candidates/figures/N1_novelty_distributions')
SUMMARY_KEYS = {
    'candidate_NP': 'candidate_molecule_NP_label_set_distribution',
    'candidate_NR': 'candidate_molecule_NR_label_set_distribution',
    'experimental_pair_NP': 'experimental_pair_NP',
    'experimental_pair_NR': 'experimental_pair_NR',
}
CANDIDATE_LABELS = {
    'candidate_NP': [('2', 'text_10'), ('2 / unresolved', 'text_11'), ('unresolved', 'text_12')],
    'candidate_NR': [('1', 'text_43'), ('2', 'text_44'), ('3', 'text_45'),
                     ('2 / unresolved', 'text_46'), ('unresolved', 'text_47')],
}
EXPERIMENTAL_MARKS = {
    'NP': [('1r', 'patch_11', 'text_26'), ('2', 'patch_12', 'text_27'),
           ('3', 'patch_13', 'text_28'), ('3 / 2', 'patch_14', 'text_29'),
           ('not applicable', 'patch_15', 'text_30')],
    'NR': [('1', 'patch_31', 'text_62'), ('2', 'patch_32', 'text_63'),
           ('3', 'patch_33', 'text_64'), ('2 / 3', 'patch_34', 'text_65'),
           ('unresolved', 'patch_35', 'text_66'), ('not applicable', 'patch_36', 'text_67')],
}


def normalize(label):
    return str(label).lower().replace(' ', '').replace('|', '/').replace('–', '/')


def group(svg, identifier):
    found = re.search(r'<g id="' + re.escape(identifier) + r'">(.*?)</g>', svg, re.S)
    if found is None:
        raise ValueError('Missing SVG layout group: ' + identifier)
    return found


def annotation(svg, identifier):
    match = re.search(r'<text\b([^>]*)>([^<]*)</text>', group(svg, identifier).group(1))
    if match is None:
        raise ValueError('Missing SVG annotation: ' + identifier)
    return match


def update_mark(svg, patch_id, text_id, count):
    current = int(annotation(svg, text_id).group(2))
    if current == count:
        return svg  # Preserve exact coordinates and bytes on repeated runs.
    if current <= 0:
        raise ValueError('Cannot infer a scale from zero-width bar: ' + patch_id)
    patch = group(svg, patch_id)
    body = patch.group(1)
    match = re.search(r'd="M ([\d.]+) ([\d.]+)\s+L ([\d.]+)', body)
    if match is None:
        raise ValueError('Expected a horizontal bar: ' + patch_id)
    left, right = float(match.group(1)), float(match.group(3))
    end = left + (right - left) * count / current
    delta = end - right
    old_token = match.group(3)
    new_body = body.replace('L ' + old_token + ' ', 'L ' + f'{end:.6f}' + ' ')
    if new_body == body:
        raise ValueError('Bar endpoint was not updated: ' + patch_id)
    svg = svg[:patch.start(1)] + new_body + svg[patch.end(1):]
    label = group(svg, text_id)
    body = label.group(1)
    attr = re.search(r'\bx="([\d.]+)"', body)
    old_x = attr.group(1)
    new_x = f'{float(old_x) + delta:.6f}'
    body = body.replace('x="' + old_x + '"', 'x="' + new_x + '"')
    body = re.sub(r'(rotate\(-?0 )' + re.escape(old_x) + r'(?= )',
                  lambda m: m.group(1) + new_x, body)
    body = re.sub(r'(?<=>)' + str(current) + r'(?=</text>)', str(count), body)
    return svg[:label.start(1)] + body + svg[label.end(1):]


def candidate_axes(svg):
    tree = ET.fromstring(svg)
    return [ET.tostring(tree.find(".//*[@id='" + key + "']"))
            for key in ('axes_1', 'axes_3')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        help='Write all four reproduced files here; leave repository assets unchanged.')
    args = parser.parse_args()
    renderer = shutil.which('rsvg-convert')
    if not renderer:
        parser.error('Install librsvg and put rsvg-convert on PATH.')
    summary = json.loads((ROOT / 'code/data/mapping/novelty_summary.json').read_text())
    data = json.loads((ROOT / SOURCE).read_text())
    original = (ROOT / ASSET.with_suffix('.svg')).read_text()
    svg = original
    for panel, summary_key in SUMMARY_KEYS.items():
        values = {normalize(k): v for k, v in summary[summary_key].items()}
        if set(values) != {normalize(k) for k in data[panel]}:
            raise ValueError('Category set changed; update layout explicitly: ' + panel)
        for label in data[panel]:
            value = values[normalize(label)]
            if not isinstance(value, int) or value < 0:
                raise ValueError('Expected a nonnegative integer count: ' + label)
            data[panel][label] = value
    for panel, labels in CANDIDATE_LABELS.items():
        if sum(data[panel].values()) != 100:
            raise ValueError('Candidate collection changed; review the layout.')
        for label, text_id in labels:
            if int(annotation(svg, text_id).group(2)) != data[panel][label]:
                raise ValueError('Candidate count changed; review the layout: ' + text_id)
    for measure, marks in EXPERIMENTAL_MARKS.items():
        panel = data['experimental_pair_' + measure]
        total = sum(panel.values())
        if total != summary['units']['experimental_pairs']:
            raise ValueError('Experimental total disagrees with novelty summary.')
        for label, patch_id, text_id in marks:
            svg = update_mark(svg, patch_id, text_id, panel[label])
        pattern = r'Experimental pairs · ' + measure + r' \(n = \d+\)'
        svg, replacements = re.subn(pattern, f'Experimental pairs · {measure} (n = {total})', svg)
        if replacements != 1:
            raise ValueError('Expected one experimental-panel title: ' + measure)
    if candidate_axes(svg) != candidate_axes(original):
        raise ValueError('Candidate-panel preservation check failed.')
    out = args.output_dir
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
    destinations = {suffix: (out / (ASSET.name + suffix) if out else ROOT / ASSET.with_suffix(suffix))
                    for suffix in ('.svg', '.png', '.pdf')}
    source_dest = out / SOURCE.name if out else ROOT / SOURCE
    # Complete both renders before replacing any release artifact.
    with tempfile.TemporaryDirectory(prefix='supplementary-figure5-') as tmp:
        tmp = Path(tmp)
        (tmp / 'figure.svg').write_text(svg)
        for suffix, flags in [('.png', ['-w', '2102', '-h', '1576']), ('.pdf', ['-f', 'pdf'])]:
            subprocess.run([renderer, *flags, '-o', str(tmp / ('figure' + suffix)),
                            str(tmp / 'figure.svg')], check=True)
        source_dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        for suffix, destination in destinations.items():
            destination.write_bytes((tmp / ('figure' + suffix)).read_bytes())
    files = [source_dest, *destinations.values()]
    print(json.dumps({'status': 'PASS', 'candidate_panels_preserved': True,
                      'experimental_pairs': summary['units']['experimental_pairs'],
                      'sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}, indent=2))


if __name__ == '__main__':
    main()

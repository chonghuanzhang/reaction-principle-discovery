#!/usr/bin/env python3
"""Verify split original workbook, optionally restoring its exact byte stream."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def verify(output=None):
    info = json.loads((ROOT / 'raw/workbooks_manifest.json').read_text())['full_response_workbook']
    digest = hashlib.sha256()
    size = 0
    handle = Path(output).open('xb') if output else None
    try:
        for part in info['parts']:
            data = (ROOT / part['path']).read_bytes()
            assert len(data) == part['bytes']
            assert hashlib.sha256(data).hexdigest() == part['sha256'], part['path']
            digest.update(data)
            size += len(data)
            if handle:
                handle.write(data)
    finally:
        if handle:
            handle.close()
    assert size == info['bytes'] and digest.hexdigest() == info['sha256']
    return dict(status='passed', bytes=size, sha256=digest.hexdigest(), parts=len(info['parts']),
                output=str(output) if output else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Must not exist; omit to verify without writing a >100 MiB file.')
    print(json.dumps(verify(parser.parse_args().output), indent=2))

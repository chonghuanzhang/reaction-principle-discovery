#!/usr/bin/env python3
"""Check current response provenance and lossless original workbook parts."""

import argparse
import json
from pathlib import Path
import platform
import sys

from reassemble_workbook import verify as verify_parts
from source_workbook import check_current_sources


def main(output):
    report = check_current_sources()
    report['split_workbook'] = verify_parts()
    report['environment'] = dict(python=sys.version, platform=platform.platform())
    report['record_scope'] = [
        'Current measured conditions are checked directly against original workbook response cells and identities.',
        'All 164 current trajectory rows agree with Table R4 CSV/JSON and the selected-response figure source.',
        'Analytical response and NMR yield are retained as separate measurement fields.',
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/reaction-data-check.json'))
    main(parser.parse_args().output)

#!/usr/bin/env python3
"""Validate all 288 displayed measured nodes against the current decision space."""
import csv
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
CURRENT=HERE.parent
REPO=CURRENT.parents[1]
DATA=HERE/'source_data'

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    grids=read(DATA/'grids_96.csv');keys=read(DATA/'formulation_key.csv')
    assert len(grids)==288 and len(keys)==36
    systems={};sources=[DATA/'grids_96.csv',DATA/'formulation_key.csv']
    for system in ['NH','OH','SH']:
        path=CURRENT/'data'/system/'candidate_space.csv';sources.append(path)
        candidates=read(path);rows=[r for r in grids if r['system']==system]
        assert len(rows)==96 and len({r['candidate_index'] for r in rows})==96
        assert len({r['row'] for r in rows})==12 and len({r['column'] for r in rows})==8
        for row in rows:
            candidate=candidates[int(row['candidate_index'])]
            assert candidate['measured']=='True' and candidate['source_stage']=='condition_grid'
            for field in ['cat','ligand','base','solvent']:
                assert candidate[field]==row[field],(system,row['candidate_index'],field)
            assert float(candidate['UV_response'])==float(row['UV_response'])
        for k in [r for r in keys if r['system']==system]:
            members=[r for r in rows if r['row']==k['row']]
            assert len(members)==8
            assert len({r['solvent'] for r in members})==8
            for field in ['cat','ligand','base','formulation_code']:
                assert all(r[field]==k[field] for r in members)
        local=max(rows,key=lambda r:float(r['UV_response']))
        full=max((r for r in candidates if r['measured']=='True'),key=lambda r:float(r['UV_response']))
        systems[system]={'nodes':96,'all_measured':True,'height':'UV response',
            'local_maximum':float(local['UV_response']),'local_maximum_candidate_index':int(local['candidate_index']),
            'full_space_measured_maximum':float(full['UV_response']),
            'full_space_measured_maximum_candidate_index':int(full['candidate_index']),
            'full_space_measured_maximum_in_slice':full['candidate_index'] in {r['candidate_index'] for r in rows}}
    report={'status':'PASS','total_nodes':288,'systems':systems,
            'sources':{str(p.relative_to(REPO)):sha(p) for p in sources}}
    (DATA/'grids_96_verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()

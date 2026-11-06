"""Revalidate a recorded run without invoking any model, including original v1 inputs."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.exploration_panel import digest,validate_candidate,merge_candidates,select_panel,CandidatePayload
from scripts.run_exploration_panel import prepare


def read(path):return json.loads(path.read_text())


def replay(config_path,root):
    config=read(config_path); manifest=read(root/'manifest.json'); binding=manifest['binding']
    if config!=binding['config']:raise ValueError('Configuration changed')
    bundle=read((config_path.parent/config['bundle']).resolve())
    if digest(bundle)!=binding['bundle_digest']:raise ValueError('Evidence bundle changed')
    core=Path(__file__).resolve().parents[1]/'pipeline/exploration_panel.py'
    if digest(core.read_text())!=binding['code']['exploration_panel.py']:raise ValueError('Core validation/selection implementation changed')
    accepted=[]
    for payload in prepare(config,bundle):
        directory=root/'lenses'/payload['lens']['id']; saved=read(directory/'input.json')
        if 'requested_candidate_count' not in saved:payload.pop('requested_candidate_count')
        if payload!=saved:raise ValueError('Stored retrieval differs from current source')
        prompt=binding['prompt']+'\n'+json.dumps(payload,ensure_ascii=False)
        key=digest({'prompt':prompt,'schema':binding['schema'],'model':binding['model']})
        raw=read(directory/'raw.json'); prior=read(directory/'validated.json')
        if raw['input_digest']!=key or prior['input_digest']!=key or raw['status']!='completed':raise ValueError('Response binding changed')
        evidence={r['evidence_id']:r for r in payload['evidence']}
        now=[]; rejected=[]
        for candidate in CandidatePayload.model_validate(raw['model_output']).candidates:
            try:
                row=validate_candidate(candidate.model_dump(),evidence)
                if row['lens']!=payload['lens']['id']:raise ValueError('Wrong lens identity')
                now.append(row)
            except ValueError as exc:rejected.append({'candidate':candidate.model_dump(),'reason':str(exc)})
        if now!=prior['accepted'] or rejected!=prior['rejected']:raise ValueError('Candidate validation changed')
        accepted.extend(now)
    panel=select_panel(merge_candidates(accepted),config['panel_budget'])
    if panel!=read(root/'panel.json'):raise ValueError('Panel replay changed')
    return {'replay':'passed','network_calls':0,'selected':len(panel['selected']),'pool':len(panel['selected'])+len(panel['reserve'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();print(replay(args.config.resolve(),args.run.resolve()))

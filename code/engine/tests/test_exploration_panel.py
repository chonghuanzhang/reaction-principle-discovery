import pytest
from pipeline import exploration_panel as m


def item(name='ethanol', smiles='CCO', atom=2, center='O', lens='polar'):
    return {'name': name, 'smiles': smiles, 'atom_indices': [atom], 'center': center,
            'family': 'alcohol', 'reactive_form': 'alkoxide possible', 'route': 'addition',
            'lens': lens, 'basis': 'model_hypothesis', 'citations': [],
            'reason': 'Test reactive-state access', 'activation': 'base dependence unknown',
            'risks': ['competing protonation'], 'diagnostic': 'compare base conditions'}


def test_unknown_hypothesis_is_admitted_and_structure_deduplicated():
    a=m.validate_candidate(item(), {})
    b=m.validate_candidate(item(smiles='OCC', atom=0), {})
    assert a['structure_key']==b['structure_key']
    pool=m.merge_candidates([a,b])
    assert len(pool)==1
    assert pool[0]['success_probability'] is None


def test_invalid_reactive_atom_and_foreign_quote_rejected():
    with pytest.raises(ValueError): m.validate_candidate(item(atom=0), {})
    r=item(); r.update(basis='local_analogy', citations=[{'evidence_id':'E1','quote':'fabricated quote'}])
    with pytest.raises(ValueError): m.validate_candidate(r, {'E1':{'quotation':'source quotation'}})


def test_budget_and_order_do_not_change_panel():
    rows=[m.validate_candidate(item(), {}), m.validate_candidate(item('methylamine','CN',1,'N','neutral'), {})]
    a=m.select_panel(m.merge_candidates(rows),1)
    b=m.select_panel(m.merge_candidates(list(reversed(rows))),1)
    assert a==b and len(a['selected'])==1
    assert a['uncovered_tags']
    with pytest.raises(ValueError): m.select_panel(rows,0)


def test_feedback_requires_target_identity_and_complete_assay():
    experiments=[{'experiment_id':'EX-other-1','role':'screen'}]
    with pytest.raises(ValueError): m.summarize_feedback(experiments,[{'experiment_id':'unknown'}])
    with pytest.raises(ValueError): m.summarize_feedback(experiments,[{'experiment_id':'EX-other-1','outcome':'target_detected'}])
    rows=[{'experiment_id':'EX-other-1','outcome':'target_detected','target_identity':'NMR and HRMS assignment',
           'assay':'calibrated qNMR','conditions':'actual recorded recipe'}]
    assert m.summarize_feedback(experiments,rows)['observed_hit_rate']==1


def test_other_reaction_configuration_and_missing_doses():
    candidates=m.merge_candidates([m.validate_candidate(item(), {})])
    panel=m.select_panel(candidates,1)
    experiments=m.experiment_plan(panel, {'study_id':'OTHER_REACTION','target':'new ester','fixed_component':'OTHER'})
    assert all('OTHER_REACTION' in r['experiment_id'] for r in experiments)
    assert all(r['instrument_ready'] is False for r in experiments)
    assert any(r['role']=='screen' for r in experiments)


def test_actual_negative_requires_detection_limit_and_missing_data_not_failed():
    experiments=[{'experiment_id':'E1','role':'screen'},{'experiment_id':'E2','role':'screen'}]
    with pytest.raises(ValueError):
        m.summarize_feedback(experiments,[{'experiment_id':'E1','outcome':'target_not_detected','assay':'LC','conditions':'record'}])
    result=m.summarize_feedback(experiments,[{'experiment_id':'E1','outcome':'inconclusive','assay':'LC','conditions':'record'}])
    assert result['observed_hit_rate'] is None and result['unmeasured_count']==1


def test_portable_orchestrator_retrieves_by_evidence_not_paper_title():
    from scripts.run_exploration_panel import prepare
    config={'study_id':'esterification','fixed_component':'acid','target':'ester','variable_role':'alcohol',
            'lenses':[{'id':'L','patterns':['oxygen','base']}],'per_source_cap':1,'evidence_per_lens':2}
    bundle={'seed':{},'principles':[],'evidence':[
        {'evidence_id':'E1','source_id':'paper1','claim':'oxygen donor','quotation':'base activates oxygen'},
        {'evidence_id':'E2','source_id':'paper1','claim':'oxygen donor','quotation':'base activates oxygen'},
        {'evidence_id':'E3','source_id':'oxygen titled paper','claim':'unrelated','quotation':'unrelated chemistry'}]}
    result=prepare(config,bundle)
    assert [r['evidence_id'] for r in result[0]['evidence']]==['E1']
    assert result[0]['study']['study_id']=='esterification'


def test_distinct_reactive_centers_on_same_reagent_are_retained():
    first=m.validate_candidate(item('ethanol','CCO',2,'O'),{})
    second=m.validate_candidate(item('ethanol','CCO',0,'C','carbon'),{})
    merged=m.merge_candidates([first,second])
    assert len(merged)==1 and len(merged[0]['hypotheses'])==2
    assert {'center:C','center:O'}<=set(merged[0]['coverage_tags'])


def test_offline_replay_refuses_missing_and_stale_responses(tmp_path):
    from scripts.run_exploration_panel import run
    import json
    cfg={'study_id':'unrelated','fixed_component':'acid','target':'ester','variable_role':'partner',
         'lenses':[{'id':'L','patterns':['oxygen']}],'per_source_cap':1,'evidence_per_lens':2,
         'model':'test-model','bundle':'bundle.json','panel_budget':1,'workers':1}
    (tmp_path/'config.json').write_text(json.dumps(cfg))
    (tmp_path/'bundle.json').write_text(json.dumps({'seed':{},'principles':[],'evidence':[]}))
    with pytest.raises(ValueError,match='Incomplete lens coverage'):
        run(tmp_path/'config.json',tmp_path/'out')
    manifest=next((tmp_path/'out').glob('*/manifest.json'))
    path=manifest.parent/'lenses/L/raw.json'; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'input_digest':'wrong','status':'completed','model_output':{}}))
    with pytest.raises(ValueError,match='Incomplete lens coverage'):
        run(tmp_path/'config.json',tmp_path/'out')
    assert not (manifest.parent/'panel.json').exists()


def test_other_reaction_full_run_and_offline_replay(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from pipeline import run_pilot
    from pipeline.api_client import ApiUsage
    from scripts.run_exploration_panel import run
    cfg={'study_id':'esterification','fixed_component':'acetic acid','target':'new C-O ester bond',
         'variable_role':'alcohol','lenses':[{'id':'L','patterns':['oxygen']}],
         'per_source_cap':1,'evidence_per_lens':2,'model':'test-only','bundle':'bundle.json','panel_budget':1,'workers':1}
    config_path=tmp_path/'config.json';config_path.write_text(json.dumps(cfg))
    (tmp_path/'bundle.json').write_text(json.dumps({'seed':{'reaction':'esterification'},'principles':[],'evidence':[]}))
    class TestProvider:
        def create_structured(self,*args):
            return SimpleNamespace(status='completed',response_id='test',returned_model='test-only',usage=ApiUsage(1,1,2),
                parsed_output={'candidates':[item(lens='L')],'uncovered':['larger alcohols']})
    monkeypatch.setattr(run_pilot,'_default_client',lambda model:TestProvider())
    path=run(config_path,tmp_path/'out',live=True)
    before=(path/'panel.json').read_bytes()
    def forbidden(model): raise RuntimeError('offline replay attempted network')
    monkeypatch.setattr(run_pilot,'_default_client',forbidden)
    assert run(config_path,tmp_path/'out',live=False)==path
    assert (path/'panel.json').read_bytes()==before
    cfg['target']='different target';config_path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='Incomplete lens coverage'):
        run(config_path,tmp_path/'out',live=False)

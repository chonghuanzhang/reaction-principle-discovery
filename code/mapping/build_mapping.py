#!/usr/bin/env python3
"""Compute input-structure correspondence and limited-evidence novelty summaries.

No network queries or model calls. Outputs are written to the selected directory.
"""
from pathlib import Path
import collections as C
import csv
import hashlib
import json
import re
from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize

import os
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('REACTION_MAPPING_OUTPUT', ROOT/'results/mapping'))
OUT.mkdir(parents=True,exist_ok=True)
STRUCT = ROOT/'data/structures'
NOV = ROOT/'data/novelty/reviewed'
OLD = ROOT/'data/novelty/baseline'
RAW = ROOT/'data/structures'
SOURCES = {}

def read(path, role):
    p=Path(path)
    SOURCES[str(p.relative_to(ROOT))]={'role':role,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
    return json.loads(p.read_text())

def dump(name, data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def csvout(name, rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,keys);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})

def can(s):return Chem.MolToSmiles(Chem.MolFromSmiles(s),isomericSmiles=True)
def parent(s):
    # For identifying PURE protonation/counterion changes only. This never
    # changes the deposited input identity or allows arbitrary precursor cleavage.
    m=Chem.MolFromSmiles(s)
    m=rdMolStandardize.LargestFragmentChooser().choose(m)
    m=rdMolStandardize.Uncharger().uncharge(m)
    return Chem.MolToSmiles(m,isomericSmiles=True)

candidates=read(STRUCT/'candidates.json','current enriched candidate structures and original hypotheses')
actual=read(STRUCT/'actual_pairs.json','current enriched actual inputs, cell-level source records and previous mapping')
nc=read(NOV/'novelty_candidates_100.json','authoritative 2026-10-23 candidate novelty labels')
nh=read(NOV/'novelty_hypotheses_115.json','authoritative 2026-10-23 hypothesis novelty labels')
np=read(NOV/'novelty_product_options_124.json','authoritative 2026-10-23 product-option novelty labels')
na=read(NOV/'novelty_actual_pairs_108.json','authoritative 2026-10-23 actual-pair novelty labels')
oldh=read(OLD/'novelty_hypotheses_115.json','2026-10-21 scores retained for audit comparison')
oldp=read(OLD/'novelty_product_options_124.json','2026-10-21 product-option scores retained for comparison')
queries=read(OLD/'pubchem_identity_results.json','2026-10-21 archived PubChem query responses')
nov_sources=read(NOV/'novelty_sources.json','35 archived novelty evidence references and access levels')
raw=read(RAW/'actual_source_rows.json','2,114 original workbook row occurrences')
old_summary=read(RAW/'actual_structures_summary.json','original 2026-10-21 extraction accounting')
by_num={c['candidate_number']:c for c in candidates}
by_ap={a['actual_pair_id']:a for a in actual}
nov_by_ap={a['actual_pair_id']:a for a in na}
candidate_exact=C.defaultdict(list)
candidate_parent=C.defaultdict(list)
for c in candidates:
    candidate_exact[can(c['candidate_smiles'])].append(c['candidate_number'])
    candidate_parent[parent(c['candidate_smiles'])].append(c['candidate_number'])

classes=['Exact Molecular Match','Structural Analogue','Reactive-form Analogue','Additional Experimental Candidate','Unmatched']
classification_policy={
    'Exact Molecular Match':'Canonical isomeric SMILES are equal, with charge and disconnected counterions retained. This compares donor inputs, not whole reactions or confirmed products.',
    'Structural Analogue':'A documented previous retrospective mapping is chemically interpretable through the proposed bonding atom and donor family; substitution, ring system, acylation or covalent skeleton differs. Additional donor-state changes are recorded separately. This is a relation, not proof of a historical substitution decision.',
    'Reactive-form Analogue':'The same neutral covalent skeleton is recovered after only counterion removal and protonation-state normalization; no substitution/ring changes or arbitrary precursor cleavage are permitted.',
    'Additional Experimental Candidate':'Requires a contemporaneous explicit record that a partner outside the list was deliberately added. No such pair-level decision record was found; therefore no rows receive this label.',
    'Unmatched':'No defensible route-compatible relation in this bounded mapping, or the recorded structure lacks the stated X–H site. Lack of a match does not prove an addition decision or experimental failure.',
    'primary_precedence':'Exact > pure reactive form > structural > explicitly documented addition > unmatched. Other valid edges are retained; primary counts are exclusive.',
    'structural_category_strength':'Broad donor-family / route-compatible association, not a conserved-scaffold or quantitative similarity claim. Substantial topology, substitution and donor-state changes remain explicit.',
    'scope':'Not an exhaustive similarity search. Existing chemically interpretable family mappings are retained and split; pure acid/base form edges are added deterministically. Carbon-site indole/2-naphthol hypotheses are not relabelled as N/O transfer hypotheses.'}

family_reason={
    27:'Pyrrolic N–H is retained, while benzannulation/substitution changes the ring and electronics; only the N-centred pyrrole hypothesis is route-compatible.',
    35:'Imidazole-type N–H centre retained; ring fusion or substitution changes the molecular structure and acid/base environment.',
    38:'Aryl-bound amine N–H is the local analogy; N substitution, ring identity and CF3 electronics differ.',
    39:'Secondary amine N–H is the local analogy; ring topology and/or O-to-C/N replacement change basicity, coordination and steric environment.',
    41:'Amide/lactam N–H is the local analogy; acyl substitution or ring closure changes acidity and resonance. It is not a molecular replacement record.',
    44:'Imide nitrogen remains the proposed bonding centre, but ring saturation and neutral versus potassium salt state both differ; this is not a pure reactive-form match.',
    46:'Secondary amine N–H is retained; ring topology or N/C substitution differs and compatibility is not inherited.',
    48:'An aryl-bound N–H provides the local analogy; secondary/cyclic/diphenyl substitution changes activation and coordination.',
    51:'Hydroxy O attached to an aromatic/conjugated framework provides the O-centre analogy; substituents, heteroaryl tautomerism and competing sites must be evaluated separately.',
    64:'Both framework/substitution and neutral phenol versus sodium phenoxide state can differ; this broad structural analogy does not demonstrate the actual phenoxide population.',
    52:'Alcohol O–H is retained but carbon substitution/saturation differs; a common O centre does not imply equal acidity or capture competence.',
    61:'Alcohol O–H is the local family analogy; chain length, substitution and competing functional groups differ.',
    68:'Aryl S–H is retained; aryl substitution and steric/electronic environment differ.',
    82:'Aryl S–H is retained; aryl substitution and possible competing groups differ.',
    75:'Alkyl/benzylic S–H is retained; carbon substitution and additional functions differ.',
    80:'Alkyl/benzylic S–H is the local analogy; steric environment at carbon and additional functionality differ.'}
unmatched_reason={
    'AP002':'Recorded NH-route partner contains no N–H; route-compatible mapping cannot be assigned.',
    'AP045':'Recorded OH-route partner is a methoxy/bromo naphthalene without O–H; it cannot be mapped as naphthol.',
    'AP058':'The proposed bonding site is carboxylic-acid O; the retained 100-candidate mapping contains no corresponding carboxylic-acid O donor. Alcohol/phenol analogy would erase the site distinction.',
    'AP105':'Recorded SH-route partner is glycidol, which has O–H but no sulfur; an OH analogy cannot validate this SH-route record.'}

def source_ref(o):
    return {k:o.get(k) for k in ['workbook','sheet','row','experiment_id','condition_id','normalization_note']}

mapping=[];edge_rows=[]
for a in actual:
    aid=a['actual_pair_id'];old=a['candidate_mapping'];route_center=a['route'][0]
    exact=candidate_exact.get(can(a['partner_smiles']),[])
    reactive=[n for n in candidate_parent.get(parent(a['partner_smiles']),[]) if n not in exact and route_center in by_num[n]['centers']]
    structural=[n for n in old['analogue_candidate_numbers'] if n not in exact+reactive]
    if aid=='AP066':
        structural=sorted(set(structural+[52,61]))  # Its archived O01 option is the alcohol-O branch.
    links=[]
    for rel,nums in [('Exact Molecular Match',exact),('Reactive-form Analogue',reactive),('Structural Analogue',structural)]:
        for n in nums:
            c=by_num[n]
            compatible=[h['hypothesis_id'] for h in c['original_generation_hypotheses'] if h['center']==route_center]
            if rel=='Structural Analogue':assert compatible,(aid,n)
            reason=family_reason.get(n,'Same recorded donor input structure.') if rel=='Structural Analogue' else ('Identical recorded donor molecular structure; no selection history is implied.' if rel=='Exact Molecular Match' else 'Neutral covalent skeleton is identical after protonation/counterion normalization; reactive population under the experimental conditions is unmeasured.')
            link={'candidate_number':n,'candidate_display_id':c['display_id'],'candidate_id':c['candidate_id'],'candidate_name_en':c['name_en'],'candidate_smiles':c['candidate_smiles'],'relation':rel,'route_center':route_center,'route_compatible_original_hypothesis_ids':compatible,'reason':reason,'neutral_parent_equal':parent(c['candidate_smiles'])==parent(a['partner_smiles']),'formal_charge_candidate':sum(x.GetFormalCharge() for x in Chem.MolFromSmiles(c['candidate_smiles']).GetAtoms()),'formal_charge_actual':sum(x.GetFormalCharge() for x in Chem.MolFromSmiles(a['partner_smiles']).GetAtoms()),'candidate_NP_labels_preserved':c['NP_results'],'candidate_NR_labels_preserved':c['NR_results'],'historical_selection_edge_status':'not recorded'}
            link['analogue_strength']='broad local donor-family association; no quantitative similarity threshold or conserved-scaffold requirement' if rel=='Structural Analogue' else 'exact graph / identical neutral skeleton as stated'
            link['applicable_archived_product_option_ids']=([aid+'-O02'] if aid in ['AP064','AP066'] and n in [51,64] else [aid+'-O01'] if aid=='AP066' and n in [52,61] else [p['option_id'] for p in nov_by_ap[aid]['options']])
            link['mapping_origin']='retained previous retrospective family association' if n in old['analogue_candidate_numbers'] else '2026-10-26 canonical/neutral-parent check or explicit archived endpoint audit'
            links.append(link);edge_rows.append({'actual_pair_id':aid,**link})
    primary='Exact Molecular Match' if exact else 'Reactive-form Analogue' if reactive else 'Structural Analogue' if structural else 'Unmatched'
    assert primary!='Unmatched' or aid in unmatched_reason
    inventory={k:'not recorded' for k in ['inventory_or_availability','toxicity_or_safety_decision','procurement_lead_time','reagent_cost','contemporaneous_compatibility_decision','decision_date','decision_maker','original_candidate_selected_or_replaced']}
    mapping.append({'actual_pair_id':aid,'route':a['route'],'electrophile_smiles':can(a['electrophile_smiles']),'actual_donor_smiles':can(a['partner_smiles']),'partner_cas_recorded':a['partner_cas'],'partner_family_en':a['partner_family_en'],'primary_mapping_class':primary,'exact_candidate_numbers':exact,'reactive_form_candidate_numbers':reactive,'structural_analogue_candidate_numbers':structural,'candidate_links':links,'unmatched_reason':unmatched_reason.get(aid),'unmapped_product_option_ids':['AP064-O01'] if aid=='AP064' else [],'human_in_the_loop_decision':inventory,'mapping_interpretation':'2026-10-26 retrospective structural audit; not a recovered candidate-selection event','previous_mapping':old,'execution_status':a['execution_status'],'execution_evidence_source':a['execution_evidence_source'],'source_occurrences':list(map(source_ref,a['source_occurrences'])),'source_occurrence_count':len(a['source_occurrences']),'unique_condition_recipe_count':len(a['unique_condition_recipes']),'sample_ids':a['sample_ids'],'input_identity_status':a['input_identity_status'],'input_identity_issues':a['input_identity_issues'],'product_identity_status':a['product_identity_status'],'quantitative_result_status':a['quantitative_result_status'],'NP_label_preserved':nov_by_ap[aid]['NP_label'],'NR_preserved':nov_by_ap[aid]['NR'],'novelty_comparison_scope':'Proposed product(s) and reaction(s) conditional on recorded inputs; not novelty of the reagent itself.'})

dump('mapping_108.json',mapping)
csvout('mapping_108.csv',[{k:v for k,v in r.items() if k not in ['source_occurrences','candidate_links','previous_mapping']}|{'source_locations':r['source_occurrences'],'previous_mapping':r['previous_mapping']} for r in mapping])
csvout('mapping_edges.csv',edge_rows)
dump('mapping_policy.json',classification_policy)
dump('previous_mapping_108.json',[{'actual_pair_id':a['actual_pair_id'],'previous_mapping':a['candidate_mapping']} for a in actual])

groups=C.defaultdict(list)
for r in raw:
    key=(r['route'],r['experiment_id'],r['row']) if r['plate_well'] else (r['workbook'],r['sheet'],r['row'])
    groups[key].append(r)
conflicts=[list(k) for k,v in groups.items() if len({(x['electrophile_smiles'],x['partner_smiles']) for x in v})>1]
donors=C.defaultdict(list);acceptors=C.defaultdict(list);pairs=C.defaultdict(list)
for a in mapping:
    donors[a['actual_donor_smiles']].append(a)
    acceptors[a['electrophile_smiles']].append(a['actual_pair_id'])
    pairs[(a['electrophile_smiles'],a['actual_donor_smiles'])].append(a['actual_pair_id'])
donor_rows=[]
for i,(sm,rows) in enumerate(sorted(donors.items()),1):
    donor_rows.append({'actual_donor_id':f'NU{i:03d}','smiles':sm,'pair_ids':[r['actual_pair_id'] for r in rows],'n_distinct_pairs':len(rows),'primary_mapping_classes':sorted({r['primary_mapping_class'] for r in rows}),'exact_candidate_numbers':sorted({n for r in rows for n in r['exact_candidate_numbers']}),'reactive_form_candidate_numbers':sorted({n for r in rows for n in r['reactive_form_candidate_numbers']}),'structural_candidate_numbers':sorted({n for r in rows for n in r['structural_analogue_candidate_numbers']}),'decision_status':'not recorded'})
mol_summary={'candidate_rows':len(candidates),'distinct_candidate_structures':len(candidate_exact),'duplicate_candidate_structures':[v for v in candidate_exact.values() if len(v)>1],'actual_distinct_donor_structures':len(donors),'actual_distinct_electrophile_structures':len(acceptors),'exact_candidate_molecule_intersection':sorted({n for r in mapping for n in r['exact_candidate_numbers']}),'distinct_actual_donors_by_primary_class':{k:sum(k in d['primary_mapping_classes'] for d in donor_rows) for k in classes},'actual_donors':donor_rows,'multiple_electrophile_donors':[d for d in donor_rows if d['n_distinct_pairs']>1],'candidate_mapping_edge_counts':dict(C.Counter(e['candidate_number'] for e in edge_rows)),'molecular_identity_rule':'RDKit canonical isomeric SMILES; salts and charges retained. A neutral-parent key is used only for separate reactive-form edges.'}
combo_summary={'actual_pair_rows':len(mapping),'distinct_ordered_electrophile_donor_pairs':len(pairs),'duplicate_pair_groups':[v for v in pairs.values() if len(v)>1],'primary_mapping_class_counts':{k:sum(r['primary_mapping_class']==k for r in mapping) for k in classes},'relation_edge_counts_nonexclusive':dict(C.Counter(r['relation'] for r in edge_rows)),'pairs_by_route':dict(C.Counter(r['route'] for r in mapping)),'source_row_occurrences':len(raw),'deduplicated_sample_row_groups':len(groups),'row_group_multiplicities':dict(C.Counter(len(v) for v in groups.values())),'duplicate_source_occurrences_beyond_one_per_group':len(raw)-len(groups),'workbook_occurrence_counts':dict(C.Counter(r['workbook'] for r in raw)),'within_sample_row_group_structure_conflicts':conflicts,'record_unit_note':'2,114 occurrences comprise 1,048 groups duplicated between two workbooks plus 18 single occurrences. Grouping follows the archived extraction key (route, experiment_id, original row when plate/well exists; otherwise workbook, sheet, row). This is not a count of independent replicate experiments. 1,064 distinct archived condition recipes are a different unit and are not used to collapse the 108 molecular pairs.','unique_condition_recipes_sum':sum(r['unique_condition_recipe_count'] for r in mapping),'author_execution_confirmation':'2026-10-23, as recorded in the archived review; distinct from independently verified product identities/yields','reduction_to_100_supported':False,'reason':'All 108 recorded ordered structure pairs differ. Repeated conditions/rows have already been separated from molecular-pair counting; deleting eight pairs would discard distinct archived combinations.','electrophiles':[{'smiles':s,'pair_ids':ids} for s,ids in sorted(acceptors.items())]}
dump('molecule_summary.json',mol_summary);dump('combination_summary.json',combo_summary)
csvout('actual_donors_102.csv',donor_rows)

def lab(v):return 'unresolved' if v is None or v=='待核' else 'not applicable' if v=='不适用' else str(v)
def dist(rows,key):return dict(C.Counter(lab(r.get(key)) for r in rows))
def setlabel(values):return ' | '.join(sorted({lab(x) for x in values}))
candidate_sets=[{'candidate_number':c['candidate_number'],'candidate_name_en':by_num[c['candidate_number']]['name_en'],'centres':c['centers'],'NP_preserved':c['NP_results'],'NR_preserved':c['NR_results'],'NP_label_set':setlabel(c['NP_results']),'NR_label_set':setlabel(c['NR_results']),'hypothesis_count':c['hypothesis_count']} for c in nc]
csvout('novelty_candidates_100_preserved.csv',candidate_sets)
dump('novelty_candidates_100_preserved.json',nc)
dump('novelty_hypotheses_115_preserved.json',nh)
dump('novelty_product_options_124_preserved.json',np)
dump('novelty_actual_pairs_108_preserved.json',na)
csvout('novelty_hypotheses_115_preserved.csv',nh)
csvout('novelty_product_options_124_preserved.csv',np)
actual_options=[p for a in na for p in a['options']]
by_center=[]
for centre in ['C','N','O','S','P','Se']:
    hs=[h for h in nh if h['center']==centre]
    cs=[c for c in nc if centre in c['centers']]
    by_center.append({'centre':centre,'candidate_molecules_nonexclusive':len(cs),'hypotheses':len(hs),'NP_hypotheses':dist(hs,'NP_label'),'NR_hypotheses':dist(hs,'NR'),'candidate_NP_label_sets':dict(C.Counter(setlabel(c['NP_results']) for c in cs))})
by_route=[]
for route in ['NH','OH','SH','PH']:
    rs=[a for a in na if a['route']==route]
    by_route.append({'route':route,'pair_count':len(rs),'distinct_donors':len({can(a['partner_smiles']) for a in rs}),'NP_pairs':dist(rs,'NP_label'),'NR_pairs':dist(rs,'NR')})
defs={'NP':{'name':'product novelty','levels':{'1R':'Exact product connectivity registered or directly reported; R specifically identifies a database connectivity registration.','1T':'Only a registered standardized tautomeric relationship; not identical bond-order graph.','2':'Exact match not found in the bounded search, but key connectivity and nearby scaffold have primary precedents.','3':'No matching key connectivity/charge endpoint precedent in the searched scope.','unresolved':'Evidence insufficient to assign a level; retained, never imputed as zero.','not applicable':'Recorded input lacks the route-required site; not a novelty score or failure.'},'scope':'Proposed product connectivity/parent scaffold; no claim about stereochemical firstness or novelty of the purchased reagent.'},'NR':{'name':'reaction novelty','levels':{'1':'Same starting-substrate class, donor form and net transformation reported; original rubric allows an HRMS-supported proposed intermediate, which must be distinguished from an isolated product.','2':'Extension of a known reaction in substrate framework, donor or activation method.','3':'No matching target substrate–partner sequence established in the bounded search.','unresolved':'Endpoint-specific comparison unresolved.','range':'Alternative endpoints retain their separate labels, e.g. 2–3; no averaging.'},'scope':'Starting substrate class, reactive donor form, net bond changes, endpoint and method; kept separate from NP.'},'calculation':'Evidence-based ordinal classification using archived structure queries and nearest-precedent comparisons. Not an arithmetic score; NP and NR are not added, averaged or converted into a success probability.'}
retention={'estimable':False,'reason':'No contemporaneous candidate-to-experiment selection/replacement chain or paired before/after choice records were recovered. Candidate hypothetical products and actual-input hypothetical products can also differ in electrophile and endpoint. Marginal distributions are descriptive and cannot identify retention or improvement attributable to Human-in-the-loop Evaluation.','exact_overlap_descriptive_only':[{'actual_pair_id':a['actual_pair_id'],'candidate_numbers':a['exact_candidate_numbers'],'actual_NP':a['NP_label_preserved'],'actual_NR':a['NR_preserved'],'electrophile_differs_from_candidate_seed':a['electrophile_smiles']!=can('O=C(CC(F)(F)F)c1ccccc1')} for a in mapping if a['exact_candidate_numbers']],'success_association':'Not established: putative product identities and calibrated quantitative results are not uniformly verified; novelty is not a success probability.'}
novel_summary={'audit_date':'2026-10-26','score_version':'2026-10-23-review-revision-v1','initial_assessment_date':'2026-10-21','review_date':'2026-10-23','new_scoring_performed':False,'definitions':defs,'data_sources_and_scope':{'registry':'PubChem PUG REST same_connectivity; 202 stored query responses dated 2026-10-21','literature':'Project literature collection and logged Crossref, Europe PMC and OpenAlex searches; accessible main text, SI, figures, author abstracts and patent abstracts were assessed at their available evidence level.','comprehensive_databases_not_used':['complete SciFinder reaction search','complete Reaxys reaction search','exhaustive patent structure search'],'novelty_reference_records':len(nov_sources),'access_levels':dict(C.Counter(s.get('access_level',s.get('evidence_level','not recorded')) for s in nov_sources)),'recorded_query_dates':sorted({q['date'] for q in queries}),'recorded_query_statuses':dict(C.Counter(q['status'] for q in queries)),'time_interpretation':'The 21 October assessment and 23 October review are dated evidence audits. Their position after candidate generation cannot be recast as proof that these scores drove the original experiments.'},'units':{'candidate_molecules':100,'candidate_hypotheses':115,'candidate_product_options':124,'distinct_candidate_product_smiles':len({p['product_smiles'] for p in np}),'experimental_pairs':108,'experimental_donor_structures':102,'experimental_applicable_pairs':sum(a['NP_label']!='不适用' for a in na),'experimental_product_options':len(actual_options),'distinct_experimental_product_smiles':len({p['product_smiles'] for p in actual_options}),'combined_queried_product_structures':len(queries)},'candidate_molecule_NP_label_set_distribution':dict(C.Counter(r['NP_label_set'] for r in candidate_sets)),'candidate_molecule_NR_label_set_distribution':dict(C.Counter(r['NR_label_set'] for r in candidate_sets)),'candidate_hypothesis_NP':dist(nh,'NP_label'),'candidate_hypothesis_NR':dist(nh,'NR'),'candidate_product_option_NP':dist(np,'NP_label'),'candidate_product_option_NR':dist(np,'NR'),'experimental_pair_NP':dist(na,'NP_label'),'experimental_pair_NR':dist(na,'NR'),'experimental_product_option_NP':dist(actual_options,'NP_label'),'experimental_product_option_NR':dist(actual_options,'NR'),'candidate_by_centre':by_center,'experimental_by_route':by_route,'old_2026_10_21_hypothesis_NP':dist(oldh,'NP_label'),'old_2026_10_21_product_option_NP':dist(oldp,'NP_label'),'retention_and_success':retention,'special_cases':{'candidate_035':'Both imidazole protonation states retained at parent-connectivity NP2 in the revised audit; salt-form novelty unresolved.','candidate_086':'All three phosphorus endpoints have NP unresolved in the revised audit; NR3 is retained.','AP064':'Carboxyl-O and phenolic-O options retain NP3/NP2 and NR3/NR2 separately; aggregated 3/2 and 2–3 are not scalar scores.','AP043':'Registered NP1R; NR is unresolved after recognizing direct trifluoropropanamide/indole prior art, pending the specific endpoint comparison.','not_applicable_pairs':['AP002','AP045','AP105']}}
dump('novelty_summary.json',novel_summary)
flat=[]
for universe,rows,npkey,nrkey in [('candidate_hypothesis',nh,'NP_label','NR'),('candidate_product_option',np,'NP_label','NR'),('experimental_pair',na,'NP_label','NR'),('experimental_product_option',actual_options,'NP_label','NR')]:
    for dim,key in [('NP',npkey),('NR',nrkey)]:
        for label,n in dist(rows,key).items():flat.append({'universe':universe,'dimension':dim,'label':label,'count':n,'denominator':len(rows),'version':'2026-10-23-review-revision-v1'})
for dim,key in [('NP','NP_label_set'),('NR','NR_label_set')]:
    for label,n in C.Counter(r[key] for r in candidate_sets).items():flat.append({'universe':'candidate_molecule_preserved_label_set','dimension':dim,'label':label,'count':n,'denominator':100,'version':'2026-10-23-review-revision-v1'})
csvout('novelty_summary.csv',flat)

# Workbook notes establish use as a model, not the reason/time of initial choice.
representatives=[]
for name,ids,model,nums,rationale in [
    ('Indoline',['AP039','AP044'],'AP039',[48],'A secondary aryl-bound cyclic N–H donor. It is structurally related to the aryl-amine candidate family, but saturation, N substitution and coordination differ; it is not identical to aniline or to the C-centred indole candidate.'),
    ('1-Naphthol',['AP047','AP048','AP049'],'AP048',[51,64],'A phenolic O–H donor on a fused aromatic framework. It probes O-centred capture and donor-state control; the 2-naphthol candidate was generated with a C-centred hypothesis and cannot be silently relabelled as the same O route.'),
    ('4-tert-Butylbenzenethiol',['AP090'],'AP090',[68,82],'A neutral aryl S–H donor structurally related to benzenethiol and 4-bromobenzenethiol. The para tert-butyl group changes electronics, sterics and physical properties; no historical procurement rationale was recovered.')]:
    notes=[]
    for aid in ids:
        for o in by_ap[aid]['source_occurrences']:
            ns=o['characterization_notes_original']
            if ns:notes.append({'actual_pair_id':aid,**source_ref(o),'notes':ns})
    representatives.append({'name':name,'actual_pair_ids':ids,'condition_screen_model_pair':model,'retrospective_candidate_relations':nums,'chemical_representativeness':rationale,'representativeness_evidence_status':'Structural interpretation only; not evidence of the original selection rationale.','model_use_recorded':any('模版反应' in str(n) for n in notes),'initial_choice_reason':'not recorded','inventory':'not recorded','toxicity':'not recorded','lead_time':'not recorded','cost':'not recorded','dated_selection_chain':'not recorded','source_notes':notes,'input_identity_issues_by_pair':{aid:by_ap[aid]['input_identity_issues'] for aid in ids},'outcome_limit':'Workbook notes sometimes report target formation, NMR/HRMS characterization, or a yield value, and other notes state that spectra or NMR yields are planned. These are retained as author records; they are not a uniformly sample-linked independent product-identity and calibrated-yield audit.'})
dump('representative_selection_audit.json',representatives)

assert len(candidates)==len(candidate_exact)==100
assert len(mapping)==len(pairs)==108 and len(donors)==102 and len(acceptors)==5
assert len(raw)==2114 and len(groups)==1066 and not conflicts
assert sum(combo_summary['primary_mapping_class_counts'].values())==108
assert sum(novel_summary['candidate_hypothesis_NP'].values())==115
assert sum(novel_summary['experimental_pair_NP'].values())==108
assert all(r['execution_status']=='executed' for r in mapping)
print(json.dumps({'mapping':combo_summary['primary_mapping_class_counts'],'molecule_mapping':mol_summary['distinct_actual_donors_by_primary_class'],'candidate_NP':novel_summary['candidate_molecule_NP_label_set_distribution'],'candidate_NR':novel_summary['candidate_molecule_NR_label_set_distribution'],'hypothesis_by_centre':by_center},ensure_ascii=False,indent=2))

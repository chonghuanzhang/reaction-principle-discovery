#!/usr/bin/env python3
"""Check identifiers, table relationships and links in the research companion."""
from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'optimization/scripts'))
from source_workbook import check_current_sources


def is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def table(name, expected):
    path = ROOT / name
    assert b'\x00' not in path.read_bytes(), f'Nonprinting NUL in {name}'
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == expected, (name, len(rows), expected)
    return rows


def main():
    sources = table('literature/catalog.csv', 370)
    source_ids = {row['source_id'] for row in sources}
    assert source_ids == {f'L{i:03}' for i in range(1, 371)}
    bibliography = table('literature/bibliography.csv', 403)
    assert {int(row['reference_number']) for row in bibliography} == set(range(1, 404))
    statements = table('literature/evidence_statements.csv', 3756)
    assert all(row['source_id'] in source_ids for row in statements)
    assert len({row['statement_id'] for row in statements}) == len(statements)
    quotations = table('evidence/quotation_records.csv', 43)
    assert {row['quotation_id'] for row in quotations} == {f'Q{i:02}' for i in range(1, 44)}
    assert all(row['source_id'] in source_ids for row in quotations)
    table('evidence/source_cases.csv', 17)
    applicability = table('evidence/applicability_records.csv', 25)
    assert len({row['source_id'] for row in applicability}) == 9
    assert all(row['source_id'] in source_ids for row in applicability)

    molecules = table('candidates/data/candidates_100.csv', 100)
    molecule_ids = {row['display_id'] for row in molecules}
    assert molecule_ids == {f'C{i:03}' for i in range(1, 101)}
    assert len({row['canonical_smiles'] for row in molecules}) == 100
    assert Counter(row['allocation'] for row in molecules) == {'recommended': 100}
    assert Counter(row['best_relationship_category'] for row in molecules) == {
        'Exact identity': 25,
        'Same scaffold, substituent or positional variation': 31,
        'Same donor family, different scaffold': 41,
        'No reasonable counterpart': 3}
    hypotheses = table('candidates/data/hypotheses_103.csv', 103)
    hypothesis_ids = {row['hypothesis_id'] for row in hypotheses}
    assert len(hypothesis_ids) == 103
    assert all(row['display_id'] in molecule_ids for row in hypotheses)
    options = table('candidates/product_options/product_options_103.csv', 103)
    assert len({row['option_id'] for row in options}) == 103
    assert all(row['display_id'] in molecule_ids for row in options)
    assert all(row['hypothesis_id'] in hypothesis_ids for row in options)
    table('candidates/product_options/table_R2.csv', 103)
    pairs = table('candidates/experiment_mapping/mapping_112.csv', 112)
    pair_ids = {row['actual_pair_id'] for row in pairs}
    assert len(pair_ids) == 112
    assert len({row['actual_donor_smiles'] for row in pairs}) == 102
    assert Counter(row['primary_relationship_category'] for row in pairs) == {
        'Exact identity': 27,
        'Same scaffold, substituent or positional variation': 39,
        'Same donor family, different scaffold': 42,
        'No reasonable counterpart': 4}
    relations = table('candidates/experiment_mapping/relations.csv', 219)
    assert all(row['actual_pair_id'] in pair_ids for row in relations)
    assert all(row['candidate_display_id'] in molecule_ids for row in relations)
    table('candidates/experiment_mapping/table_R1.csv', 112)

    table('experiments/condition_library/components.csv', 20)
    campaign_summary = json.loads((ROOT / 'optimization/current/protocol.json').read_text())['campaigns']
    selected_counts = {row['system']: row['unique_conditions'] for row in campaign_summary}
    selected = table('experiments/selected_responses/selected_responses.csv', sum(selected_counts.values()))
    assert Counter(row['system'] for row in selected) == selected_counts == {'NH':60, 'OH':56, 'SH':48}
    assert len({(row['system'], row['candidate_index']) for row in selected}) == len(selected)
    source_check = check_current_sources()
    for system in selected_counts:
        candidates=table(f'optimization/current/data/{system}/candidate_space.csv',13920)
        assert len({(r['catalyst_index'],r['solvent_index'],r['base_index']) for r in candidates})==13920
    table('optimization/current/data/catalyst_ligand_formulations.csv',145)
    table('experiments/bo_trajectories/round_by_round_stopping.csv',35)

    graph = json.loads((ROOT/'knowledge_graph/data/network.json').read_text(encoding='utf-8'))
    graph_ids = {node['id'] for node in graph['nodes']}
    assert len(graph_ids) == len(graph['nodes']) == 164
    assert Counter(node['kind'] for node in graph['nodes']) == {
        'evidence': 17, 'principle': 4, 'family': 43, 'candidate': 100}
    assert {node['id'] for node in graph['nodes'] if node['kind'] == 'candidate'} == molecule_ids
    assert len({edge['id'] for edge in graph['edges']}) == len(graph['edges']) == 291
    assert Counter(edge['kind'] for edge in graph['edges']) == {
        'source_to_principle': 19, 'principle_to_family': 172, 'family_membership': 100}
    assert all(edge['source'] in graph_ids and edge['target'] in graph_ids for edge in graph['edges'])
    assert set(graph['source_register']) == source_ids
    citations = graph['candidate_citation_links']
    assert len(citations) == 170
    assert len({link['candidate_id'] for link in citations}) == 75
    assert all(link['candidate_id'] in molecule_ids and link['catalog_id'] in source_ids for link in citations)
    tiers = json.loads((ROOT/'knowledge_graph/data/tier_summary.json').read_text(encoding='utf-8'))
    assert {tier['tier']: tier['corpus_source_count'] for tier in tiers} == {1: 139, 2: 101, 3: 88, 4: 42}
    assert all(len(tier['corpus_source_ids']) == tier['corpus_source_count'] for tier in tiers)
    tier_source_ids = [source_id for tier in tiers for source_id in tier['corpus_source_ids']]
    assert len(tier_source_ids) == len(set(tier_source_ids)) == len(source_ids)
    assert set(tier_source_ids) == source_ids
    for number in range(1, 10):
        assert (ROOT/f'knowledge_graph/figures/G{number}.png').is_file()
    for number in range(1, 5):
        assert (ROOT/f'knowledge_graph/figures/RP{number}_focus.png').is_file()
    assert (ROOT/'candidates/figures/N1_novelty_distributions.png').is_file()

    composition = json.loads((ROOT/'figures/source/Figure_4_composition.json').read_text(encoding='utf-8'))
    assert composition['canvas_px'] == [2096, 2148]
    assert set(composition['panels']) == set('abcde')
    asset = composition['authoritative_master']
    path = (ROOT/asset['path']).resolve()
    assert is_within(path, ROOT), asset['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset['sha256'], asset['path']
    for key in ['source_data', 'vector_pdf', 'vector_svg']:
        assert (ROOT/composition[key]).is_file(), key
    representatives = json.loads((ROOT/composition['representative_source']).read_text(encoding='utf-8'))
    assert representatives['figure'] == 'Figure 4b'
    assert set(representatives['public_ids']) <= molecule_ids
    assert representatives['nucleophile_centres'] == dict(Counter(row['center'] for row in molecules))
    assert representatives['source'] == 'candidates/data/candidates_100.json'
    assert hashlib.sha256((ROOT/representatives['source']).read_bytes()).hexdigest() == representatives['sha256']

    asset_manifest = json.loads((ROOT/'figures/current_asset_manifest.json').read_text(encoding='utf-8'))
    assert asset_manifest['candidate_source'] == 'candidates/data/candidates_100.json'
    assert (ROOT/asset_manifest['candidate_source']).is_file()
    for asset in asset_manifest['assets']:
        asset_path = (ROOT/asset['path']).resolve()
        assert is_within(asset_path, ROOT), asset['path']
        assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == asset['sha256'], asset['path']

    # Check human-facing pages and illustrations; internal code fixtures may
    # intentionally contain example paths that are not repository resources.
    pages = list(ROOT.glob('*.md'))
    for folder in ['docs', 'literature', 'evidence', 'candidates', 'experiments', 'figures', 'knowledge_graph', 'skills']:
        pages.extend((ROOT/folder).rglob('*.md'))
    for name in ['code/README.md', 'code/METHODS.md', 'optimization/README.md', 'optimization/METHODS.md', 'optimization/FIGURE_GUIDE.md']:
        pages.append(ROOT/name)
    checked = 0
    for path in pages:
        content = path.read_text(encoding='utf-8')
        content = re.sub(r'```.*?```', '', content, flags=re.S)
        content = re.sub(r'`[^`]*`', '', content)
        links = re.findall(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)', content)
        links += re.findall(r'(?:src|href)=["\']([^"\']+)', content)
        for link in links:
            target = unquote(urlsplit(link.strip('<>')).path)
            if not target or urlsplit(link).scheme or link.startswith('//'):
                continue
            resolved = (path.parent/target).resolve()
            assert is_within(resolved, ROOT), (str(path.relative_to(ROOT)), link)
            assert resolved.exists(), (str(path.relative_to(ROOT)), link)
            checked += 1
    print(json.dumps({
        'literature_sources': 370, 'bibliography_references': 403,
        'source_statements': 3756, 'quotations': 43, 'source_cases': 17,
        'recommended_molecules': 100, 'hypotheses': 103, 'product_options': 103,
        'experimental_pairs': 112, 'condition_components': 20,
        'selected_responses': len(selected),
        'measured_source_conditions': source_check['measured_candidates_verified'],
        'knowledge_graph_nodes': 164, 'knowledge_graph_edges': 291,
        'knowledge_graph_views': 9, 'si_principle_focus_views': 4,
        'figure_4_master_checksum': 'verified',
        'local_links_checked': checked, 'status': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Check identifiers, table relationships and links in the research companion."""
from collections import Counter
from pathlib import Path
from statistics import median, mean
import csv
import json
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


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
    assert Counter(row['allocation'] for row in molecules) == {'working': 48, 'reserve': 52}
    hypotheses = table('candidates/data/hypotheses_115.csv', 115)
    hypothesis_ids = {row['hypothesis_id'] for row in hypotheses}
    assert len(hypothesis_ids) == 115
    assert all(row['display_id'] in molecule_ids for row in hypotheses)
    options = table('candidates/product_options/product_options_124.csv', 124)
    assert len({row['option_id'] for row in options}) == 124
    assert all(row['display_id'] in molecule_ids for row in options)
    assert all(row['hypothesis_id'] in hypothesis_ids for row in options)
    table('candidates/product_options/table_R2.csv', 124)
    pairs = table('candidates/experiment_mapping/mapping_108.csv', 108)
    pair_ids = {row['actual_pair_id'] for row in pairs}
    assert len(pair_ids) == 108
    assert Counter(row['primary_mapping_class'] for row in pairs) == {
        'Exact Molecular Match': 3, 'Structural Analogue': 101, 'Unmatched': 4}
    relations = table('candidates/experiment_mapping/relations.csv', 177)
    assert all(row['actual_pair_id'] in pair_ids for row in relations)
    assert all(row['candidate_display_id'] in molecule_ids for row in relations)
    table('candidates/experiment_mapping/table_R1.csv', 108)

    table('experiments/condition_library/components.csv', 20)
    budgets = table('experiments/bo_benchmark/paired_first_hit_budgets.csv', 100)
    assert {int(row['seed']) for row in budgets} == set(range(5000, 5100))
    bo = [int(row['bo_exact_budget']) for row in budgets]
    random = [int(row['random_exact_budget']) for row in budgets]
    assert all(value in range(12, 97, 12) for value in bo + random)
    assert (median(bo), median(random)) == (24, 48)
    assert abs(mean(b-a for a, b in zip(bo, random))-25.8) < 1e-10
    selected = table('experiments/selected_responses/selected_responses.csv', 180)
    assert Counter(row['pool_id'] for row in selected) == {
        'NH_PL36': 60, 'OH_PL37': 60, 'OH_PL38': 60}
    assert len({(row['pool_id'], row['base'], row['solvent']) for row in selected}) == 180

    graph = json.loads((ROOT/'knowledge_graph/data/network.json').read_text(encoding='utf-8'))
    graph_ids = {node['id'] for node in graph['nodes']}
    assert len(graph_ids) == len(graph['nodes']) == 133
    assert Counter(node['kind'] for node in graph['nodes']) == {
        'evidence': 17, 'principle': 4, 'family': 12, 'candidate': 100}
    assert {node['id'] for node in graph['nodes'] if node['kind'] == 'candidate'} == molecule_ids
    assert len({edge['id'] for edge in graph['edges']}) == len(graph['edges']) == 142
    assert Counter(edge['kind'] for edge in graph['edges']) == {
        'source_to_principle': 19, 'principle_to_family': 23, 'family_membership': 100}
    assert all(edge['source'] in graph_ids and edge['target'] in graph_ids for edge in graph['edges'])
    assert set(graph['source_register']) == source_ids
    citations = graph['candidate_citation_links']
    assert len(citations) == 53
    assert len({link['candidate_id'] for link in citations}) == 46
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

    # Check human-facing pages and illustrations; internal code fixtures may
    # intentionally contain example paths that are not repository resources.
    pages = list(ROOT.glob('*.md'))
    for folder in ['docs', 'literature', 'evidence', 'candidates', 'experiments', 'figures', 'knowledge_graph']:
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
            assert resolved.is_relative_to(ROOT), (str(path.relative_to(ROOT)), link)
            assert resolved.exists(), (str(path.relative_to(ROOT)), link)
            checked += 1
    print(json.dumps({
        'literature_sources': 370, 'bibliography_references': 403,
        'source_statements': 3756, 'quotations': 43, 'source_cases': 17,
        'recommended_molecules': 100, 'hypotheses': 115, 'product_options': 124,
        'experimental_pairs': 108, 'condition_components': 20,
        'paired_benchmark_seeds': 100, 'selected_responses': 180,
        'knowledge_graph_nodes': 133, 'knowledge_graph_edges': 142,
        'knowledge_graph_views': 9, 'si_principle_focus_views': 4,
        'local_links_checked': checked, 'status': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()

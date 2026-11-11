"""Two supporting BO composites from unchanged archived CSV values.

No models are fitted and no policy is rerun.
"""
from pathlib import Path
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('REACTION_FIGURE_OUTPUT',ROOT/'results/figures'))
FIG = OUT / 'figures'
QA = OUT / 'qa'
for path in (FIG, QA):
    path.mkdir(parents=True, exist_ok=True)
os.environ['MPLCONFIGDIR'] = '/tmp/bo_paper_supporting_mplconfig'
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle, Patch
from matplotlib.ticker import MaxNLocator

BLUE = '#204DA0'
CYAN = '#2FA4C3'
TEAL = '#5EC0C1'
GREEN = '#268773'
PURPLE = '#9865B4'
GOLD = '#D99329'
INK = '#1D2730'
GREY = '#66717A'
PALE = '#DFE7EC'
ARCH = ROOT / 'benchmark/data'
PRIOR = ROOT / 'figures'
AUDIT = ROOT / 'figures/source_data'
POOLS = [('NH_PL36', 'N–H', 'UV response', BLUE, 6000),
         ('OH_CuNi_96', 'O–H', 'UV response', GREEN, 8000)]
inputs = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, predicate=None):
    inputs.append(Path(path))
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return [r for r in csv.DictReader(f) if predicate is None or predicate(r)]


def read_json(path):
    inputs.append(Path(path))
    return json.loads(Path(path).read_text())


for path in (PRIOR / 'qa/fonts').glob('Helvetica-*.ttf'):
    font_manager.fontManager.addfont(str(path))
plt.rcParams.update({
    'font.family': os.environ.get('REACTION_FONT','DejaVu Sans'), 'font.size': 7.5,
    'text.color': INK, 'axes.labelcolor': INK, 'axes.edgecolor': INK,
    'axes.labelsize': 7.5, 'axes.linewidth': .65,
    'axes.spines.top': True, 'axes.spines.right': True,
    'xtick.color': INK, 'ytick.color': INK,
    'xtick.labelsize': 6.8, 'ytick.labelsize': 6.8,
    'xtick.major.width': .6, 'ytick.major.width': .6,
    'xtick.major.size': 2.6, 'ytick.major.size': 2.6,
    'legend.frameon': False, 'legend.fontsize': 6.5,
    'pdf.fonttype': 42, 'svg.fonttype': 'none',
    'savefig.facecolor': 'white', 'figure.facecolor': 'white',
    'mathtext.fontset': 'custom', 'mathtext.rm': os.environ.get('REACTION_FONT','DejaVu Sans'),
    'mathtext.it': os.environ.get('REACTION_FONT','DejaVu Sans')+':italic', 'mathtext.bf': os.environ.get('REACTION_FONT','DejaVu Sans')+':bold',
})


def clean(ax):
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(INK)
        spine.set_linewidth(.65)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.tick_params(direction='in', top=True, right=True, pad=3)


def letter(ax, value, x=-.14):
    ax.text(x, 1.035, value, transform=ax.transAxes, fontsize=10.5,
            fontweight='bold', ha='left', va='bottom')


def save(fig, stem, dimensions_mm):
    fig.canvas.draw()
    for ext in ('pdf', 'svg', 'png'):
        fig.savefig(FIG / f'{stem}.{ext}', dpi=600)
    fig.savefig(QA / f'{stem}_preview.png', dpi=170)
    plt.close(fig)
    pdf = FIG / f'{stem}.pdf'
    # Render the actual PDF for the preview, retaining a matching stable name.
    poppler = shutil.which('pdftoppm')
    if poppler:
        subprocess.run([poppler, '-singlefile', '-r', '170', '-png', str(pdf), str(QA / f'{stem}_preview')], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {'stem': stem, 'dimensions_mm': dimensions_mm,
            'exports': [{'path': str((FIG / f'{stem}.{ext}')),
                         'sha256': sha(FIG / f'{stem}.{ext}')} for ext in ('pdf', 'svg', 'png')],
            'preview': str((QA / f'{stem}_preview.png')),
            'png_dpi': 600, 'preview_dpi': 170}


diag = read(PRIOR / 'source_data/NH_OH_round_diagnostics.csv')
assert len(diag) == 10
posteriors = read(PRIOR / 'source_data/NH_OH_posteriors_by_round.csv')
assert len(posteriors) == 960
uncertainty_checks = []
for pool, label, units, color, seed in POOLS:
    rows = sorted([r for r in diag if r['pool'] == pool], key=lambda r: int(r['round']))
    assert [int(r['selected_count']) for r in rows] == [12, 24, 36, 48, 60]
    checks = read(ROOT / f'selections/{pool}/stopping_checks.csv')
    for round_number, (d, check) in enumerate(zip(rows, checks), 1):
        pr = [r for r in posteriors if r['pool'] == pool and int(r['after_round']) == round_number]
        remaining = [r for r in pr if r['selected_by_this_round'] == '0']
        assert len(pr) == 96 and len(remaining) == 96 - 12 * round_number
        assert np.isclose(np.mean([float(r['latent_posterior_sd']) for r in pr]),
                          float(d['mean_latent_sd_all_96']), atol=1e-12, rtol=0)
        assert np.isclose(np.mean([float(r['latent_posterior_sd']) for r in remaining]),
                          float(d['mean_latent_sd_unselected']), atol=1e-12, rtol=0)
        assert np.isclose(max(float(r['latent_ucb']) for r in remaining) - float(d['best_observed']),
                          float(d['max_unselected_ucb_gap']), atol=1e-12, rtol=0)
        assert np.isclose(float(check['ucb_minus_observed_best']), float(d['max_unselected_ucb_gap']), atol=1e-12, rtol=0)
        assert np.isclose(float(check['delta_response_units']), float(d['delta']), atol=1e-12, rtol=0)
    assert rows[-1]['decision'] == 'BUDGET_REACHED_CRITERION_NOT_MET'
    uncertainty_checks.append({'pool': pool, 'seed': seed, 'rows': rows})


def uncertainty_stopping():
    f = plt.figure(figsize=(180 / 25.4, 123 / 25.4))
    ys = [.590, .150]
    x_positions = [.135, .635]
    width, height = .335, .320
    for k, (pool, label, units, color, seed) in enumerate(POOLS):
        rows = uncertainty_checks[k]['rows']
        axes = [f.add_axes([x, ys[k], width, height]) for x in x_positions]
        left, right = axes
        for j, ax in enumerate(axes):
            letter(ax, 'abcdef'[2 * k + j])
            ax.set(xlim=(.7, 5.3), xticks=range(1, 6), xlabel='Selection batch')
            clean(ax)
        left.plot(range(1, 6), [float(r['mean_latent_sd_all_96']) for r in rows],
                  color=PURPLE, lw=1.45, marker='o', ms=3.2, label='All 96 candidates')
        left.plot(range(1, 6), [float(r['mean_latent_sd_unselected']) for r in rows],
                  color=GREY, lw=1.05, ls=(0, (3, 2)), marker='o', ms=2.4,
                  markerfacecolor='white', label='Unselected subset')
        left.set(ylim=(0, max(float(r['mean_latent_sd_unselected']) for r in rows) * 1.18),
                 ylabel=f'{label}: mean latent SD\n({units})')
        gap = [float(r['max_unselected_ucb_gap']) for r in rows]
        delta = float(rows[0]['delta'])
        right.axhline(delta, color=GREY, lw=.95, ls=(0, (4, 2)), label='Tolerance δ')
        right.plot(range(1, 6), gap, color=color, lw=1.45, marker='o', ms=3.2,
                   label='UCB gap')
        right.scatter([5], [gap[-1]], marker='s', s=25, facecolor=GOLD,
                      edgecolor='white', lw=.45, zorder=5, label='60-condition limit')
        right.set(ylim=(min(-.12 * max(gap), min(gap) - .09 * max(gap)), max(gap) * 1.15),
                  ylabel=f'Max unselected UCB − best\n({units})')
        left.legend(loc='upper right', handlelength=1.8, labelspacing=.35,
                    handletextpad=.5, borderaxespad=.45)
        handles, labels = right.get_legend_handles_labels()
        legend_position = dict(loc='lower left', bbox_to_anchor=(.005, .12)) if k == 0 else dict(loc='upper right')
        right.legend([handles[1], handles[0], handles[2]],
                     [labels[1], labels[0], labels[2]], **legend_position,
                     handlelength=1.8, labelspacing=.35, handletextpad=.5,
                     borderaxespad=.45)
    return save(f, 'SI_BO2_uncertainty_stopping', [180, 123])


grid = read(PRIOR / 'source_data/SH_PL40_full_measured_grid_seed5010.csv')
grid.sort(key=lambda r: int(r['candidate_index']))
replay = read(PRIOR / 'source_data/SH_PL40_paired_replay_seed5010.csv')
trajectories = read(ARCH / 'cumulative_best_trajectories.csv', lambda r: r['pool_id'] == 'SH_PL40')
budgets = read(ARCH / 'run_budgets.csv', lambda r: r['pool_id'] == 'SH_PL40')
oracle = read(ARCH / 'source_records_and_oracle.csv', lambda r: r['pool_id'] == 'SH_PL40')
oracle.sort(key=lambda r: int(r['candidate_index']))
assert len(grid) == len(oracle) == 96 and len(replay) == 192
assert len(trajectories) == 1600 and len(budgets) == 200
assert {int(r['seed']) for r in trajectories} == set(range(5000, 5100))
assert all(r['base'] == s['base'] and r['solvent'] == s['solvent'] and
           float(r['measured_uv_response']) == float(s['response']) for r, s in zip(grid, oracle))
assert len({(r['base'], r['solvent']) for r in grid}) == 96
ys = np.array([float(r['measured_uv_response']) for r in grid])
peak = int(np.argmax(ys))
assert peak == 65 and ys[peak] == 3.20446096654275
assert {int(r['bo_selection_round']) for r in grid} == set(range(1, 9))
for strategy in ['BO-UCB', 'random']:
    rr = [r for r in replay if r['strategy'] == strategy]
    assert len(rr) == 96
    for rnd in range(1, 9):
        archived = next(r for r in trajectories if r['strategy'] == strategy and
                        int(r['seed']) == 5010 and int(r['round']) == rnd)
        values = [float(r['measured_uv_response']) for r in rr if int(r['round']) <= rnd]
        assert max(values) == float(archived['cumulative_best_response'])
    if strategy == 'BO-UCB':
        assert all(int(r['round']) == int(grid[int(r['candidate_index'])]['bo_selection_round']) for r in rr)

initial_bo = sorted([int(r['candidate_index']) for r in replay if r['strategy'] == 'BO-UCB' and r['round'] == '1'])
initial_random = sorted([int(r['candidate_index']) for r in replay if r['strategy'] == 'random' and r['round'] == '1'])
assert initial_bo == initial_random
diagnostics = read_json(AUDIT / 'SH_audit_diagnostics.json')
summary_by_name = {r['diagnostic']: r for r in diagnostics}
full_budgets = [int(r['exact_budget']) for r in budgets if r['strategy'] == 'BO-UCB']
random_budgets = [int(r['exact_budget']) for r in budgets if r['strategy'] == 'random']
median_values = [float(np.median(full_budgets)), summary_by_name['same_model_greedy_mean']['median'],
                 summary_by_name['additive_UCB']['median'], float(np.median(random_budgets))]
assert median_values == [24, 24, 24, 48]
aggregate = {}
for strategy in ['BO-UCB', 'random']:
    data = []
    for budget in range(12, 97, 12):
        values = [float(r['cumulative_best_response']) for r in trajectories
                  if r['strategy'] == strategy and int(r['budget_end']) == budget]
        assert len(values) == 100
        data.append({'budget': budget, 'n': len(values), 'mean': float(np.mean(values)),
                     'q25': float(np.quantile(values, .25)), 'q75': float(np.quantile(values, .75))})
    aggregate[strategy] = data
assert aggregate['BO-UCB'][0] == aggregate['random'][0]
assert np.isclose(aggregate['BO-UCB'][1]['mean'], 2.582997513, atol=1e-8)


def sh_replay_diagnostics():
    f = plt.figure(figsize=(180 / 25.4, 180 / 25.4))
    axa = f.add_axes([.165, .595, .300, .345])
    axb = f.add_axes([.665, .595, .300, .345])
    axc = f.add_axes([.165, .115, .325, .285])
    axd = f.add_axes([.665, .115, .300, .285])
    for ax, label in zip([axa, axb, axc, axd], 'abcd'):
        letter(ax, label, x=-.18 if label in 'ac' else -.17)
    response_map = LinearSegmentedColormap.from_list('measured_response',
        ['#FBFBF3', '#E6EEE1', '#A8CEB6', '#68B39D', GREEN], N=512)
    im = axa.imshow(ys.reshape(12, 8), origin='upper', aspect='auto',
                    cmap=response_map, vmin=0, vmax=float(ys.max()), interpolation='nearest')
    # Native Helvetica subscripts avoid a FreeType failure on mathtext glyphs
    # at the 6.5-point tick-label size while retaining chemical typography.
    base_labels = ['K₃PO₄', 'DIPEA', 'KHCO₃', 'NaHCO₃', 'K₂CO₃',
                   'K₂HPO₄', 'NaOH', 'Na₃PO₄·12H₂O', 'CsOH/2', 'CsF', 'NaH', 'KOtBu']
    solvent_labels = ['n-hexane', 'DCE', 'MeCN', 'THF', '1,4-dioxane', 'toluene', 'HFIP', 'DMF']
    axa.set(xticks=range(8), yticks=range(12), xticklabels=solvent_labels,
            yticklabels=base_labels, xlabel='Solvent', ylabel='Base/additive')
    axa.tick_params(length=0, labelsize=6.5, pad=3)
    plt.setp(axa.get_xticklabels(), rotation=45, ha='right', rotation_mode='anchor')
    axa.set_xticks(np.arange(-.5, 8, 1), minor=True)
    axa.set_yticks(np.arange(-.5, 12, 1), minor=True)
    axa.grid(which='minor', color='white', lw=.5)
    axa.tick_params(which='minor', bottom=False, left=False)
    for spine in axa.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(.65)
        spine.set_color(INK)
    for i, r in enumerate(grid):
        axa.text(i % 8, i // 8, r['bo_selection_round'], ha='center', va='center',
                 fontsize=6.3, color='white' if ys[i] > 2.1 else INK)
    axa.add_patch(Rectangle((peak % 8 - .48, peak // 8 - .48), .96, .96,
                            fill=False, edgecolor=GOLD, lw=1.6, zorder=5))
    axa.legend(handles=[Patch(facecolor='none', edgecolor=GOLD, linewidth=1.4,
                             label='Highest response'),
                        Patch(facecolor='none', edgecolor='none',
                              label='Digits: BO round')],
               loc='upper left', bbox_to_anchor=(-.015, -.335), ncol=2,
               fontsize=6.2, columnspacing=.8, handlelength=1.2,
               handletextpad=.45, borderaxespad=0)
    cax = f.add_axes([.49, .595, .012, .345])
    cb = f.colorbar(im, cax=cax)
    cb.set_label('UV response', fontsize=7, labelpad=4)
    cb.ax.tick_params(labelsize=6.5, length=2.2, pad=2)
    cb.outline.set_linewidth(.5)
    for strategy, color, label in [('BO-UCB', BLUE, 'BO UCB'), ('random', TEAL, 'Random')]:
        rr = [r for r in trajectories if r['strategy'] == strategy and int(r['seed']) == 5010]
        rr.sort(key=lambda r: int(r['round']))
        axb.step([int(r['round']) for r in rr], [float(r['cumulative_best_response']) for r in rr],
                 where='post', color=color, lw=1.45, marker='o', ms=3, label=label)
    axb.set(xlim=(.7, 8.3), xticks=range(1, 9), ylim=(0, 3.55),
            xlabel='Selection batch', ylabel='Best UV response')
    axb.legend(loc='lower right', handlelength=1.6, labelspacing=.35)
    clean(axb)
    for strategy, color, label in [('BO-UCB', BLUE, 'BO UCB'), ('random', TEAL, 'Random')]:
        rows = aggregate[strategy]
        x = np.array([r['budget'] for r in rows])
        axc.fill_between(x, [r['q25'] for r in rows], [r['q75'] for r in rows],
                         color=color, alpha=.16, linewidth=0, step='post')
        axc.step(x, [r['mean'] for r in rows], where='post', color=color, lw=1.45,
                 marker='o', ms=2.8, label=label)
    axc.set(xlim=(8, 100), xticks=[12, 24, 48, 72, 96], ylim=(0, 3.55),
            xlabel='Evaluated conditions', ylabel='Mean best UV response')
    axc.legend(handles=[Line2D([], [], color=BLUE, lw=1.45, marker='o', ms=2.8,
                              label='BO UCB mean'),
                        Line2D([], [], color=TEAL, lw=1.45, marker='o', ms=2.8,
                               label='Random mean'),
                        Patch(facecolor=BLUE, alpha=.16, edgecolor='none',
                              label='BO UCB IQR'),
                        Patch(facecolor=TEAL, alpha=.16, edgecolor='none',
                              label='Random IQR')],
               loc='lower right', fontsize=6.3, handlelength=1.6,
               labelspacing=.3, handletextpad=.5, borderaxespad=.4)
    clean(axc)
    axd.bar(range(4), median_values, width=.58, color=BLUE, alpha=.9, linewidth=0)
    for x, value in enumerate(median_values):
        axd.text(x, value + 1.1, f'{value:g}', ha='center', va='bottom', fontsize=7)
    axd.set(xticks=range(4), xticklabels=['Full\nUCB', 'Greedy\nmean', 'Additive\nUCB', 'Random'],
            xlim=(-.6, 3.6), ylim=(0, 55), ylabel='Median first-hit budget\n(conditions)')
    axd.set_yticks([0, 12, 24, 36, 48])
    clean(axd)
    axd.set_yticks([0, 12, 24, 36, 48])
    axd.tick_params(axis='x', length=0, pad=5, labelsize=6.7)
    return save(f, 'SI_BO3_SH_replay_diagnostics', [180, 180])


CAPTIONS = '''Supplementary Figure BO2 | Numerically reproduced latent uncertainty and stopping diagnostics for Bayesian condition selection in N–H and O–H.
Rows correspond to N–H/Ag2SO4/PPh3 (NH_PL36, seed 6000; a,b) and O–H formulation–solvent selection (OH_CuNi_96, seed 8000; c,d). Each computational round reveals 12 selected responses, up to a budget of 60 conditions. Left, mean latent posterior standard deviation across the same 96 candidate identities (solid purple) and across the currently unselected candidates (dashed grey). The latter subset changes after each round; its means do not describe a fixed population. Posterior uncertainty need not decrease monotonically. Right, the largest latent upper confidence bound among unselected candidates minus the best selected response, with the fixed tolerance delta shown by the dashed line. UCB is the posterior mean plus 1.96 latent standard deviations. Gold squares mark the 60-condition budget limit. The tolerance equals 0.10 times the first-batch response population standard deviation. The stopping test becomes eligible at 36 selected conditions and requires both a two-round improvement no greater than delta and a remaining UCB no greater than the best selected response plus delta, in two consecutive checks. A constant first batch disables this stopping route. Both reproduced stopping-diagnostic calculations reach the budget limit without satisfying the rule; the O–H calculation has its first joint pass only at round 5. Posterior calculations use only the 60 selected responses per system, with no unselected response labels. These are latent-function uncertainties, excluding future-observation noise; 1.96 is a heuristic acquisition coefficient, not a calibrated 95% coverage guarantee. Values retain system-specific UV response units and are not percentage yields. Bayesian condition selection used the recorded N–H and O–H responses. The exported rounds, fixed seeds and stopping calculations describe the numerical reproduction and are not primary laboratory execution logs. The retrospective BO/random comparison reported in the main analysis concerns S–H.

Supplementary Figure BO3 | Measured sulfur response landscape and retrospective replay diagnostics.
a, The complete 96-condition SH_PL40 UV-response matrix, with the original twelve base/additive entries and eight solvent identities. Digits give the Bayesian selection round in the illustrative seed-5010 replay; the gold outline marks the highest recorded response, at CsOH/2 in DCE. CsOH/2 is retained as an unresolved source label. Each cell is a discrete measured condition, and no intermediate chemical conditions are implied. b, Best measured response at each completed batch for the single paired replay with seed 5010; BO and random sampling share their first 12 conditions and then select 12 conditions per round. This one-run illustration does not replace the 100-run aggregate. c, Mean best response across 100 paired computational runs, seeds 5000–5099, on the same measured grid. Shading gives the empirical interquartile range across algorithm seeds, not a confidence interval. Only batch-end results are shown. d, Median first-hit budgets for the full interaction-feature UCB policy, the same model using posterior mean alone, an additive-feature UCB policy with no interaction terms, and random sampling; these are 24, 24, 24 and 48 conditions. Each diagnostic uses the same seed range; no error bars are inferred from the saved diagnostic summaries. The exact-hit endpoint is the first completed batch reaching the maximum archived response, with a response tolerance of 1e-12. The full grid maximum belongs to the evaluator and is unavailable to the selection policies; it is not an operational stopping rule. The results quantify initialization variation conditional on one fixed historical response grid and do not measure laboratory repeatability or prospective experimental savings. Response is the recorded combined two-peak UV signal, not calibrated yield. The equal diagnostic medians do not isolate a unique contribution from the UCB uncertainty term or interaction features.
'''


def main():
    source_hashes = {str(p): sha(p) for p in dict.fromkeys(inputs)}
    outputs = [uncertainty_stopping(), sh_replay_diagnostics()]
    assert all(sha(Path(p)) == digest for p, digest in source_hashes.items())
    (OUT / 'supporting_captions_en.txt').write_text(CAPTIONS)
    manifest = {
        'status': 'complete', 'builder': str(Path(__file__)),
        'builder_sha256': sha(__file__), 'model_refits': 0, 'new_policy_replays': 0,
        'source_files_unchanged': True,
        'sources': [{'path': str(Path(p)), 'sha256': v}
                    for p, v in source_hashes.items()],
        'figures': outputs,
        'validation': {'SH_maximum_response': float(ys.max()), 'SH_maximum_index': peak,
                       'SH_paired_seed_range': [5000, 5099], 'SH_aggregate_runs_per_policy': 100,
                       'SH_median_budgets_full_greedy_additive_random': median_values,
                       'SH_full_mean_budget': float(np.mean(full_budgets)),
                       'SH_random_mean_budget': float(np.mean(random_budgets)),
                       'SH_aggregate_mean_and_empirical_quartiles': aggregate,
                       'NH_OH_diagnostic_rows_reconciled': len(diag),
                       'NH_OH_posterior_rows_reconciled': 960,
                       'both_NH_OH_end_at_60_without_stopping': True,
                       'image_values_equal_original_oracle': True,
                       'seed_5010_round_values_equal_original_trajectories': True},
        'style': {'font': os.environ.get('REACTION_FONT','DejaVu Sans'), 'pdf_fonttype': 42, 'svg_fonttype': 'none',
                  'four_sided_axes': True, 'decorative_grids': False,
                  'SI_BO2_legends_on_every_panel': True,
                  'SI_BO3_legends_for_peak_round_digits_lines_and_IQR': True,
                  'background': 'white', 'palette': [BLUE, CYAN, TEAL, GREEN, PURPLE, GOLD, INK, GREY]},
        'captions': str((OUT / 'supporting_captions_en.txt')),
    }
    (OUT / 'supporting_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'figures': [r['stem'] for r in outputs],
                      'dimensions_mm': [r['dimensions_mm'] for r in outputs],
                      'validated_sources': len(source_hashes), 'source_values_unchanged': True}))


if __name__ == '__main__':
    main()

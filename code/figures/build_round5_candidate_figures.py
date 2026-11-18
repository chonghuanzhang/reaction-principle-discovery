"""Build candidate-related round-5 figures from the released 100-molecule package.

The script has no network dependency.  It reads the reviewed molecular,
evidence-network and experimental-mapping records, assigns public C001-C100
identifiers by review rank, and writes the main and supplementary figure
assets used by the manuscript and SI.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]

from round5_figure_inputs import load_round5_figure_inputs

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image, ImageDraw, ImageFont


def resolve_font(environment_name, filenames):
    candidates = []
    configured = os.environ.get(environment_name)
    if configured:
        candidates.append(Path(configured))
    candidates.extend(Path(path) for path in filenames)
    for path in candidates:
        if path.is_file():
            return str(path)
    raise FileNotFoundError("No usable font found for {}".format(environment_name))


FONT_FILE = resolve_font("REACTION_FONT_FILE", [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    str(Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"),
])
BOLD_FILE = resolve_font("REACTION_BOLD_FONT_FILE", [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    str(Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans-Bold.ttf"),
])
fontManager.addfont(FONT_FILE)
fontManager.addfont(BOLD_FILE)
FONT_FAMILY = FontProperties(fname=FONT_FILE).get_name()
SVG_RENDERER = shutil.which("rsvg-convert")
plt.rcParams.update({
    "font.family": FONT_FAMILY,
    "font.size": 8,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "axes.linewidth": 0.65,
    "xtick.major.width": 0.65,
    "ytick.major.width": 0.65,
})

INK = "#1d2b38"
GREY = "#6d7c88"
LIGHT = "#dfe7ec"
BLUE = "#377cbd"
GREEN = "#17a386"
ORANGE = "#d99329"
PURPLE = "#9865b4"
CENTER_COLORS = {"N": BLUE, "O": "#2fa4c3", "S": "#268773", "P": PURPLE}
RP_COLORS = {"RP1": BLUE, "RP2": GREEN, "RP3": ORANGE, "RP4": PURPLE}
RP_NAMES = {
    "RP1": "Acceptor access",
    "RP2": "Donor competence",
    "RP3": "Capture and fluorine fate",
    "RP4": "Product persistence",
}
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def load_data():
    package = load_round5_figure_inputs(ROOT)
    candidates = deepcopy(package.candidates)
    candidates.sort(key=lambda row: row["review_rank"])
    for row in candidates:
        row["public_id"] = row["display_id"]
    return (
        candidates,
        package.network,
        package.mappings,
        package.hypotheses,
        package.products,
        package.llm_baseline,
        package.literature_baseline,
        package.comparison_summary,
    )


CANDIDATES, NETWORK, MAPPINGS, HYPOTHESES, PRODUCTS, LLM_BASELINE, LITERATURE_BASELINE, COMPARISON_SUMMARY = load_data()
CANDIDATE_BY_ID = {row["display_id"]: row for row in CANDIDATES}
CANDIDATE_BY_PUBLIC = {row["public_id"]: row for row in CANDIDATES}
MAPPING_BY_ID = {row["actual_pair_id"]: row for row in MAPPINGS}


def canon(smiles: str) -> str:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(smiles)
    return Chem.MolToSmiles(mol)


def molecule_rgba(smiles: str, size=(520, 300), color=None):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(smiles)
    rdDepictor.Compute2DCoords(mol)
    drawer = rdMolDraw2D.MolDraw2DCairo(*size)
    options = drawer.drawOptions()
    options.useBWAtomPalette()
    options.padding = 0.08
    options.bondLineWidth = 2.2
    options.fixedBondLength = 36
    options.minFontSize = 22
    options.maxFontSize = 22
    options.fontFile = FONT_FILE
    options.clearBackground = False
    if color:
        rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        highlights = {atom.GetIdx(): rgb for atom in mol.GetAtoms()}
        drawer.DrawMolecule(mol, highlightAtoms=list(highlights), highlightAtomColors=highlights)
    else:
        drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    from io import BytesIO
    return Image.open(BytesIO(drawer.GetDrawingText())).convert("RGBA")


def add_molecule(ax, smiles, extent, color=None):
    img = molecule_rgba(smiles, color=color)
    ax.imshow(img, extent=extent, interpolation="lanczos", aspect="auto", zorder=3)


def save_figure(fig, stem: Path, dpi=300):
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".png"), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_figure1():
    """Retain the accepted overview and redraw only candidate-dependent areas."""
    source = ROOT / "figures/source/current/Figure_1_publication.png"
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    regular = lambda n: ImageFont.truetype(FONT_FILE, n)
    bold = lambda n: ImageFont.truetype(BOLD_FILE, n)

    # Rebuild the complete interior of panel c so no legacy molecule or label
    # remains below the released representatives.
    draw.rounded_rectangle((1210, 515, 2055, 885), radius=26, fill="white")
    draw.text((1245, 542), "c", font=bold(36), fill="#285b30", anchor="mm")
    draw.text((1300, 542), "Candidate reaction partner design", font=bold(35), fill="#285b30", anchor="lm")
    draw.rounded_rectangle((1225, 570, 1500, 615), radius=20, fill="#dff4d6")
    draw.text((1362, 593), "100 candidate partners", font=bold(21), fill="#101410", anchor="mm")
    draw.rounded_rectangle((1580, 565, 2025, 630), radius=28, fill="#dff4d6")
    draw.text((1802, 597), "Human selection &\nchemical reasoning", font=bold(22), fill="#101410", anchor="mm", spacing=2)
    draw.line((1545, 575, 1545, 858), fill="#9aaba0", width=2)

    # Six representatives spanning N, O, S and P recommendations.
    representatives = [
        "C001", "C002", "C003", "C042", "C004", "C090"
    ]
    placements = [(1225, 635), (1325, 635), (1425, 635),
                  (1225, 745), (1325, 745), (1425, 745)]
    for cid, (x, y) in zip(representatives, placements):
        row = CANDIDATE_BY_PUBLIC[cid]
        mol = molecule_rgba(row["canonical_smiles"], (320, 190)).resize((92, 66), Image.Resampling.LANCZOS)
        image.paste(mol, (x, y), mol)
        label = row["name_en"]
        if len(label) > 22:
            label = label[:21] + "..."
        draw.text((x + 46, y + 70), f"{cid}\n{label}", font=regular(10), fill="#2b5532", anchor="ma", spacing=0)

    # Panel c right: selection logic that generated the displayed 100.
    bullets = [
        "Feasibility class",
        "Novelty review priority",
        "Evidence traceability",
        "Experimental correspondence",
    ]
    for idx, text in enumerate(bullets):
        yy = 665 + idx * 49
        draw.ellipse((1580, yy - 6, 1592, yy + 6), fill="#45a72f")
        draw.text((1605, yy), text, font=regular(20), fill="#18201c", anchor="lm")

    # Panel e: the released set contains N, O, S and P donors, but no Se donor.
    scheme_crop = image.crop((100, 790, 620, 905))
    draw.rectangle((100, 805, 620, 1018), fill="white")
    image.paste(scheme_crop, (100, 790))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((135, 900, 605, 1015), radius=18, fill="#fff0db")
    draw.text((370, 925), "Nu = nucleophile", font=regular(20), fill="#814a0c", anchor="mm")
    category_x = [220, 320, 420, 520]
    for x, symbol in zip(category_x, ["N", "O", "S", "P"]):
        color = CENTER_COLORS[symbol]
        draw.ellipse((x - 23, 948, x + 23, 994), fill="white", outline=color, width=3)
        draw.text((x, 971), symbol, font=bold(28), fill=color, anchor="mm")

    out = ROOT / "figures/main/Figure_1.png"
    image.save(out, dpi=(300, 300), optimize=True)
    image.convert("RGB").save(ROOT / "figures/main/Figure_1.jpeg", quality=96, subsampling=0, dpi=(300, 300))
    # PDF and SVG intentionally embed the approved raster composition; molecule
    # structures are additionally deposited as vector assets by the data release.
    pdf = ROOT / "figures/main/Figure_1.pdf"
    image.save(pdf, "PDF", resolution=300.0)
    svg = ROOT / "figures/main/Figure_1.svg"
    import base64
    payload = base64.b64encode(out.read_bytes()).decode("ascii")
    svg.write_text(
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {image.width} {image.height}" '
        f'width="{image.width}" height="{image.height}"><image width="100%" height="100%" '
        f'href="data:image/png;base64,{payload}"/></svg>\n'
    )
    source_dir = ROOT / "figures/source/round5_figure1"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "representatives.json").write_text(json.dumps({
        "public_ids": representatives,
        "selection_fields": bullets,
        "nucleophile_centres": {"N": 40, "O": 30, "S": 25, "P": 5},
        "source": "candidates/data/candidates_100.json",
        "sha256": sha256(out),
    }, indent=2) + "\n")


def draw_network(highlight_rp=None, highlight_center=None):
    nodes = {row["id"]: row for row in NETWORK["nodes"]}
    evidence = [row for row in NETWORK["nodes"] if row["kind"] == "evidence"]
    families = [row for row in NETWORK["nodes"] if row["kind"] == "family"]
    citations = {row["candidate_id"] for row in NETWORK["candidate_citation_links"]}
    family_members = {row["id"]: row["members"] for row in families}
    candidate_center = {row["display_id"]: row["center"] for row in CANDIDATES}

    fig, ax = plt.subplots(figsize=(7.1, 6.55))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.subplots_adjust(left=.02, right=.98, bottom=.04, top=.94)
    title = "Evidence-to-principle-to-candidate network"
    if highlight_rp:
        title = f"{highlight_rp}: {RP_NAMES[highlight_rp]}"
    elif highlight_center:
        title = f"{highlight_center}-centred candidate families"
    fig.suptitle(title, x=.5, y=.985, fontsize=11, fontweight="bold")
    ax.text(.12, .965, "Literature evidence\n17 nodes", ha="center", va="top", fontsize=8.5, fontweight="bold")
    ax.text(.36, .965, "Reaction principles\n4 reaction principles", ha="center", va="top", fontsize=8.5, fontweight="bold")
    ax.text(.64, .965, "Precursor families\n43 families", ha="center", va="top", fontsize=8.5, fontweight="bold")
    ax.text(.89, .965, "Recommended molecules\n100 candidates", ha="center", va="top", fontsize=8.5, fontweight="bold")

    ey = {row["id"]: y for row, y in zip(evidence, list(reversed([.075 + i * .048 for i in range(17)])))}
    rpy = {"RP1": .82, "RP2": .61, "RP3": .39, "RP4": .18}
    family_center = {}
    for family in families:
        member = CANDIDATE_BY_ID[family["members"][0]]
        family_center[family["id"]] = member["center"]
    family_groups = {center: [f for f in families if family_center[f["id"]] == center] for center in "NOSP"}
    band_ranges = {"N": (.58, .90), "O": (.35, .55), "S": (.12, .32), "P": (.055, .105)}
    fy = {}
    for center, group in family_groups.items():
        low, high = band_ranges[center]
        for row, y in zip(sorted(group, key=lambda x: x["label"]), list(reversed([low + (high-low)*(i+.5)/len(group) for i in range(len(group))]))):
            fy[row["id"]] = y
    candidate_y = {}
    for center, group in family_groups.items():
        low, high = band_ranges[center]
        members = [cid for family in group for cid in family_members[family["id"]]]
        members.sort(key=lambda cid: CANDIDATE_BY_ID[cid]["review_rank"])
        for cid, y in zip(members, [low + (high-low)*(i+.5)/len(members) for i in range(len(members))]):
            candidate_y[cid] = y

    # Evidence -> RP edges.
    for edge in NETWORK["edges"]:
        if edge["kind"] != "source_to_principle":
            continue
        active = highlight_rp is None or edge["target"] == highlight_rp
        alpha = .38 if active else .055
        ax.plot([.145, .315], [ey[edge["source"]], rpy[edge["target"]]],
                color=RP_COLORS[edge["target"]], lw=.75 if active else .35, alpha=alpha, zorder=0)
    # RP -> family edges (all 43 x 4 retained, deliberately faint).
    for edge in NETWORK["edges"]:
        if edge["kind"] != "principle_to_family":
            continue
        active = highlight_rp is None or edge["source"] == highlight_rp
        if highlight_center and family_center[edge["target"]] != highlight_center:
            active = False
        ax.plot([.405, .59], [rpy[edge["source"]], fy[edge["target"]]],
                color=RP_COLORS[edge["source"]], lw=.32, alpha=.14 if active else .02,
                linestyle=(0, (2, 2)), zorder=0)
    # Family -> candidate edges.
    for family in families:
        center = family_center[family["id"]]
        active = highlight_center is None or center == highlight_center
        for cid in family["members"]:
            ax.plot([.685, .86], [fy[family["id"]], candidate_y[cid]],
                    color=CENTER_COLORS[center], lw=.35, alpha=.24 if active else .025, zorder=0)

    # Evidence nodes and abbreviated labels.
    for row in evidence:
        active = highlight_rp is None or highlight_rp in row.get("rps", [])
        ax.scatter([.13], [ey[row["id"]]], s=28, facecolor=row["color"] if active else "white",
                   edgecolor=row["color"], linewidth=.9, alpha=1 if active else .18, zorder=3)
        label = row["label"].replace("\n", " ").replace("¹⁹F", "19F")
        if len(label) > 31:
            label = label[:30] + "..."
        ax.text(.115, ey[row["id"]], label, ha="right", va="center", fontsize=4.8,
                color=INK if active else "#b8c0c6")
    # RP nodes.
    for rp, y in rpy.items():
        active = highlight_rp is None or rp == highlight_rp
        ax.scatter([.36], [y], s=1150, facecolor=RP_COLORS[rp], edgecolor="white", linewidth=1.5,
                   alpha=1 if active else .13, zorder=4)
        ax.text(.36, y + .003, rp, ha="center", va="center", color="white", fontsize=10,
                fontweight="bold", alpha=1 if active else .35, zorder=5)
        ax.text(.36, y - .065, RP_NAMES[rp], ha="center", va="top", fontsize=6.2,
                fontweight="bold", color=INK if active else "#b8c0c6")

    # Family nodes and names.
    for family in families:
        center = family_center[family["id"]]
        active = highlight_center is None or center == highlight_center
        count = len(family["members"])
        ax.scatter([.62], [fy[family["id"]]], s=18 + count * 7,
                   facecolor=CENTER_COLORS[center] if active else "white",
                   edgecolor=CENTER_COLORS[center], linewidth=.7, alpha=1 if active else .17, zorder=3)
        label = family["label"].replace("_", " ")
        if len(label) > 24:
            label = label[:23] + "..."
        ax.text(.64, fy[family["id"]], f"{label} ({count})", ha="left", va="center", fontsize=4.4,
                color=INK if active else "#bec5ca")
    for center, (low, high) in band_ranges.items():
        total = sum(len(f["members"]) for f in family_groups[center])
        ax.text(.55, high + .009, f"{center}  {len(family_groups[center])} families / {total} molecules",
                ha="left", va="bottom", fontsize=5.6, fontweight="bold", color=CENTER_COLORS[center])

    # Candidate dots: fill encodes a direct candidate citation link.
    for row in CANDIDATES:
        cid = row["display_id"]
        center = row["center"]
        active = highlight_center is None or center == highlight_center
        cited = cid in citations
        ax.scatter([.875 + (.018 if row["review_rank"] % 2 else 0)], [candidate_y[cid]], s=12,
                   facecolor=CENTER_COLORS[center] if cited else "white", edgecolor=CENTER_COLORS[center],
                   linewidth=.55, alpha=1 if active else .13, zorder=3)
    ax.scatter([], [], s=16, facecolor=GREY, edgecolor=GREY, label="Candidate citation link")
    ax.scatter([], [], s=16, facecolor="white", edgecolor=GREY, label="No direct candidate citation link")
    ax.legend(loc="lower center", bbox_to_anchor=(.72, -.006), frameon=False, ncol=2, fontsize=5.2)
    ax.text(.08, .018, "19 evidence-to-RP edges  |  172 RP-to-family edges  |  100 family-membership edges",
            fontsize=5.6, color=GREY, va="bottom")
    return fig


def build_network_figures():
    main = ROOT / "knowledge_graph/figures/Figure_3"
    save_figure(draw_network(), main, dpi=300)
    shutil.copy2(main.with_suffix(".svg"), ROOT / "knowledge_graph/figures/network_full.svg")
    shutil.copy2(main.with_suffix(".png"), ROOT / "knowledge_graph/figures/G1.png")
    for index, rp in enumerate(["RP1", "RP2", "RP3", "RP4"], 2):
        stem = ROOT / f"knowledge_graph/figures/{rp}_focus"
        save_figure(draw_network(highlight_rp=rp), stem, dpi=300)
        shutil.copy2(stem.with_suffix(".png"), ROOT / f"knowledge_graph/figures/G{index}.png")
    for index, center in enumerate("NOSP", 6):
        stem = ROOT / f"knowledge_graph/figures/center_{center}_focus"
        save_figure(draw_network(highlight_center=center), stem, dpi=300)
        shutil.copy2(stem.with_suffix(".png"), ROOT / f"knowledge_graph/figures/G{index}.png")
    data = {
        "nodes": {"evidence": 17, "reaction_principles": 4, "families": 43, "candidates": 100},
        "edges": {"evidence_to_principle": 19, "principle_to_family": 172, "family_membership": 100},
        "candidate_citations": {"linked_candidates": 75, "links": 170, "catalog_sources": 17},
        "supplementary_figures": {f"Supplementary Figure {i}": f"RP{i}_focus" for i in range(1, 5)},
    }
    (ROOT / "knowledge_graph/data/round5_figure_summary.json").write_text(json.dumps(data, indent=2) + "\n")


def style_axis(ax):
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(.65)
        spine.set_color("#6a737a")
    ax.tick_params(width=.6, labelsize=7)


def build_figure4():
    fig = plt.figure(figsize=(7.1, 7.15), facecolor="white")
    grid = fig.add_gridspec(3, 2, height_ratios=[1.0, .56, 1.28], hspace=.38, wspace=.24)

    # a. Reacting-centre composition.
    ax = fig.add_subplot(grid[0, 0])
    counts = Counter(row["center"] for row in CANDIDATES)
    labels = list("NOSP")
    values = [counts[x] for x in labels]
    bars = ax.bar(labels, values, color=[CENTER_COLORS[x] for x in labels], width=.65)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, value + .8, str(value), ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, 47); ax.set_ylabel("Recommended molecules")
    ax.set_title("a   Reacting-centre composition", loc="left", fontsize=9.5, fontweight="bold")
    ax.grid(axis="y", color="#e8ecef", lw=.5, zorder=0); style_axis(ax)

    # b. Representative recommendations.
    ax = fig.add_subplot(grid[0, 1]); ax.set_axis_off()
    ax.set_title("b   Representative recommendations", loc="left", fontsize=9.5, fontweight="bold")
    reps = ["C001", "C002", "C003", "C042", "C004", "C090"]
    for idx, cid in enumerate(reps):
        row, col = divmod(idx, 3)
        x0 = col / 3 + .01; x1 = (col + 1) / 3 - .01
        y1 = .92 - row * .47; y0 = y1 - .29
        record = CANDIDATE_BY_PUBLIC[cid]
        add_molecule(ax, record["canonical_smiles"], (x0, x1, y0, y1), color=CENTER_COLORS[record["center"]])
        name = record["name_en"]
        if len(name) > 20: name = name[:19] + "..."
        ax.text((x0+x1)/2, y0-.015, f"{cid}  {name}", ha="center", va="top", fontsize=5.6)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # c. Accounting.
    ax = fig.add_subplot(grid[1, :]); ax.set_axis_off()
    ax.set_title("c   Molecular, hypothesis and product-option accounting", loc="left", fontsize=9.5, fontweight="bold")
    items = [("100", "recommended molecules", BLUE), ("103", "site/pathway hypotheses", GREEN),
             ("103", "product options", ORANGE)]
    for idx, (number, label, color) in enumerate(items):
        x = .17 + idx * .33
        ax.add_patch(FancyBboxPatch((x-.12, .2), .24, .50, boxstyle="round,pad=.015,rounding_size=.02",
                                    facecolor="white", edgecolor=color, linewidth=1.2))
        ax.text(x, .52, number, ha="center", va="center", fontsize=19, color=color, fontweight="bold")
        ax.text(x, .31, label, ha="center", va="center", fontsize=7.2)
        if idx < 2:
            ax.add_patch(FancyArrowPatch((x+.13, .45), (x+.20, .45), arrowstyle="-|>",
                                         mutation_scale=10, lw=.9, color=GREY))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # d. Relationship categories and chemical examples.
    ax = fig.add_subplot(grid[2, 0]); ax.set_axis_off()
    ax.set_title("d   Recommended-to-experimental correspondence", loc="left", fontsize=9.5, fontweight="bold")
    relation_counts = [("Exact identity", 25, BLUE), ("Same scaffold / substituent", 31, "#2fa4c3"),
                       ("Same donor family", 41, GREEN), ("Unmatched", 3, "#9aa5ad")]
    left = 0
    for label, value, color in relation_counts:
        ax.add_patch(Rectangle((left/100, .86), value/100, .08, facecolor=color, edgecolor="white", lw=.5))
        if value >= 10:
            ax.text((left+value/2)/100, .90, str(value), ha="center", va="center", color="white", fontsize=7, fontweight="bold")
        left += value
    for idx, (label, value, color) in enumerate(relation_counts):
        y = .80 - idx*.055
        ax.add_patch(Rectangle((.01, y-.014), .025, .026, facecolor=color, edgecolor="none"))
        ax.text(.045, y, f"{label}: {value}", ha="left", va="center", fontsize=5.8)

    examples = [
        ("C002", "AP044", "Exact identity"),
        ("C042", "AP048", "Same scaffold / positional variation"),
        ("C004", "AP096", "Same donor family / different scaffold"),
    ]
    for idx, (cid, apid, label) in enumerate(examples):
        y_top = .57 - idx * .205
        candidate = CANDIDATE_BY_PUBLIC[cid]
        actual = MAPPING_BY_ID[apid]
        add_molecule(ax, candidate["canonical_smiles"], (.00, .30, y_top-.14, y_top+.015), color=CENTER_COLORS[candidate["center"]])
        add_molecule(ax, actual["actual_donor_smiles"], (.62, .96, y_top-.14, y_top+.015), color=CENTER_COLORS[candidate["center"]])
        ax.add_patch(FancyArrowPatch((.33, y_top-.06), (.60, y_top-.06), arrowstyle="-|>", mutation_scale=9,
                                     lw=.8, color=GREY))
        ax.text(.465, y_top-.02, label, ha="center", va="bottom", fontsize=4.7, color=GREY)
        ax.text(.15, y_top-.155, f"{cid}  {candidate['name_en']}", ha="center", va="top", fontsize=4.8)
        actual_name = {"AP044": "Indoline", "AP048": "1-Naphthol", "AP096": "4-Methoxythiophenol"}[apid]
        ax.text(.79, y_top-.155, f"{apid}  {actual_name}", ha="center", va="top", fontsize=4.8)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    # e. Feasibility and novelty-priority distributions.
    ax = fig.add_subplot(grid[2, 1])
    ax.set_title("e   Feasibility and novelty review priorities", loc="left", fontsize=9.5, fontweight="bold")
    feasibility = Counter(row["feasibility_class"] for row in CANDIDATES)
    novelty = Counter(str(row["novelty_review_priority"]) for row in CANDIDATES)
    cats = ["A", "B", "C", "1", "2", "3"]
    vals = [feasibility[x] for x in "ABC"] + [novelty[x] for x in "123"]
    cols = [BLUE, GREEN, ORANGE, BLUE, GREEN, ORANGE]
    yy = list(reversed(range(6)))
    bars = ax.barh(yy, vals, color=cols, height=.62)
    ax.set_yticks(yy, ["Feasibility A", "Feasibility B", "Feasibility C",
                       "Novelty priority 1", "Novelty priority 2", "Novelty priority 3"])
    ax.set_xlim(0, 82); ax.set_xlabel("Recommended molecules")
    for bar, value in zip(bars, vals):
        ax.text(value + 1, bar.get_y()+bar.get_height()/2, str(value), va="center", fontsize=7)
    ax.axhline(2.5, color=LIGHT, lw=.8)
    ax.grid(axis="x", color="#e8ecef", lw=.5, zorder=0); style_axis(ax)

    fig.subplots_adjust(left=.075, right=.98, top=.96, bottom=.06)
    stem = ROOT / "figures/main/Figure_4"
    save_figure(fig, stem, dpi=300)
    Image.open(stem.with_suffix(".png")).convert("RGB").save(stem.with_suffix(".jpeg"), quality=96, subsampling=0, dpi=(300, 300))
    source = ROOT / "figures/source/round5_figure4"
    source.mkdir(parents=True, exist_ok=True)
    payload = {
        "reacting_centres": dict(counts),
        "accounting": {"candidates": 100, "hypotheses": 103, "product_options": 103},
        "best_correspondence": {"exact_identity": 25, "same_scaffold_or_substituent": 31,
                                "same_donor_family": 41, "unmatched": 3},
        "feasibility": dict(feasibility),
        "novelty_priority": dict(novelty),
        "examples": [{"candidate": a, "experimental_pair": b, "relationship": c} for a, b, c in examples],
    }
    (source / "figure_data.json").write_text(json.dumps(payload, indent=2) + "\n")
    (source / "caption.txt").write_text(
        "Fig. 4 | Composition and experimental correspondence of the recommended nucleophile set. "
        "a, Reacting-centre composition of the 100 recommendations. b, Representative structures spanning "
        "the four donor classes. c, Accounting of recommended molecules, site/pathway hypotheses and product "
        "options. d, Best structural relationship assigned to each recommendation across the experimental "
        "collection, with representative exact, scaffold/positional and donor-family correspondences. "
        "e, Feasibility classes and novelty review priorities used to organize the recommendation set.\n"
    )


def build_supplementary_figure5():
    def unique_label_set(values):
        return "/".join(dict.fromkeys(str(value) for value in values))
    candidate_np = Counter(unique_label_set(row["NP_labels"]) for row in CANDIDATES)
    candidate_nr = Counter(unique_label_set(row["NR_labels"]) for row in CANDIDATES)
    exp_np = Counter(str(row.get("NP_label", "unresolved")) for row in MAPPINGS)
    exp_nr = Counter(str(row.get("NR_label", "unresolved")) for row in MAPPINGS)
    # Normalize display labels while retaining mixed and not-applicable records.
    def norm(counter):
        out = Counter()
        for key, value in counter.items():
            k = key.lower().replace("not_applicable", "not applicable")
            if k == "不适用": k = "not applicable"
            if k in {"none", "null"}: k = "unresolved"
            if k in {"2 | unresolved", "2/unresolved", "2 | unresolved"}: k = "2 / unresolved"
            if k in {"3 | 2", "3/2"}: k = "3 / 2"
            if k in {"2 | 3", "2–3", "2-3"}: k = "2 / 3"
            out[k] += value
        return out
    candidate_np, candidate_nr, exp_np, exp_nr = map(norm, [candidate_np, candidate_nr, exp_np, exp_nr])
    assert sum(candidate_np.values()) == 100 and sum(candidate_nr.values()) == 100
    assert sum(exp_np.values()) == 108 and sum(exp_nr.values()) == 108
    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2))
    panels = [
        (axes[0, 0], "Candidate molecules · NP (n = 100)", candidate_np, "NP"),
        (axes[0, 1], "Experimental pairs · NP (n = 108)", exp_np, "NP"),
        (axes[1, 0], "Candidate molecules · NR (n = 100)", candidate_nr, "NR"),
        (axes[1, 1], "Experimental pairs · NR (n = 108)", exp_nr, "NR"),
    ]
    order = ["1r", "1t", "1", "2", "3", "2 / 3", "3 / 2", "2 / unresolved", "unresolved", "not applicable"]
    for ax, title, data, prefix in panels:
        keys = [key for key in order if data.get(key, 0)] + [key for key in data if key not in order]
        values = [data[key] for key in keys]
        y = list(reversed(range(len(keys))))
        bars = ax.barh(y, values, color="#5f8194", height=.66)
        display = []
        for key in keys:
            if key == "unresolved": label = "Unresolved only" if "Candidate" in title else "Unresolved"
            elif key == "not applicable": label = "Not applicable"
            elif key == "2 / unresolved": label = f"{prefix}2 / unresolved"
            elif key in {"1r", "1t"}: label = prefix + key.upper()
            elif key.replace(" / ", "").isdigit(): label = prefix + key.replace(" ", "")
            else: label = key
            if "Candidate" in title and key in {"1", "2", "3"}: label += " only"
            display.append(label)
        ax.set_yticks(y, display)
        ax.set_title(title, loc="left", fontsize=8.5, fontweight="bold")
        ax.set_xlabel("Count")
        ax.grid(axis="x", color="#e8ecef", lw=.5, zorder=0)
        for bar, value in zip(bars, values):
            ax.text(value + max(values)*.012, bar.get_y()+bar.get_height()/2, str(value), va="center", fontsize=7)
        ax.set_xlim(0, max(values)*1.18 + 1); style_axis(ax)
    fig.suptitle("Novelty category distributions", fontsize=11, fontweight="bold", y=.995)
    fig.tight_layout()
    stem = ROOT / "candidates/figures/N1_novelty_distributions"
    save_figure(fig, stem, dpi=300)
    shutil.copy2(stem.with_suffix(".png"), ROOT / "candidates/figures/N1.png")
    source = ROOT / "figures/source/round5_supplementary_figure5.json"
    source.write_text(json.dumps({
        "candidate_NP": dict(candidate_np), "candidate_NR": dict(candidate_nr),
        "experimental_pair_NP": dict(exp_np), "experimental_pair_NR": dict(exp_nr),
    }, indent=2) + "\n")


def svg_element(parent, tag, **attrs):
    return ET.SubElement(parent, f"{{{SVG_NS}}}{tag}", {key.replace("_", "-"): str(value) for key, value in attrs.items()})


def svg_text(parent, x, y, value, size=26, color=INK, anchor="start", weight="normal"):
    element = svg_element(parent, "text", x=x, y=y, fill=color, font_family=FONT_FAMILY,
                          font_size=size, text_anchor=anchor, font_weight=weight)
    element.text = value
    return element


def molecule_svg(smiles, width=390, height=150):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(smiles)
    rdDepictor.Compute2DCoords(mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    options = drawer.drawOptions(); options.useBWAtomPalette(); options.padding = .07
    options.bondLineWidth = 2.7; options.fixedBondLength = 38
    options.minFontSize = 25; options.maxFontSize = 25
    options.fontFile = FONT_FILE; options.clearBackground = False
    drawer.DrawMolecule(mol); drawer.FinishDrawing()
    return ET.fromstring(drawer.GetDrawingText())


def exact_candidate_matches(records):
    candidate_map = defaultdict(list)
    for row in CANDIDATES:
        candidate_map[canon(row["canonical_smiles"])].append(row["public_id"])
    for row in records:
        row["round5_exact_recommendation_ids"] = candidate_map.get(canon(row["canonical_smiles"]), [])
    return records


def build_baseline_panel(records, kind):
    width, height, cell_w, cell_h = 2010, 900, 2010/5, 212
    svg = ET.Element(f"{{{SVG_NS}}}svg", {"width": "6.7in", "height": "3in", "viewBox": f"0 0 {width} {height}"})
    svg_element(svg, "rect", x=0, y=0, width=width, height=height, fill="white")
    for index, record in enumerate(records):
        col, row = index % 5, index // 5
        x, y = col * cell_w, 45 + row * cell_h
        group = svg_element(svg, "g", transform=f"translate({x} {y})")
        positive = record["response_positive"] if kind == "literature" else record["product_positive"]
        experimental = record.get("exact_rp_actual_pair_ids", []) if kind == "literature" else record.get("exact_rp_experimental_pair_matches", [])
        recommended = record["round5_exact_recommendation_ids"]
        if experimental:
            svg_element(group, "rect", x=10, y=22, width=382, height=158, rx=12, fill="none",
                        stroke="#3b7293", stroke_width=3.5, data_overlap="experimental")
        if recommended:
            inset = 6 if experimental else 0
            svg_element(group, "rect", x=10+inset, y=22+inset, width=382-2*inset, height=158-2*inset,
                        rx=12, fill="none", stroke="#c88c52", stroke_width=3.5,
                        stroke_dasharray="12 8", data_overlap="recommended")
        mol = molecule_svg(record["canonical_smiles"])
        mol.attrib.update({"x": "6", "y": "31", "width": "390", "height": "150"})
        group.append(mol)
        svg_text(group, cell_w/2, 208, "Product" if positive else "Trace", size=26, anchor="middle",
                 color="#23845c" if positive else "#707781")
    return svg


def write_svg_derivatives(svg, stem):
    if SVG_RENDERER is None:
        raise RuntimeError(
            "SVG export requires rsvg-convert (librsvg); see code/requirements-figures.txt"
        )
    stem.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(svg).write(stem.with_suffix(".svg"), encoding="utf-8", xml_declaration=True)
    subprocess.run([SVG_RENDERER, "-f", "png", "-d", "300", "-p", "300",
                    "-o", str(stem.with_suffix(".png")), str(stem.with_suffix(".svg"))], check=True)
    subprocess.run([SVG_RENDERER, "-f", "pdf", "-o", str(stem.with_suffix(".pdf")),
                    str(stem.with_suffix(".svg"))], check=True)


def build_figure6():
    llm = exact_candidate_matches(deepcopy(LLM_BASELINE))
    lit_all = LITERATURE_BASELINE["records"]
    lit = exact_candidate_matches([deepcopy(row) for row in lit_all if row["unique_structure_representative"] == row["record_id"]])
    llm_hits = [(row["baseline_id"], row["round5_exact_recommendation_ids"]) for row in llm if row["round5_exact_recommendation_ids"]]
    lit_hits = [(row["record_id"], row["round5_exact_recommendation_ids"]) for row in lit if row["round5_exact_recommendation_ids"]]
    assert sum(bool(ids) for _, ids in llm_hits) == 2, llm_hits
    assert sum(bool(ids) for _, ids in lit_hits) == 5, lit_hits

    out = ROOT / "figures/source/round5_figure6"
    out.mkdir(parents=True, exist_ok=True)
    llm_panel = build_baseline_panel(llm, "llm")
    lit_panel = build_baseline_panel(lit, "literature")
    write_svg_derivatives(llm_panel, out / "direct_llm_molecular_panel")
    write_svg_derivatives(lit_panel, out / "literature_selection_molecular_panel")

    # Panels a-b retain the experimental statistics and experimental-set intersections.
    summary = COMPARISON_SUMMARY
    stats = summary["statistics"]
    patterns = [row["count"] for row in summary["unique_structure_intersections"]]
    fig = plt.figure(figsize=(6.7, 2.25), facecolor="white")
    ax = fig.add_axes([.085, .23, .37, .62])
    values = [100*row["fraction"] for row in stats]
    colors = ["#3b7293", "#c88c52", "#7c8f77"]
    ax.bar(range(3), values, width=.62, color=colors, zorder=3)
    ax.errorbar(range(3), values,
                yerr=[[100*(row["fraction"]-row["wilson95_low"]) for row in stats],
                      [100*(row["wilson95_high"]-row["fraction"]) for row in stats]],
                fmt="none", ecolor="#30343a", capsize=3, elinewidth=.8, zorder=4)
    for index, row in enumerate(stats):
        ax.text(index, 100*row["wilson95_high"]+2.5,
                f"{values[index]:.1f}%\n{row['positive']}/{row['tested_unique_donors']}",
                ha="center", va="bottom", fontsize=8)
    labels = ["RP-guided", "Direct LLM\nrecommendation", "Literature\nselection"]
    ax.set_xticks(range(3), labels); ax.tick_params(axis="x", length=0, labelsize=7)
    ax.set_ylim(0, 68); ax.set_yticks([0, 20, 40, 60]); ax.set_ylabel("Reaction-positive fraction (%)")
    ax.yaxis.grid(True, color="#e9ebee", linewidth=.5, zorder=0); style_axis(ax)
    fig.text(.012, .94, "a", fontsize=12, weight="bold")
    fig.text(.085, .94, "Experimental outcomes", fontsize=9, weight="bold")
    axb = fig.add_axes([.66, .48, .325, .37])
    axb.bar(range(5), patterns, color="#627c8a", width=.65)
    for index, value in enumerate(patterns): axb.text(index, value+3, str(value), ha="center", va="bottom", fontsize=8)
    axb.set_ylim(0, 112); axb.set_yticks([0, 50, 100]); axb.set_ylabel("Unique donors"); axb.set_xticks([]); style_axis(axb)
    matrix = [tuple(row["membership"]) for row in summary["unique_structure_intersections"]]
    axm = fig.add_axes([.66, .12, .325, .31], sharex=axb)
    for index, membership in enumerate(matrix):
        axm.scatter([index]*3, [0,1,2], c="#dfe3e7", s=19, linewidths=0)
        active = [j for j, value in enumerate(membership) if value]
        if len(active)>1: axm.plot([index,index],[min(active),max(active)],c="#364e60",lw=1.3,zorder=2)
        axm.scatter([index]*len(active), active, c="#364e60", s=22, linewidths=0, zorder=3)
    axm.set_xlim(-.6,4.6); axm.set_ylim(2.5,-.5); axm.set_yticks([0,1,2], labels)
    axm.tick_params(axis="both", length=0, labelsize=6.8); axm.set_xticks([]); style_axis(axm)
    fig.text(.515,.94,"b",fontsize=12,weight="bold"); fig.text(.56,.94,"Exact experimental-set overlap",fontsize=9,weight="bold")
    fig.savefig(out / "comparison_statistics.svg"); plt.close(fig)

    root = ET.Element(f"{{{SVG_NS}}}svg", {"width":"6.7in","height":"8.62in","viewBox":"0 0 2010 2586"})
    svg_element(root, "rect", x=0, y=0, width=2010, height=2586, fill="white")
    files = [(out/"comparison_statistics.svg",0,675),(out/"direct_llm_molecular_panel.svg",708,900),
             (out/"literature_selection_molecular_panel.svg",1653,900)]
    for file, y, height in files:
        element = ET.parse(file).getroot()
        element.attrib.update({"x":"0","y":str(y),"width":"2010","height":str(height)})
        if "comparison" not in file.name:
            letter = svg_element(element, "text", x=12, y=40, font_family=FONT_FAMILY, font_size=50,
                                 font_weight="bold", fill="black")
            letter.text = "c" if "direct" in file.name else "d"
        prefix = file.stem + "-"
        idmap = {child.attrib["id"]: prefix + child.attrib["id"] for child in element.iter() if "id" in child.attrib}
        for child in element.iter():
            for key, value in list(child.attrib.items()):
                if key == "id": child.attrib[key] = idmap[value]
                elif value.startswith("#") and value[1:] in idmap: child.attrib[key] = "#" + idmap[value[1:]]
                elif value.startswith("url(#") and value[5:-1] in idmap: child.attrib[key] = "url(#" + idmap[value[5:-1]] + ")"
        root.append(element)
    main_stem = ROOT / "figures/main/Figure_6"
    write_svg_derivatives(root, main_stem)
    (out / "recommended_overlap.json").write_text(json.dumps({
        "direct_llm": llm_hits, "literature_selection": lit_hits,
        "total_exact_recommendation_overlaps": 7,
        "experimental_statistics": {"RP-guided": "35/94", "direct_LLM": "4/20", "literature": "3/20"},
    }, indent=2) + "\n")


def update_manifest():
    assets = []
    for path in [
        ROOT / "figures/main/Figure_1.png", ROOT / "knowledge_graph/figures/Figure_3.png",
        ROOT / "figures/main/Figure_4.png", ROOT / "figures/main/Figure_6.png",
        ROOT / "candidates/figures/N1_novelty_distributions.png",
    ]:
        with Image.open(path) as image:
            assets.append({"path": str(path.relative_to(ROOT)), "width_px": image.width,
                           "height_px": image.height, "sha256": sha256(path)})
    payload = {"release": "round5-candidate-set", "assets": assets,
               "candidate_source": "candidates/data/candidates_100.json"}
    (ROOT / "figures/current_asset_manifest.json").write_text(json.dumps(payload, indent=2) + "\n")


def main():
    build_figure1()
    build_network_figures()
    build_figure4()
    build_supplementary_figure5()
    build_figure6()
    update_manifest()
    print(json.dumps({
        "figure_1": "figures/main/Figure_1.png",
        "figure_3": "knowledge_graph/figures/Figure_3.png",
        "figure_4": "figures/main/Figure_4.png",
        "figure_6": "figures/main/Figure_6.png",
        "supplementary_1_4": [f"knowledge_graph/figures/RP{i}_focus.png" for i in range(1,5)],
        "supplementary_5": "candidates/figures/N1_novelty_distributions.png",
    }, indent=2))


if __name__ == "__main__":
    main()

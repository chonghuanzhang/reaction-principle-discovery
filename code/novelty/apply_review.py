#!/usr/bin/env python3
"""Version the 2026-10-21 novelty tables without modifying chemistry or source files.

Run with Python 3. Standard library only; all decisions are explicit below.
Current NP/NR refer to the stated comparison scope. None means unresolved, never 0.
"""
from pathlib import Path
from collections import Counter
import copy
import csv
import hashlib
import json

HERE = Path(__file__).resolve().parent
import os
ROOT = HERE.parent
SOURCE = ROOT / "data/novelty/baseline"
OUT = Path(os.environ.get("REACTION_NOVELTY_OUTPUT", ROOT/"results/novelty"))
VERSION = "2026-10-23-review-revision-v1"
DATE = "2026-10-23"
N_DOI = "10.1002/adsc.202200352"
S_DOI = "10.1021/acs.joc.0c02436"
REVIEW = "outputs/2026-10-22_workflow_independent_review/审核报告.md"
SEVEN = {"AP022", "AP043", "AP044", "AP045", "AP046", "AP047", "AP049"}
FILES = ["novelty_candidates_100.json", "novelty_hypotheses_115.json",
         "novelty_product_options_124.json", "novelty_actual_pairs_108.json"]
MODEL_N_DESCRIPTORS = {27: "吡咯", 35: "咪唑", 40: "吡唑", 49: "1,2,4-三唑"}
ACTUAL_N_DESCRIPTORS = {
    "AP001": "叔丁基取代咪唑", "AP004": "溴代四氢咔唑", "AP005": "溴代吲哚",
    "AP006": "溴苯基取代吲哚", "AP007": "苯并含O/N杂环胺", "AP009": "乙酰基取代吲哚",
    "AP011": "N-乙基萘胺", "AP012": "酯基取代四氢咔唑", "AP016": "N-甲基氨基吡啶",
    "AP017": "甲氧基咔唑", "AP018": "甲氧基吲哚", "AP019": "甲基吲哚",
    "AP020": "二甲基咔唑", "AP021": "甲基四氢喹啉", "AP022": "4-甲基吲哚",
    "AP023": "另一位次的甲基吲哚（以所录SMILES为准）", "AP024": "氟代吲哚",
    "AP025": "碘代咔唑", "AP026": "氰基吲哚", "AP027": "另一位次的氰基吲哚（以所录SMILES为准）",
    "AP028": "羧基苯并咪唑", "AP032": "羟基氮杂吲哚", "AP035": "N-苄基苯胺",
    "AP036": "苄氧基吲哚", "AP038": "二苯胺", "AP039": "吲哚啉",
    "AP040": "吩噻嗪", "AP041": "多环稠合咔唑", "AP042": "稠合四氢咔唑", "AP044": "吲哚啉",
}


def load(name):
    return json.loads((SOURCE / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def csvsave(name, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list))
                        else "待核" if v is None else v for k, v in row.items()})


def audit(row, fields):
    row["version"] = VERSION
    row["previous_score"] = {k: copy.deepcopy(row.get(k)) for k in fields}
    row["score_change_reason"] = "保留既有数值；本次未逐项重新穷尽查新。"
    row["review_status"] = "retained_not_independently_rescored"


def compare(ref, doi, similarity, difference, evidence, pending):
    return {"reference_code": ref, "doi": doi, "same": similarity,
            "different": difference, "evidence_level": evidence,
            "pending": pending}


def aggregate(row, options):
    vals = [o["NP"] for o in options]
    resolved = [x for x in vals if x is not None]
    row["NP_label"] = "/".join(dict.fromkeys(o["NP_label"] for o in options))
    row["NP_all_resolved"] = all(v is not None for v in vals)
    row["NP_unresolved_options"] = [o["option_id"] for o in options if o["NP"] is None]
    row["NP_min"] = min(vals) if vals and row["NP_all_resolved"] else None
    row["NP_max"] = max(vals) if vals and row["NP_all_resolved"] else None
    row["NP_known_min"] = min(resolved) if resolved else None
    row["NP_known_max"] = max(resolved) if resolved else None
    nrs = [o["NR"] for o in options]
    row["NR_all_resolved"] = all(n is not None for n in nrs)
    row["NR_unresolved_options"] = [o["option_id"] for o in options if o["NR"] is None]
    if not nrs:
        row["NR"] = "不适用"
        row["NP_label"] = "不适用"
        row["NR_min"] = row["NR_max"] = None
    elif not row["NR_all_resolved"]:
        row["NR"] = row["NR_min"] = row["NR_max"] = None
    else:
        row["NR_min"], row["NR_max"] = min(nrs), max(nrs)
        row["NR"] = nrs[0] if len(set(nrs)) == 1 else f"{min(nrs)}–{max(nrs)}"


def role(h):
    """2026-10-23 study-design role, explicitly not a recovered historical rank."""
    n, i = h["candidate_number"], h["hypothesis_index"]
    if n in {3, 16, 20}:
        return "已知参考", "与原C–C种子相同的有机硼供体路线，用于建立底物/条件基线；具体取代基兼容性仍待验证。"
    if n == 78:
        return "已知参考", "二硫化物与三氟丙酰胺已有直接C–S方法，可作供体形式比较；不能等同于本酮/硫醇路线的阳性对照。"
    if n in {27, 35} and ((n == 27 and i == 2) or (n == 35 and i == 2)):
        return "优先探索", "中性杂芳环N形成C(F)–N的局部先例明确；以目标羰基与新条件的兼容性为待检问题。"
    if n in {38, 40, 48, 49, 51, 52, 61, 68, 75, 80, 82}:
        return "优先探索", "对应常规N–H/O–H/S–H供体及目标局部连接已有先例，终态可明确；优先验证本底物与催化/碱条件兼容性。"
    if n in {85, 89, 90, 94, 95, 99}:
        reason = "P–H/P(O)–H类有正向成键依据；目标羰基、供体活性形式与当前金属/碱条件仍需匹配，保留为有正支持的挑战伙伴。"
        if n == 95:
            reason = "Ph2PH形成单氟C(F)–P已有37%正例（V05 SI S15）；本CF3羰基与现有条件需另证，不预设为失败对照。"
        if n in {85, 89}:
            reason += "本试剂是(RO)2P(O)H亚磷酸酯，不是R2P(O)H二烷基膦氧化物。"
        return "条件受限挑战", reason
    if n == 100:
        return "条件受限挑战", "PhSeH有66%的PhSe–CH=CF2成功例；C(F)–Se单氟先例使用selenosulfonate，需分开检验供体形式及连接位点。"
    if n == 35 and i == 1:
        return "推演待证", "与H02共用母体连接；质子化/反离子及可分离盐型未确证，不作为额外新骨架优先。"
    if n in {39, 46}:
        return "条件受限挑战", "同类CF3酮胺化有HRMS中间体依据，尚非分离终产物；V05还报告哌啶不形成相应单氟产物，需单独寻找条件。"
    if n in {45, 58, 59, 60, 62, 63, 64, 65, 70, 71, 72, 76, 79}:
        return "条件受限挑战", "局部连接有类比，但预成盐、供体形态、氧化态或竞争位点改变了活化要求，需与中性供体分别验证。"
    if n in {1, 6, 9, 10, 13, 14, 23, 26, 31, 32, 33, 50}:
        return "条件受限挑战", "存在已知产物/相邻反应或具体条件限制；当前供体活化和目标终态兼容性仍未建立。"
    return "推演待证", "当前主要为结构/机理推演，或终态及活化步骤尚未明确；高NP/NR或数据库未命中均不提升成功优先级。"


def main():
    OUT.mkdir(exist_ok=True)
    originals = {name: load(name) for name in FILES}
    source_hashes = {name: sha(SOURCE / name) for name in FILES}
    hs = copy.deepcopy(originals["novelty_hypotheses_115.json"])
    ps = copy.deepcopy(originals["novelty_product_options_124.json"])
    aps = copy.deepcopy(originals["novelty_actual_pairs_108.json"])
    changes = []
    pmap = {p["option_id"]: p for p in ps}
    for p in ps:
        audit(p, ["NP", "NP_label", "NR"])
        p["NP_scope"] = "所列产物的连接/明确标注的互变体关系；不涉及立体化学首创性"
        p["parent_connectivity_key"] = p["product_inchikey"].split("-")[0]
        p["NP_status"] = "inherited_bounded_assessment"
        p["NR_status"] = "inherited_bounded_assessment"
        p["assessment"] = "沿用对应假设的既有证据边界。"

    for idx in ["035-H01-O01", "035-H02-O01"]:
        p = pmap[idx]
        p.update(NP=2, NP_label="2", NP_status="parent_connectivity_assessed",
                 NP_scope="母体连接；盐型/质子化状态不新增骨架",
                 parent_group_id="PARENT-035-N-vinylimidazole",
                 salt_form_novelty_status="unresolved" if "H01" in idx else "not_separately_claimed",
                 counterion=None, isolability_status="not_verified",
                 evidence_kind="same_parent_connectivity_acid_base_forms",
                 note="H01/H02的InChIKey连接层均为VQEJOXYKURNHHU。两种酸碱态保留原SMILES；不计两个新骨架。",
                 assessment="中性N-氟乙烯咪唑已有局部连接先例；本目标属于羰基骨架范围扩展。离子盐型需反离子、稳定性和分离证据后单独评价。",
                 score_change_reason="将母体连接与质子化/盐型创新分开；H01旧NP3不再作为新成键骨架评分，H02的NP2保留。",
                 review_status="corrected_parent_scope")
    p = pmap["055-H01-O01"]
    p.update(assessment="NP1T表示与已登记β-酮酰氟的互变体关系；NR3表示拟议CF3羰基起始物至该终态的路线尚未核实。",
             note="登记互变体关系不等于相同键级图，也不证明本反应得到可分离含氟烯醇。",
             score_change_reason="仅清除与NP1T冲突的旧‘3分只对所画烯醇’理由；数值保持NP1T/NR3。",
             review_status="reason_corrected_scores_retained")
    for j, endpoint in enumerate(["保留两个SiMe3的二硅基膦", "保留一个SiMe3的单硅基膦", "不含Si的一级膦PH2终态"], 1):
        p = pmap[f"086-H01-O{j:02d}"]
        p.update(NP=None, NP_label="待核", NP_status="unresolved_endpoint_specific_search",
                 endpoint_identity=endpoint, evidence_kind="endpoint_specific_novelty_unresolved",
                 note=f"本选项为{endpoint}；精确PubChem未命中仍保留，但尚无足够匹配文献支持当前NP2或NP3判定。",
                 assessment=f"与V05的Ph2PH单氟产物比较：同为C(F)–P，P取代基不同。本选项为{endpoint}；该终态的近例检索及能否形成/分离待核。",
                 score_change_reason="旧NP3按候选编号统一赋值；本次拆分终态，缺少终态专属证据时用待核，避免把去硅PH2误标为silyl phosphine。",
                 review_status="endpoint_specific_uncertainty",
                 NR_status="retained_bounded_no_matching_route")

    for h in hs:
        audit(h, ["NP_label", "NP_min", "NP_max", "NR"])
        h["product_options"] = [pmap[p["option_id"]] for p in h["product_options"]]
        aggregate(h, h["product_options"])
        n = h["candidate_number"]
        if n in {35, 55, 86}:
            h["assessment"] = "；".join(dict.fromkeys(p["assessment"] for p in h["product_options"]))
            h["score_change_reason"] = h["product_options"][0]["score_change_reason"]
            h["review_status"] = h["product_options"][0]["review_status"]
        if h["center"] == "N" and n in MODEL_N_DESCRIPTORS:
            donor = MODEL_N_DESCRIPTORS[n]
            h["assessment"] = (
                f"{donor}的局部N-氟乙烯连接有既有近例。V31已报道三氟丙酰胺与吲哚生成N-单氟烯基产物，"
                f"因此不能把‘含氟羰基C–N’笼统作为空白；本假设为苯基酮PhCOCH2CF3与{donor}，"
                "具体差别是酮/酰胺及N杂环身份，准确取代范围和条件兼容性仍待逐例核实，保留现有NP/NR。")
            if n == 35:
                h["assessment"] += "H01/H02共用母体连接，质子化、反离子和可分离盐型另待核，不新增骨架。"
            if n == 27:
                h["assessment"] += "此处仅指N端，不能与另列吡咯C端反应混同。"
            if n == 49:
                h["assessment"] += "三唑的区域异构终态还须核对。"
            h["references"] = ["V31"] + [x for x in h["references"] if x != "V31"]
            h["nearest_precedent_dois"] = [N_DOI] + [x for x in h["nearest_precedent_dois"] if x != N_DOI]
            reason = "理由补入直接三氟丙酰胺/吲哚先例，具体区分酮/酰胺及N伙伴身份；不另改分。"
            h["score_change_reason"] = (h["score_change_reason"] + " " + reason) if n == 35 else reason
            h["review_status"] = "specific_N_comparison_corrected"
            for p in h["product_options"]:
                p.update(assessment=h["assessment"], references=list(h["references"]),
                         nearest_precedent_dois=list(h["nearest_precedent_dois"]),
                         score_change_reason=h["score_change_reason"], review_status=h["review_status"])
        if n == 58:
            h["assessment"] = (
                "C(F)–OAr局部连接已有；本候选为4-CF3苯酚钠，预成盐及目标苯基酮的兼容性仍待核。"
                "V05主文Fig.4所述缺电子酚和芳硫酚低效指完整两步路线及最终CF2产物；"
                "未拆分单氟形成与后续HF步骤的贡献，不能据此判定本候选单氟形成失败。NP2/NR2保留。")
            h["score_change_reason"] = "修正V05限制的反应终点：完整两步路线低效，不定位为单氟形成失败；数值不变。"
            h["review_status"] = "two_step_endpoint_scope_corrected"
            for p in h["product_options"]:
                p.update(assessment=h["assessment"], score_change_reason=h["score_change_reason"], review_status=h["review_status"])
        for p in h["product_options"]:
            if p["assessment"] == "沿用对应假设的既有证据边界。":
                p["assessment"] = h["assessment"]
        h["recommendation_role"], h["recommendation_reason"] = role(h)
        h["recommendation_scope"] = "2026-10-23修订时的研究设计角色；不代表历史生成排序、成功概率或独立预测验证。"
        h["recommendation_evidence_timing"] = "current_synthesis_including_post_generation_literature"
        h["score_scope"] = "原2026-10-21有限检索及2026-10-23显式审稿修订；无全球首次证明，未改写原候选生成时间线。"
        h["target_substrate_comparators"] = []
        if h["center"] == "N" and n in {27, 35, 40, 49}:
            h["target_substrate_comparators"].append(compare("V31", N_DOI,
                "三氟丙酰胺经脱氟生成含N单氟烯基产物的底物类别", "文献为吲哚；当前为其他N杂环及苯基酮模型",
                "primary_author_abstract", "具体范围、产物结构图和原文SI"))
        if h["center"] == "S" and n in {68, 71, 72, 75, 78, 79, 80, 82}:
            h["target_substrate_comparators"].append(compare("V32", S_DOI,
                "三氟丙酰胺脱氟硫化及单氟含S产物类别", "文献供体为二硫化物；模型为苯基酮，供体依当前候选明确区分",
                "primary_author_abstract", "准确原子连接、逐底物产率和条件适用范围"))

    for a in aps:
        audit(a, ["NP_label", "NR"])
        a["execution_status"] = "executed"
        a["execution_evidence_source"] = "author_confirmation2026-10-23"
        a["execution_confirmation_date"] = DATE
        a["execution_evidence_note"] = "作者确认全部108个组合均已实际执行；该确认只更新执行状态，不代替投料身份、谱图和定量核验。"
        a["execution_status_before_review"] = "undetermined_scaleup_only" if a["actual_pair_id"] in SEVEN else "workbook_recorded"
        a["unique_sample_ids"] = [x for x in a["sample_ids"] if x != "放大量"]
        a["sample_id_status"] = "missing_unique_sample_id" if not a["unique_sample_ids"] else "recorded_not_independently_audited"
        a["input_identity_status"] = "workbook_structure_not_independently_verified"
        a["input_identity_issues"] = []
        a["product_identity_status"] = "not_independently_confirmed"
        a["quantitative_result_status"] = "not_independently_calibrated_or_verified"
        a["structure_basis"] = "原表采用的SMILES假设，未因作者确认执行而更改结构"
        if a["actual_pair_id"] in {"AP022", "AP039"}:
            a["input_identity_status"] = "unresolved_name_smiles_conflict"
            a["input_identity_issues"].append("汇总NH-底物扩展Q40/Q41为YL-4-OMe，但R40/R41为对甲基酮；相关组合保留原SMILES，实际称量/配液身份待核。")
        if a["actual_pair_id"] == "AP049":
            a["input_identity_status"] = "unresolved_name_smiles_conflict"
            a["input_identity_issues"].append("汇总OH-底物扩展S80为YL-OMe，但T80为N-苯基三氟丙酰胺；保留原SMILES，实际投料身份待核。")
        if a["actual_pair_id"] in {"AP002", "AP045", "AP105"}:
            a["input_identity_issues"].append("所录结构缺少所标分支要求的X–H；执行确认不使此目标假设变为适用，也不等于反应失败。")
        for o in a["options"]:
            audit(o, ["NP", "NP_label", "NR"])
            o["assessment"] = a["assessment"]
            o["NP_status"] = "registered_connectivity" if o["NP_label"] == "1R" else "inherited_bounded_assessment"
            o["NR_status"] = "inherited_bounded_assessment"
            o["references"] = list(a["references"])
            o["nearest_precedent_dois"] = list(a["nearest_precedent_dois"])
            o["comparison_evidence"] = []
        if a["route"] == "NH" and a["options"] and a["actual_pair_id"] != "AP043":
            apid = a["actual_pair_id"]
            electrophile = "N-苯基三氟丙酰胺" if "Nc1ccccc1" in a["electrophile_smiles"] else "对甲氧基芳基三氟乙基酮" if a["electrophile_smiles"].startswith("COc") else "对甲基芳基三氟乙基酮"
            donor = ACTUAL_N_DESCRIPTORS.get(apid, "本行CAS/SMILES明确的N伙伴")
            old_reason = a["assessment"]
            if "N-H杂芳环" in old_reason or "芳胺单氟连接" in old_reason:
                difference = f"本组合按原表结构为{electrophile}+{donor}；"
                difference += "电亲体同属三氟丙酰胺，但吲哚啉与吲哚的饱和度及N环境不同" if apid == "AP044" else "与V31的比较差别在酮/酰胺、N伙伴的环系/饱和度或具体取代基"
                a["assessment"] = ("V31已报道三氟丙酰胺与吲哚的Pd催化选择性脱氟，不能以广义含氟羰基C–N缺乏先例作为区别。"
                    + difference + "，具体逐底物重叠和条件范围仍待原文/SI核对。既有局部连接近例继续参考，保留本项NP/NR数值。")
            else:
                a["assessment"] = old_reason + (
                    f" V31另提供三氟丙酰胺/吲哚的直接C–N比较背景；本组合为{electrophile}，"
                    "本行N伙伴与吲哚的功能类别及活性形式不同，不由该文推定本组合成功或未报道；保留现有NP/NR并逐例待核。")
            a["references"] = ["V31"] + [x for x in a["references"] if x != "V31"]
            a["nearest_precedent_dois"] = [N_DOI] + [x for x in a["nearest_precedent_dois"] if x != N_DOI]
            a["score_change_reason"] = "修正笼统N类理由；纳入三氟丙酰胺/吲哚直接先例，明确本项电亲体和伙伴差别，数值保持不变。"
            a["review_status"] = "specific_N_comparison_corrected_scores_retained"
            for o in a["options"]:
                o.update(assessment=a["assessment"], references=list(a["references"]),
                         nearest_precedent_dois=list(a["nearest_precedent_dois"]),
                         score_change_reason=a["score_change_reason"], review_status=a["review_status"])
                o["comparison_evidence"] = [compare("V31", N_DOI,
                    "三氟乙基羰基底物的选择性脱氟C–N及单氟N-烯基产物类别",
                    f"本项{electrophile}与{donor}，按原表SMILES逐例比较；不把酰胺、酮或不同N家族等同",
                    "primary_author_abstract", "原文/SI具体底物、成键终态及条件；本项身份冲突如有则另待核")]
        if a["actual_pair_id"] == "AP064":
            for o in a["options"]:
                if o["option_id"].endswith("O01"):
                    o["assessment"] = "羧酸O形成烯基酯的选项；当前证据未核实该羧酸供体的CF3羰基串联，保留NR3。"
                else:
                    o["NR"] = 2
                    o["assessment"] = "酚O形成C(F)–OAr烯醚的选项；按V05/V10酚类局部连接和目标骨架范围扩展标准记NR2，羧酸基仅作为共存官能团。"
                o["score_change_reason"] = "按每个产物的实际成键O位点评价；O01羧酸分支NR3，O02酚氧分支NR2。"
                o["review_status"] = "product_specific_NR_corrected"
                o["NR_status"] = "option_specific_bounded_assessment"
            a["assessment"] = "AP064-O01羧酸O进攻：NP3/NR3；AP064-O02酚O进攻：NP2/NR2。组合层报告NR2–3，不以单一分数替代位点分支。"
            a["score_change_reason"] = "修正羧酸分支理由错误传播到酚氧产物；保留原结构和两种NP。"
            a["review_status"] = "product_specific_NR_corrected"
        if a["actual_pair_id"] == "AP043":
            a["references"] = ["V31"] + a["references"]
            a["nearest_precedent_dois"] = [N_DOI] + a["nearest_precedent_dois"]
            a["assessment"] = "直接比较应为三氟丙酰胺与吲哚的Pd催化选择性脱氟（Du等2022），并核对CN115322131家族。当前预测产物连接已登记（CID175467892，NP1R）；不能再用‘含氟羰基骨架不同’作为NR2主理由。精确底物/吲哚取代及专利实施例、条件相同程度未完成核对，NR暂待核。"
            a["score_change_reason"] = "新纳入直接同底物类别/N伙伴类别先例，旧NR2理由失效；证据不足以确认具体分档，暂置待核而不机械降为1。"
            a["review_status"] = "nearest_direct_precedent_added_NR_unresolved"
            for o in a["options"]:
                o.update(NR=None, NR_status="unresolved_direct_prior_art_overlap",
                         assessment=a["assessment"], references=a["references"],
                         nearest_precedent_dois=a["nearest_precedent_dois"],
                         score_change_reason=a["score_change_reason"], review_status=a["review_status"])
                o["comparison_evidence"] = [compare("V31", N_DOI,
                    "三氟丙酰胺+吲哚及单氟N-烯基连接类别；产物连接登记相同",
                    "具体取代基、实际催化条件和E/Z尚待逐例核实", "primary_author_abstract_plus_registry",
                    "CN115322131原实施例与论文SI，不凭摘要补出产率")]
        if a["route"] == "SH" and a["options"]:
            a["references"] = ["V32"] + a["references"]
            a["nearest_precedent_dois"] = [S_DOI] + a["nearest_precedent_dois"]
            a["assessment"] = "Shen等2021直接报道三氟丙酰胺与二硫化物的Cu催化选择性脱氟硫化。本组合采用所录硫醇，比较重点是供体形式、具体取代基及条件/终点控制；不能声称三氟丙酰胺C–S类别首次。保留NR2作为供体/范围扩展的有限评价，准确原子连接与逐例结构待原文/SI核对。"
            if a["actual_pair_id"] in {"AP096", "AP104"}:
                a["assessment"] += "该预测产物已有相同连接登记并关联CN112341368A/B，NP1R保留；登记关联本身不证明已核对原实施例。"
            a["score_change_reason"] = "保留NP/NR数值，最近比较改为直接三氟丙酰胺C–S文献；硫醇/二硫化物区别显式记录。"
            a["review_status"] = "nearest_direct_precedent_added_scores_retained"
            for o in a["options"]:
                o.update(assessment=a["assessment"], references=a["references"],
                         nearest_precedent_dois=a["nearest_precedent_dois"],
                         score_change_reason=a["score_change_reason"], review_status=a["review_status"])
                o["comparison_evidence"] = [compare("V32", S_DOI,
                    "三氟丙酰胺底物类别与单氟含S产物类别",
                    "本表为硫醇，文献为二硫化物；精确结构和条件范围逐例核对",
                    "primary_author_abstract_plus_registry" if o["NP_label"] == "1R" else "primary_author_abstract",
                    "原文结构图、SI和CN112341368A/B实施例，不能仅凭名称确定同一连接")]
        aggregate(a, a["options"])

    cs = []
    for original in originals["novelty_candidates_100.json"]:
        c = copy.deepcopy(original)
        audit(c, ["NP_results", "NR_results"])
        sub = [h for h in hs if h["candidate_number"] == c["candidate_number"]]
        c["NP_results"] = [h["NP_label"] for h in sub]
        c["NR_results"] = [h["NR"] for h in sub]
        c["NP_all_resolved"] = all(h["NP_all_resolved"] for h in sub)
        c["NP_unresolved_options"] = [p for h in sub for p in h["NP_unresolved_options"]]
        c["NR_all_resolved"] = all(h["NR_all_resolved"] for h in sub)
        c["assessment"] = [h["assessment"] for h in sub]
        c["recommendation_roles"] = list(dict.fromkeys(h["recommendation_role"] for h in sub))
        c["recommendation_role"] = "/".join(c["recommendation_roles"])
        c["recommendation_by_hypothesis"] = [{"hypothesis_id": h["hypothesis_id"],
            "role": h["recommendation_role"], "reason": h["recommendation_reason"]} for h in sub]
        c["recommendation_scope"] = sub[0]["recommendation_scope"]
        c["score_change_reason"] = "；".join(dict.fromkeys(h["score_change_reason"] for h in sub))
        c["review_status"] = "aggregated_from_revised_hypotheses"
        cs.append(c)

    outputs = dict(zip(FILES, [cs, hs, ps, aps]))
    for name, rows in outputs.items():
        save(name, rows)
        csvsave(name.replace(".json", ".csv"), rows)
    actual_options = [{"actual_pair_id": a["actual_pair_id"], "route": a["route"], **o}
                      for a in aps for o in a["options"]]
    save("actual_product_options_108_pairs.json", actual_options)
    csvsave("actual_product_options_108_pairs.csv", actual_options)

    # Keep all original evidence immutable; add a supplemental comparison catalog.
    source_catalog = load("novelty_sources.json")
    for ref, doi, filename, title in [
        ("V31", N_DOI, "indole_crossref.json", "Palladium-Catalyzed Selective C-F Bond Cleavage of Trifluoropropanamides Leading to (Z)-N-α-Fluorovinylindoles"),
        ("V32", S_DOI, "sulfuration_epmc.json", "Copper-Catalyzed Selective Defluorinative Sulfuration of Trifluoropropanamides Leading to α-Fluorothioacrylamides")]:
        source_catalog.append({"reference_code": ref, "doi": doi, "title": title,
            "access_level": "primary_author_abstract", "reviewed_date": DATE,
            "local_path": f"outputs/2026-10-22_workflow_independent_review/notes/patents/{filename}",
            "scope": "摘要支持底物/伙伴/产物类别；本修订脚本未取得全文或SI，不补写具体产率。"})
    save("novelty_sources.json", source_catalog)

    for name, rows in outputs.items():
        idfield = "candidate_number" if "candidates" in name else "hypothesis_id" if "hypotheses" in name else "option_id" if "product_options" in name else "actual_pair_id"
        for r in rows:
            current = {k: r.get(k) for k in r["previous_score"]}
            if current != r["previous_score"] or r["review_status"] not in {"retained_not_independently_rescored", "aggregated_from_revised_hypotheses"}:
                changes.append({"dataset": name, "id": r[idfield], "previous_score": r["previous_score"],
                    "current_score": current, "score_changed": current != r["previous_score"],
                    "reason": r["score_change_reason"]})
    for a in aps:
        for o in a["options"]:
            if o["review_status"] != "retained_not_independently_rescored":
                changes.append({"dataset": "actual_product_options_108_pairs.json", "id": o["option_id"],
                    "previous_score": o["previous_score"],
                    "current_score": {k: o.get(k) for k in o["previous_score"]},
                    "score_changed": any(o.get(k) != v for k, v in o["previous_score"].items()),
                    "reason": o["score_change_reason"]})
    save("change_log.json", changes)
    csvsave("change_log.csv", changes)

    # Integrity checks: structure strings, IDs, source locations and source hashes unchanged.
    checks = {}
    checks["source_hashes_unchanged"] = source_hashes == {n: sha(SOURCE / n) for n in FILES}
    checks["row_counts"] = {n: len(outputs[n]) == len(originals[n]) for n in FILES}
    checks["all_candidate_structures_unchanged"] = all(x["candidate_smiles"] == y["candidate_smiles"] for x,y in zip(originals[FILES[0]], cs))
    checks["all_hypothesis_reagent_structures_unchanged"] = all(all(x[k] == y[k] for k in ["candidate_smiles", "electrophile_smiles", "hypothesis_id"]) for x,y in zip(originals[FILES[1]], hs))
    checks["all_model_product_structures_unchanged"] = all(all(x[k] == y[k] for k in ["option_id", "product_smiles", "product_inchikey"]) for x,y in zip(originals[FILES[2]], ps))
    checks["all_actual_structures_source_records_unchanged"] = all(all(x[k] == y[k] for k in ["electrophile_smiles", "partner_smiles", "sample_ids", "source_occurrences", "issues", "confirmation_status"]) and all(xo["product_smiles"] == yo["product_smiles"] for xo,yo in zip(x["options"],y["options"])) for x,y in zip(originals[FILES[3]],aps))
    checks["nested_flat_model_options_equal"] = [p for h in hs for p in h["product_options"]] == ps
    checks["all_108_author_confirmed_executed"] = all(a["execution_status"] == "executed" and a["execution_evidence_source"] == "author_confirmation2026-10-23" for a in aps)
    checks["exact_seven_missing_unique_ids"] = {a["actual_pair_id"] for a in aps if not a["unique_sample_ids"]} == SEVEN
    checks["all_115_design_roles_populated"] = all(h["recommendation_role"] and h["recommendation_scope"] for h in hs)
    checks["no_old_water_score_reason"] = "3分只对所画烯醇" not in next(h["assessment"] for h in hs if h["candidate_number"] == 55)
    checks["AP064_option_NR"] = [o["NR"] for a in aps if a["actual_pair_id"] == "AP064" for o in a["options"]] == [3,2]
    checks["086_unresolved_all_endpoints"] = all(pmap[f"086-H01-O{j:02d}"]["NP"] is None for j in [1,2,3])
    checks["035_same_parent_no_new_skeleton_from_protonation"] = pmap["035-H01-O01"]["parent_group_id"] == pmap["035-H02-O01"]["parent_group_id"] and pmap["035-H01-O01"]["NP"] == pmap["035-H02-O01"]["NP"] == 2
    checks["no_generic_N_carbonyl_absence_rationale"] = not any(
        "含氟羰基底物及共轭骨架不同" in r["assessment"] or "本羰基骨架和环化/芳基取代为范围差别" in r["assessment"]
        for r in hs + ps + aps + actual_options)
    checks["058_two_step_not_monofluoro_failure"] = all(
        "完整两步路线" in r["assessment"] and "不能据此判定本候选单氟形成失败" in r["assessment"]
        for r in hs + ps if r.get("candidate_number") == 58)
    checks["all_applicable_NH_options_specific_V31_context"] = all(
        "10.1002/adsc.202200352" in o["nearest_precedent_dois"] and o["assessment"] == a["assessment"]
        for a in aps if a["route"] == "NH" for o in a["options"])
    # The source_occurrences cell intentionally preserves many source rows; allow
    # larger CSV cells than Python's small default when checking the exports.
    csv.field_size_limit(10000000)
    checks["csv_json_row_counts_match"] = {}
    for path in sorted(OUT.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as f:
            csvrows = list(csv.DictReader(f))
        checks["csv_json_row_counts_match"][path.name] = len(csvrows) == len(json.loads(path.with_suffix(".json").read_text()))
    assert all(all(v.values()) if isinstance(v, dict) else v for v in checks.values()), checks
    summary = {"version": VERSION, "source_snapshot": str(SOURCE.relative_to(ROOT)), "source_sha256": source_hashes,
        "counts": {"candidates": len(cs), "hypotheses": len(hs), "model_product_options": len(ps),
                   "actual_pairs": len(aps), "applicable_actual_pairs": sum(bool(a["options"]) for a in aps),
                   "actual_product_options": len(actual_options),
                   "unique_model_product_smiles": len({p["product_smiles"] for p in ps}),
                   "unique_actual_product_smiles": len({o["product_smiles"] for o in actual_options}),
                   "combined_unique_product_smiles": len({p["product_smiles"] for p in ps} | {o["product_smiles"] for o in actual_options}),
                   "all_executed_author_confirmed": len(aps), "missing_unique_sample_id": 7,
                   "explicit_electrophile_name_smiles_conflicts": 3,
                   "model_option_NP_numerical": sum(p["NP"] is not None for p in ps),
                   "model_option_NP_unresolved": sum(p["NP"] is None for p in ps),
                   "hypotheses_NP_unresolved": sum(not h["NP_all_resolved"] for h in hs),
                   "actual_pair_NR_unresolved": sum(a["NR"] is None for a in aps),
                   "actual_pair_NR_not_applicable": sum(a["NR"] == "不适用" for a in aps),
                   "actual_pair_NR_numerical_or_range": sum(a["NR"] is not None and a["NR"] != "不适用" for a in aps)},
        "recommendation_roles_115": dict(Counter(h["recommendation_role"] for h in hs)),
        "model_option_NP_current": dict(Counter(p["NP_label"] for p in ps)),
        "actual_NR_current": dict(Counter("待核" if a["NR"] is None else str(a["NR"]) for a in aps)),
        "field_counts": {n: {"union": len(set().union(*(r.keys() for r in rows))),
                            "intersection": len(set.intersection(*(set(r) for r in rows))),
                            "all_fields": list(dict.fromkeys(k for r in rows for k in r))}
                         for n, rows in outputs.items()},
        "checks": checks,
        "limits": ["108项执行确认不等于108个化学结构均已确认。", "预测产物SMILES保持不变；107种实际预测产物和202种合并查询结构仍以原表身份假设为条件。",
                   "NP/NR为有限证据范围的分类，待核不可当0，不可从聚合中隐去。", "31/32等文献总量不得据本目录自行更新全项目来源分母；V31/S需由主报告按DOI去重。",
                   "本次角色是可解释研究设计，未重算4,391项迁移判断，未声称独立于结果的预测验证。"]}
    save("summary.json", summary)
    print(json.dumps({"counts": summary["counts"], "roles": summary["recommendation_roles_115"], "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

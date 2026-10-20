#!/usr/bin/env python3
"""知衢 · 案例库完整版报告：由计算结果和手写内容生成 report.json，再出 PDF/HTML 并按付费报告标准检查。

一份报告分两部分，更新时只动有变化的那部分：
- 随数据变的（位次、概率、志愿表与逐条说明、敏感性、事后对照、假设、来源）：从 retro_ranks/<位次>/ 自动生成；
- 人写的：案例目录的 narrative.json（画像、方向证据、矛盾、行动、追问等）与 research.json（院校调研，每条带官方来源），
  方向的通用部分（反面、有条件的前景、验证、去向）在 data/directions.json，多个案例共用。

数据或方法更新后的顺序（技能目录）：
  python3 scripts/retro_run.py examples/<案例>          # 重算候选池、志愿表与对照
  python3 scripts/retro_sensitivity.py examples/<案例>  # 重算敏感性
  python3 scripts/case_report.py examples/<案例> --profile-version profile.txt  # 重新生成报告；会列出 narrative.json 里带数字的句子，提醒人工复查
首次建院校调研：--import-research <目录>，从逐校 JSON 里按 narrative.json 的 research_schools 挑选写入 research.json。
"""
import csv
import glob
import json
import math
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent

PROV = {
    "zhejiang": dict(name="浙江", auth="浙江省教育考试院", batch="普通类第一段（专业+院校平行志愿）", home="https://www.zjzs.net/",
                     tdate="2026-09-28", ydate="2026-10-07", yurl="https://www.zjzs.net/art/2026/6/26/art_45_12452.html"),
    "shandong": dict(name="山东", auth="山东省教育招生考试院", batch="普通类常规批第 1 次（专业（类）+学校平行志愿）", home="https://www.sdzk.cn/",
                     tdate="2026-09-28", ydate="2026-10-07", yurl="https://www.sdzk.cn/NewsInfo.aspx?NewsID=7258"),
    "hebei": dict(name="河北", auth="河北省教育考试院", batch="本科批（专业（类）+学校平行志愿）", home="http://www.hebeea.edu.cn/",
                  tdate="2026-09-28", ydate="2026-09-28", yurl="http://www.hebeea.edu.cn/"),
    "jiangsu": dict(name="江苏", auth="江苏省教育考试院", batch="本科批（院校专业组平行志愿）", home="https://www.jseea.cn/",
                    tdate="2026-09-28", ydate="2026-09-29", yurl="https://www.jseea.cn/webfile/index/index_zkxx/2026-06-24/7475494421979467776.html"),
    "hubei": dict(name="湖北", auth="湖北省教育考试院", batch="本科普通批（院校专业组平行志愿）", home="https://jyt.hubei.gov.cn/",
                  tdate="2026-09-28", ydate="2026-09-28", yurl="https://jyt.hubei.gov.cn/"),
}
GRADE = {"zhejiang": "B", "shandong": "A", "hebei": "A", "jiangsu": "B", "hubei": "B"}
WNAME = {"major": "专业（兴趣与适配）", "school": "学校层次", "city": "城市与地域", "outlook": "就业/升学前景"}


def clean(name):
    return name.replace("[公办]", "").replace("[民办]", "")


def school_of(name):
    return re.sub(r"[（(][^()（）]*[市县][)）]", "", clean(name).split("·")[0])


def pct(p, g):
    """正文概率：A 级写整数百分比；B 级取整到 5%。"""
    if p >= 0.995:
        return "超过 99%" if g == "A" else "超过 95%"
    if g == "B":
        if p < 0.05:
            return "不到 5%"
        if p > 0.95:
            return "超过 95%"
        return f"约 {int(round(p * 20)) * 5}%"
    if p < 0.01:
        return "不到 1%"
    return f"约 {p:.0%}"


def round_text(t, g):
    """B 级把作者写的百分数取整到 5%，与志愿表一致；“约前 12%”这类人数占比不改；不到 5% 写“不到 5%”。"""
    if g != "B" or not isinstance(t, str):
        return t
    def f(m):
        if m.group(1):
            return m.group(0)  # “前 12%”是人数占比
        v = float(m.group(3))
        if v < 5:
            return "不到 5%"
        if v > 95:
            return "超过 95%"
        return ("约 " if (m.group(2) or "").startswith("约") else (m.group(2) or "")) + f"{int(round(v / 5)) * 5}%"
    return re.sub(r"(前 ?)?(超过 ?|约 ?)?(\d+(?:\.\d+)?)%(?:\s?左右)?", f, t)


def round_all(x, g):
    if isinstance(x, str):
        return round_text(x, g)
    if isinstance(x, list):
        return [round_all(v, g) for v in x]
    if isinstance(x, dict):
        return {k: round_all(v, g) for k, v in x.items()}
    return x


def read_csv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def subjects_text(cat):
    m = re.search(r"（([^（）]*)）\s*$", cat)
    head = "物理类 · " if cat.startswith("物理类") else "历史类 · " if cat.startswith("历史类") else ""
    return f"{head}选考{m.group(1)}" if m else cat


def import_research(case_dir, folder, schools):
    """从逐校调研 JSON 中按偏好顺序挑选：先取 ≥ 4 项有证据的学校，再补到 3—4 所，写入 research.json。"""
    files = {}
    for f in glob.glob(str(Path(folder) / "*.json")):
        r = json.loads(Path(f).read_text(encoding="utf-8"))
        files[r["school"]] = r
    found = []
    for s in schools:
        key = next((k for k in files if k == s or k.startswith(s) or s.startswith(k)), None)
        if key:
            r = files[key]
            found.append(dict(school=r["school"], sources=[u for u in r["sources"] if str(u).startswith("http")],
                              items=[[str(a), str(b), str(c)] for a, b, c, *_ in r["items"]]))
    ok = lambda r: sum(1 for i in r["items"] if not str(i[2]).startswith("未取到"))
    strong = [r for r in found if ok(r) >= 4]
    chosen = (strong + [r for r in found if r not in strong and ok(r) >= 2])[:max(3, min(4, len(strong)))]
    if found and found[0] not in chosen:
        chosen.append(found[0])  # 最可能去的学校无论资料多少都列出，查不到的照实写
    chosen = [r for r in found if r in chosen]
    (case_dir / "research.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return chosen


def import_opportunities(case_dir, path):
    """把“入学后的机会”（荣誉学院、二次选拔、辅修、推免）并入 research.json 各校，作为单独一项。"""
    opp = json.loads(Path(path).read_text(encoding="utf-8"))
    rp = case_dir / "research.json"
    research = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else []
    for r in research:
        key = next((k for k in opp if k == r["school"] or r["school"].startswith(k) or k.startswith(r["school"])), None)
        if not key:
            continue
        o = opp[key]
        r["items"] = [i for i in r["items"] if i[0] != "入学后的机会"] + [["入学后的机会", o["finding"], o["grade"]]]
        r["sources"] += [u for u in o.get("sources", []) if u not in r["sources"]]
    rp.write_text(json.dumps(research, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build(case_dir, research_dir=None, opportunities=None, render=True, profile_version=None):
    """render=False 时只返回 report.json 的内容，不写文件、不出 PDF（测试“同样输入得到同样报告”用）。"""
    if render and not profile_version:
        raise ValueError("生成报告必须明确指定 profile_version / --profile-version")
    d = Path(case_dir).resolve()
    case = d.name
    cfg = json.loads((d / "retro_config.json").read_text(encoding="utf-8"))
    cj = json.loads((d / "case.json").read_text(encoding="utf-8"))
    run = next((d / "retro_ranks").iterdir())
    res = json.loads((run / "result.json").read_text(encoding="utf-8"))
    hind = json.loads((run / "hindsight.json").read_text(encoding="utf-8"))
    pool = {r["id"]: r for r in read_csv(run / "pool.csv")}
    attrs = {r["id"]: r for r in read_csv(run / "attributes.csv")}
    review = json.loads((run / "preferences_review.json").read_text(encoding="utf-8"))
    prefs = json.loads((run / "preferences_config.json").read_text(encoding="utf-8"))
    sens = read_csv(run / "sensitivity.csv")
    rules = json.loads((SKILL / f"data/{cfg['province']}/rules.json").read_text(encoding="utf-8"))["items"]
    c = json.loads((d / "narrative.json").read_text(encoding="utf-8"))
    D = json.loads((SKILL / "data" / "directions.json").read_text(encoding="utf-8"))
    prof = dict(re.findall(r"^([^：\n]+)：(.*)$", (d / "profile.txt").read_text(encoding="utf-8"), flags=re.M))
    P, g = PROV[cfg["province"]], GRADE[cfg["province"]]
    L = res["list"]
    R = hind["rank"]
    years = cfg["data_years"]
    yrs = f"{years[0]}—{years[-1]}" if len(years) > 1 else str(years[0])
    group = cfg["key"] == "group"
    top = max(L, key=lambda x: x["p_land"])
    weights = sorted(review["weights"].items(), key=lambda kv: -kv[1])
    if "score" in cfg:
        score_txt = f"{cfg['score']} 分"
    else:
        from rank import Table
        yf = {"zhejiang": "yfyd_2026", "shandong": "yfyd_2026"}.get(cfg["province"], f"yfyd_{cfg.get('series', 'physics')}_2026")
        table = SKILL / "data" / cfg["province"] / f"{yf}.csv"
        score_txt = f"约 {Table(str(table)).score_of(R):g} 分（由登记位次换算）"

    # ---------- meta
    meta = dict(title="高考志愿填报决策报告",
                subtitle=f"{P['name']} · {subjects_text(cj['category'])} · 2026 年 · {c['direction_label']}",
                candidate=cj["candidate"], province=P["name"], category=cj["category"], batch=P["batch"],
                score=score_txt, rank=f"{R:,}", date="按 2026 年出分后填报的情形回溯（只用 2025 年及以前的数据）",
                slots=cfg["optimize"]["slots"], case_id=case, generated_on="2026-10-17", prob_grade=g,
                grade_note=grade_note(cfg, g),
                utility_scale=f"0 分 = 你确认的底线（{prefs['scenarios']['student']['anchors']['low']['name'].split('：', 1)[-1]}），100 分 = 最好的学校、最想读的专业、最想去的城市凑在一起（现实中未必存在）")

    # ---------- summary
    lead, keys = c["lead"], c["points"]
    points = [round_text(k, g) for k in keys][:4]
    points.append(f"整张表 {len(L)} 个志愿，按你的排序算出的平均满意度 {res['expected_utility']:.1f} 分（0—100 分），模拟中滑档{'约为 0' if res['p_fall'] < 0.0005 else '约 ' + format(res['p_fall'], '.1%')}。")
    summary = dict(headline=round_text(lead, g), points=points[:5], actions=round_all(c["actions"][:3], g),
                   after_the_fact=round_all(c["after_the_fact"][:2], g))

    # ---------- profile
    facts = [["省份与位次", f"{P['name']}；{score_txt}，全省位次 {R:,}（分数换位次用 2026 年官方一分一段表）" if "score" in cfg else f"{P['name']}；位次 {R:,}（事先登记的位次）"],
             ["选考科目", cj["category"]],
             ["批次与志愿数", f"{P['batch']}，最多 {cfg['optimize']['slots']} 个（2026 年规则）"]]
    for k, label in [("毕业后第一意向", "第一意向"), ("感兴趣的专业", "感兴趣的专业"), ("明确不想读", "不想读"),
                     ("学得轻松的科目", "学得轻松"), ("犯怵的科目", "犯怵的科目"), ("是否愿离开本省", "城市"),
                     ("院校层次最低期望", "院校"), ("家庭经济（学费）", "费用"), ("身体条件", "身体条件"),
                     ("冲稳保风格", "风险态度"), ("家里人的期望", "家里的期望")]:
        if prof.get(k):
            facts.append([label, prof[k]])
    if cfg.get("retake"):
        rt = cfg["retake"]
        facts.insert(1, ["复读前", f"2025 年 {rt['score_2025']} 分，全省位次 {rt['rank_2025']:,}（2025 年官方一分一段表）"])
    constraints = []
    constraints.append("只考虑公办本科；民办、独立学院、中外合作办学不进候选（按教育部名单备注与默认排除词）" if cfg.get("public", True)
                       else "民办、中外合作按你的意愿可以进候选；专项计划、预科、定向等需要特殊资格的一律排除")
    if cfg.get("in_provinces") or cfg.get("in_province"):
        constraints.append(f"候选院校所在地限 {(cfg.get('in_provinces') or cfg.get('in_province')).replace(',', '、')}")
    if prof.get("家庭经济（学费）"):
        constraints.append(f"费用：{prof['家庭经济（学费）']}")
    if cfg.get("subjects"):
        constraints.append(f"选科：你选考{cfg['subjects']['taken'].replace(',', '、')}，已按官方 2027 版选考要求表剔除明显不符的专业；2026 年适用 2024 版，须逐条核对")
    if group:
        constraints.append("专业组省份：组内有哪些专业要看 2026 年招生计划，本表按组排，未逐组核对组内专业")
    constraints += c.get("constraints_extra", [])
    profile = dict(intro=c["intro"], facts=facts, priorities=[[WNAME[k], round(v, 2)] for k, v in weights],
                   constraints=constraints, tensions=round_all(c["tensions"], g))
    s = sum(x[1] for x in profile["priorities"])
    profile["priorities"][0][1] = round(profile["priorities"][0][1] + 1 - s, 2)

    # ---------- directions
    dirs = []
    for x in c["dirs"]:
        key, name, fit, ev = x["key"], x["name"], x["fit"], x["evidence"]
        base = D[key]
        dirs.append(dict(name=name, fit=fit, majors=base["majors"], evidence=round_all(ev, g), counter=base["counter"],
                         outlook=base["outlook"], verify=base["verify"], paths=base["paths"]))

    # ---------- roadmap
    # 备选必须比最可能的去向更好考（预测线更靠后），否则顶不上
    safe = next((x for x in L if x["p_clear"] >= 0.85 and x["order"] > top["order"]
                 and x["expected_cut_rank"] > top["expected_cut_rank"]), None)
    rushes = [x for x in L if x["tag"] == "冲"][:2]
    gap = f"位次 {R:,}。最可能的去向 {clean(top['name'])}，预测线 {top['expected_cut_rank']:,}，单独过线{pct(top['p_clear'], g)}。"
    if rushes:
        gap += "冲刺的 " + "、".join(f"{clean(x['name'])}（预测线 {x['expected_cut_rank']:,}）" for x in rushes) + "，比你的位次靠前。"
    switch = (f"若真实位次比 {top['expected_cut_rank']:,} 还靠后，最可能的去向会失去余量，"
              + (f"第 {safe['order']} 志愿 {clean(safe['name'])}（预测线 {safe['expected_cut_rank']:,}）顶上；" if safe else "要补入更稳的志愿；")
              + "若真实位次明显靠前，把冲刺志愿换成更高一档的学校重算。" + "".join(c.get("switch", [])))
    roadmap = [["门槛与差距", round_text(gap, g)],
               ["顺序与投入", "出分当天确认位次 → 计划公布后逐条核对选考要求、专业代码与计划数" + ("、组内专业" if group else "") + " → 按 06 节核对重点学校的章程（体检、单科、收费） → 填报前一天对着官方计划册检查顺序。"],
               ["里程碑与截止", str(rules["fill_window"]["value"]).replace("见该文件附件 1", "见当年志愿填报通知的附件 1")],
               ["切换条件与备选", round_text(switch, g)],
               ["下次检查点", "出分当天（真实位次）→ 计划公布（核对代码与选考要求）→ 填报截止前一天（最后检查）→ 投档线公布（对照本报告第 11 节）→ 入学第一学期末（转专业窗口）。"]]

    # ---------- news（本省规则）
    news = []
    for k, impact in [("slots", f"本表按 {cfg['optimize']['slots']} 个志愿位计算"), ("parallel", "平行志愿：冲刺放前面不会拖累后面的保底"),
                      ("tie_break", "与录取线同分时按这个规则排序"), ("subject_req", "选考科目不符的志愿不能填，须逐条核对")]:
        it = rules.get(k)
        if it:
            news.append([str(it["value"]).replace("见该文件附件 1", "见当年志愿填报通知的附件 1"), f"2026 年规则（{it['verified']} 核实）", f"{P['auth']} {it['source']}", impact])

    # ---------- list_notes
    notes = {}
    hrows = {r["order"]: r for r in hind["rows"]}
    for x in L:
        p = pool[x["id"]]
        hist = "、".join(f"{y} 年 {int(p[f'rank_{y}']):,}" for y in sorted(years, reverse=True) if p.get(f"rank_{y}"))
        role = {"冲": "冲刺", "稳": "稳妥", "保": "保底"}[x["tag"]]
        t = f"{role}：单独过线{pct(x['p_clear'], g)}，最终落在这里的可能{pct(x['p_land'], g) if x['p_land'] >= 0.005 else '很小'}。"
        if x["order"] == top["order"]:
            t = "整张表最可能的落点。" + t
        t += f" 近年位次：{hist or '只有最近一年记录'}；预测线 {x['expected_cut_rank']:,}"
        if p.get("pred_low") and p.get("pred_high"):
            t += f"（80% 区间 {int(float(p['pred_low'])):,}—{int(float(p['pred_high'])):,}）"
        if p.get("plan"):
            t += f"；{years[-1]} 年计划 {p['plan']} 人"
        if group and p.get("requirement"):
            t += f"；选科要求 {p['requirement']}"
        t += "。" + c.get("notes", {}).get(x["name"], "")
        notes[x["name"]] = t
    need = min(len(L), max(10, len(L) // 4))
    keep = sorted(L, key=lambda x: (-x["p_land"], x["order"]))[:max(need, 12)]
    list_notes = {x["name"]: notes[x["name"]] for x in sorted(keep, key=lambda x: x["order"])}

    # ---------- why
    why = ["平行志愿从上到下依次检查，一旦某个志愿够线就被投档，后面的志愿不再起作用。所以表内按“你有多想去”从高到低排，前面的冲刺志愿不会拖累后面的保底；每个志愿的“最终落在这里”的概率，已经扣除了前面志愿先把你录走的部分。",
           f"整张表 {len(L)} 个志愿，本批次最多可填 {cfg['optimize']['slots']} 个。" + (
               f"排到第 {safe['order']} 个（{clean(safe['name'])}，单独过线{pct(safe['p_clear'], g)}）之后，再往后加志愿对平均满意度几乎没有帮助，所以不强制填满；你可以在后面补几个“录了也愿意去”的作为额外保险。" if safe and len(L) < cfg['optimize']['slots'] * 0.6
               else "你的位次附近单条志愿的把握都不大，所以表里用较多志愿兜底；志愿越多，滑档的可能越小。")]
    why += [round_text(b, g) for b in c["why"]]

    # ---------- sensitivity
    base_s = sens[0]
    sensitivity = [[f"基准：共同波动 {res['params']['rho']}、滑档代价 {res['params']['u_fall']:g}".replace("-", "−"), base_s["expected_utility"], "约 0" if float(base_s["p_fall"]) < 0.0005 else f"{float(base_s['p_fall']):.1%}", "—"]]
    for r in sens[1:]:
        if r["id"] == "ufall_-100" and res["params"]["u_fall"] <= -100:
            continue  # 基准已经是最怕滑档的设定，这一行与基准相同
        same = r["top"] == base_s["top"]
        note = ("否：最可能的去向不变" if same else f"是：最可能的去向变为 {clean(r['top'])}") + ("，前 5 位不变" if r["same_top5"] == "是" else "，前 5 位有变化")
        label = r["scenario"].replace("前景悲观", "前景悲观")
        sensitivity.append([label, r["expected_utility"], "约 0" if float(r["p_fall"]) < 0.0005 else f"{float(r['p_fall']):.1%}", note])

    # ---------- research
    if research_dir:
        import_research(d, research_dir, c.get("research_schools", []))
    if opportunities:
        import_opportunities(d, opportunities)
    research = json.loads((d / "research.json").read_text(encoding="utf-8")) if (d / "research.json").exists() else []
    from urllib.parse import unquote
    for r in research:  # 网址里的中文按原样显示，家长看得懂；浏览器打开时会自动转码
        r["sources"] = [unquote(u) for u in r["sources"]]

    # ---------- questions / todo
    questions = c["questions"] + ["这个专业每年大概有多少人转出、多少人转入？门槛是什么？", "这个专业近两届毕业生去了哪些单位、多少人读研？（看学校就业质量报告）",
                                  "大一大二的课程负荷怎么样？哪些课最难？"]
    todo = [["2026 年适用的选考要求（2024 版）：表中每个志愿是否接受你的选科", f"{P['auth']}选考要求查询；{rules['subject_req']['source']}"],
            ["2026 年招生计划：专业" + ("组及组内专业" if group else "") + "是否继续招生、代码是否变化（本表代码取自 2025 年投档表）", f"{P['auth']}招生计划与各校招生网"],
            ["各校 2026 年招生章程的体检、单科成绩、外语语种限制", "各校本科招生网；阳光高考 https://gaokao.chsi.com.cn/zsgs/zhangcheng/"],
            ["重点学校的学费、住宿费与就读校区", "见第 06 节；以各校章程与缴费通知为准"],
            ["同分时的排序规则", f"{rules['tie_break']['source']}"],
            ["真实位次（出分当天）", f"{P['auth']} 2026 年一分一段表"],
            ["入学后的机会：荣誉学院、二次选拔的实验班、辅修与转专业的报名时间", "见第 06 节各校“入学后的机会”；以学校当年通知为准"]]
    todo += c.get("todo", [])

    # ---------- assumptions / backtest / methods
    drift = res["params"]["drift"]
    assumptions = [["考生位次", f"{R:,}", "分数事先登记，用 2026 年官方一分一段表换算" if "score" in cfg else "事先登记的位次"],
                   ["数据年份", yrs, f"只用 2026 年以前公布的{P['name']}投档表；2026 年表只在第 11 节读取"],
                   ["全省漂移 drift", f"{drift}", "用登记的往年数据，相邻两年同一条目位次对数比的中位数，取最近至多三步平均"],
                   ["波动倍数 sigma-scale", "1.0", "默认值；本案未按目标年调参"],
                   ["共同波动相关 rho", f"{res['params']['rho']}（敏感性 0.1 / 0.5）", "优化器默认"],
                   ["滑档效用 / 滑档上限", f"{cfg['optimize']['u_fall']} / {cfg['optimize']['max_fall']:.1%}", "按你对录取稳妥的要求设定"],
                   ["效用权重", "、".join(f"{WNAME[k][:2]} {v:.2f}" for k, v in weights), "按你的排序用排序倒数法换算（preferences.py）"],
                   ["候选池", f"{len(pool)} 个", "方向、公办、所在地、位次段筛选后，过线概率不低于 2% 的候选"],
                   ["模拟次数 / 种子 / 压力倍数", f"{res['params']['sims']} / {res['params']['seed']} / {res['params']['stress']:g}", "optimize.py 默认"],
                   ["决策模式", "simulation（模拟）", "2024 版选考要求与 2026 年招生计划未入库，资格项待核"]]
    backtest = backtest_text(cfg)
    methods = methods_block(cfg, P, res, pool, yrs, drift, g, group, top, hind)

    # ---------- hindsight
    hindsight = hindsight_block(cfg, P, hind, L, pool, R)

    # ---------- sources
    sources = [[f"{P['name']} {yrs} 年投档表（排表所用全部位次）", f"{P['auth']} {P['home']}；各年原表链接见 data/{cfg['province']}/sources.csv", P["tdate"]],
               [f"{P['name']} 2026 年投档表（只用于第 11 节对照）", f"{P['auth']} {P['home']}；链接见 data/{cfg['province']}/sources.csv", P["tdate"]],
               [f"{P['name']} 2026 年一分一段表（分数换位次）", f"{P['auth']} {P['yurl']}", P["ydate"]],
               ["本省志愿个数与投档方式", f"{P['auth']} {rules['slots']['source']}", rules["slots"]["verified"]],
               ["同分排序规则", f"{P['auth']} {rules['tie_break']['source']}", rules["tie_break"]["verified"]],
               ["选考科目要求", f"{P['auth']} {rules['subject_req']['source']}", rules["subject_req"]["verified"]],
               ["填报时间", f"{P['auth']} {rules['fill_window']['source']}", rules["fill_window"]["verified"]],
               ["院校所在地与公办民办", "教育部 2025 年全国普通高等学校名单 http://www.moe.gov.cn/jyb_xxgk/s5743/s5744/", "2026-09-28"]]
    if cfg.get("subjects"):
        sources.append(["2027 版选考科目要求汇总（筛选用，2026 年适用 2024 版）", "各省考试院 2025 年公布的《2027 年拟在本省招生的普通高校专业选考科目要求》，见 data/README.md", "2026-10-07"])
    for r in research:
        for u in r["sources"][:3]:
            sources.append([f"{r['school']}院校调研", u, "2026-10-17"])

    rep = dict(meta=meta, summary=summary, profile=profile,
               directions_intro="以下方向由你的兴趣、能力、目标和约束交叉得出。每个方向列出支持证据、反面证据、有条件的前景判断、验证办法，以及考研、考公、就业三条去向的门槛与代价。",
               directions=dirs, roadmap=roadmap, news=news, list_notes=list_notes, why=why, stress_mult="2",
               sensitivity=sensitivity, research=research, questions=questions, todo=todo, ask_me=round_all(c["ask_me"], g),
               assumptions=assumptions, backtest=backtest, methods=methods, hindsight=hindsight, sources=sources,
               numeric_claims=[dict(report_path=f"summary.points.{len(summary['points']) - 1}", number_index=1,
                                    result_path="expected_utility", tolerance=0.05)])
    if not render:
        return rep
    (d / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rel = lambda p: str(Path(p).relative_to(SKILL))
    for ext in ("pdf", "html"):
        out = subprocess.run([sys.executable, "scripts/report.py", rel(d / "report.json"), "--opt", rel(run / "result.json"),
                              "--out", rel(d / f"report.{ext}"), "--profile-version", str(profile_version)], cwd=SKILL, capture_output=True, text=True)
        if out.returncode:
            print(case, ext, out.stderr[-800:])
            if ext == "pdf":
                sys.exit(f"{case}：PDF 没有通过生成步骤（见上），不要交付")
    chk = subprocess.run([sys.executable, "scripts/check_report.py", rel(d / "report.json"), "--opt", rel(run / "result.json"),
                          "--html", rel(d / "report.html")], cwd=SKILL, capture_output=True, text=True)
    sys.path.insert(0, str(SKILL / "scripts"))
    import check_report
    errs = check_report.check_sections(rep, res) + check_report.check_grade(rep, res)
    digits = [t for t in walk(c) if re.search(r"\d", t)]
    from operator_check import generate as generate_operator_check
    generate_operator_check(d, rep)
    return chk.stdout.strip() + chk.stderr.strip(), errs, digits


def walk(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in ("research_schools", "direction_label"):
                yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def plain_change(a):
    """登记后的改动写成家长能看懂的话；技术细节留在 retro_config.json。"""
    t = a.get("change", "")
    if "rank.py" in t:
        return "分数换位次时，第一行合并档的人数没算全，位次少算了几十名；改用官方累计人数后重跑。所有志愿的过线判定都没有变。"
    if "retro_judge" in t:
        return "对照 2026 年结果时，把同一专业不同年份全角、半角括号的写法，以及河北校名里“(北京市)”这类后缀统一了。志愿表本身没改，只影响哪些志愿能和 2026 年对上号。"
    if "pool.py 修正：专业组" in t:
        return "候选池原先漏排了需要特殊资格的组（专项计划、预科班、联合培养等，这些标记写在选科要求一栏）；排除后重跑。" + ("同时按画像去掉了护理类组。" if "护理" in t else "")
    if "legacy" in t or "括号" in t:
        return "往年数据里同一专业的括号写法统一后，能读到的历史位次更全；本案保留登记时的结果，改动前后的差别已核对。"
    return t


def grade_note(cfg, g):
    p = PROV[cfg["province"]]["name"]
    if cfg["province"] in ("jiangsu", "hubei"):
        return (f"{p}按“院校+组号”匹配的历年检验评 B（按选科要求匹配可到 A，但本表按组号排）；"
                f"组号每年重编，组内专业变化，预测误差比专业+院校省份大。2026 年不是改版年，按 B 写：百分比取整到 5%，并给出 80% 区间。")
    if g == "B":
        return f"{p}在十省可信度体检中评 B：常规年份 80% 区间覆盖较好，但选考要求改版那年（2024 年）明显失准。2026 年不是改版年，按 B 写：百分比取整到 5%，并给出 80% 区间。"
    return f"{p}在十省可信度体检中评 A：历年回头检验里，说“八成把握”的区间大约八成真的落在里面，说“95% 稳”的失手不超过 7%。按 A 写：可以写百分比，仍注明是按历年波动推算，不是录取率。"


def backtest_text(cfg):
    key = {"zhejiang": "general", "shandong": "general"}.get(cfg["province"], cfg.get("series", "physics"))
    rows = [r for r in read_csv(SKILL / "data/calibration/province_health.csv")
            if r["province"] == cfg["province"] and r["category"] == key and r["record"] == "year"
            and r["target_year"].isdigit() and int(r["target_year"]) <= 2025 and r["coverage_80"]]
    seen = {}
    for r in rows:
        seen.setdefault(r["target_year"], r)
    parts = [f"{y} 年 80% 区间覆盖 {float(r['coverage_80']):.0%}、“95% 稳”实际失手 {float(r['fail_95']):.1%}" for y, r in sorted(seen.items())]
    p = PROV[cfg["province"]]["name"]
    head = f"{p}按只用目标年以前数据的逐年检验（province_health.py，只列 2025 年及以前）："
    return head + ("；".join(parts) if parts else "可检验的年份太少") + "。区间覆盖接近 80% 说明预测的宽窄大致合适；改版年或数据年份少时会失准，本表用敏感性情景补充。"


def methods_block(cfg, P, res, pool, yrs, drift, g, group, top, hind):
    obs = [r for r in hind["rows"] if r["cleared"] is not None]
    m = [dict(title="1. 数据与口径", paras=[
        f"录取数据：{P['auth']}公布的 {yrs} 年投档表，按{'院校+专业组' if group else '院校+专业名'}对齐历年记录；2026 年投档表只在第 11 节对照时读取。",
        f"位次：分数用 2026 年官方一分一段表换算（取该分数的累计人数，即同分考生的最后一名），与出分后考生能拿到的信息一致。",
        "院校所在地、公办民办取自教育部 2025 年全国普通高等学校名单；专项、预科、定向、联合培养等需要特殊资格的条目一律排除。"]),
         dict(title="2. 模型设定", paras=[
             "每条录取线在位次的对数上预测：以最近一年为主（权重 1、0.15、0.05 依次递减），叠加全省整体漂移；按位次段、历史长度和是否跳变区分波动大小。",
             "整张表用 4000 次模拟评估：每次模拟里各校的线一起涨跌一部分（共同波动），另有各自的独立波动；按平行志愿规则从上往下投档，记录落在哪一条。",
             "志愿表用贪心加交换的方法，选出平均满意度最高、滑档概率不超过上限的组合；满意度按你的排序换算权重，0 分与 100 分固定在本人确认的锚点上。"]),
         dict(title="3. 参数选择与样本外证据", paras=[
             f"全省漂移 {drift}：只用登记的往年数据估计（相邻两年同一条目位次对数比的中位数，取最近至多三步平均）。",
             "波动倍数取 1.0、共同波动相关 0.3，均为默认值；本案没有用 2026 年的结果调任何参数。",
             "人物、分数、筛选条件、打分规则与参数在读取 2026 年投档表之前写定并提交（提交 feb6438）；之后的改动逐条记在 retro_config.json 的 amendments 里。"]),
         dict(title="4. 不确定性与校准", paras=[
             "过线概率是按历年波动推算的，不是录取率：同一年各校的线会一起涨跌，所以不能把几条志愿的概率简单相乘。",
             f"第 05 节的敏感性表展示了共同波动、滑档代价、全省整体松紧和前景悲观时表的变化；第 11 节用 2026 年真实投档线检验，能对上号的 {len(obs)} 条里，预测与实际的差距逐条列出。"]),
         dict(title="5. 局限与效度威胁", paras=[
             "2026 年适用的 2024 版选考要求与 2026 年招生计划没有入库，资格项全部待核；章程里的体检、单科、外语限制模型不检查，要人工核对。",
             "前景分是有条件的判断，不是统计结果；学校分按本省该校录取位次的中间值换算，代表认可度，不是排名榜。",
             "这是一位模拟考生、一年的回溯；2026 年结果已经公布，不是盲测。"] + (["专业组省份组号每年重编，往年组线只用最近一年，预测误差比专业+院校省份大。"] if group else [])),
         dict(title="6. 结论与证据等级", paras=["每条结论按证据强弱分四档：已证实、有证据待确认、目前无证据、不可能或极不可能。"],
              columns=["结论", "依据", "等级"],
              rows=[["排表用的历年位次与官方原表一致", "逐条对照官方投档表（独立复核）", "已证实"],
                    [f"最可能的去向是 {clean(top['name'])}", "模型推算：按历年波动模拟 4000 次", "有证据待确认"],
                    ["表中志愿都满足选考要求", "只按 2027 版官方表粗筛，2026 年适用 2024 版未核" if cfg.get("subjects") else "2024 版选考要求未入库", "有证据待确认"],
                    ["本表在 2026 年的真实结果", "第 11 节逐条对照 2026 年官方投档表", "已证实"],
                    ["某所学校“一定录取”", "平行志愿下任何单条都有波动", "不可能或极不可能"]])]
    return m


def hindsight_block(cfg, P, hind, L, pool, R):
    cols = ["序", "志愿", "标签", "预测过线", "预测线", "2026 实际线", "实际过线", "说明"]
    table = []
    stop = hind["landing_order"] or max(12, next((r["order"] for r in hind["rows"] if r["cleared"]), 12))
    for r in hind["rows"]:
        if r["order"] > max(stop, 12):
            break
        table.append([r["order"], clean(r["name"]), r["tag"], round_text(f"{r['p_clear']:.0%}", "B" if cfg["province"] in ("zhejiang", "jiangsu", "hubei") else "A"), f"{r['expected_cut_rank']:,}",
                      f"{r['actual_rank']:,}" if r["actual_rank"] else "—",
                      "—" if r["cleared"] is None else ("是" if r["cleared"] else "否"), r["note"]])
    obs = [r for r in hind["rows"] if r["cleared"] is not None]
    harder = sum(r["actual_rank"] < r["expected_cut_rank"] for r in obs)
    same = sum(r["actual_rank"] == r["expected_cut_rank"] for r in obs)
    notes = [f"判定规则：从第 1 个志愿往下，第一个 2026 年最低位次不高于你的位次（{R:,}）的志愿就是落点；遇到 2026 年对不上号的志愿记为“无法判定”，不跳过。退档、体检和章程限制不在判定范围内。",
             f"结果：{hind['status']}" + (f"，第 {hind['landing_order']} 志愿 {clean(hind['landing'])}" if hind["landing"] else (f"（第 {hind['blocker_order']} 志愿对不上号）" if hind["blocker_order"] else "")) + "。",
             f"能对上号的 {len(obs)} 条里，{harder} 条 2026 年实际比预测更难考（录取位次数字更小），{len(obs) - harder - same} 条更好考" + (f"，{same} 条一样" if same else "") + "。",
             (f"Brier 分数 {hind['brier']:.3f}（越小越准；全猜 50% 为 0.25）。" if hind.get("brier") is not None else "")]
    extra = []
    am = cfg.get("amendments", [])
    if am:
        extra.append(dict(title="登记后的改动（全部公开）", columns=["日期", "改了什么", "改前的结果"],
                          rows=[[a["date"], plain_change(a), round_text(a.get("before", ""), "B" if cfg["province"] in ("zhejiang", "jiangsu", "hubei") else "A")] for a in am], notes=["每处改动都在读取 2026 年结果之后发现，修正后重跑；判定结论见上。"]))
    return dict(intro=f"本节是回溯：上面各节只用 2025 年及以前的数据写成，下面用{P['auth']}公布的 2026 年投档线逐条对照。",
                columns=cols, table=table, notes=[n for n in notes if n], extra=extra)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("cases", nargs="+", help="案例目录，如 examples/2026-GK-R12")
    ap.add_argument("--import-research", help="逐校调研 JSON 所在目录（首次建 research.json 时用）")
    ap.add_argument("--import-opportunities", help="逐校“入学后的机会” JSON（学校名 → finding/grade/sources），并入 research.json")
    ap.add_argument("--profile-version", required=True, help="明确指定每个案例内实际所用画像文件或存档版本")
    ap.add_argument("--quiet", action="store_true", help="不列出 narrative.json 里带数字的句子")
    a = ap.parse_args()
    bad = 0
    for cs in a.cases:
        path = (SKILL / cs) if not Path(cs).is_absolute() else Path(cs)
        msg, errs, digits = build(path, a.import_research, a.import_opportunities, profile_version=a.profile_version)
        print(f"{path.name}：{msg.splitlines()[0] if msg else ''}")
        for e in errs:
            print(f"  ✗ {e}")
        bad += bool(errs)
        if digits and not a.quiet:
            print(f"  提醒：narrative.json 有 {len(digits)} 句带数字，数据或方法更新后请人工复查")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

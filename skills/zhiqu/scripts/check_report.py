#!/usr/bin/env python3
"""核验报告元数据、显式数字声明及 HTML 志愿表，不猜测自然语言的数字含义。"""
import argparse
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path


def at(obj, path):
    for key in path.split('.'):
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    return obj


def check_report(rep, result, html=None):
    errors = []
    params = result['params']
    for key in ('rank', 'slots'):
        value = rep.get('meta', {}).get(key)
        if value is not None:
            number = re.fullmatch(r'\s*(\d+(?:,\d{3})*(?:\.\d+)?)(?:[（(][^）)]*[）)])?\s*', str(value))
            if not number or float(number.group(1).replace(',', '')) != float(params[key]):
                errors.append(f'meta.{key} 与 result.params.{key} 不一致或格式无效')
    try:
        multiplier = float(rep.get('stress_mult', 2))
        if not math.isfinite(multiplier) or multiplier != float(params.get('stress', 2)):
            errors.append('stress_mult 与 result.params.stress 不一致')
    except (TypeError, ValueError):
        errors.append('stress_mult 必须为有效数字')
    for i, claim in enumerate(rep.get('numeric_claims', [])):
        try:
            text = str(at(rep, claim['report_path']))
            numbers = re.findall(r'-?\d+(?:,\d{3})*(?:\.\d+)?', text)
            value = float(numbers[claim.get('number_index', 0)].replace(',', ''))
            expected = float(at(result, claim['result_path'])) * claim.get('scale', 1)
            tolerance = float(claim.get('tolerance', 0.05))
            if tolerance < 0 or not all(math.isfinite(x) for x in (value, expected, tolerance)):
                raise ValueError('数字及容差须为有限值，容差不可为负')
            if abs(value - expected) > tolerance + 1e-10:
                errors.append(f'numeric_claims[{i}] {claim["report_path"]}: {value} ≠ {expected:g}（容差 {tolerance:g}）')
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            errors.append(f'numeric_claims[{i}] 无效: {exc}')
    if html is not None:
        parser = Tables()
        parser.feed(html)
        from html import unescape
        from report import UTILITY_SCALE, interval80, prob_formatter
        grade = rep.get('meta', {}).get('prob_grade', 'A')
        fmt = prob_formatter(grade)
        numeric = grade in ('A', 'B')
        rank_head = '预测位次' if grade == 'A' else '预测位次（80% 区间）'
        head = ['序', '志愿', '类型', '偏好'] + (['单独过线', '最终录取'] if numeric else []) + [rank_head, '说明']
        tables = [t for t in parser.tables if t and t[0] == head]
        if len(tables) != 1:
            errors.append('HTML 须有且仅有一张完整志愿表')
        else:
            rows = tables[0][1:]
            if len(rows) != len(result['list']):
                errors.append('HTML 志愿行数与 result 不一致')
            for i, (cells, item) in enumerate(zip(rows, result['list'])):
                rank_cell = f'{item["expected_cut_rank"]:,}' + ('' if grade == 'A' else interval80(item))
                probs = [unescape(fmt(item['p_clear'])), unescape(fmt(item['p_land'], 1))] if numeric else []
                expected = [str(item['order']), item['tag'], f'{item["utility"]:.1f}'] + probs + [rank_cell]
                idx = (0, 2, 3) + ((4, 5, 6) if numeric else (4,))
                actual = [cells[j] for j in idx] if len(cells) == len(head) else []
                if actual != expected or not cells[1].startswith(item['name']):
                    errors.append(f'HTML 志愿表第 {i+1} 行与 result 不一致')
        metrics = Metrics()
        metrics.feed(html)
        items = result['list']
        if items:
            likely = max(items, key=lambda item: item['p_land'])
            name, probability = likely['name'], likely['p_land']
            if likely.get('majors'):
                major = max(likely['majors'], key=lambda major: major['p'])
                name, probability = name.split('·')[0] + '·' + major['name'], major['p']
            good = sum(sum(m['p'] for m in x['majors'] if m['utility'] >= 70) if x.get('majors') else (x['p_land'] - x.get('p_adjusted', 0) if x['utility'] >= 70 else 0) for x in items)
            sims = params.get('sims', 4000)
            fall = lambda p: (f'< {100/sims:.2g}%' if grade == 'A' else '模拟中未出现') if p == 0 else (unescape(fmt(p, 1)) if numeric else '有风险，见第 05 节')
            head4 = [str(len(items)), f'本批次可填 {rep.get("meta", {}).get("slots", "–")} 个', name]
            if grade == 'A':
                mid = ['概率约 ' + percentage(probability), percentage(good), rep.get('meta', {}).get('utility_scale', UTILITY_SCALE)]
            elif numeric:
                mid = ['概率' + unescape(fmt(probability)), unescape(fmt(good)), rep.get('meta', {}).get('utility_scale', UTILITY_SCALE)]
            else:
                mid = ['落点最集中的志愿（本省评级不给精确概率）', ' / '.join(str(sum(x['tag'] == t for x in items)) for t in ('冲', '稳', '保')), '按模型过线可能性分档，不给百分比']
            sp = result['stress']['p_fall']
            if grade == 'A' or result['p_fall']:
                tail = [fall(result['p_fall']), '录取线整体大波动时 ' + fall(sp)]
            else:
                tail = ['未出现', f'{sims:,} 次模拟中没有出现滑档；录取线整体大波动时' + ('也没有' if not sp else '：' + fall(sp))]
            expected = head4 + mid + tail
            if metrics.values != expected:
                errors.append('HTML 摘要指标与 result 不一致')
    return errors


RESEARCH_ASPECTS = ('培养方案', '转专业', '收费', '校区', '就业')
PATH_WORDS = ('考研', '考公', '就业')
ROADMAP_ROWS = ('门槛与差距', '顺序与投入', '里程碑与截止', '切换条件与备选', '下次检查点')
METHOD_TOPICS = ('数据', '模型', '参数', '不确定性', '局限', '证据等级')
EVIDENCE_GRADES = ('已证实', '有证据待确认', '目前无证据', '不可能或极不可能')



GRADES = "ABCD"
PROVINCE_KEYS = {"山东": "shandong", "河南": "henan", "河北": "hebei", "山西": "shanxi", "广东": "guangdong", "福建": "fujian",
                 "浙江": "zhejiang", "江苏": "jiangsu", "湖南": "hunan", "湖北": "hubei"}
HEALTH = Path(__file__).resolve().parent.parent / "data" / "calibration" / "province_health.csv"
# 正文里作者写的“概率”：过线、落点、落在、概率、把握、可能性后面 15 字内出现的百分数
PROB_TEXT = re.compile(r"(过线|落点|落在|概率|把握|可能性)[^，。；：！？\n]{0,15}?(\d+(?:\.\d+)?)%")


def province_grade(meta):
    """本省本科类在十省体检中的评级（主匹配方式那一行）；查不到返回 None。"""
    import csv
    key = PROVINCE_KEYS.get(str(meta.get("province", ""))[:2])
    if not key or not HEALTH.is_file():
        return None
    cat = str(meta.get("category", ""))
    stem = "history" if "历史" in cat else ("general" if key in ("zhejiang", "shandong") else "physics")
    with open(HEALTH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["record"] == "pooled" and r["province"] == key and r["category"] == stem:
                return r["grade"]
    return None


def check_grade(rep, result=None):
    """按本省评级写概率（references/report-guide.md）：评级不比体检更乐观，保底余量够，正文概率写法合规。"""
    errs, meta = [], rep.get("meta", {})
    g = meta.get("prob_grade")
    if g not in tuple(GRADES):
        return ["meta.prob_grade 须为 A、B、C、D 之一（见 report-guide“按本省评级写概率”）"]
    if not meta.get("grade_note"):
        errs.append("meta.grade_note 须写明本省评级、是否改版年和采用这一档的理由")
    base = province_grade(meta)
    if base:
        floor = GRADES[min(len(GRADES) - 1, GRADES.index(base) + (1 if meta.get("reform_year") else 0))]
        if GRADES.index(g) < GRADES.index(floor):
            errs.append(f"prob_grade {g} 比本省评级允许的 {floor} 更乐观（体检评级 {base}{'，改版年降一档' if meta.get('reform_year') else ''}）")
    if result and result.get("list"):
        lst, rank = result["list"], float(result.get("params", {}).get("rank") or 0)
        wide = lambda x, k: rank and x.get("expected_cut_rank", 0) >= k * rank
        if g == "A" and not any(x["p_clear"] >= 0.95 for x in lst):
            errs.append("A 级保底不足：须至少一个志愿单独过线 ≥ 95%")
        if g == "B" and not any(x["p_clear"] >= 0.99 and wide(x, 1.2) for x in lst):
            errs.append("B 级保底不足：须至少一个志愿单独过线 ≥ 99% 且预测线比本人位次宽 20% 以上")
        if g in "CD" and sum(bool(wide(x, 1.3)) for x in lst) < 2:
            errs.append(f"{g} 级保底不足：须至少两个志愿的预测线比本人位次宽 30% 以上")
    if g in "BCD":
        s = rep.get("summary", {})
        texts = [s.get("headline", "")] + list(s.get("points", [])) + list(s.get("actions", [])) + list(rep.get("why", []))
        texts += list(rep.get("list_notes", {}).values()) + [str(r[1]) for r in rep.get("roadmap", [])]
        texts += [str(i.get(k, "")) for grp in rep.get("ask_me", []) for i in grp.get("items", []) for k in ("q", "why")]
        for t in texts:
            for mt in PROB_TEXT.finditer(str(t)):
                v = float(mt.group(2))
                if g in "CD" or "." in mt.group(2) or v % 5:
                    errs.append(f"{g} 级正文不应写“{mt.group(0)}”：" + ("不写百分比，改用冲稳保与区间" if g in "CD" else "取整到 5%"))
    return errs


def check_sections(rep, result=None):
    """付费报告每节的必备内容与篇幅下限（范围写在 references/report-guide.md）。不判断写得好不好，只查有没有、够不够、能不能溯源。"""
    errs = []
    s = rep.get('summary', {})
    if len(str(s.get('headline', ''))) < 20:
        errs.append('summary.headline 太短或缺失（≥ 20 字）')
    if not 3 <= len(s.get('points', [])) <= 5:
        errs.append('summary.points 须 3–5 条')
    if not 1 <= len(s.get('actions', [])) <= 3:
        errs.append('summary.actions 须 1–3 条')
    pr = rep.get('profile', {})
    if len(pr.get('facts', [])) < 8:
        errs.append('profile.facts 至少 8 行')
    pri = pr.get('priorities', [])
    if len(pri) < 4 or abs(sum(float(b) for _, b in pri) - 1) > 0.02:
        errs.append('profile.priorities 至少 4 项且权重之和为 1')
    if len(pr.get('constraints', [])) < 3 or not pr.get('tensions'):
        errs.append('profile.constraints 至少 3 条、tensions 至少 1 条')
    ds = rep.get('directions', [])
    if not 2 <= len(ds) <= 4:
        errs.append('directions 须 2–4 个')
    for d in ds:
        name = d.get('name', '?')
        if len(d.get('evidence', [])) < 2 or not d.get('counter') or not d.get('verify'):
            errs.append(f'方向「{name}」须有 ≥ 2 条支持、≥ 1 条反面和怎么验证')
        outlook = d.get('outlook', [])
        if len(outlook) < 2 or not all('若' in x for x in outlook):
            errs.append(f'方向「{name}」outlook 须 ≥ 2 条且每条是“若……则……”的有条件判断')
        paths = d.get('paths', [])
        if not all(any(w in str(r[0]) for r in paths) for w in PATH_WORDS) or any(len(r) != 4 or not all(str(c).strip() for c in r) for r in paths):
            errs.append(f'方向「{name}」paths 须覆盖考研、考公、就业，每行 [去向, 门槛, 代价, 依据] 四格齐全')
    road = [r[0] for r in rep.get('roadmap', [])]
    if tuple(road) != ROADMAP_ROWS:
        errs.append('roadmap 须依次为：' + '、'.join(ROADMAP_ROWS))
    if len(rep.get('news', [])) < 2:
        errs.append('news 至少 2 条近期报道或政策')
    if len(rep.get('why', [])) < 3:
        errs.append('why 至少 3 段')
    sens = rep.get('sensitivity', [])
    if len(sens) < 3 or not any('悲观' in str(r[0]) for r in sens):
        errs.append('sensitivity 至少 3 行且含前景悲观情景')
    if result is not None:
        notes = rep.get('list_notes', {})
        n = len(result.get('list', []))
        need = min(n, max(10, n // 4))  # 志愿表不足 10 条时，逐条都要说明
        if len(notes) < need:
            errs.append(f'list_notes 至少覆盖 {need} 个志愿（现有 {len(notes)}）')
        unknown = set(notes) - {x['name'] for x in result.get('list', [])}
        if unknown:
            errs.append('list_notes 含不在志愿表中的名称：' + '、'.join(sorted(unknown)[:3]))
    rs = rep.get('research', [])
    if len(rs) < 3:
        errs.append('research 至少 3 所院校')
    covered = 0
    for r in rs:
        items = r.get('items', [])
        got = {a for a in RESEARCH_ASPECTS if any(a in str(i[0]) and not str(i[2]).startswith('未取到') for i in items if len(i) == 3)}
        covered += len(got) >= 4
        if len([u for u in r.get('sources', []) if str(u).startswith('https://')]) < 2 or any(len(i) != 3 or not str(i[2]).strip() for i in items):
            errs.append(f'院校「{r.get("school", "?")}」须有 ≥ 2 条 https 来源，且每条发现标证据等级')
        if not got:
            errs.append(f'院校「{r.get("school", "?")}」没有任何有证据的调研项（取不到的写“未取到”并说明原因，也要有其余可查的内容）')
    if rs and covered < 3:
        errs.append(f'至少 3 所院校须覆盖{"、".join(RESEARCH_ASPECTS)}中 ≥ 4 项有证据的内容（证据等级以“未取到”开头的不计），现有 {covered} 所')
    if len(rep.get('questions', [])) < 5 or len(rep.get('todo', [])) < 5:
        errs.append('questions 与 todo 各至少 5 条')
    ask = rep.get('ask_me', [])
    if not 2 <= len(ask) <= 4 or not 6 <= sum(len(x.get('items', [])) for x in ask) <= 10:
        errs.append('ask_me 须 2–4 组、共 6–10 条')
    if len(rep.get('assumptions', [])) < 6 or not rep.get('backtest'):
        errs.append('assumptions 至少 6 行且有 backtest')
    titles = ' '.join(str(b.get('title', '')) for b in rep.get('methods', []))
    lacking = [w for w in METHOD_TOPICS if w not in titles]
    if lacking:
        errs.append('methods 须有以下小节（标题含这些词）：' + '、'.join(lacking))
    grade = next((b for b in rep.get('methods', []) if '证据等级' in str(b.get('title', ''))), None)
    if grade and (len(grade.get('rows', [])) < 4 or any(len(r) != 3 or str(r[2]) not in EVIDENCE_GRADES for r in grade['rows'])):
        errs.append('“结论与证据等级”至少 4 行，每行 [结论, 依据, 等级]，等级为：' + '、'.join(EVIDENCE_GRADES))
    src = rep.get('sources', [])
    if len(src) < 8 or any(len(r) != 3 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(r[2])) for r in src):
        errs.append('sources 至少 8 行，每行 [数据, 来源, YYYY-MM-DD]')
    bad = set(rep.get('omitted', {})) - {'hindsight'}
    if bad:
        errs.append('付费报告除“事后回看”外不得用 omitted 省略章节：' + '、'.join(sorted(bad)))
    errs += check_grade(rep, result)
    return errs


def percentage(value, decimals=0):
    if decimals == 0 and 0 < value < 0.01:
        decimals = 1
    return f'{100*value:.{decimals}f}%'


class Metrics(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth, self.cell, self.values = 0, None, []

    def handle_starttag(self, tag, attrs):
        if tag == 'div' and (self.depth or dict(attrs).get('class') == 'kpis'):
            self.depth += 1
        elif self.depth and tag in ('span', 'em'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.depth and tag in ('span', 'em') and self.cell is not None:
            self.values.append(''.join(self.cell).strip())
            self.cell = None
        elif self.depth and tag == 'div':
            self.depth -= 1


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table = []
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report')
    ap.add_argument('--opt', required=True)
    ap.add_argument('--html', help='report.py 生成的 HTML，核验其中的志愿表')
    args = ap.parse_args()
    rep = json.loads(Path(args.report).read_text(encoding='utf-8'))
    result = json.loads(Path(args.opt).read_text(encoding='utf-8'))
    html = Path(args.html).read_text(encoding='utf-8') if args.html else None
    errors = check_report(rep, result, html)
    if errors:
        ap.exit(1, '\n'.join(errors) + '\n')
    print(f'核验通过：元数据、{len(rep.get("numeric_claims", []))} 条数字声明' + ('、HTML 摘要与志愿表' if html else ''))
    print('自然语言中未标注的数字及敏感性情景须人工核对；本工具不核验 PDF 排版。')


if __name__ == '__main__':
    main()

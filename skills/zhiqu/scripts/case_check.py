#!/usr/bin/env python3
"""个案门槛检查：按阶段核对案例目录里的中间产物，上一步不全或对不上账就不能进下一步。

用法：python3 scripts/case_check.py <案例目录> --stage N
高考 N=0..8；读研、求职 N=0..10；均检查 0..N。--delivery 核正式交付批准。
阶段与文件见 references/case-workflow.md。脚本只能保证"步骤做全、账对得上、数字有出处"，
不能证明判断正确或来源真的这么写，那一步靠独立复核和操控者核查。
"""
import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from decision_evidence import require_formal, validate_evidence  # noqa: E402

SKILL = SCRIPTS.parent
PROFILE_HEAD = '【高考志愿 · 自我盘点】'
PROFILE_FIELDS = ['年份', '省份', '位次', '选科', '批次', '体检', '学费上限', '调剂态度', '优先级']
FIELD_STATUS = {'given', 'inferred', 'unknown'}
CASE_ID = re.compile(r'^\d{4}-GK-(\d{4}|[SR]\d{2})$')
SKIP_REASONS = {'rank_band', 'direction', 'hard_constraint', 'category', 'manual', 'duplicate', 'other'}
PROVINCE_ALIASES = {'北京市': '北京', '天津市': '天津', '上海市': '上海', '重庆市': '重庆',
                    '内蒙古自治区': '内蒙古', '广西壮族自治区': '广西', '西藏自治区': '西藏',
                    '宁夏回族自治区': '宁夏', '新疆维吾尔自治区': '新疆'}
PROVINCE_SUFFIX_NAMES = set('河北 山西 辽宁 吉林 黑龙江 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 海南 四川 贵州 云南 陕西 甘肃 青海 台湾'.split())
PITFALLS = ['没查到写成不存在', '群体数字当个人概率', '经验帖数字做决定', '按编号引用问卷', '同一事实写两处', '会过期的事实', '八字越界', '委派判断类任务', '取页摘要当原文']
REPORT_MIN = {'summary_points': 3, 'directions': 2, 'research_schools': 3, 'ask_me_items': 6, 'sources': 8, 'sensitivity': 3}


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def parse_day(text):
    try:
        return date.fromisoformat(str(text))
    except ValueError:
        return None


def province_name(value):
    """只归一省级名称写法；不把吉林市等地级市当作同名省。"""
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if value.endswith('省') and value[:-1] in PROVINCE_SUFFIX_NAMES:
        return value[:-1]
    return PROVINCE_ALIASES.get(value, value)


class Gate:
    def __init__(self, case_dir):
        self.dir = Path(case_dir)
        self.errors, self.notes = [], []
        self.case = {}

    def err(self, stage, msg):
        self.errors.append(f'[阶段 {stage}] {msg}')

    def need(self, stage, name):
        path = self.dir / name
        if not path.is_file():
            self.err(stage, f'缺文件 {name}')
            return None
        return path

    def json(self, stage, name):
        path = self.need(stage, name)
        if path is None:
            return None
        try:
            return load_json(path)
        except ValueError as exc:
            self.err(stage, f'{name} 不是有效 JSON：{exc}')

    def csv(self, stage, name):
        path = self.need(stage, name)
        if path is None:
            return None
        try:
            return load_csv(path)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            self.err(stage, f'{name} 读取失败：{exc}')

    # 阶段 0：案例登记
    def stage0(self):
        case = self.json(0, 'case.json')
        if case is None:
            return
        self.case = case
        for key in ('case_id', 'province', 'year', 'category', 'mode', 'prepared_on', 'data_commit', 'province_rules', 'rank', 'slots'):
            if case.get(key) in (None, ''):
                self.err(0, f'case.json 缺 {key}')
        if not CASE_ID.match(str(case.get('case_id', ''))):
            self.err(0, 'case_id 格式须为 年份-GK-四位序号（样板用 S 加两位序号，如 2027-GK-S01；回溯样板用 R，如 2026-GK-R01）')
        elif case['case_id'] != self.dir.name:
            self.err(0, f'case_id {case["case_id"]} 与目录名 {self.dir.name} 不一致')
        if case.get('mode') not in ('formal', 'simulation'):
            self.err(0, 'mode 须为 formal 或 simulation')
        if parse_day(case.get('prepared_on')) is None:
            self.err(0, 'prepared_on 须为 YYYY-MM-DD')
        if not re.fullmatch(r'[0-9a-f]{7,40}', str(case.get('data_commit', ''))):
            self.err(0, 'data_commit 须为所用数据所在的仓库提交号')
        rules = SKILL / str(case.get('province_rules', ''))
        if not rules.is_file():
            self.err(0, f'省份层规则文件不存在：{case.get("province_rules")}')
        else:
            try:
                declared = load_json(rules)
            except (OSError, ValueError, UnicodeError):
                self.err(0, '省份层规则文件无法读取或不是有效JSON；须取得本省规则，不能借用其他省份')
                return
            if not isinstance(declared, dict) or not province_name(declared.get('province')):
                self.err(0, '省份层规则缺少有效province；不能确认适用省份')
            elif province_name(declared['province']) != province_name(case.get('province')):
                self.err(0, f'省份层规则属于{declared["province"]}，与案例省份{case.get("province")}不一致；不能跨省借用')

    # 阶段 1：画像与缺项
    def stage1(self):
        from profile_store import active_profile, parse_profile
        try:
            raw = active_profile(self.dir)
            structured = parse_profile(raw)
            if structured is not None and structured['zhiqu'] != 'gaokao':
                self.err(1, '画像 JSON 须为 gaokao 类型')
            elif structured is None and not raw.lstrip().startswith(PROFILE_HEAD):
                self.err(1, f'旧文字画像须以 {PROFILE_HEAD} 开头')
        except (OSError, ValueError) as exc:
            self.err(1, '画像读取失败：'+str(exc))
        parse = self.json(1, 'profile_parse.json')
        if parse is None:
            return
        fields = {f.get('field'): f for f in parse.get('fields', [])}
        for name in PROFILE_FIELDS:
            f = fields.get(name)
            if not f:
                self.err(1, f'画像解析缺字段「{name}」（未知也要写 unknown）')
                continue
            if f.get('status') not in FIELD_STATUS:
                self.err(1, f'「{name}」status 须为 given / inferred / unknown')
            elif f['status'] == 'inferred' and not f.get('confirmed'):
                self.err(1, f'「{name}」是推断值，须向本人确认（confirmed=true）')
            elif f['status'] == 'unknown' and name not in parse.get('missing', []):
                self.err(1, f'「{name}」未知，须列入 missing')
            elif f['status'] != 'unknown' and f.get('value') in (None, ''):
                self.err(1, f'「{name}」缺 value')
        if str(fields.get('位次', {}).get('value', '')) and self.case.get('rank') and fields.get('位次', {}).get('status') != 'unknown':
            if not re.search(str(int(float(self.case['rank']))), str(fields['位次'].get('value', '')).replace(',', '')):
                self.err(1, '画像位次与 case.json 的 rank 不一致')
        origin = fields.get('省份', {})
        if origin.get('status') in ('given', 'inferred') and origin.get('value') not in (None, ''):
            if province_name(origin['value']) != province_name(self.case.get('province')):
                self.err(1, '画像生源省与 case.json 的 province 不一致；不能用登记覆盖本人省份')

    # 阶段 2：方向
    def stage2(self):
        data = self.json(2, 'directions.json')
        if data is None:
            return
        items = data.get('directions', [])
        if not 2 <= len(items) <= 4:
            self.err(2, f'方向应为 2–4 个，现有 {len(items)}')
        for d in items:
            for key in ('name', 'support', 'counter', 'verify'):
                if not d.get(key):
                    self.err(2, f'方向「{d.get("name", "?")}」缺 {key}（支持证据、反证、怎么验证都要写）')

    # 阶段 3：本省规则与数据（现取现核）
    def stage3(self):
        data = self.json(3, 'rules_check.json')
        rules_path = SKILL / str(self.case.get('province_rules', ''))
        if data is None or not rules_path.is_file():
            return
        rules = load_json(rules_path)
        checked = parse_day(data.get('checked_on'))
        prepared = parse_day(self.case.get('prepared_on'))
        if checked is None or prepared is None:
            self.err(3, 'checked_on / prepared_on 须为 YYYY-MM-DD')
            return
        if not 0 <= (prepared - checked).days <= 30:
            self.err(3, f'规则复核日期 {checked} 距出稿准备日 {prepared} 须在 30 天内')
        done = {i.get('key'): i for i in data.get('items', [])}
        for key, item in rules.get('items', {}).items():
            if item.get('volatile'):
                got = done.get(key)
                if not got:
                    self.err(3, f'会变的规则「{key}」本次未复核')
                elif got.get('still_valid') is not True and not got.get('note'):
                    self.err(3, f'规则「{key}」本次核对不一致，须写 note 说明并更新省份层')
        for name in ('history', 'yfyd', 'plan_current', 'subject_req_table'):
            ds = rules.get('datasets', {}).get(name)
            if ds is None:
                self.err(3, f'省份层缺数据项 datasets.{name}')
            elif ds.get('status') in ('缺', '未公布', '未入库') and name not in data.get('data_gaps', {}):
                self.err(3, f'数据项「{name}」状态为{ds["status"]}，本案须在 rules_check.json 的 data_gaps 写明怎么处理')
        hist = rules.get('datasets', {}).get('history', {})
        for y in hist.get('years', []):
            if not (SKILL / hist.get('path', '').format(year=y)).is_file():
                self.err(3, f'历年数据文件缺失：{hist.get("path", "").format(year=y)}')

    # 阶段 4：全量筛选对账 + 候选池
    def stage4(self):
        scr = self.json(4, 'screening.json')
        pool = self.csv(4, 'pool.csv')
        if scr is None or pool is None:
            return
        src = SKILL / str(scr.get('source_table', ''))
        if not src.is_file():
            self.err(4, f'screening.source_table 不存在：{scr.get("source_table")}')
            return
        raw = len(load_csv(src))
        steps = scr.get('steps', [])
        if not steps:
            self.err(4, 'screening.steps 为空')
            return
        if steps[0].get('before') != raw:
            self.err(4, f'筛选起点 {steps[0].get("before")} ≠ 源表实际行数 {raw}')
        for a, b in zip(steps, steps[1:]):
            if a.get('after') != b.get('before'):
                self.err(4, f'「{a.get("name")}」之后 {a.get("after")} ≠ 「{b.get("name")}」之前 {b.get("before")}，账对不上')
        for s in steps:
            if s.get('reason') not in SKIP_REASONS or not s.get('rule'):
                self.err(4, f'筛选步骤「{s.get("name")}」须有 rule 和合法 reason（{"/".join(sorted(SKIP_REASONS))}）')
            if not isinstance(s.get('before'), int) or not isinstance(s.get('after'), int) or s['after'] > s['before']:
                self.err(4, f'筛选步骤「{s.get("name")}」的 before/after 无效')
            elif s.get('excluded_file'):
                rows = self.csv(4, s['excluded_file']) or []
                if len(rows) != s['before'] - s['after']:
                    self.err(4, f'{s["excluded_file"]} 行数 {len(rows)} ≠ 该步剔除数 {s["before"] - s["after"]}')
                elif any(not r.get('reason') for r in rows):
                    self.err(4, f'{s["excluded_file"]} 每行都须写剔除原因')
        if steps[-1].get('after') != len(pool):
            self.err(4, f'筛选终点 {steps[-1].get("after")} ≠ pool.csv 行数 {len(pool)}')
        ids = [r.get('id') for r in pool]
        if len(set(ids)) != len(ids) or not all(ids):
            self.err(4, 'pool.csv 的 id 为空或重复')
        slots = int(self.case.get('slots', 0) or 0)
        if len(pool) < 2 * slots and not self.case.get('pool_shortfall_reason'):
            self.err(4, f'候选池 {len(pool)} 少于志愿位的 2 倍（{2 * slots}），须在 case.json 写 pool_shortfall_reason')
        year = self.case.get('year')
        for r in pool:
            try:
                item = json.loads(r.get('eligibility_evidence') or '{}')
                if self.case.get('mode') == 'formal':
                    require_formal(r, year)
                else:
                    validate_evidence(item)
            except (ValueError, TypeError) as exc:
                self.err(4, f'{r.get("id")} 资格证据不合格：{exc}')
                break
            if not r.get('source_grade'):
                self.err(4, f'{r.get("id")} 缺 source_grade（来源等级）')
                break
        self.notes.append(f'筛选账：全量 {raw} → 候选池 {len(pool)}（{len(steps)} 步）')

    # 阶段 5：本人确认的打分
    def stage5(self):
        attrs = self.csv(5, 'attributes.csv')
        cfg = self.json(5, 'preferences_config.json')
        self.json(5, 'preferences_review.json')
        reviewed = self.csv(5, 'reviewed.csv')
        pool = load_csv(self.dir / 'pool.csv') if (self.dir / 'pool.csv').is_file() else []
        if cfg:
            for name, sc in cfg.get('scenarios', {}).items():
                if sc.get('confirmed') is not True:
                    self.err(5, f'场景 {name} 未经本人确认（confirmed 须为 true）')
        if attrs is not None:
            bad = [r.get('id') for r in attrs if not (r.get('basis') or '').strip()]
            if bad:
                self.err(5, f'{len(bad)} 条打分没有 basis（打分依据），如 {bad[0]}')
        if reviewed is not None and pool:
            if {r['id'] for r in reviewed} != {r['id'] for r in pool}:
                self.err(5, 'reviewed.csv 与 pool.csv 的候选不一致')
            if any(not r.get('utility') for r in reviewed):
                self.err(5, 'reviewed.csv 有候选没有效用')

    # 阶段 6：计算与敏感性
    def stage6(self):
        res = self.json(6, 'result.json')
        run = self.json(6, 'run.json')
        if res is None or run is None:
            return
        p = res.get('params', {})
        if self.case.get('rank') and float(p.get('rank', -1)) != float(self.case['rank']):
            self.err(6, 'result.params.rank 与 case.json 的 rank 不一致')
        if self.case.get('slots') and int(p.get('slots', -1)) != int(self.case['slots']):
            self.err(6, 'result.params.slots 与 case.json 的 slots 不一致')
        if not run.get('commands'):
            self.err(6, 'run.json 须记录实际运行的命令')
        sens = sorted((self.dir / 'sensitivity').glob('*.json')) if (self.dir / 'sensitivity').is_dir() else []
        if len(sens) < 2:
            self.err(6, f'至少两组敏感性结果（sensitivity/*.json），现有 {len(sens)}')
        variants = set()
        for f in sens:
            q = load_json(f).get('params', {})
            name = Path(str(q.get('csv'))).name
            if name != Path(str(p.get('csv'))).name and not (self.dir / 'sensitivity' / name).is_file():
                self.err(6, f'{f.name} 用了不同的候选表 {name}；重新打分的情景须把候选表放在 sensitivity/ 下')
            diff = tuple(k for k in ('rho', 'u_fall', 'drift', 'sigma_scale') if q.get(k) != p.get(k)) + (('csv',) if name != Path(str(p.get('csv'))).name else ())
            if not diff:
                self.err(6, f'{f.name} 的 rho、u_fall、drift、sigma_scale 和候选表都与主结果相同，不算敏感性')
            variants.add((q.get('rho'), q.get('u_fall'), q.get('drift'), q.get('sigma_scale'), name))
        if sens and len(variants) < len(sens):
            self.err(6, '敏感性结果有重复参数')

    # 阶段 7：报告与填报单
    def stage7(self):
        from check_report import check_report, check_sections, report_mode_errors
        rep = self.json(7, 'report.json')
        res = self.json(7, 'result.json')
        sheet = self.csv(7, 'entry_sheet.csv')
        if rep is None or res is None:
            return
        for msg in report_mode_errors(self.case, rep):
            self.err(7, msg)
        if rep.get('meta', {}).get('case_id') != self.case.get('case_id'):
            self.err(7, 'report.meta.case_id 须等于案例号')
        if not rep.get('meta', {}).get('generated_on'):
            self.err(7, 'report.meta.generated_on（报告生成日期）缺失')
        for msg in check_sections(rep, res):
            self.err(7, msg)
        html = self.dir / 'report.html'
        for msg in check_report(rep, res, html.read_text(encoding='utf-8') if html.is_file() else None):
            self.err(7, msg)
        pdf = f"{self.case.get('case_id')}-report.pdf"
        if not html.is_file() and not (self.dir / pdf).is_file():
            self.err(7, f'缺 report.html 或 {pdf}')
        if sheet is not None:
            if len(sheet) != len(res.get('list', [])):
                self.err(7, f'填报单 {len(sheet)} 行 ≠ result 志愿数 {len(res.get("list", []))}')
            for r in sheet:
                if not r.get('院校代码') or not (r.get('专业代码') or r.get('专业组')):
                    self.err(7, f'填报单第 {r.get("序", "?")} 行有空代码')
                    break

    # 阶段 8：独立复核
    def stage8(self):
        rev = self.json(8, 'review.json')
        if rev is None:
            return
        if rev.get('independent') is not True or not rev.get('reviewer') or not parse_day(rev.get('date')):
            self.err(8, '复核记录须写明 independent=true、reviewer 和日期（新会话，不是分析者本人）')
        checks = {c.get('item'): c for c in rev.get('pitfalls', [])}
        for name in PITFALLS:
            c = checks.get(name)
            if not c or c.get('result') not in ('pass', 'fail') or not c.get('note'):
                self.err(8, f'复核缺项「{name}」（须给 pass/fail 和说明）')
            elif c['result'] == 'fail':
                self.err(8, f'复核未通过「{name}」：{c["note"]}')
        src = rev.get('sampled_sources', [])
        if len(src) < 5:
            self.err(8, f'须随机抽查至少 5 条来源，现有 {len(src)}')
        for s in src:
            if not (s.get('claim') and s.get('source') and s.get('matches') is True):
                self.err(8, f'抽查来源未通过或不完整：{s.get("claim", "?")}')
                break
        from planning_workflow import review_errors
        self.errors.extend(review_errors(self.dir, delivery=False))
        from operator_check import validate_operator
        self.errors.extend(validate_operator(self.dir, require_completed=True))


def run(case_dir, stage, delivery=False):
    case_path = Path(case_dir) / 'case.json'
    if case_path.is_file() and load_json(case_path).get('kind') in ('grad', 'career'):
        if delivery and stage!=10:raise ValueError('--delivery须检查读研/求职阶段10')
        from planning_workflow import PlanningCase
        gate = PlanningCase(case_dir)
        gate.notes = []
        gate.check(stage, delivery)
        if stage >= 1:
            from profile_store import alignment_errors
            gate.errors.extend(alignment_errors(case_dir))
        return gate
    if stage > 8:
        raise ValueError('高考阶段保持0..8')
    if delivery and stage != 8:
        raise ValueError('--delivery 须检查高考阶段8；阶段7生成不等于独立批准交付')
    gate = Gate(case_dir)
    for n in range(stage + 1):
        getattr(gate, f'stage{n}')()
        if n == 0 and gate.errors:
            break
    if stage >= 1:
        from profile_store import alignment_errors
        gate.errors.extend(alignment_errors(case_dir))
    if delivery:
        report_path = Path(case_dir) / 'report.json'
        if report_path.is_file() and load_json(report_path).get('research_status') == 'pending':
            gate.err(8, '院校调研仍为待核实；模拟报告可供讨论，不能批准正式交付')
        from planning_workflow import review_errors
        gate.errors.extend(review_errors(case_dir, delivery=True))
        result_path = Path(case_dir) / 'result.json'
        uses_database = result_path.is_file() and any(
            item.get('data_provenance') for item in load_json(result_path).get('list', []))
        if gate.case.get('claim_check_required') or uses_database:
            from claim_check import errors as claim_errors
            gate.errors.extend(claim_errors(case_dir))
    return gate


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('case_dir')
    ap.add_argument('--stage', type=int, required=True, choices=range(0, 11), help='检查 0..N 阶段')
    ap.add_argument('--delivery', action='store_true', help='检查操控者和新会话批准交付状态')
    ap.add_argument('--parse-profile', action='store_true', help='检查前按最新画像数据生成字段；文字画像沿用人工解析')
    ap.add_argument('--replace-profile', action='store_true', help='与 --parse-profile 同用，确认重做已有画像解析')
    args = ap.parse_args()
    try:
        if args.replace_profile and not args.parse_profile:
            raise ValueError('--replace-profile 须与 --parse-profile 同用')
        if args.parse_profile:
            from profile_store import prepare
            print(prepare(args.case_dir, args.replace_profile)['status'])
        gate = run(args.case_dir, args.stage, args.delivery)
    except (ValueError,KeyError,TypeError,OSError) as exc:ap.exit(1,str(exc)+'\n未通过阶段检查。\n')
    for note in gate.notes:
        print(note)
    if gate.errors:
        print('\n'.join(gate.errors))
        ap.exit(1, f'未通过：{len(gate.errors)} 个问题\n')
    print(f'阶段 0–{args.stage} 通过。通过只说明步骤做全、账对得上；判断与来源仍须复核。')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Reproducible local fault injection; never edits the examples or their validators.

Run from any directory: python3 PATH/error_injection.py [--output DIR] [--variants 10].
The denominator is injected examples, not independent error families or real-world errors.
Generation failures block downstream publication; old PDFs are never treated as new output.
"""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import random
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parents[2]
sys.path.insert(0, str(SCRIPTS))
from planning_workflow import PlanningCase, walk, dump, pointer
from planning_report import generate, assemble
from check_layout import check_pdf
from verify_report import verify, report_pdf_name

CATEGORIES = {
    'unsupported_number': '无出处的数字', 'wrong_number': '数字与摘录不符',
    'expired_evidence': '过期证据日期', 'review_before_retrieval': '复核期限早于取文日',
    'wrong_unit': '单位错', 'calculation_tamper': '计算结果篡改',
    'missing_evidence_id': '引用不存在的证据 ID', 'third_party_as_official': '第三方数据冒充官方',
    'personal_probability': '群体比例写成个人概率', 'pdf_body_tamper': '改 PDF 正文不改附件',
    'pdf_attachment_tamper': '改附件不改正文', 'short_cover': '封面结论过短',
    'development_language': '正文插入开发用语', 'unsupported_qualitative': '插入没有原文支持的定性句',
}
BASES = {
    'grad': ROOT/'skills/zhiqu-grad/examples/2027-YJ-S01',
    'career': ROOT/'skills/zhiqu-career/examples/2027-QZ-S01',
    'gaokao': ROOT/'skills/zhiqu/examples/2026-GK-R12',
}


def read(p):
    return json.loads(p.read_text())


def run_check(fn):
    try:
        result = fn()
        return list(result or [])
    except (Exception, SystemExit) as exc:
        return [type(exc).__name__+': '+str(exc)]


def workflow(root):
    """Each independent stage executes, even when an earlier stage rejects the case."""
    case = PlanningCase(root)
    outcomes = {}
    for stage in range(11):
        case.errors = []
        extra = run_check(lambda: getattr(case, 'stage'+str(stage))())
        outcomes[str(stage)] = list(case.errors)+extra
    return outcomes


def change_leaf(obj, path, value):
    parts = path[1:].split('/')
    for raw in parts[:-1]:
        key = raw.replace('~1', '/').replace('~0', '~')
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    key = parts[-1].replace('~1', '/').replace('~0', '~')
    obj[int(key) if isinstance(obj, list) else key] = value


def mutate(root, category, index, rng):
    evidence = read(root/'evidence.json')
    official = [e for e in evidence['items'] if e.get('grade') == '官方'
                and isinstance(e.get('value'), (int, float)) and not isinstance(e.get('value'), bool)]
    # Only evidence actually used in a rendered node; an unused mutation is not a valid test.
    case = PlanningCase(root)
    cited = ''.join(str(case.get_node(x['ref'])) for nodes in case.nodes().values() for x in nodes)
    used = [e for e in official if e['id'] in cited]
    e = rng.choice(used or official)
    eid = e['id']
    field = 'evidence.json#'+eid
    before = dict(e)
    if category == 'wrong_number':
        e['value'] += index+11
    elif category in ('expired_evidence', 'review_before_retrieval'):
        asof = date.fromisoformat(case.case['context']['as_of'])
        if category == 'expired_evidence':
            e['retrieved_on'] = (asof-timedelta(days=50+index)).isoformat()
            e['review_due'] = (asof-timedelta(days=1+index)).isoformat()
        else:
            e['review_due'] = (date.fromisoformat(e['retrieved_on'])-timedelta(days=index+1)).isoformat()
    elif category == 'wrong_unit':
        markdown_before, _ = assemble(case)
        choices = []
        seen = set()
        submechanism = 'scale_yuan_to_wanyuan' if index < 4 else 'monthly_annual' if index < 7 else 'cny_to_usd'
        pattern = r'(\{\{[^{}]+\}\}\s*)元([／/])(月|年)' if submechanism == 'monthly_annual' else r'(\{\{[^{}]+\}\}\s*)元'
        for entries in case.nodes().values():
            for entry in entries:
                ref = entry['ref']
                node = case.get_node(ref)
                for leaf, text in walk(node.get('content', {})):
                    if not isinstance(text, str) or (ref, leaf) in seen:
                        continue
                    seen.add((ref, leaf))
                    match = re.search(pattern, text)
                    if match and case.expand(text) in markdown_before:
                        try:
                            float(case.expand(match[1]).replace(',', '').strip())
                        except ValueError:
                            continue
                        choices.append((ref, leaf, text))
        choice_index = (index-4)//2 if submechanism == 'monthly_annual' else index//2
        ref, leaf, old = choices[choice_index % len(choices)]
        match = re.search(pattern, old)
        if submechanism == 'monthly_annual':
            replacement = match[1]+'元'+match[2]+('年' if match[3] == '月' else '月')
        else:
            replacement = match[1]+('万元' if submechanism == 'scale_yuan_to_wanyuan' else '美元')
        new = old[:match.start()]+replacement+old[match.end():]
        file, node_path = ref.split('#', 1)
        obj = read(root/file)
        path = node_path+'/content'+leaf
        change_leaf(obj, path, new)
        dump(root/file, obj)
        changed = PlanningCase(root)
        markdown_after, _ = assemble(changed)
        rendered_before, rendered_after = case.expand(old), changed.expand(new)
        assert markdown_before != markdown_after and rendered_after in markdown_after
        assert rendered_before != rendered_after
        assert re.sub(r'[\s*]', '', changed.expand(replacement)) not in re.sub(r'[\s*]', '', markdown_before)
        return {'field': file+'#'+path, 'before': old, 'after': new,
                'mode': 'presented_unit_without_value_conversion', 'submechanism': submechanism,
                'rendered_wrong_token': changed.expand(replacement),
                'rendered_before': rendered_before, 'rendered_after': rendered_after,
                'assembled_target_present': True}
    elif category == 'third_party_as_official':
        e['source'] = {'organization': '第三方考研经验整理平台',
                       'url': 'https://example.org/third-party/record-'+str(index),
                       'locator': '第三方自行汇编，未经官方核对'}
        # Keep the false official label: tests authentication, not the allowed-grade enum.
        e['grade'] = '官方'
        e['retrieval_method'] = 'provided'
        e['excerpt'] = before.get('excerpt', '')
    else:
        if category == 'calculation_tamper':
            obj = read(root/'calculations.json')
            leaves = [(p, v) for p, v in walk(obj) if type(v) in (int, float)]
            rng.choice(leaves)  # Preserve the seed stream of unrelated categories.
            whitelist = {
                'grad': ['/annual_cost', '/annual_margin', '/total_cost_over_program',
                         '/annual_cost_if_living_plus_200', '/annual_margin_if_living_plus_200'],
                'career': ['/monthly_expenses', '/monthly_remaining',
                           '/monthly_remaining_if_housing_plus_600',
                           '/hypothetical_offers/0/annual_take_home_cash',
                           '/hypothetical_offers/1/monthly_remaining_cash'],
            }
            path = whitelist[case.kind][(index//2) % 5]
            value = pointer(obj, path)
            _, trace = assemble(case)
            assert any('c:'+path+'}' in x['ref'] or 'c:'+path+'|' in x['ref'] for x in trace)
            assert type(value) in (int, float)
            change_leaf(obj, path, value+index+11)
            dump(root/'calculations.json', obj)
            return {'field': 'calculations.json#'+path, 'before': value, 'after': value+index+11,
                    'mode': 'derived_calculation_output', 'original_output_rendered': True}
        if category == 'short_cover':
            obj = read(root/'case.json')
            old = obj['report_meta']['conclusion']
            obj['report_meta']['conclusion'] = ['继续准备。', '先调查。', '需要核对。', '认真选择。', '暂缓决定。'][index % 5] * (1+index//5)
            dump(root/'case.json', obj)
            return {'field': 'case.json#/report_meta/conclusion', 'before': old,
                    'after': obj['report_meta']['conclusion']}
        obj = read(root/'narrative.json')
        node = obj['sections']['01']['analysis'][index % len(obj['sections']['01']['analysis'])]
        old = node['content']['text']
        if category == 'unsupported_number':
            addition = f' 该方向今年录取人数为 {41+index*7} 人。'
        elif category == 'development_language':
            addition = ' '+['返工后继续。','此处用于复现。','这是演示结果。','运行脚本即可。','按快照处理。','请查看data.json。','调用worker.py。','检查字段路径。','这里需要返工。','这份演示可以复现。'][index%10]
        elif category == 'unsupported_qualitative':
            addition = ' '+['本专业毕业生一律免试进入国企。','该校毕业生自动获得事业编制。','该方向是用人单位公认的最佳专业。','所有岗位均承诺终身稳定。','这所学校的课程完全不涉及数学。','本专业学生无需审核即可跨专业调剂。','该方向毕业即获得正式编制。','录用后单位保证永不裁员。','这个专业的学生全部享有免学费资格。','任何考生都能自动取得录取资格。'][index%10]
        elif category == 'missing_evidence_id':
            addition = ' 核验数值为 {{e:MISSING_'+str(index)+'#/value}}。'
            node['evidence_refs'].append('MISSING_'+str(index))
        elif category == 'personal_probability':
            # Half use digits, half Chinese natural phrasing: expose regex-only safeguards.
            addition = (f' 过去群体录取率为 {40+index}%，所以你的个人录取概率为 {40+index}%。'
                        if index < 5 else
                        [' 历史群体有四成录取，因此你也有四成机会被录取。',
                         ' 往届人群一半录取，所以你被录取的可能性就是一半。',
                         ' 这个群体八成通过，所以你的录取机会就是八成。',
                         ' 群体中三成入围，因此你个人考上的概率就是三成。',
                         ' 这个项目过半录取，所以你考上的机会超过一半。'][index % 5])
        else:
            raise ValueError(category)
        node['content']['text'] += addition
        dump(root/'narrative.json', obj)
        return {'field': 'narrative.json#/sections/01/analysis/'+str(index % len(obj['sections']['01']['analysis'])),
                'before': old, 'after': node['content']['text']}
    dump(root/'evidence.json', evidence)
    return {'field': field, 'before': before, 'after': e}


def tamper_pdf(pdf, category, index):
    import pymupdf
    out = pdf.with_name('mutated.pdf')
    with pymupdf.open(pdf) as doc:
        original_text = [page.get_text() for page in doc]
        original_attachments = {name: doc.embfile_get(name) for name in doc.embfile_names()}
        if category == 'pdf_body_tamper':
            page = doc[1+(index % (len(doc)-1))]
            # A real visible body text alteration, retaining all embedded attachments.
            page.insert_text((30, 40), 'INJECTED WRONG VALUE '+str(701+index), fontsize=9)
            mutation = {'field': 'report.pdf/page/'+str(page.number+1), 'after': 'INJECTED WRONG VALUE '+str(701+index)}
        else:
            obj = json.loads(doc.embfile_get('case.json'))
            field = 'target_year' if obj.get('kind') in ('grad', 'career') else 'year'
            assert field in obj and obj[field] is not None
            old = obj[field]
            assert str(old) in ''.join(page.get_text() for page in doc)
            obj[field] = 2040+index
            # Delete/add uses the public bytes API; embfile_upd in some PyMuPDF builds
            # exposes an internal buffer object despite its Python signature.
            doc.embfile_del('case.json')
            doc.embfile_add('case.json', (json.dumps(obj, ensure_ascii=False)+'\n').encode())
            mutation = {'field': 'report.pdf/attachment/case.json#/'+field, 'before': old, 'after': 2040+index,
                        'mode': 'existing_rendered_case_field', 'original_field_exists': True}
        doc.save(out)
    with pymupdf.open(out) as changed:
        if category == 'pdf_body_tamper':
            assert all(changed.embfile_get(k) == v for k, v in original_attachments.items())
            assert [p.get_text() for p in changed] != original_text
            mutation['attachments_unchanged'] = True
        else:
            assert [p.get_text() for p in changed] == original_text
            assert all(changed.embfile_get(k) == v for k, v in original_attachments.items() if k != 'case.json')
            assert json.loads(changed.embfile_get('case.json'))[field] == 2040+index
            mutation['page_texts_unchanged'] = True
    out.replace(pdf)
    return mutation


def baseline(out):
    values = {}
    for kind, source in BASES.items():
        values[kind] = {'layout_errors': check_pdf(source/report_pdf_name(read(source/'case.json')['case_id'])),
                        'verify_errors': verify(source/report_pdf_name(read(source/'case.json')['case_id']))['errors']}
        if kind != 'gaokao':
            values[kind]['workflow'] = workflow(source)
            values[kind]['semantic_ok'] = not PlanningCase(source).check(8)
            from claim_check import errors as claim_errors
            values[kind]['claim_review_errors'] = claim_errors(source)
    values['_input_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for source in BASES.values() for p in source.rglob('*') if p.is_file()}
    dump(out/'baseline.json', values)
    if any(x['layout_errors'] or x['verify_errors'] or x.get('semantic_ok') is False or x.get('claim_review_errors') for key, x in values.items() if not key.startswith('_')):
        raise ValueError('Unhealthy baseline; see baseline.json')
    return values


def experiment(output, variants=10, seed=20261020, resume=False):
    if variants < 10:
        raise ValueError('At least ten variants are required for every category')
    output.mkdir(parents=True, exist_ok=True)
    previous_baseline = read(output/'baseline.json') if resume and (output/'baseline.json').exists() else {}
    fresh_baseline = baseline(output)
    if resume and previous_baseline.get('_input_sha256') != fresh_baseline['_input_sha256']:
        raise ValueError('Resume refused: source files changed or missing fingerprints')
    rng = random.Random(seed)
    rows = []
    if resume:
        with (output/'results.csv').open() as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            for key in ('variant', 'seed'):
                row[key] = int(row[key])
            for key in ('semantic_intercepted', 'snapshot_intercepted', 'generation_intercepted',
                        'content_or_integrity_intercepted', 'end_to_end_original_snapshot_intercepted',
                        'escaped_publication_checks'):
                row[key] = row[key] == 'True'
    completed = len(rows)
    trial_number = 0
    for category in CATEGORIES:
        for index in range(variants):
            kind = (['grad', 'career', 'gaokao'][index % 3] if category.startswith('pdf_')
                    else ['grad', 'career'][index % 2])
            with tempfile.TemporaryDirectory(prefix='trial-', dir=output) as tmp:
                case_dir = Path(tmp)/BASES[kind].name
                shutil.copytree(BASES[kind], case_dir)
                pdf = case_dir/report_pdf_name(read(case_dir/'case.json')['case_id'])
                before_pdf = hashlib.sha256(pdf.read_bytes()).hexdigest()
                pdf_only = category.startswith('pdf_')
                mutation = tamper_pdf(pdf, category, index) if pdf_only else mutate(case_dir, category, index, rng)
                trial_number += 1
                if trial_number <= completed:
                    existing = rows[trial_number-1]
                    if (existing['category'], existing['variant'], existing['base'], existing['seed']) != (category, index+1, kind, seed) or json.loads(existing['mutation']) != mutation:
                        raise ValueError('Resume refused: mutation plan differs '+category+' '+str(index+1))
                    continue
                stages = workflow(case_dir) if kind != 'gaokao' else {}
                semantic = [str(n)+': '+e for n in range(9) for e in stages.get(str(n), [])]
                # Newly introduced unreviewed claims are a coverage gate. Generic
                # stale artifact hashes remain separately counted as before (v3).
                if category=='unsupported_qualitative':
                    semantic += ['9: '+e for e in stages.get('9',[]) if '句子/组件/引用摘录清单不完整' in e]
                snapshot = [str(n)+': '+e for n in (9, 10) for e in stages.get(str(n), [])]
                generation_errors = []
                unit_pdf_confirmed = False
                downstream = 'mutated_pdf' if pdf_only else 'not_run_generation_blocked'
                if not pdf_only:
                    # Full publication path, including the renderer's layout gate and PDF verification.
                    # Generation has its own independent stage 0–8 checks; do not skip it after rejection.
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        generation_errors = run_check(lambda: (generate(case_dir, profile_version=read(case_dir/'case.json')['report_profile']['file']), None)[1])
                    if not generation_errors:
                        downstream = 'newly_generated_pdf'
                if downstream != 'not_run_generation_blocked':
                    layout = run_check(lambda: check_pdf(pdf))
                    verified = verify(pdf)
                    verification = verified['errors']
                    if category == 'wrong_unit':
                        import pymupdf
                        with pymupdf.open(pdf) as doc:
                            text = re.sub(r'\s+', '', ''.join(p.get_text() for p in doc))
                        expected = re.sub(r'[\s*]', '', mutation['rendered_wrong_token'])
                        assert expected in text, 'Wrong-unit mutation was not visible in generated PDF'
                        unit_pdf_confirmed = True
                else:
                    layout = verification = []
                    # A blocked generation must retain the old deliverable atomically.
                    if hashlib.sha256(pdf.read_bytes()).hexdigest() != before_pdf:
                        raise AssertionError('Failed generation modified an existing PDF')
                robust = bool(semantic or generation_errors or layout or verification)
                operational = bool(robust or snapshot)
                first = ('planning_workflow' if semantic else 'planning_report' if generation_errors else
                         'check_layout' if layout else 'verify_report' if verification else '')
                row = {'category': category, 'category_zh': CATEGORIES[category], 'variant': index+1,
                       'base': kind, 'seed': seed, 'mutation': json.dumps(mutation, ensure_ascii=False),
                       'mutation_mode': mutation.get('mode', 'structured_evidence_or_text'),
                       'unit_wrong_token_visible_in_pdf': unit_pdf_confirmed,
                       'generation_status': 'not_applicable_post_generation_tamper' if pdf_only else 'executed',
                       'workflow_status': 'not_applicable_gaokao' if kind == 'gaokao' else 'executed_0_to_10',
                       'workflow_stages': json.dumps(stages, ensure_ascii=False),
                       'semantic_intercepted': bool(semantic), 'snapshot_intercepted': bool(snapshot),
                       'generation_intercepted': bool(generation_errors),
                       'generation_errors': json.dumps(generation_errors, ensure_ascii=False),
                       'downstream_status': downstream, 'layout_errors': json.dumps(layout, ensure_ascii=False),
                       'verification_errors': json.dumps(verification, ensure_ascii=False),
                       'first_content_or_integrity_intercept': first,
                       'content_or_integrity_intercepted': robust, 'end_to_end_original_snapshot_intercepted': operational,
                       'escaped_publication_checks': not robust}
                rows.append(row)
                with (output/'results.csv').open('w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=list(row)); writer.writeheader(); writer.writerows(rows)
                print(category, index+1, kind, 'blocked' if robust else 'ESCAPED', flush=True)
    return summarize(output, rows, variants, seed)


def summarize(output, rows, variants, seed):
    summaries = []
    for category, title in CATEGORIES.items():
        selected = [r for r in rows if r['category'] == category]
        summaries.append({'category': category, 'name': title, 'n': len(selected),
                          'intercepted': sum(r['content_or_integrity_intercepted'] for r in selected),
                          'snapshot_included': sum(r['end_to_end_original_snapshot_intercepted'] for r in selected),
                          'missed': sum(r['escaped_publication_checks'] for r in selected)})
    unit_mechanisms = []
    for mechanism in ('scale_yuan_to_wanyuan', 'monthly_annual', 'cny_to_usd'):
        selected = [r for r in rows if r['category'] == 'wrong_unit' and json.loads(r['mutation']).get('submechanism') == mechanism]
        if selected:
            unit_mechanisms.append({'mechanism': mechanism, 'n': len(selected), 'intercepted': sum(r['content_or_integrity_intercepted'] for r in selected)})
    dump(output/'summary.json', {'seed': seed, 'trials': len(rows), 'families': summaries,
                               'base_commit': '26ffa7a', 'protocol_version': 3, 'independent_random_sample': False,
                               'unit_submechanisms': unit_mechanisms,
                               'content_or_integrity_intercepted': sum(r['content_or_integrity_intercepted'] for r in rows),
                               'snapshot_included_intercepted': sum(r['end_to_end_original_snapshot_intercepted'] for r in rows)})
    lines = ['# 错误注入实验', '', '固定种子 '+str(seed)+'；每类 '+str(variants)+' 个变体，共 '+str(len(rows))+' 次。内容/完整性门禁拦截 '+str(sum(r['content_or_integrity_intercepted'] for r in rows))+'/'+str(len(rows))+'（'+format(sum(r['content_or_integrity_intercepted'] for r in rows)/len(rows), '.1%')+'）；保留旧审批快照时拦截 '+str(sum(r['end_to_end_original_snapshot_intercepted'] for r in rows))+'/'+str(len(rows))+'。', '',
             '读研、求职示例均先通过阶段 0–8、原 PDF 版面与核对。高考 R12 通过原 PDF 版面与核对；高考没有 planning_workflow 结构，因此仅参与 PDF 正文和附件篡改两类。', '',
             '每次复制完整底本，仅注入一类错误。结构化变体执行每个独立阶段 0–10、planning_report 全量生成门禁（含 PDF 渲染）、新 PDF 的 check_layout 和 verify_report。生成被阻止时，下游记为未运行，不将底本 PDF 当成变体已通过的证据。PDF 篡改发生在健康成品之后；为保留篡改，planning_report 记为不适用、不重新生成；阶段检查按结构适用性执行，随后实际运行版面和附件核对。高考没有该阶段工作流，对应字段也记为不适用。', '',
             '两种拦截率分别列出：内容/完整性拦截率排除单纯“源文件已变更，旧快照失效”；保留原始 review/trace 快照的端到端率包含此拦截。后者证明发布版本绑定，不能证明检查理解了错误语义。无基于摘要重写快照来伪装审批，也不修改任何既有检查。', '',
             '| 错误类别 | 变体数 | 内容/完整性拦截 | 原快照端到端拦截 | 内容门禁漏网 |',
             '| --- | ---: | ---: | ---: | ---: |']
    for s in summaries:
        lines.append(f"| {s['name']} | {s['n']} | {s['intercepted']}/{s['n']} ({s['intercepted']/s['n']:.0%}) | {s['snapshot_included']}/{s['n']} ({s['snapshot_included']/s['n']:.0%}) | {s['missed']} |")
    lines += ['', '单位类按子机制：'+ '；'.join(x['mechanism']+' '+str(x['intercepted'])+'/'+str(x['n']) for x in unit_mechanisms)+'。元→万元的拦截来自新增“万”被当作未绑定数量，不能据此称为通用量纲检查。', '', '## 变体有效性', '',
              '协议 v3 以最终 120 次有效变体为准。单位类修改实际呈现节点，包含 4 次元→万元、3 次元/月↔元/年、3 次人民币元→美元，数值均不换算；每条先断言变化进入 assemble，若生成成功再断言错误值和单位确实出现在 PDF 正文。计算类只改实际展示的派生输出白名单，不含输入镜像、常量和直方图频数。附件类只改既有且正文依赖的 case.target_year（读研/求职）或 case.year（高考），断言原字段存在且非空。PDF 单边变体还逐项断言另一侧未变：正文改动保留所有附件原字节；附件改动保留所有页文字与其他附件。', '',
              '## 漏网与原因', '',
              '完整变体、字段前后值、每个阶段错误和首个拦截点见 results.csv。以下仅列实际漏网：', '']
    for category in CATEGORIES:
        missed = [r for r in rows if r['category'] == category and r['escaped_publication_checks']]
        if missed:
            r = missed[0]
            detail = json.loads(r['mutation'])
            after = detail['after']
            if isinstance(after, dict):
                after = {key: after.get(key) for key in ('value', 'unit', 'review_due', 'grade')} | {'source': after.get('source', {}).get('organization')}
            elif isinstance(after, str) and isinstance(detail.get('before'), str):
                after = after.removeprefix(detail['before']).strip()
            lines.append('- '+CATEGORIES[category]+'：'+str(len(missed))+' 个；示例 '+r['base']+' / '+str(r['variant'])+'，字段 '+detail['field']+'，注入后 '+json.dumps(after, ensure_ascii=False))
    lines += ['', '## 局限及建议', '',
              '这是一批有意构造的有限变体，不能外推为真实使用错误率，也不是十个独立来源场景的随机抽样。相同规则的文字改写存在相关性，不给伪精确的总体置信区间。三份底本均为模拟用户，不涉及真实名单。', '',
              '本实验不在线访问来源，因此官方域名、取文真实性、摘录与主张是否语义相符均不能被离线完整性证明。单位字段与数值/显示单位的关联、review_due 是否早于报告 as_of、第三方内容冒充官方和中文自然语言的个人概率表述，须按实际漏网结果补充检查。建议增加官方来源身份白名单与原文取文凭据、结构化量纲、逐条有效期核对、主张及概率边界的人工复核。这里只记录建议，未改既有门禁。', '',
              'PDF 完整性实验只测试正文/附件单边改动；没有测试同时重做正文、所有附件和哈希的协同伪造。原工具未作数字签名，不能据此证明作者身份或官方事实。', '',
              '临时案例、变体 PDF 与渲染缓存随每个试验删除；留存结果 CSV、基线和统计 JSON。脚本不启动后台任务，渲染器负责终止其 Chrome 子进程。']
    (output/'README.md').write_text('\n'.join(lines)+'\n')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.cache/error-injection')
    parser.add_argument('--variants', type=int, default=10)
    parser.add_argument('--seed', type=int, default=20261020)
    parser.add_argument('--resume', action='store_true', help='Resume only if source hashes and every prior mutation agree')
    args = parser.parse_args()
    experiment(args.output.resolve(), args.variants, args.seed, args.resume)


if __name__ == '__main__':
    main()

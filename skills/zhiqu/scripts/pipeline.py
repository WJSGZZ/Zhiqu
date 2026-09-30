#!/usr/bin/env python3
"""用已核实的数据与人工确认的偏好一键运行 pool → predict → optimize → report。"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from check_report import check_report

SCRIPTS = Path(__file__).resolve().parent
SHARED = {'rank', 'rank-sd', 'sigma-floor', 'sigma-single', 'sigma-scale', 'sigma-rule', 'drift', 'target-year', 'cohort', 'cohort-now'}
ALLOWED_PREFERENCES = {'id', 'utility', 'adj', 'p_adjust', 'utility_adjusted', 'obey', 'majors', 'majors_complete', 'rule', 'gap', 'limits'}


def options(values):
    args = []
    for key, value in values.items():
        if value is True:
            args.append('--' + key)
        elif value is not False and value is not None:
            for item in value if isinstance(value, list) else [value]:
                args.extend(['--' + key, str(item)])
    return args


def run(script, args, cwd):
    subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, check=True)


def merge_preferences(pool, preferences, dest):
    with open(pool, encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames, list(reader)
    with open(preferences, encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        extra, reviewed = reader.fieldnames, list(reader)
    if not fields or not rows or not extra or 'id' not in extra:
        raise ValueError('候选池不可为空；偏好 CSV 必须含 id')
    if set(extra) - ALLOWED_PREFERENCES:
        raise ValueError('偏好 CSV 只可补效用、约束和组内分配参数，不能覆盖历史事实: ' + ', '.join(sorted(set(extra) - ALLOWED_PREFERENCES)))
    by_id = {}
    for row in reviewed:
        if not row['id'] or row['id'] in by_id:
            raise ValueError('偏好 CSV 的 id 为空或重复')
        if not row.get('utility') and not row.get('majors'):
            raise ValueError(f'{row["id"]} 缺少人工确认的 utility 或 majors')
        if row.get('majors') and row.get('majors_complete') not in ('0', '1'):
            raise ValueError(f'{row["id"]} 使用 majors 时必须显式填写 majors_complete=0 或 1')
        by_id[row['id']] = row
    if set(by_id) - {r['id'] for r in rows}:
        raise ValueError('偏好表含不在候选池中的 id，可能沿用了旧候选池')
    selected = [dict(r, **by_id[r['id']]) for r in rows if r['id'] in by_id]
    if not selected:
        raise ValueError('没有人工确认的候选')
    with open(dest, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields + [x for x in extra if x not in fields])
        writer.writeheader()
        writer.writerows(selected)
    print(f'仅保留人工确认的 {len(selected)}/{len(rows)} 个候选；未确认的不会自动打分', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('config', help='JSON 配置，路径均相对该配置所在目录')
    ap.add_argument('--out-dir', required=True, help='必须为空的新输出目录，避免覆盖原报告')
    args = ap.parse_args()
    config_path = Path(args.config).resolve()
    base = config_path.parent
    config = json.loads(config_path.read_text(encoding='utf-8'))
    out = Path(args.out_dir).resolve()
    try:
        shared = config['shared']
        if set(shared) - SHARED or 'rank' not in shared:
            raise ValueError('shared 只允许预测与优化共用的模型参数，且必须含 rank')
        for stage, reserved in [('pool', {'out'}), ('predict', SHARED | {'out'}), ('optimize', SHARED | {'json'})]:
            if set(config.get(stage, {})) & reserved:
                raise ValueError(f'{stage} 不可覆盖统一参数或输出路径')
        if out.exists() and any(out.iterdir()):
            raise ValueError('输出目录已有内容，请使用新目录')
        out.mkdir(parents=True, exist_ok=True)
        pool, scored, predicted, result, html = [out / n for n in ('pool.csv', 'reviewed.csv', 'predicted.csv', 'result.json', 'report.html')]
        run('pool.py', options(config['pool']) + ['--out', str(pool)], base)
        merge_preferences(pool, base / config['preferences'], scored)
        run('rank.py', ['predict', str(scored), *options(shared), *options(config.get('predict', {})), '--out', str(predicted)], base)
        run('optimize.py', [str(predicted), *options(shared), *options(config['optimize']), '--json', str(result)], base)
        report = base / config['report']
        rep = json.loads(report.read_text(encoding='utf-8'))
        opt = json.loads(result.read_text(encoding='utf-8'))
        errors = check_report(rep, opt)
        if errors:
            raise ValueError('\n'.join(errors))
        run('report.py', [str(report), '--opt', str(result), '--out', str(html)], base)
        errors = check_report(rep, opt, html.read_text(encoding='utf-8'))
        if errors:
            raise ValueError('\n'.join(errors))
        if config.get('pdf', False):
            run('report.py', [str(report), '--opt', str(result), '--out', str(out / 'report.pdf')], base)
        print(f'流程与数字核验完成：{out}\nHTML 摘要与志愿表已核验；正文未标注的数字、敏感性与版式仍须人工复核。')
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        ap.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""专业组内容相似度候选建议；只有单独人工确认的一对一记录才能导出历史对应。"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path
import re

CONTEXT = ('province', 'category', 'batch', 'school')
REQUIRED = set(CONTEXT) | {'year', 'group', 'major', 'requirement', 'campus', 'pathway', 'complete', 'source'}
FIELDS = [*CONTEXT, 'from_year', 'from_group', 'from_code', 'to_year', 'to_group', 'to_code',
          'jaccard', 'common_majors', 'removed_majors', 'added_majors', 'from_complete', 'to_complete',
          'from_requirement', 'to_requirement', 'from_campus', 'to_campus', 'from_pathway', 'to_pathway',
          'from_source', 'to_source', 'warnings', 'confirmed', 'verification_source', 'verification_note', 'history_key']


def clean(value):
    return re.sub(r'\s+', '', value or '')


def load_groups(path):
    groups = {}
    with open(path, encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError('组内容表缺列：' + ', '.join(sorted(missing)))
        for line, raw in enumerate(reader, 2):
            row = {k: (v or '').strip() for k, v in raw.items()}
            if any(not row[k] for k in (*CONTEXT, 'year', 'group', 'major')):
                raise ValueError(f'第 {line} 行语境、年份、组号和专业不可为空')
            if row['complete'] not in ('0', '1'):
                raise ValueError(f'第 {line} 行 complete 必须显式为 0 或 1')
            year = int(row['year'])
            key = tuple(row[k] for k in CONTEXT) + (year, row['group'])
            descriptors = tuple(row[k] for k in ('requirement', 'campus', 'pathway', 'complete', 'code') if k in row)
            if key not in groups:
                groups[key] = {'row': row, 'descriptors': descriptors, 'majors': set(), 'sources': set()}
            item = groups[key]
            if descriptors != item['descriptors']:
                raise ValueError(f'第 {line} 行同组条件或完整性不一致；先核对目录，不能混成一个组')
            major = clean(row['major'])
            if major in item['majors']:
                raise ValueError(f'第 {line} 行同组专业重复：{row["major"]}')
            item['majors'].add(major)
            if row['source']:
                item['sources'].add(row['source'])
    return groups


def suggestions(groups, from_year, to_year):
    if to_year <= from_year:
        raise ValueError('后年必须晚于前年')
    by_context = defaultdict(lambda: defaultdict(list))
    for key, group in groups.items():
        by_context[key[:4]][key[4]].append(group)
    output = []
    for context, years in sorted(by_context.items()):
        previous, following = years[from_year], years[to_year]
        for old in previous:
            for new in following:
                a, b = old['majors'], new['majors']
                overlap = a & b
                if not overlap:
                    continue
                before, after = old['row'], new['row']
                warnings = []
                if before['complete'] != '1' or after['complete'] != '1':
                    warnings.append('incomplete_directory')
                for key in ('requirement', 'campus', 'pathway'):
                    if not before[key] or not after[key]:
                        warnings.append(key + '_unknown')
                    elif clean(before[key]) != clean(after[key]):
                        warnings.append(key + '_changed')
                if a != b:
                    warnings.append('major_content_changed')
                if not old['sources'] or not new['sources']:
                    warnings.append('source_missing')
                # 只表示多组有重叠，不宣称真正发生了拆组/合组。
                if sum(bool(a & g['majors']) for g in following) > 1:
                    warnings.append('possible_split_or_multiple_overlap')
                if sum(bool(b & g['majors']) for g in previous) > 1:
                    warnings.append('possible_merge_or_multiple_overlap')
                row = dict(zip(CONTEXT, context))
                row.update(from_year=from_year, from_group=before['group'], from_code=before.get('code', ''),
                           to_year=to_year, to_group=after['group'], to_code=after.get('code', ''),
                           jaccard=f'{len(overlap)/len(a|b):.6f}', common_majors=';'.join(sorted(overlap)),
                           removed_majors=';'.join(sorted(a-b)), added_majors=';'.join(sorted(b-a)),
                           from_complete=before['complete'], to_complete=after['complete'],
                           from_source=';'.join(sorted(old['sources'])), to_source=';'.join(sorted(new['sources'])),
                           warnings=';'.join(warnings), confirmed='0', verification_source='', verification_note='', history_key='')
                for key in ('requirement', 'campus', 'pathway'):
                    row['from_' + key], row['to_' + key] = before[key], after[key]
                output.append(row)
    return sorted(output, key=lambda row: (*[row[k] for k in CONTEXT], -float(row['jaccard']), row['from_group'], row['to_group']))


def write_csv(path, rows, fields):
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_confirmed(path, school_field='name'):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        if not set(FIELDS) <= set(reader.fieldnames or []):
            raise ValueError('人工核实表必须保留完整建议表字段')
        selected = [r for r in reader if r['confirmed'].strip() == '1']
    if not selected:
        raise ValueError('没有显式 confirmed=1 的人工核实行')
    contexts = {tuple(r[k] for k in CONTEXT[:3]) for r in selected}
    if len(contexts) != 1:
        raise ValueError('一次导出只能含同省、同科类、同批次；禁止跨语境拼接')
    seen, stable, pairs = {}, {}, set()
    for row in selected:
        if any(not row[k].strip() for k in CONTEXT):
            raise ValueError('确认行的省份、科类、批次、学校不可为空')
        if int(row['to_year']) <= int(row['from_year']):
            raise ValueError('确认行的后年必须晚于前年')
        pair = (*[row[k] for k in CONTEXT], row['from_year'], row['from_group'], row['to_year'], row['to_group'])
        if pair in pairs:
            raise ValueError('人工核实表含重复对应行')
        pairs.add(pair)
        for field in ('verification_source', 'verification_note', 'history_key'):
            if not row[field].strip():
                raise ValueError('确认行须填写 ' + field + '；分数和组号不是核实证据')
        if not all(url.startswith(('https://', 'http://')) for url in row['verification_source'].split(';')):
            raise ValueError('verification_source 须为实际核实的公开来源 URL，多个用分号分隔')
        if row['from_complete'] != '1' or row['to_complete'] != '1':
            raise ValueError('不完整目录不可导出正式跨年对应')
        if row['removed_majors'] or row['added_majors']:
            raise ValueError('组内专业内容变化，不能作为同一组历史直接拼接')
        for key in ('requirement', 'campus', 'pathway'):
            a, b = row['from_' + key], row['to_' + key]
            if not a or not b or clean(a) != clean(b):
                raise ValueError(key + ' 未知或变更，不可直接导出正式跨年对应')
        if not row['from_source'] or not row['to_source']:
            raise ValueError('前后年目录来源均不可为空')
        for side in ('from', 'to'):
            year, group = int(row[side+'_year']), row[side+'_group']
            school = row['school'] if school_field == 'name' else row[side+'_code']
            if not school or not group:
                raise ValueError('导出使用的学校标识与组号不可为空')
            key, history = (year, school, group), row['history_key'].strip()
            value = { 'year':year, school_field:school, 'group':group, 'history_key':history, 'source':row['verification_source'] + ' | ' + row['verification_note']}
            if key in seen and seen[key]['history_key'] != history:
                raise ValueError('同一年度专业组对应多个历史键，疑似拆组/合组')
            if (year, history) in stable and stable[(year, history)] != key:
                raise ValueError('同一年度历史键对应多个专业组，疑似拆组/合组')
            if history in stable and stable[history] != row['school']:
                raise ValueError('历史键跨学校复用')
            if key in seen:
                value['source'] = seen[key]['source'] + ' ; ' + value['source']
            seen[key], stable[(year, history)], stable[history] = value, key, row['school']
    output = list(seen.values())
    return sorted(output, key=lambda row:(row['year'],row['history_key']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    suggest = commands.add_parser('suggest', help='生成候选建议，全部 confirmed=0')
    suggest.add_argument('csv')
    suggest.add_argument('--from-year', type=int, required=True)
    suggest.add_argument('--to-year', type=int, required=True)
    suggest.add_argument('--out', required=True)
    export = commands.add_parser('export', help='导出人工确认的完整一致且一对一的历史对应')
    export.add_argument('csv')
    export.add_argument('--school', choices=('name','code'), default='name')
    export.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        if Path(args.out).exists():
            raise ValueError('输出文件已存在，请用新文件名，避免覆盖人工核实记录')
        if args.command == 'suggest':
            rows = suggestions(load_groups(args.csv), args.from_year, args.to_year)
            write_csv(args.out, rows, FIELDS)
            print(f'已写出 {len(rows)} 个相似度候选；全部未确认，不能交给 pool --group-map')
        else:
            rows = export_confirmed(args.csv, args.school)
            write_csv(args.out, rows, ['year',args.school,'group','history_key','source'])
            print(f'已导出 {len(rows)} 条人工确认对应；pool 须使用 --school {args.school}，且只用于核实表的省/科类/批次')
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()

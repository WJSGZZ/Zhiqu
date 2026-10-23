#!/usr/bin/env python3
"""Append independently recomputed anonymous initial-score aggregates to a candidate pair.

Individual records and scores are not an input format. The older hand-off importer
continues to quarantine summaries lacking original-file proof.
"""
import argparse, hashlib, json, math, re, sqlite3
from pathlib import Path
from ingest_kaoyan_lines import SOURCE, candidate_path, dump, insert_exact, number, privacy, validate_source

FIELDS = set(('record_id institution_id school college program_code program_name degree_type year study_mode '
              'list_type admission_route special_plan direction joint_program n min median max '
              'source_id src_page src_table src_row scope_raw').split())
PROOF = {'source_id', 'original_rows', 'included_rows', 'excluded_rows', 'exclusions',
         'sample_count', 'sample_locators', 'sample_passed', 'dual_read_equal',
         'score_column', 'method', 'review_status'}


def ingest(database, manifest):
    p = candidate_path(database)
    privacy(manifest)
    if set(manifest) != {'sources', 'rows', 'files'}:
        raise ValueError('仅接受来源、匿名分组摘要、文件级核对证明')
    proofs = {}
    for f in manifest['files']:
        if set(f) != PROOF or f['source_id'] in proofs:
            raise ValueError('文件核对证明字段或来源重复')
        for k in ('original_rows', 'included_rows', 'excluded_rows', 'sample_count'):
            if type(f[k]) is not int or f[k] < 0:
                raise ValueError('文件行数非法')
        if f['original_rows'] != f['included_rows'] + f['excluded_rows']:
            raise ValueError('原行数未闭合')
        need = min(f['original_rows'], max(3, math.ceil(f['original_rows'] * .03)))
        locators = f['sample_locators']
        if (not isinstance(locators, list)
                or any(not isinstance(x, dict) or set(x) != {'page', 'table', 'row'}
                       or any(type(v) is not int or v < 1 for v in x.values()) for x in locators)):
            raise ValueError('抽核原页表行定位非法')
        if (f['sample_count'] < need or f['sample_count'] != len({dump(x) for x in locators})
                or f['sample_passed'] is not True or f['dual_read_equal'] is not True
                or f['review_status'] != 'approved' or f['score_column'] not in {'初试成绩', '初试总分'}):
            raise ValueError('双读、初试总分角色、主审或文件抽核未通过')
        if not isinstance(f['exclusions'], dict) or any(type(x) is not int or x < 0 for x in f['exclusions'].values()) or sum(f['exclusions'].values()) != f['excluded_rows']:
            raise ValueError('排除数未闭合')
        proofs[f['source_id']] = f
    c = sqlite3.connect(p)
    out = {'sources_inserted': 0, 'rows_inserted': 0, 'rows_existing': 0, 'samples_inserted': 0}
    try:
        cfg = dict(c.execute('SELECT key,value FROM storage_manifest'))
        audit = p.parent / cfg['audit_file']
        if not audit.is_file():
            raise ValueError('缺配对审计库')
        c.execute('ATTACH DATABASE ? AS audit', (str(audit),))
        if c.execute("SELECT value FROM audit.storage_manifest WHERE key='generation'").fetchone()[0] != cfg['generation']:
            raise ValueError('配对代号不同')
        c.execute('BEGIN IMMEDIATE')
        def guard(action, a, b, db, trigger):
            if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_INSERT and not ((db == 'main' and a in {'source', 'ky_score_dist'}) or (db == 'audit' and a == 'check_sample_misc')):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.set_authorizer(guard)
        for s in manifest['sources']:
            if set(s) != set(SOURCE) or s['grade'] != '官方' or not re.fullmatch('[0-9a-f]{64}', s['archive_sha256'] or ''):
                raise ValueError('须为带原名单指纹的完整官方来源')
            validate_source(s)
            out['sources_inserted'] += insert_exact(c, 'source', s, ['source_id'])
        sums = {sid: 0 for sid in proofs}
        first = {}
        for r in manifest['rows']:
            if set(r) != FIELDS or r['source_id'] not in proofs:
                raise ValueError('匿名摘要字段或来源不符')
            sid = r['source_id']; f = proofs[sid]
            school = c.execute('SELECT name FROM institution WHERE institution_id=?', (r['institution_id'],)).fetchone()
            if not school or school[0] != r['school'] or not c.execute("SELECT 1 FROM source WHERE source_id=? AND grade='官方'", (sid,)).fetchone():
                raise ValueError('学校身份或来源不符')
            vals = {k: number(r[k], k) for k in ('year', 'n', 'min', 'median', 'max')}
            if (any(v is None for v in vals.values()) or not 1900 <= vals['year'] <= 2100
                    or vals['n'] < 1 or not vals['n'].is_integer()
                    or not vals['min'] <= vals['median'] <= vals['max'] or r['list_type'] != '拟录取'
                    or not all(str(r[k] or '').strip() for k in ('src_row', 'src_table', 'scope_raw', 'admission_route'))):
                raise ValueError('摘要数值、类型或原件定位非法')
            sums[sid] += int(vals['n']); first.setdefault(sid, r)
            data = dict(r); data.update(vals); data['n'] = int(vals['n'])
            data.update(scope='官方拟录取名单初试总分匿名统计', scope_parse_status='主审通过，分组范围按原标签',
                        quarantine_reason=None, statistics_complete='仅n/min/median/max；q1/q3/mean未计算',
                        scope_mismatch='未自动匹配', scope_mismatch_note='按名单原学院/专业/学习方式/专项/类型分组，未假定与资格线方向范围一致',
                        locator_method='两独立读法内存逐格一致，文件固定随机抽核通过；只存匿名聚合',
                        locator_status='原名单页/表/行范围和指纹已留，原件已删除',
                        extra_json=dump({'file_proof_sha256': hashlib.sha256(dump(f).encode()).hexdigest(), 'score_column': f['score_column'], 'aggregation': 'n=count；min/max取端点；median排序后奇数取中项、偶数取中间两项算术平均'}),
                        value_status=dump({k: {'status': '官方原值' if k == 'year' else '推算', 'reason': '原文年份' if k == 'year' else '从官方初试总分列匿名聚合；双读与文件抽核通过'} for k in vals} | {k: {'status': '来源未提供', 'reason': '官方名单未直接给该统计，本次未计算'} for k in ('q1','q3','mean','excluded_count')}))
            added = insert_exact(c, 'ky_score_dist', data, ['record_id']); out['rows_inserted' if added else 'rows_existing'] += 1
        if any(sums[sid] != f['included_rows'] for sid, f in proofs.items()):
            raise ValueError('分组人数与文件纳入人数不闭合')
        for sid, f in proofs.items():
            if sid not in first:
                raise ValueError('核对文件无可入匿名分组')
            sample = dict(sample_id='verified-stats-' + hashlib.sha256(sid.encode()).hexdigest()[:24], domain='考研', table_name='ky_score_dist', row_key=first[sid]['record_id'], field='整份名单双读与抽核（仅匿名证明）', db_value=dump({'groups_n': sums[sid]}), official_value=dump(f), official_source_id=sid, verdict='一致', checked_on=next(s['retrieved'] for s in manifest['sources'] if s['source_id']==sid), reason='全体原行闭合；固定随机抽核通过；不保存抽样人的分数/姓名/号码', excerpt='初试成绩匿名汇总，不含复试成绩和加权总成绩', locator=dump({k:first[sid][k] for k in ('src_page','src_table','src_row')}), reviewer='独立双读及主代理列角色/范围核定')
            # insert_exact quotes table names; the attached owner must be explicit.
            old = c.execute('SELECT '+','.join(sample)+' FROM audit.check_sample_misc WHERE sample_id=?',(sample['sample_id'],)).fetchone()
            if old is None:
                c.execute('INSERT INTO audit.check_sample_misc('+','.join(sample)+') VALUES('+','.join('?' for _ in sample)+')',list(sample.values()));out['samples_inserted'] += 1
            elif tuple(old) != tuple(sample.values()):
                raise ValueError('已有抽核证明冲突')
        c.commit(); return out
    except Exception:
        c.rollback(); raise
    finally:
        c.close()

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--database',required=True);ap.add_argument('--manifest',required=True);ap.add_argument('--receipt',required=True);a=ap.parse_args()
    result=ingest(a.database,json.loads(Path(a.manifest).read_text()));Path(a.receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(dump(result))

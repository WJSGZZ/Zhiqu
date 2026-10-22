#!/usr/bin/env python3
"""Insert reviewed MOE national lines (ky_national_line) and their check samples into a candidate pair only."""
import argparse, hashlib, json, re, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_kaoyan_lines import SOURCE, candidate_path, dump, insert_exact, number, privacy, validate_source

COLS = ('record_id year category program_name degree_type region scope scope_raw source_id src_page src_table src_row '
        'locator_method locator_status line_total single_100 single_over_100 value_status extra_json').split()
NUM = ('line_total', 'single_100', 'single_over_100')
REGIONS = {'A', 'B', '少数民族照顾', '骨干计划'}
STATUS = {'官方原值', '来源未提供', '未公布'}
SAMPLE = 'sample_id domain table_name row_key field db_value official_value official_source_id verdict checked_on reason excerpt locator reviewer'.split()
VERDICTS = {'一致', '不一致', '口径不同', '未取到'}


def check_row(row):
    if set(row) - set(COLS) or not {'record_id', 'year', 'category', 'region', 'source_id', 'src_page', 'src_table', 'src_row', 'value_status'} <= set(row):
        raise ValueError('国家线行字段不全或含未知列')
    if not isinstance(row['year'], int) or isinstance(row['year'], bool) or not 2000 <= row['year'] <= 2100:
        raise ValueError('年份必须为整数')
    if row['region'] not in REGIONS:
        raise ValueError('未知分区')
    if row.get('degree_type') not in ('学术', '专业', '混合', '通用'):
        raise ValueError('未知学位类型')
    status = json.loads(row['value_status'])
    for k in NUM:
        row[k] = number(row.get(k), k)
        st = status.get(k, {}).get('status')
        if st not in STATUS:
            raise ValueError('逐值状态缺失:' + k)
        if (row[k] is None) != (st != '官方原值'):
            raise ValueError('空值与逐值状态不符:' + k)
        if st != '官方原值' and not str(status[k].get('reason') or '').strip():
            raise ValueError('空值须说明原因:' + k)
    if row['region'] == '骨干计划' and row['line_total'] is None:
        raise ValueError('骨干计划须有原文总分')
    if not re.fullmatch(r'[0-9a-f]{24}', row['record_id']):
        raise ValueError('record_id 格式')
    return row


def ingest(database, manifest):
    p = candidate_path(database)
    privacy(manifest)
    if set(manifest) - {'sources', 'rows', 'samples'}:
        raise ValueError('manifest 顶层字段未知')
    c = sqlite3.connect(p)
    c.execute('PRAGMA foreign_keys=ON')
    result = {'sources_inserted': 0, 'rows_inserted': 0, 'rows_existing': 0, 'samples_inserted': 0}
    try:
        config = dict(c.execute('SELECT key,value FROM storage_manifest'))
        audit = p.parent / config.get('audit_file', '')
        if not re.fullmatch(r'audit-[a-z0-9-]+\.sqlite', audit.name) or not audit.is_file():
            raise ValueError('缺少配对审计库')
        c.execute('ATTACH DATABASE ? AS audit', (str(audit),))
        gen = c.execute("SELECT value FROM audit.storage_manifest WHERE key='generation'").fetchone()
        if not gen or gen[0] != config.get('generation'):
            raise ValueError('查询与审计库代号不一致')
        c.execute('BEGIN IMMEDIATE')

        def guard(action, a, b, db, trigger):
            if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_INSERT and not ((db == 'main' and a in {'source', 'ky_national_line'}) or (db == 'audit' and a == 'check_sample_misc')):
                return sqlite3.SQLITE_DENY
            if action in (sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.set_authorizer(guard)
        for source in manifest.get('sources', []):
            if set(source) != set(SOURCE) or source['grade'] != '官方':
                raise ValueError('source 须为官方原17列')
            validate_source(source)
            result['sources_inserted'] += insert_exact(c, 'source', {k: source[k] for k in SOURCE}, ['source_id'])
        for row in manifest.get('rows', []):
            row = check_row(dict(row))
            if not c.execute("SELECT 1 FROM source WHERE source_id=? AND grade='官方'", (row['source_id'],)).fetchone():
                raise ValueError('缺少官方来源')
            data = {k: row.get(k) for k in COLS}
            added = insert_exact(c, 'ky_national_line', data, ['record_id'])
            result['rows_inserted' if added else 'rows_existing'] += 1
        for s in manifest.get('samples', []):
            if set(s) != set(SAMPLE) or s['verdict'] not in VERDICTS or s['table_name'] != 'ky_national_line':
                raise ValueError('抽核记录字段不合规')
            if not c.execute('SELECT 1 FROM ky_national_line WHERE record_id=? AND source_id=?', (s['row_key'], s['official_source_id'])).fetchone():
                raise ValueError('抽核记录未对应国家线行与来源')
            old = c.execute('SELECT ' + ','.join(SAMPLE) + ' FROM audit.check_sample_misc WHERE sample_id=?', (s['sample_id'],)).fetchone()
            if old is not None:
                if tuple(old) != tuple(s[k] for k in SAMPLE):
                    raise ValueError('已有抽核记录冲突')
                continue
            c.execute('INSERT INTO audit.check_sample_misc(' + ','.join(SAMPLE) + ') VALUES(' + ','.join('?' * len(SAMPLE)) + ')', [s[k] for k in SAMPLE])
            result['samples_inserted'] += 1
        c.commit()
        return result
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--database', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--receipt', required=True)
    a = ap.parse_args()
    m = Path(a.manifest)
    r = ingest(a.database, json.loads(m.read_text()))
    r.update(database=str(Path(a.database).resolve()), manifest_sha256=hashlib.sha256(m.read_bytes()).hexdigest())
    Path(a.receipt).write_text(json.dumps(r, ensure_ascii=False, indent=2) + '\n')
    print(dump(r))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Insert reviewed official admission-catalogue rows (ky_program_year) and their check samples into a candidate pair only."""
import argparse, hashlib, json, re, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_kaoyan_lines import SOURCE, candidate_path, dump, insert_exact, privacy, validate_source
from ingest_kaoyan_national import SAMPLE, VERDICTS

COLS = ('record_id institution_id school college program_code program_name degree_type year study_mode direction direction_raw '
        'special_plan scope scope_raw source_id src_row src_page src_table locator_method locator_status planned planned_raw '
        'planned_scope subjects extra_json value_status tuimian').split()
REQUIRED = {'record_id', 'institution_id', 'school', 'year', 'source_id', 'src_table', 'src_row', 'value_status'}
STATUS = {'官方原值', '来源未提供', '未公布'}


def check_row(c, row):
    if set(row) - set(COLS) or not REQUIRED <= set(row):
        raise ValueError('招生目录行字段不全或含未知列')
    if not isinstance(row['year'], int) or isinstance(row['year'], bool):
        raise ValueError('年份必须为整数')
    if not re.fullmatch(r'[0-9a-z-]{8,64}', row['record_id']):
        raise ValueError('record_id 格式')
    name = c.execute('SELECT name FROM institution WHERE institution_id=?', (row['institution_id'],)).fetchone()
    if not name or name[0] != row['school']:
        raise ValueError('官方校名与身份未精确匹配')
    # Some official catalogues (e.g. PKU) prefix their six-digit code with S.
    # Preserve that literal code; stripping the prefix would change its identity.
    if row.get('program_code') not in (None, '') and not re.fullmatch(r'(?:[0-9]{4}[0-9A-Z]{2}|S[0-9]{6})', row['program_code']):
        raise ValueError('专业代码格式')
    status = json.loads(row['value_status'])
    planned = row.get('planned')
    if planned is not None and (not isinstance(planned, int) or isinstance(planned, bool) or planned < 0):
        raise ValueError('招生人数必须为非负整数')
    if status.get('planned', {}).get('status') not in STATUS or (planned is None) != (status['planned']['status'] != '官方原值'):
        raise ValueError('planned 逐值状态不符')
    if planned is None and not str(status['planned'].get('reason') or '').strip():
        raise ValueError('空人数须说明原因')
    if 'tuimian' in row or 'tuimian' in status:
        recommended = row.get('tuimian')
        if recommended is not None and (not isinstance(recommended, int) or isinstance(recommended, bool) or recommended < 0):
            raise ValueError('推免人数必须为非负整数，星号不得当人数')
        mark = status.get('tuimian', {})
        if mark.get('status') not in STATUS or (recommended is None) != (mark['status'] != '官方原值'):
            raise ValueError('tuimian 逐值状态不符')
        if recommended is None and not str(mark.get('reason') or '').strip():
            raise ValueError('空推免人数须说明原因')
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
            if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE):
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_INSERT and not ((db == 'main' and a in {'source', 'ky_program_year'}) or (db == 'audit' and a == 'check_sample_misc')):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.set_authorizer(guard)
        for source in manifest.get('sources', []):
            if set(source) != set(SOURCE) or source['grade'] != '官方':
                raise ValueError('source 须为官方原17列')
            validate_source(source)
            result['sources_inserted'] += insert_exact(c, 'source', {k: source[k] for k in SOURCE}, ['source_id'])
        for row in manifest.get('rows', []):
            row = check_row(c, dict(row))
            if not c.execute("SELECT 1 FROM source WHERE source_id=? AND grade='官方'", (row['source_id'],)).fetchone():
                raise ValueError('缺少官方来源')
            added = insert_exact(c, 'ky_program_year', {k: row.get(k) for k in COLS}, ['record_id'])
            result['rows_inserted' if added else 'rows_existing'] += 1
        for s in manifest.get('samples', []):
            if set(s) != set(SAMPLE) or s['verdict'] not in VERDICTS or s['table_name'] != 'ky_program_year':
                raise ValueError('抽核记录字段不合规')
            if not c.execute('SELECT 1 FROM ky_program_year WHERE record_id=? AND source_id=?', (s['row_key'], s['official_source_id'])).fetchone():
                raise ValueError('抽核记录未对应目录行与来源')
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

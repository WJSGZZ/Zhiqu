"""Independent read-back of anonymous manifests using real SQLite affinities."""
import sqlite3
import json
from pathlib import Path

from ingest_kaoyan_lines import RAW, SOURCE, SCOPES, dump, privacy


def _quote(s):
    return '"'+s.replace('"','""')+'"'


def _exact(c, table, data, keys):
    info={r[1]:r[2] for r in c.execute('pragma table_info('+_quote(table)+')')}
    if not data or not set(data)<=set(info):raise ValueError('新增行校验字段不符')
    columns=list(data)
    with sqlite3.connect(':memory:')as ram:
        # Apply the REAL/TEXT/INTEGER affinities of the actual destination, then
        # compare both values and SQLite storage types. NULL is never zero.
        ram.execute('create table expected('+','.join(_quote(k)+' '+info[k] for k in columns)+')')
        ram.execute('insert into expected values('+','.join('?'for _ in columns)+')',list(data.values()))
        projection=','.join(_quote(k)for k in columns)+','+','.join('typeof('+_quote(k)+')'for k in columns)
        expected=ram.execute('select '+projection+' from expected').fetchone()
    actual=c.execute('select '+projection+' from '+_quote(table)+' where '+
                     ' and '.join(_quote(k)+' IS ?'for k in keys),[data[k]for k in keys]).fetchall()
    if len(actual)!=1 or tuple(actual[0])!=expected:raise ValueError('新增行的实际值、类型或定位与核准清单不符')


def verify_manifest_rows(database, manifests, deadline=None):
    counts={'sources':0,'rows':0,'components':0}
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)as c:
        c.execute('pragma query_only=on')
        for layer,manifest in manifests:
            privacy(manifest)
            for source in manifest['sources']:
                if deadline:deadline()
                _exact(c,'source',{k:source[k]for k in SOURCE},['source_id']);counts['sources']+=1
            for row in manifest['rows']:
                if deadline:deadline()
                if layer=='lines':
                    expected={k:row['row'].get(k)for k in RAW}
                    expected.update(record_id=row['record_id'],institution_id=row['institution_id'],source_id=row['source_id'])
                    source=next(s for s in manifest['sources']if s['source_id']==row['source_id'])
                    expected.update(published_date=source['published']or None,retrieved_date=source['retrieved']or None)
                    if row.get('scope_kind'):
                        expected['line_scope']=row['scope_kind']
                        if row['scope_kind']!=row['row'].get('line_scope'):expected['note']=(expected['note']or'')+'；原scope='+str(row['row'].get('line_scope')or'')
                    _exact(c,'ky_retest_line',expected,['record_id'])
                    loc=c.execute('select locator_json from ky_retest_line_source where record_id=? and source_id=?',(row['record_id'],row['source_id'])).fetchall()
                    if len(loc)!=1 or any(json.loads(loc[0][0]).get(k)!=row.get(k)for k in ['src_page','src_row','src_table']):raise ValueError('新增线的原页表行关联不符')
                    context=row.get('scope_context')
                    if context is not None:_exact(c,'ky_line_scope_context',dict(record_id=row['record_id'],source_id=row['source_id'],**{k:context.get(k,'')for k in SCOPES}),['record_id'])
                    compact={k:row.get(k)for k in ('src_page','src_table','src_row')}
                    compact.update(evidence_record_id=row['record_id'],audit_table='ky_line_original_evidence')
                    if isinstance(row.get('locator'),dict):compact['sha256']=row['locator'].get('sha256')
                    for component,value in row.get('components',{}).items():
                        _exact(c,'ky_line_component',dict(record_id=row['record_id'],component=component,value=value,source_id=row['source_id'],src_locator=dump(compact)),['record_id','component']);counts['components']+=1
                else:
                    _exact(c,{'catalog':'ky_program_year','stats':'ky_score_dist'}[layer],dict(row),['record_id'])
                    if layer=='stats' and (type(row['n'])is not int or row['n']<3):raise ValueError('禁止不足三人的统计组')
                counts['rows']+=1
    return {'ok':True,**counts,'method':'真实目标列亲和性转存RAM后，实际值及typeof、行身份与原定位逐项比对'}

"""Append-only staging and atomic publication of an immutable query/audit pair.

No network access or ingestion policy lives here. ``expected_delta`` accepts
``{'data.table': n, 'audit.table': n}`` or nested owner dictionaries; omitted
physical tables must have zero additions. A deadline callback returns None/True
while work may continue, and False (or raises) when the deadline has expired.
The caller supplies its complete validation checklist, not just a summary flag.
"""
from contextlib import contextmanager, closing
from functools import lru_cache
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import uuid

from db_storage import ident

_PROTOCOL = 'kaoyan-append-only-v1'
_FK_PROTOCOL = 'kaoyan-foreign-key-certificate-v1'
_AUDIT = re.compile(r'audit-[a-z0-9-]+\.sqlite')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_MUTABLE_KEYS = ('generation', 'audit_file')


class TransactionError(ValueError):
    """A safe diagnostic which never contains rows, SQL errors or source values."""


def _check(deadline):
    try:
        expired = deadline() is False
    except Exception:
        raise TimeoutError('数据库操作已超过期限') from None
    if expired:
        raise TimeoutError('数据库操作已超过期限')


def _sha(path, deadline=None):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            if deadline is not None:
                _check(deadline)
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sealed(path):
    if any(Path(str(path) + suffix).exists() and Path(str(path) + suffix).stat().st_size
           for suffix in ('-wal', '-journal')):
        raise TransactionError('数据库存在未封存写入')


def _open(path):
    c = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)
    c.execute('PRAGMA query_only=ON')
    return c


def _pair(query):
    query = Path(query)
    if query.is_symlink():
        raise TransactionError('数据库路径不安全')
    query = query.resolve()
    if not query.is_file():
        raise TransactionError('数据库文件不存在')
    _sealed(query)
    with closing(_open(query)) as c:
        config = dict(c.execute('SELECT key,value FROM storage_manifest'))
    filename = config.get('audit_file', '')
    if not isinstance(filename, str) or not _AUDIT.fullmatch(filename):
        raise TransactionError('审计库文件名不合规')
    audit = query.parent / filename
    if audit.is_symlink() or not audit.is_file() or audit.resolve().parent != query.parent:
        raise TransactionError('配对审计库不可用')
    _sealed(audit)
    with closing(_open(audit)) as c:
        ac = dict(c.execute('SELECT key,value FROM storage_manifest'))
    if not config.get('generation') or config['generation'] != ac.get('generation'):
        raise TransactionError('查询库与审计库代号不一致')
    if 'audit_file' in ac and ac['audit_file'] != filename:
        raise TransactionError('审计库清单引用不一致')
    return query, audit, config['generation']


def _snapshot(pair, deadline=None):
    q, a, generation = pair
    return {'query_sha256': _sha(q, deadline), 'audit_sha256': _sha(a, deadline),
            'generation': generation, 'audit_file': a.name}


def _backup(source, destination, deadline):
    _check(deadline)
    with closing(_open(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst, pages=256, progress=lambda *_: _check(deadline))
    _check(deadline)


def _clone_file(source, destination, deadline):
    """APFS clone when available; SQLite online backup otherwise."""
    _check(deadline)
    try:
        cp = subprocess.run(['cp', '-c', str(source), str(destination)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=2, check=False)
        cloned = cp.returncode == 0 and destination.is_file()
    except (OSError, subprocess.TimeoutExpired):
        cloned = False
    _check(deadline)
    if cloned:
        return 'cp-c'
    if destination.exists():
        destination.unlink()
    _backup(source, destination, deadline)
    return 'sqlite-backup'


def clone_pair(live, candidate, deadline):
    """Create a separate candidate pair, changing only two manifest values."""
    owned = []
    try:
        started=time.monotonic()
        _check(deadline)
        original = _pair(live)
        before = _snapshot(original, deadline)
        baseline_at=time.monotonic()
        candidate = Path(candidate).absolute()
        if candidate.is_symlink() or candidate.exists() or candidate.resolve() == original[0]:
            raise TransactionError('候选路径已存在或与正式库重合')
        candidate.parent.mkdir(parents=True, exist_ok=True)
        generation = uuid.uuid4().hex
        audit = candidate.parent / ('audit-' + generation + '.sqlite')
        if audit.exists():
            raise TransactionError('候选审计代号已存在')
        owned.extend((candidate, audit))
        methods = [_clone_file(original[0], candidate, deadline),
                   _clone_file(original[1], audit, deadline)]
        copied_at=time.monotonic()
        with closing(_open(candidate)) as c:
            copied = dict(c.execute('SELECT key,value FROM storage_manifest'))
        if copied.get('generation') != original[2] or copied.get('audit_file') != original[1].name:
            raise TransactionError('克隆期间正式库发生变化')
        for path in (candidate, audit):
            _check(deadline)
            with closing(sqlite3.connect(path)) as c, c:
                c.execute("UPDATE storage_manifest SET value=? WHERE key='generation'", (generation,))
                c.execute("UPDATE storage_manifest SET value=? WHERE key='audit_file'", (audit.name,))
        if before != _snapshot(_pair(live), deadline):
            raise TransactionError('克隆期间正式库发生变化')
        pair = _pair(candidate)
        return {'candidate': str(pair[0]), 'audit': str(pair[1]), 'generation': generation,
                'live': before, 'copy_methods': methods, 'ok': True,
                'timings':{'baseline_hash':baseline_at-started,'copy':copied_at-baseline_at,
                           'manifest_and_live_recheck':time.monotonic()-copied_at,'total':time.monotonic()-started}}
    except Exception as error:
        for path in owned:
            for suffix in ('', '-journal', '-wal', '-shm'):
                try:
                    Path(str(path) + suffix).unlink(missing_ok=True)
                except OSError:
                    pass
        if isinstance(error, (TransactionError, TimeoutError)):
            raise
        raise TransactionError('克隆配对数据库失败') from None


def _schema(c, owner):
    return c.execute('SELECT type,name,tbl_name,sql FROM ' + ident(owner) +
                     '.sqlite_schema ORDER BY type,name').fetchall()


def _tables(schema):
    return [row[1] for row in schema if row[0] == 'table']


def _delta(expected, tables):
    flat = {}
    if not isinstance(expected, dict):
        raise TransactionError('预期增量格式不合规')
    for key, value in expected.items():
        if key in ('data', 'audit') and isinstance(value, dict):
            entries = [(key + '.' + table, n) for table, n in value.items()]
        else:
            entries = [(key, value)]
        for name, n in entries:
            if name in flat or name not in tables or type(n) is not int or n < 0:
                raise TransactionError('预期增量包含未知表或非法数量')
            flat[name] = n
    return {name: flat.get(name, 0) for name in tables}


def _without_rowid(c, owner, table):
    # Use SQLite's parsed flag, not a regex: a DEFAULT literal can contain the
    # words WITHOUT ROWID, while valid DDL can put comments between the words.
    rows=c.execute('PRAGMA '+ident(owner)+'.table_list('+ident(table)+')').fetchall()
    matches=[r for r in rows if len(r)>=5 and r[0]==owner and r[1]==table]
    if len(matches)!=1 or matches[0][4]not in (0,1):
        raise TransactionError('旧表行身份类型无法确定')
    return bool(matches[0][4])


def _projection(c, owner, table):
    cols = c.execute('PRAGMA ' + ident(owner) + '.table_xinfo(' + ident(table) + ')').fetchall()
    # Hidden virtual-table fields are not persisted values. Generated columns are
    # included; their expression is independently protected by the schema check.
    names = [row[1] for row in cols if row[6] != 1]
    without = _without_rowid(c,owner,table)
    shadowed={name.lower()for name in names}
    rowid = next((n for n in ('rowid', '_rowid_', 'oid') if n not in shadowed), None)
    if not without and rowid is None:
        raise TransactionError('旧行身份无法完整核对')
    fields = [] if without else [ident(rowid)]
    for name in names:
        col = ident(name)
        if table == 'storage_manifest' and name == 'value':
            mask = "key COLLATE BINARY IN ('generation','audit_file')"
            fields.extend(('CASE WHEN ' + mask + ' THEN NULL ELSE typeof(' + col + ') END',
                           'CASE WHEN ' + mask + ' THEN NULL ELSE ' + col + ' COLLATE BINARY END'))
        else:
            fields.extend(('typeof(' + col + ')', col + ' COLLATE BINARY'))
    order = [ident(row[1]) for row in sorted(cols, key=lambda r: r[5]) if row[5]] if without else [ident(rowid)]
    if not order:
        raise TransactionError('旧行身份无法完整核对')
    return ','.join(fields), ','.join(order), 'primary_key' if without else 'rowid'


def _indexed_old_rows_equal(c, owner, table):
    """Indexed identity lookup, then every persisted value and storage type.

    EXCEPT materializes a B-tree containing every projected byte.  A LEFT JOIN
    uses the rowid/primary-key lookup already present in both sealed files and
    streams the same proof without a second copy of the table.  Lookup may use
    the declared PK collation; the subsequent BINARY comparison independently
    checks every key byte as well, including a NOCASE primary key.
    """
    old_owner = 'old_' + owner
    cols = c.execute('PRAGMA ' + ident(old_owner) + '.table_xinfo(' + ident(table) + ')').fetchall()
    names = [r[1] for r in cols if r[6] != 1]
    without = _without_rowid(c,old_owner,table)
    if without:
        keys = [r[1] for r in sorted(cols, key=lambda r: r[5]) if r[5]]
        if not keys:
            raise TransactionError('旧行身份无法完整核对')
        # WITHOUT ROWID primary-key fields are guaranteed NOT NULL by SQLite.
        lookup = ' AND '.join('n.' + ident(k) + '=o.' + ident(k) for k in keys)
        missing = 'n.' + ident(keys[0]) + ' IS NULL'
    else:
        shadowed={name.lower()for name in names}
        key = next((n for n in ('rowid', '_rowid_', 'oid') if n not in shadowed), None)
        if key is None:
            raise TransactionError('旧行身份无法完整核对')
        lookup = 'n.' + ident(key) + '=o.' + ident(key)
        missing = 'n.' + ident(key) + ' IS NULL'
    differences = []
    for name in names:
        a, b = 'o.' + ident(name), 'n.' + ident(name)
        changed = '(typeof(' + a + ')<>typeof(' + b + ') OR ' + a + ' COLLATE BINARY IS NOT ' + b + ' COLLATE BINARY)'
        if table == 'storage_manifest' and name == 'value':
            # IS NOT keeps NULL keys strict as well; NOT IN would yield NULL
            # and accidentally hide a changed value on that otherwise old row.
            changed = "((o.key COLLATE BINARY IS NOT 'generation' AND o.key COLLATE BINARY IS NOT 'audit_file') AND " + changed + ')'
        differences.append(changed)
    sql = ('SELECT 1 FROM ' + ident(old_owner) + '.' + ident(table) + ' o LEFT JOIN ' +
           ident(owner) + '.' + ident(table) + ' n ON ' + lookup +
           ' WHERE ' + missing + ' OR ' + ' OR '.join(differences) + ' LIMIT 1')
    return c.execute(sql).fetchone() is None


def _changed_sqlite_pages(old, new, deadline=None, limit=4096):
    """Byte comparison only, never persist page contents or trust file mtimes.

    This is a sufficient proof shortcut, not a parser for arbitrary databases.
    Unknown formats, a changed record interpretation or a large rewrite use the
    ordinary typed SQL comparison instead. dbstat subsequently attributes every
    changed B-tree/overflow page in BOTH files, including newly allocated pages.
    """
    with Path(old).open('rb') as a, Path(new).open('rb') as b:
        ah, bh = a.read(100), b.read(100)
        if len(ah) != 100 or len(bh) != 100 or ah[:16] != b'SQLite format 3\x00' or bh[:16] != ah[:16]:
            return None
        # Page size, read/write format, reserved bytes and payload fractions;
        # record format version and text encoding must be exactly unchanged.
        if (ah[:24], ah[44:48], ah[56:60]) != (bh[:24], bh[44:48], bh[56:60]):
            return None
        size = int.from_bytes(ah[16:18], 'big')
        size = 65536 if size == 1 else size
        if size < 512 or size > 65536 or size & (size - 1):return None
        if Path(old).stat().st_size % size or Path(new).stat().st_size % size:return None
        a.seek(0); b.seek(0)
        changed, offset = set(), 0
        while True:
            if deadline is not None:_check(deadline)
            x, y = a.read(8 * 1024 * 1024), b.read(8 * 1024 * 1024)
            if not x and not y:break
            if x != y:
                for start in range(0, max(len(x), len(y)), size):
                    if x[start:start+size] != y[start:start+size]:
                        changed.add((offset+start)//size+1)
                        if len(changed)>limit:return None
            offset += 8 * 1024 * 1024
        return changed


def _byte_unchanged_tables(c, owner, old, new, schema, deadline=None):
    """Prove whole table storage identical, otherwise return it to typed SQL.

    Header/freelist pages alone do not establish table identity: every rootpage
    is compared and dbstat walks every B-tree plus overflow page in both files.
    Index changes conservatively send their owning table through SQL as well.
    """
    changed = _changed_sqlite_pages(old, new, deadline)
    if changed is None:return set(), {'available':False,'reason':'format_or_rewrite_fallback'}
    aliases = ('old_' + owner, owner)
    try:
        # Trigger names use a separate namespace and can equal a table name.
        # dbstat names only B-tree objects, so a same-named trigger must never
        # overwrite the page-to-table mapping or hide a moved table root.
        roots = [dict(c.execute('SELECT name,rootpage FROM ' + ident(alias) + ".sqlite_schema WHERE type IN ('table','index')")) for alias in aliases]
        parent = {r[1]:r[2] for r in schema if r[0]in {'table','index'}}
        affected = {parent[name] for name in roots[0] if roots[0][name] != roots[1].get(name) and name in parent}
        if changed:
            # Integers came from local page offsets, never from source text.
            pages = ','.join(str(p) for p in sorted(changed))
            for alias,path in zip(aliases,(old,new)):
                try:
                    names=[row[0]for row in c.execute('SELECT DISTINCT name FROM dbstat(?) WHERE pageno IN ('+pages+')',(alias,))]
                except sqlite3.Error:
                    names=_dbstat_page_owners(path,pages,deadline)
                    if names is None:return set(),{'available':False,'reason':'dbstat_unavailable_fallback'}
                for name in names:
                    if name in parent:affected.add(parent[name])
        virtual = {r[1] for r in schema if re.match(r'\s*CREATE\s+VIRTUAL\s+TABLE\b',r[3] or '',re.I)}
        # A virtual/generated expression may depend on an unavailable custom
        # function. Preserve the original SQL evaluation proof for these tables.
        virtual.update(r[1]for r in schema if r[0]=='table'and any(
            column[6]>=2 for column in c.execute('PRAGMA '+ident(aliases[0])+'.table_xinfo('+ident(r[1])+')')))
        eligible = set(_tables(schema)) - affected - virtual
        return eligible, {'available':True,'changed_pages':len(changed),'affected_tables':sorted(affected),
                          'byte_identical_tables':len(eligible),'both_dbstat_walks_include_overflow':True}
    except sqlite3.Error:
        if deadline is not None:_check(deadline)
        return set(), {'available':False,'reason':'dbstat_or_root_mapping_fallback'}


def _dbstat_page_owners(path, pages, deadline):
    """Use the installed readonly SQLite shell if Python lacks dbstat.

    pages is a bounded list of locally computed integers. Only table names leave
    the process, never page payloads or individual records. No shell or extension
    loading is involved. A missing module/binary, timeout or malformed result
    disables the shortcut rather than trusting incomplete attribution.
    """
    binary=shutil.which('sqlite3')
    if not binary:return None
    if deadline is not None:_check(deadline)
    sql='PRAGMA query_only=ON;SELECT DISTINCT name FROM dbstat WHERE pageno IN ('+pages+');'
    process=None
    try:
        process=subprocess.Popen([binary,'-readonly','-json',str(path),sql],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        start=time.monotonic()
        while True:
            if deadline is not None:_check(deadline)
            try:
                output,_=process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic()-start>60:return None
        if process.returncode or len(output)>1024*1024:return None
        rows=json.loads(output)if output.strip()else[]
        if not isinstance(rows,list)or not all(isinstance(row,dict)and set(row)=={'name'}and isinstance(row['name'],str)for row in rows):return None
        return [row['name']for row in rows]
    except (OSError,ValueError):return None
    finally:
        if process is not None and process.poll()is None:
            process.kill();process.communicate()


@lru_cache(maxsize=1)
def _sha3_shell():
    binary = shutil.which('sqlite3')
    if not binary:
        return None
    try:
        result = subprocess.run([binary, ':memory:', "SELECT lower(hex(sha3_query('SELECT 1')));"],
                                capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and _DIGEST.fullmatch(result.stdout.strip()):
            return binary
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _sha3_projection(path, table, projection, order):
    """Typed, rowid-bound equivalent of shell sha3sum; never hash SELECT * alone."""
    binary = _sha3_shell()
    if not binary:
        return None
    query = 'SELECT ' + projection + ' FROM ' + ident(table) + ' ORDER BY ' + order
    sql = "PRAGMA query_only=ON;SELECT lower(hex(sha3_query('" + query.replace("'", "''") + "')));"
    try:
        result = subprocess.run([binary, '-readonly', str(path), sql],
                                capture_output=True, text=True, timeout=30)
        digest = result.stdout.strip()
        if result.returncode == 0 and _DIGEST.fullmatch(digest):
            return digest
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _foreign_keys(c, affected_tables=None, details=None):
    details={}if details is None else details
    details.update(local_tables_scanned=0,external_links_scanned=0)
    for owner in ('data', 'audit'):
        if affected_tables is None:
            if c.execute('PRAGMA ' + ident(owner) + '.foreign_key_check').fetchone() is not None:
                raise TransactionError('候选库本地外键核对失败')
            details['local_tables_scanned']+=len(_tables(_schema(c,owner)))
        else:
            for name in sorted(affected_tables):
                if not name.startswith(owner+'.'):continue
                table=name[len(owner)+1:]
                if c.execute('PRAGMA ' + ident(owner) + '.foreign_key_check('+ident(table)+')').fetchone() is not None:
                    raise TransactionError('候选库本地外键核对失败')
                details['local_tables_scanned']+=1
    exists = c.execute("SELECT 1 FROM data.sqlite_schema WHERE name='storage_external_fk' AND type='table'").fetchone()
    if not exists:
        return 0
    n = 0
    for owner, table, from_json, parent_owner, parent, to_json in c.execute(
            'SELECT owner,table_name,from_columns,parent_owner,parent_table,to_columns FROM data.storage_external_fk'):
        if owner not in ('data', 'audit') or parent_owner not in ('data', 'audit'):
            raise TransactionError('跨库外键登记不合规')
        source_cols, target_cols = json.loads(from_json), json.loads(to_json)
        if not isinstance(source_cols, list) or not source_cols or not isinstance(target_cols, list) or len(source_cols) != len(target_cols):
            raise TransactionError('跨库外键列登记不合规')
        parent_info = c.execute('PRAGMA ' + ident(parent_owner) + '.table_info(' + ident(parent) + ')').fetchall()
        child_info = c.execute('PRAGMA ' + ident(owner) + '.table_info(' + ident(table) + ')').fetchall()
        if target_cols and all(x is None for x in target_cols):
            target_cols = [r[1] for r in sorted(parent_info, key=lambda r: r[5]) if r[5]]
        if len(target_cols) != len(source_cols) or not set(source_cols) <= {r[1] for r in child_info} or not set(target_cols) <= {r[1] for r in parent_info}:
            raise TransactionError('跨库外键目标不合规')
        nonnull = ' AND '.join('c.' + ident(x) + ' IS NOT NULL' for x in source_cols)
        joined = ' AND '.join('p.' + ident(y) + '=c.' + ident(x) for x, y in zip(source_cols, target_cols))
        sql = ('SELECT 1 FROM ' + ident(owner) + '.' + ident(table) + ' c WHERE ' + nonnull +
               ' AND NOT EXISTS(SELECT 1 FROM ' + ident(parent_owner) + '.' + ident(parent) + ' p WHERE ' + joined + ') LIMIT 1')
        if affected_tables is None or owner+'.'+table in affected_tables:
            if c.execute(sql).fetchone() is not None:
                raise TransactionError('候选库跨库外键核对失败')
            details['external_links_scanned']+=1
        n += 1
    return n


def foreign_key_certificate(proof):
    """A local reusable certificate from a completed full/transitive proof.

    It is not a signature or permission to trust an arbitrary remote JSON. The
    caller persists it only after successful publication; every reuse binds both
    exact file SHA256s, generation, audit name, schema and FK registry size.
    Legacy v1 proofs always ran every FK and can seed the same local cache.
    """
    try:
        if not isinstance(proof,dict)or proof.get('protocol')!=_PROTOCOL or proof.get('ok')is not True:return None
        if proof.get('local_foreign_keys_ok')is not True or proof.get('external_foreign_keys_ok')is not True:return None
        links=proof['external_foreign_keys_checked'];finger=proof['candidate'];schemas=proof['schema_sha256']
        if type(links)is not int or links<0:return None
        if set(finger)!={'query_sha256','audit_sha256','generation','audit_file'}:return None
        if not all(_DIGEST.fullmatch(str(finger[k]))for k in ['query_sha256','audit_sha256']):return None
        if set(schemas)!={'data','audit'}or not all(_DIGEST.fullmatch(str(v))for v in schemas.values()):return None
        if not proof.get('tables'):return None
        method=proof.get('foreign_key_checks',{}).get('method','full-scan')
        if method not in {'full-scan','inherited-old-plus-changed-child-tables'}:return None
        return {'protocol':_FK_PROTOCOL,'fingerprints':dict(finger),'schema_sha256':dict(schemas),
                'all_fk_valid':True,'external_foreign_key_links':links,'validation_method':method}
    except (KeyError,TypeError,ValueError):return None


def _matching_fk_certificate(c, certificate, before, schemas, expected):
    if not isinstance(certificate,dict):return False
    exists=c.execute("SELECT 1 FROM data.sqlite_schema WHERE name='storage_external_fk' AND type='table'").fetchone()
    links=c.execute('SELECT count(*) FROM data.storage_external_fk').fetchone()[0]if exists else 0
    # New relationship registrations can constrain old rows. They require a full
    # check, even when none of those child tables gained rows in this batch.
    return (certificate.get('protocol')==_FK_PROTOCOL and certificate.get('all_fk_valid')is True
            and certificate.get('fingerprints')==before and certificate.get('schema_sha256')==schemas
            and type(certificate.get('external_foreign_key_links'))is int
            and certificate['external_foreign_key_links']==links
            and certificate.get('validation_method')in {'full-scan','inherited-old-plus-changed-child-tables'}
            and expected.get('data.storage_external_fk',0)==0)


def verify_append_only(live, candidate, expected_delta, *, progress=None, deadline=None, baseline_fk_certificate=None):
    """Prove unchanged old rowids/types/values, exact additions and every FK."""
    try:
        started = time.monotonic()
        if deadline is not None:_check(deadline)
        lp, cp = _pair(live), _pair(candidate)
        if lp[0] == cp[0] or lp[2] == cp[2]:
            raise TransactionError('候选必须使用独立的新代号')
        uuid.UUID(cp[2])
        before, staged = _snapshot(lp, deadline), _snapshot(cp, deadline)
        snapshot_seconds = time.monotonic() - started
        c = sqlite3.connect(':memory:', uri=True)
        if deadline is not None:
            def budget():
                _check(deadline)
                return 0
            c.set_progress_handler(budget, 50000)
        try:
            for owner, path in [('old_data', lp[0]), ('old_audit', lp[1]), ('data', cp[0]), ('audit', cp[1])]:
                c.execute('ATTACH DATABASE ? AS ' + ident(owner), (path.as_uri() + '?mode=ro',))
            c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN')
            schemas = {}
            tables = {}
            for owner in ('data', 'audit'):
                old = _schema(c, 'old_' + owner)
                new = _schema(c, owner)
                if old != new:
                    raise TransactionError('候选改变了数据库结构')
                schemas[owner] = hashlib.sha256(json.dumps(old, ensure_ascii=False).encode()).hexdigest()
                tables.update({owner + '.' + t: t for t in _tables(old)})
            expected = _delta(expected_delta, tables)
            changes = {}
            guard_started = time.monotonic()
            page_guards, unchanged = {}, {}
            for owner, old_path, new_path in [('data',lp[0],cp[0]),('audit',lp[1],cp[1])]:
                unchanged[owner], page_guards[owner] = _byte_unchanged_tables(
                    c,owner,old_path,new_path,_schema(c,'old_'+owner),deadline)
                if progress is not None:progress({'phase':'page_bytes_verified','owner':owner,
                    'seconds':time.monotonic()-guard_started,**page_guards[owner]})
            page_seconds = time.monotonic()-guard_started
            for name, table in tables.items():
                table_started = time.monotonic()
                if deadline is not None:_check(deadline)
                owner = name.split('.', 1)[0]
                old_count = c.execute('SELECT count(*) FROM ' + ident('old_' + owner) + '.' + ident(table)).fetchone()[0]
                byte_identical = table in unchanged[owner]
                new_count = old_count if byte_identical else c.execute('SELECT count(*) FROM ' + ident(owner) + '.' + ident(table)).fetchone()[0]
                if new_count - old_count != expected[name]:
                    raise TransactionError('候选表增量与预期不符')
                _, _, identity = _projection(c, 'old_' + owner, table)
                if not byte_identical and not _indexed_old_rows_equal(c, owner, table):
                    raise TransactionError('候选改动或删除了已有行')
                seconds = time.monotonic() - table_started
                if progress is not None:progress({'table':name,'phase':'old_rows_verified','tables_done':len(changes)+1,'tables_total':len(tables),'seconds':seconds})
                changes[name] = {'old_rows': old_count, 'new_rows': new_count,
                                 'added_rows': new_count - old_count, 'identity': identity,
                                 'method': 'sqlite-page-bytes' if byte_identical else 'indexed-typed-row-join', 'seconds': seconds}
            if progress is not None:progress({'phase':'all_foreign_keys','tables_done':len(changes),'tables_total':len(tables)})
            fk_started = time.monotonic()
            inherited=_matching_fk_certificate(c,baseline_fk_certificate,before,schemas,expected)
            affected={name for name,n in expected.items()if n>0}if inherited else None
            fk_details={'method':'inherited-old-plus-changed-child-tables'if inherited else'full-scan',
                        'baseline_exact_pair_and_schema_bound':inherited,
                        'old_rows_typed_or_page_bytes_proved_before_fk':True}
            fk_count = _foreign_keys(c,affected,fk_details)
            fk_seconds = time.monotonic() - fk_started
        finally:
            c.close()
        final_hash_started = time.monotonic()
        if before != _snapshot(_pair(live), deadline) or staged != _snapshot(_pair(candidate), deadline):
            raise TransactionError('核对期间数据库发生变化')
        proof={'protocol': _PROTOCOL, 'ok': True, 'live': before, 'candidate': staged,
                'schema_sha256': schemas, 'tables': changes, 'local_foreign_keys_ok': True,
                'external_foreign_keys_checked': fk_count, 'external_foreign_keys_ok': True,
                'foreign_key_checks':fk_details,
                'page_byte_guards':page_guards,
                'timings': {'initial_pair_hashes': snapshot_seconds,
                            'page_byte_guard':page_seconds,
                            'old_rows_and_counts': sum(r['seconds'] for r in changes.values()),
                            'foreign_keys': fk_seconds, 'final_pair_hashes': time.monotonic()-final_hash_started,
                            'total': time.monotonic()-started}}
        proof['foreign_key_certificate']=foreign_key_certificate(proof)
        return proof
    except (TransactionError, TimeoutError):
        raise
    except Exception:
        # sqlite3 turns a progress-handler interruption into OperationalError.
        # Recover only the budget state, never echo SQLite's row/SQL diagnostic.
        if deadline is not None:_check(deadline)
        raise TransactionError('只增不改核对失败') from None


def _validations(validation):
    if not isinstance(validation, dict) or not validation or validation.get('ok', True) is not True:
        raise TransactionError('调用方全套检查未通过')
    checks = validation.get('checks', {k: v for k, v in validation.items() if k != 'ok'})
    if not isinstance(checks, dict) or not checks:
        raise TransactionError('缺少调用方逐项检查')
    for name, result in checks.items():
        if not isinstance(name, str) or not name or not (result is True or isinstance(result, dict) and result.get('ok') is True):
            raise TransactionError('调用方全套检查未通过')
    return sorted(checks)


@contextmanager
def _publish_lock(live, deadline):
    path = live.with_name('.' + live.name + '.publish.lock')
    with path.open('a+b') as lock:
        while True:
            _check(deadline)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_copy(source, target, expected_sha, deadline):
    # APFS clones retain identical bytes without writing a second 20GB copy.
    # Other filesystems fall back to bounded streaming; both paths hash/fsync.
    _check(deadline)
    if target.exists():raise TransactionError('发布临时文件已存在')
    cloned=False
    try:
        copied=subprocess.run(['cp','-c',str(source),str(target)],stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,timeout=2,check=False)
        cloned=copied.returncode==0 and target.is_file()
    except (OSError,subprocess.TimeoutExpired):pass
    _check(deadline)
    if not cloned:
        target.unlink(missing_ok=True)
        with source.open('rb') as src, target.open('xb') as dst:
            while True:
                _check(deadline)
                chunk = src.read(8 * 1024 * 1024)
                if not chunk:break
                dst.write(chunk)
            dst.flush();os.fsync(dst.fileno())
    else:
        with target.open('rb')as f:os.fsync(f.fileno())
    if _sha(target, deadline) != expected_sha:
        raise TransactionError('发布副本与已核候选不一致')


def publish_pair(live, candidate, expected_live_sha256, proof, validation, deadline):
    """Durably install a unique audit first; replace the query pointer last.

    Old audits are deliberately retained for readers which opened the old query
    before publication. No irreversible query replacement happens after expiry.
    """
    temporary = []
    try:
        started=time.monotonic()
        _check(deadline)
        checked = _validations(validation)
        if not isinstance(proof, dict) or proof.get('protocol') != _PROTOCOL or proof.get('ok') is not True:
            raise TransactionError('缺少候选只增不改证明')
        if proof.get('local_foreign_keys_ok') is not True or proof.get('external_foreign_keys_ok') is not True:
            raise TransactionError('候选外键核对未通过')
        lp, cp = _pair(live), _pair(candidate)
        if not isinstance(expected_live_sha256, str) or not _DIGEST.fullmatch(expected_live_sha256):
            raise TransactionError('正式库指纹不合规')
        if proof.get('live', {}).get('query_sha256') != expected_live_sha256:
            raise TransactionError('正式库基线与证明不一致')
        if _snapshot(cp, deadline) != proof.get('candidate'):
            raise TransactionError('候选在核对后发生变化')
        if cp[2] == lp[2] or cp[1].name != 'audit-' + cp[2] + '.sqlite':
            raise TransactionError('候选审计代号不合规')
        candidate_at=time.monotonic()
        with _publish_lock(lp[0], deadline):
            if _snapshot(_pair(live), deadline) != proof['live']:
                raise TransactionError('正式库已变化，拒绝覆盖')
            baseline_at=time.monotonic()
            audit_target = lp[0].parent / cp[1].name
            if audit_target.exists() and audit_target.resolve() != cp[1]:
                raise TransactionError('发布审计代号已存在')
            nonce = uuid.uuid4().hex
            if audit_target.resolve() == cp[1]:
                with audit_target.open('rb') as f:
                    os.fsync(f.fileno())
            else:
                audit_tmp = lp[0].parent / ('.' + audit_target.name + '.' + nonce + '.tmp')
                temporary.append(audit_tmp)
                _durable_copy(cp[1], audit_tmp, proof['candidate']['audit_sha256'], deadline)
                _check(deadline)
                os.replace(audit_tmp, audit_target)
            _fsync_dir(lp[0].parent)
            audit_at=time.monotonic()
            query_tmp = lp[0].parent / ('.' + lp[0].name + '.' + nonce + '.tmp')
            temporary.append(query_tmp)
            _durable_copy(cp[0], query_tmp, proof['candidate']['query_sha256'], deadline)
            query_at=time.monotonic()
            _check(deadline)
            # Cooperative writers hold the stable lock. Recheck immediately before
            # the commit point, after every callback and all long file copies.
            if _snapshot(_pair(live), deadline) != proof['live']:
                raise TransactionError('正式库已变化，拒绝覆盖')
            if _sha(audit_target, deadline) != proof['candidate']['audit_sha256']:
                raise TransactionError('已发布审计副本与证明不一致')
            # The deadline callback is a budget check, not an arbitrary writer.
            # No long hash/copy is allowed after this last pre-commit check.
            _check(deadline)
            os.replace(query_tmp, lp[0])
            _fsync_dir(lp[0].parent)
        return {'ok': True, 'generation': cp[2], 'query_sha256': proof['candidate']['query_sha256'],
                'audit_sha256': proof['candidate']['audit_sha256'], 'audit_file': audit_target.name,
                'old_audit_file_retained': lp[1].name, 'validation_checks': checked,
                'publication_order': ['audit_fsync', 'audit_directory_fsync', 'query_replace', 'query_directory_fsync'],
                'timings':{'candidate_recheck':candidate_at-started,'lock_and_live_recheck':baseline_at-candidate_at,
                           'audit_copy_fsync':audit_at-baseline_at,'query_copy_fsync':query_at-audit_at,
                           'last_recheck_and_atomic_commit':time.monotonic()-query_at,'total':time.monotonic()-started}}
    except (TransactionError, TimeoutError):
        raise
    except Exception:
        raise TransactionError('配对数据库发布失败') from None
    finally:
        for path in temporary:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

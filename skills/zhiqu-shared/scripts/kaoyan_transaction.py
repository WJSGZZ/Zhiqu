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
        _check(deadline)
        original = _pair(live)
        before = _snapshot(original, deadline)
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
                'live': before, 'copy_methods': methods, 'ok': True}
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


def _projection(c, owner, table):
    cols = c.execute('PRAGMA ' + ident(owner) + '.table_xinfo(' + ident(table) + ')').fetchall()
    # Hidden virtual-table fields are not persisted values. Generated columns are
    # included; their expression is independently protected by the schema check.
    names = [row[1] for row in cols if row[6] != 1]
    sql = c.execute('SELECT sql FROM ' + ident(owner) + '.sqlite_schema WHERE name=?', (table,)).fetchone()[0]
    without = bool(re.search(r'\bWITHOUT\s+ROWID\b', sql or '', re.I))
    rowid = next((n for n in ('rowid', '_rowid_', 'oid') if n not in names), None)
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


def _foreign_keys(c):
    for owner in ('data', 'audit'):
        if c.execute('PRAGMA ' + ident(owner) + '.foreign_key_check').fetchone() is not None:
            raise TransactionError('候选库本地外键核对失败')
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
        if c.execute(sql).fetchone() is not None:
            raise TransactionError('候选库跨库外键核对失败')
        n += 1
    return n


def verify_append_only(live, candidate, expected_delta, *, progress=None):
    """Prove unchanged old rowids/types/values, exact additions and every FK."""
    try:
        lp, cp = _pair(live), _pair(candidate)
        if lp[0] == cp[0] or lp[2] == cp[2]:
            raise TransactionError('候选必须使用独立的新代号')
        uuid.UUID(cp[2])
        before, staged = _snapshot(lp), _snapshot(cp)
        c = sqlite3.connect(':memory:', uri=True)
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
            paths = {'data': (lp[0], cp[0]), 'audit': (lp[1], cp[1])}
            for name, table in tables.items():
                owner = name.split('.', 1)[0]
                old_count = c.execute('SELECT count(*) FROM ' + ident('old_' + owner) + '.' + ident(table)).fetchone()[0]
                new_count = c.execute('SELECT count(*) FROM ' + ident(owner) + '.' + ident(table)).fetchone()[0]
                if new_count - old_count != expected[name]:
                    raise TransactionError('候选表增量与预期不符')
                projection, order, identity = _projection(c, 'old_' + owner, table)
                strategy = 'sql-except'
                same = False
                if new_count == old_count:
                    a = _sha3_projection(paths[owner][0], table, projection, order)
                    b = _sha3_projection(paths[owner][1], table, projection, order) if a is not None else None
                    same = a is not None and a == b
                    if same:
                        strategy = 'typed-rowid-sha3'
                if not same:
                    sql = ('SELECT ' + projection + ' FROM ' + ident('old_' + owner) + '.' + ident(table) +
                           ' EXCEPT SELECT ' + projection + ' FROM ' + ident(owner) + '.' + ident(table) + ' LIMIT 1')
                    if c.execute(sql).fetchone() is not None:
                        raise TransactionError('候选改动或删除了已有行')
                if progress is not None:progress({'table':name,'phase':'old_rows_verified','tables_done':len(changes)+1,'tables_total':len(tables)})
                changes[name] = {'old_rows': old_count, 'new_rows': new_count,
                                 'added_rows': new_count - old_count, 'identity': identity, 'method': strategy}
            if progress is not None:progress({'phase':'all_foreign_keys','tables_done':len(changes),'tables_total':len(tables)})
            fk_count = _foreign_keys(c)
        finally:
            c.close()
        if before != _snapshot(_pair(live)) or staged != _snapshot(_pair(candidate)):
            raise TransactionError('核对期间数据库发生变化')
        return {'protocol': _PROTOCOL, 'ok': True, 'live': before, 'candidate': staged,
                'schema_sha256': schemas, 'tables': changes, 'local_foreign_keys_ok': True,
                'external_foreign_keys_checked': fk_count, 'external_foreign_keys_ok': True}
    except (TransactionError, TimeoutError):
        raise
    except Exception:
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
        with _publish_lock(lp[0], deadline):
            if _snapshot(_pair(live), deadline) != proof['live']:
                raise TransactionError('正式库已变化，拒绝覆盖')
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
            query_tmp = lp[0].parent / ('.' + lp[0].name + '.' + nonce + '.tmp')
            temporary.append(query_tmp)
            _durable_copy(cp[0], query_tmp, proof['candidate']['query_sha256'], deadline)
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
                'publication_order': ['audit_fsync', 'audit_directory_fsync', 'query_replace', 'query_directory_fsync']}
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

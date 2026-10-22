"""Read-only federation of the query store and its generation-bound audit store.

SQLite persistent views cannot reference another database. Owned view definitions
are therefore installed as TEMP views; source text and record values never become
SQL. Existing ``data.name`` callers keep the same logical schema.
"""
from pathlib import Path
import re
import sqlite3

_TOKEN = re.compile(r"(--[^\n]*(?:\n|$)|/\*[\s\S]*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|[A-Za-z_][A-Za-z_0-9]*|\s+|.)")
_NAME = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')


def ident(name):
    if not _NAME.fullmatch(name):
        raise ValueError('Invalid storage identifier')
    return '"' + name + '"'


def word(token):
    if token.startswith(('"', '`', '[')):
        return token[1:-1].replace(token[0] * 2, token[0])
    return token


def tokens(sql):
    return _TOKEN.findall(sql)


def meaningful(parts):
    return [i for i, p in enumerate(parts) if not p.isspace() and not p.startswith(('--', '/*'))]


def qualify_select(sql, tables, views, moved, overlays=()):
    """Route explicit old schemas; SQLite resolves unqualified names and CTE scope.

    TEMP views can read both attached stores. Qualifying an unqualified name
    ourselves would incorrectly bypass a WITH clause that shadows a table.
    """
    parts = tokens(sql)
    indexes = meaningful(parts)
    for position, index in enumerate(indexes[:-1]):
        if parts[index].upper() not in ('FROM', 'JOIN'):
            continue
        target = indexes[position + 1]
        if position + 3 >= len(indexes) or parts[indexes[position + 2]] != '.':
            continue
        prefix = word(parts[target])
        name = word(parts[indexes[position + 3]])
        if prefix not in ('main', 'data') or (name not in tables and name not in views):
            continue
        owner = 'temp' if name in views or name in overlays else 'audit' if name in moved else 'data'
        parts[target] = ident(owner)
    return ''.join(parts)


def select_body(definition):
    parts = tokens(definition)
    for i in meaningful(parts):
        if parts[i].upper() == 'AS':
            return ''.join(parts[i + 1:]).strip().rstrip(';')
    raise ValueError('View definition missing SELECT body')


class StorageConnection(sqlite3.Connection):
    """Route only owned, qualified logical table names, never record text."""
    routes = None

    def execute(self, sql, parameters=(), /):
        routes = self.routes or {}
        if routes:
            parts = tokens(sql)
            indexes = meaningful(parts)
            for pos, index in enumerate(indexes[:-2]):
                if word(parts[index]) != 'data' or parts[indexes[pos + 1]] != '.':
                    continue
                target = indexes[pos + 2]
                name = word(parts[target])
                if name in routes:
                    parts[index] = ident(routes[name])
                elif name == 'table_info' and pos + 4 < len(indexes):
                    token = parts[indexes[pos + 4]]
                    argument = token[1:-1].replace("''", "'") if token.startswith("'") else word(token)
                    if argument in routes:
                        parts[index] = ident(routes[argument])
            sql = ''.join(parts)
        return super().execute(sql, parameters)


def install_audit(connection, query_path):
    """Attach the paired immutable generation; absent manifest means old layout."""
    exists = connection.execute("SELECT 1 FROM data.sqlite_master WHERE type='table' AND name='storage_manifest'").fetchone()
    if not exists:
        return set()
    config = dict(connection.execute('SELECT key,value FROM data.storage_manifest'))
    filename = config['audit_file']
    if not re.fullmatch(r'audit-[a-z0-9-]+\.sqlite', filename):
        raise ValueError('Invalid audit generation filename')
    query_path = Path(query_path).resolve()
    audit_path = query_path.parent / filename
    if not audit_path.is_file() or audit_path.resolve().parent != query_path.parent:
        raise ValueError('Paired audit database is unavailable')
    connection.execute('ATTACH DATABASE ? AS audit', (audit_path.as_uri() + '?mode=ro',))
    generation = connection.execute("SELECT value FROM audit.storage_manifest WHERE key='generation'").fetchone()
    if not generation or generation[0] != config['generation']:
        raise ValueError('Query/audit generation mismatch')
    objects = [dict(zip(('name', 'kind', 'definition'), row)) for row in
               connection.execute('SELECT name,kind,definition FROM data.storage_object')]
    tables = {o['name'] for o in objects if o['kind'] == 'table'}
    views = {o['name'] for o in objects if o['kind'] == 'view'}
    moved = {row[0] for row in connection.execute('SELECT name FROM data.storage_moved')}
    if not moved <= tables:
        raise ValueError('Invalid moved table registry')
    overlays = {'core_delta_context'} if config.get('context_hash_split') == '1' else set()
    if overlays:
        fields = [row[1] for row in connection.execute('PRAGMA audit.table_info(core_context_identity)')]
        if fields != ['context_id', 'context_hash']:
            raise ValueError('Invalid context identity schema')
        original = next(o for o in objects if o['name'] == 'core_delta_context' and o['kind'] == 'table')
        # The original order is persisted explicitly, never inferred from cell values.
        import json
        columns = json.loads(config['context_columns'])
        select = ','.join(('h.' if col == 'context_hash' else 'c.') + ident(col) for col in columns)
        connection.execute('CREATE TEMP VIEW core_delta_context AS SELECT ' + select +
                           ' FROM data.core_delta_context c LEFT JOIN audit.core_context_identity h USING(context_id)')
    for obj in objects:
        if obj['kind'] == 'view':
            body = qualify_select(select_body(obj['definition']), tables, views, moved, overlays)
            connection.execute('CREATE TEMP VIEW ' + ident(obj['name']) + ' AS ' + body)
    connection.routes = {**{n: 'audit' for n in moved},
                         **{n: 'temp' for n in views | overlays}}
    connection.storage_logical_names = tables | views
    return tables | views


def logical_names(connection):
    return getattr(connection, 'storage_logical_names', set())

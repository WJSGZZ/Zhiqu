"""Generation-bound query/audit federation fixtures, with no real DB dependency."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
spec=importlib.util.spec_from_file_location('storage_fixture',SCRIPTS/'db_storage.py');storage=importlib.util.module_from_spec(spec);spec.loader.exec_module(storage)
spec=importlib.util.spec_from_file_location('storage_query_fixture',SCRIPTS/'zhiqu_db.py');query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)


class StorageFederation(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.query=self.root/'education.sqlite';self.audit=self.root/'audit-test-g1.sqlite'
 def make(self,views=(),overlay=False,manifest=True,generation='g1',audit_file='audit-test-g1.sqlite'):
  with sqlite3.connect(self.query) as c:
   c.executescript('create table base_t(id integer primary key,val,marker text);insert into base_t values(1,1,"one"),(2,NULL,"two");')
   if not manifest:return
   c.executescript('create table storage_manifest(key text primary key,value text);create table storage_object(name text primary key,kind text,definition text);create table storage_moved(name text primary key);')
   config={'generation':'g1','audit_file':audit_file}
   if overlay:
    config.update(context_hash_split='1',context_columns=json.dumps(['context_id','context_hash','year','label']))
    c.execute('create table core_delta_context(context_id integer primary key,year integer,label text)');c.execute('insert into core_delta_context values(1,2025,"scope")')
    c.execute('insert into storage_object values(?,?,?)',('core_delta_context','table','CREATE TABLE core_delta_context(context_id integer primary key,context_hash blob,year integer,label text)'))
   c.executemany('insert into storage_manifest values(?,?)',config.items())
   c.executemany('insert into storage_object values(?,?,?)',[('base_t','table','CREATE TABLE base_t(id integer primary key,val,marker text)'),('moved_t','table','CREATE TABLE moved_t(id integer primary key,val,payload blob)')])
   c.execute("insert into storage_moved values('moved_t')")
   c.executemany('insert into storage_object values(?,?,?)',[(name,'view',sql) for name,sql in views])
  with sqlite3.connect(self.audit) as c:
   c.executescript('create table storage_manifest(key text,value text);create table moved_t(id integer primary key,val,payload blob);')
   c.execute('insert into storage_manifest values(?,?)',('generation',generation));c.executemany('insert into moved_t values(?,?,?)',[(1,'1',b'\x00\xff'),(2,None,None)])
   if overlay:
    c.execute('create table core_context_identity(context_id integer primary key,context_hash blob)');c.execute('insert into core_context_identity values(1,?)',(b'original-hash',))
 def open(self):return query._open('education',db=self.query)
 def test_legacy_layout_no_manifest_unaffected(self):
  self.make(manifest=False)
  with self.open() as (c,_):
   self.assertEqual([tuple(r) for r in c.execute('select * from data.base_t order by id')],[(1,1,'one'),(2,None,'two')])
   self.assertFalse(storage.logical_names(c));self.assertIn('base_t',query._tables(c))
   self.assertEqual(c.execute('pragma query_only').fetchone()[0],1)
 def test_cross_database_view_keeps_null_storage_types_and_blob(self):
  self.make(views=[('joined','CREATE VIEW joined AS SELECT b.id,b.val AS n,m.val AS t,m.payload FROM base_t b LEFT JOIN moved_t m USING(id)')])
  with self.open() as (c,_):
   rows=[tuple(r) for r in c.execute('select id,n,t,payload,typeof(n),typeof(t) from data.joined order by id')]
   self.assertEqual(rows,[(1,1,'1',b'\x00\xff','integer','text'),(2,None,None,None,'null','null')])
 def test_table_info_routes_to_audit_and_temp(self):
  self.make(views=[('v','CREATE VIEW v AS SELECT id,val FROM moved_t')])
  with self.open() as (c,_):
   self.assertEqual([r[1] for r in c.execute('pragma data.table_info("moved_t")')],['id','val','payload'])
   self.assertEqual([r[1] for r in c.execute('pragma data.table_info("v")')],['id','val'])
   self.assertEqual(query._cols(c,'moved_t'),{'id','val','payload'});self.assertTrue({'v','moved_t'}<=query._tables(c))

 def test_table_info_string_literal_argument_routes_like_identifier(self):
  self.make()
  with self.open() as (c,_):self.assertEqual([r[1] for r in c.execute("pragma data.table_info('moved_t')")],['id','val','payload'])
 def test_string_literals_and_comments_not_rewritten(self):
  self.make(views=[('v',"CREATE VIEW v AS SELECT 'FROM moved_t; data.moved_t' AS text FROM moved_t /* FROM base_t */")])
  with self.open() as (c,_):
   self.assertEqual(c.execute("select 'data.moved_t' from data.base_t limit 1").fetchone()[0],'data.moved_t')
   self.assertEqual(c.execute('select text from data.v limit 1').fetchone()[0],'FROM moved_t; data.moved_t')
 def test_nested_views_quoted_ids_and_noncolliding_cte(self):
  self.make(views=[('inner_v','CREATE VIEW "inner_v" AS SELECT id,val FROM "moved_t"'),('outer_v','CREATE VIEW outer_v AS WITH chosen AS (SELECT * FROM "inner_v") SELECT id,val FROM chosen WHERE id=1')])
  with self.open() as (c,_):self.assertEqual(tuple(c.execute('select * from data."outer_v"').fetchone()),(1,'1'))
 def test_cte_shadowing_original_table_preserves_sql_semantics(self):
  self.make(views=[('shadowed','CREATE VIEW shadowed AS WITH moved_t AS (SELECT 999 AS val) SELECT val FROM moved_t')])
  with self.open() as (c,_):self.assertEqual([r[0] for r in c.execute('select val from data.shadowed')],[999])
 def test_qualified_logical_table_in_original_view_definition(self):
  self.make(views=[('qualified','CREATE VIEW qualified AS SELECT id,val FROM "data"."moved_t"')])
  with self.open() as (c,_):self.assertEqual(tuple(c.execute('select * from data.qualified where id=1').fetchone()),(1,'1'))
 def test_context_hash_overlay_restores_original_column_order(self):
  self.make(overlay=True,views=[('context_v','CREATE VIEW context_v AS SELECT * FROM core_delta_context')])
  with self.open() as (c,_):
   rows=c.execute('select * from data.core_delta_context');self.assertEqual([r[0] for r in rows.description],['context_id','context_hash','year','label']);self.assertEqual(tuple(rows.fetchone()),(1,b'original-hash',2025,'scope'))
   self.assertEqual(tuple(c.execute('select * from data.context_v').fetchone()),(1,b'original-hash',2025,'scope'))
 def test_generation_mismatch_refused(self):
  self.make(generation='g-other')
  with self.assertRaisesRegex(ValueError,'generation mismatch'):
   with self.open():pass
 def test_missing_paired_audit_refused(self):
  self.make();self.audit.unlink()
  with self.assertRaisesRegex(ValueError,'unavailable'):
   with self.open():pass
 def test_readonly_query_and_audit_files_unchanged(self):
  self.make();before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.query,self.audit)}
  with self.open() as (c,_):
   self.assertEqual(c.execute('pragma query_only').fetchone()[0],1)
   for sql in ('update data.base_t set val=9','update data.moved_t set val=9','update audit.moved_t set val=9','create table data.injected(x)'):
    with self.assertRaises(sqlite3.OperationalError):c.execute(sql)
  self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.query,self.audit)})
 def test_path_traversal_generation_filename_refused(self):
  self.make(audit_file='../audit-test-g1.sqlite')
  with self.assertRaisesRegex(ValueError,'filename'):
   with self.open():pass
 def test_symlink_outside_query_folder_refused(self):
  self.make();outside=self.root/'outside';outside.mkdir();other=outside/self.audit.name;self.audit.rename(other);self.audit.symlink_to(other)
  with self.assertRaisesRegex(ValueError,'unavailable'):
   with self.open():pass

if __name__=='__main__':unittest.main()

"""Small offline pairs only: no production database, network or personal records."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('kaoyan_transaction_fixture', SCRIPTS / 'kaoyan_transaction.py')
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def change(path, sql, values=()):
    with closing(sqlite3.connect(path)) as c, c:
        c.execute(sql, values)


class PairTransaction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / 'live' / 'education.sqlite'
        self.live.parent.mkdir()
        self.audit = self.live.parent / 'audit-g1.sqlite'
        self.candidate = self.root / 'stage' / 'education.sqlite'
        with closing(sqlite3.connect(self.live)) as c, c:
            c.executescript('''
                CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE storage_external_fk(owner TEXT,table_name TEXT,from_columns TEXT,
                  parent_owner TEXT,parent_table TEXT,to_columns TEXT,id INTEGER,
                  on_update TEXT,on_delete TEXT,match TEXT,PRIMARY KEY(owner,table_name,id));
                CREATE TABLE base(id INTEGER PRIMARY KEY,val,label TEXT COLLATE NOCASE);
                CREATE TABLE keyed(k TEXT PRIMARY KEY,val) WITHOUT ROWID;
                CREATE TABLE query_child(id INTEGER PRIMARY KEY,base_id INTEGER REFERENCES base(id));
                INSERT INTO query_child VALUES(1,1);
                CREATE INDEX base_label ON base(label);
                CREATE VIEW base_view AS SELECT id,val FROM base;
                INSERT INTO base VALUES(1,1,'Alpha'),(2,x'00ff','Beta');
                INSERT INTO keyed VALUES('key',7);
            ''')
            c.executemany('INSERT INTO storage_manifest VALUES(?,?)',
                          [('generation', 'g1'), ('audit_file', self.audit.name), ('domain', 'education')])
            c.execute('INSERT INTO storage_external_fk VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('audit', 'evidence', '["base_id"]', 'data', 'base', '["id"]', 0,
                       'NO ACTION', 'NO ACTION', 'NONE'))
        with closing(sqlite3.connect(self.audit)) as c, c:
            c.executescript('''
                CREATE TABLE storage_manifest(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO storage_manifest VALUES('generation','g1');
                CREATE TABLE evidence(id INTEGER PRIMARY KEY,base_id INTEGER,note TEXT);
                INSERT INTO evidence VALUES(1,1,'synthetic');
                CREATE TABLE local_parent(id INTEGER PRIMARY KEY);
                CREATE TABLE local_child(id INTEGER PRIMARY KEY,parent_id INTEGER REFERENCES local_parent(id));
                INSERT INTO local_parent VALUES(1);
                INSERT INTO local_child VALUES(1,1);
            ''')
        self.before = (digest(self.live), digest(self.audit))
        # The streaming indexed proof must not depend on an optional extension.
        self.sha3 = patch.object(tx, '_sha3_shell', return_value=None)
        self.sha3.start()
        self.addCleanup(self.sha3.stop)

    def clone(self):
        result = tx.clone_pair(self.live, self.candidate, lambda: True)
        self.ca = Path(result['audit'])
        return result

    def append(self):
        self.clone()
        change(self.candidate, "INSERT INTO base VALUES(3,330,'Gamma')")
        change(self.ca, "INSERT INTO evidence VALUES(2,3,'synthetic-new')")
        return tx.verify_append_only(self.live, self.candidate, {'data.base': 1, 'audit.evidence': 1})

    def assertLiveUnchanged(self):
        self.assertEqual(self.before, (digest(self.live), digest(self.audit)))

    def baseline_certificate(self):
        """A real fully checked/published tiny pair, never a hand-written flag."""
        self.clone()
        proof=tx.verify_append_only(self.live,self.candidate,{})
        tx.publish_pair(self.live,self.candidate,proof['live']['query_sha256'],proof,{'fixture':True},lambda:True)
        self.audit=tx._pair(self.live)[1]
        self.before=(digest(self.live),digest(self.audit))
        self.candidate=self.root/'stage-second'/'education.sqlite'
        return proof['foreign_key_certificate']

    def test_clone_falls_back_to_backup_and_only_manifest_values_change(self):
        with patch.object(tx.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            result = self.clone()
        self.assertEqual(result['copy_methods'], ['sqlite-backup', 'sqlite-backup'])
        self.assertNotEqual(result['generation'], 'g1')
        proof = tx.verify_append_only(self.live, self.candidate, {})
        self.assertTrue(proof['ok'])
        self.assertEqual(proof['external_foreign_keys_checked'], 1)
        self.assertEqual(proof['tables']['data.keyed']['identity'], 'primary_key')
        self.assertTrue(all(r['method'] in {'sqlite-page-bytes','indexed-typed-row-join'} for r in proof['tables'].values()))
        self.assertLiveUnchanged()

    def test_clone_rejects_existing_target_without_deleting_it(self):
        self.candidate.parent.mkdir()
        self.candidate.write_bytes(b'synthetic-existing-file')
        with self.assertRaises(tx.TransactionError):
            tx.clone_pair(self.live, self.candidate, lambda: True)
        self.assertEqual(self.candidate.read_bytes(), b'synthetic-existing-file')
        self.assertLiveUnchanged()

    def test_old_value_change_is_refused_without_echoing_values(self):
        self.clone()
        change(self.candidate, 'UPDATE base SET val=? WHERE id=1', ('SYNTHETIC_PRIVATE_MARKER',))
        with self.assertRaises(tx.TransactionError) as caught:
            tx.verify_append_only(self.live, self.candidate, {})
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(caught.exception))
        self.assertNotIn('Alpha', str(caught.exception))
        self.assertLiveUnchanged()

    def test_old_storage_type_change_is_refused(self):
        self.clone()
        change(self.candidate, "UPDATE base SET val='1' WHERE id=1")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_nocase_collation_does_not_hide_case_change(self):
        self.clone()
        change(self.candidate, "UPDATE base SET label='alpha' WHERE id=1")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_rowid_reassignment_is_refused(self):
        self.clone()
        change(self.candidate, 'UPDATE base SET id=99 WHERE id=1')
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_without_rowid_value_change_is_refused(self):
        self.clone()
        change(self.candidate, 'UPDATE keyed SET val=8')
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_composite_without_rowid_key_is_exact_even_under_nocase(self):
        ddl='CREATE TABLE composite(a TEXT COLLATE NOCASE,b INTEGER,val,PRIMARY KEY(a,b)) WITHOUT ROWID'
        change(self.live,ddl)
        change(self.live,"INSERT INTO composite VALUES('Upper',1,x'00ff')")
        self.clone()
        self.assertTrue(tx.verify_append_only(self.live,self.candidate,{})['ok'])
        change(self.candidate,"UPDATE composite SET a='upper'")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_deletion_and_replacement_with_same_count_is_refused(self):
        self.clone()
        change(self.candidate,"DELETE FROM base WHERE id=1")
        change(self.candidate,"INSERT INTO base VALUES(3,1,'Alpha')")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_null_empty_text_and_empty_blob_are_not_interchangeable(self):
        for old,new in [(None,''),('',b''),(b'',None),(0,0.0)]:
            with self.subTest(old_type=type(old).__name__,new_type=type(new).__name__):
                change(self.live,'UPDATE base SET val=? WHERE id=1',(old,))
                target=self.root/('types-'+type(old).__name__+'-'+type(new).__name__)/'education.sqlite'
                tx.clone_pair(self.live,target,lambda:True)
                change(target,'UPDATE base SET val=? WHERE id=1',(new,))
                with self.assertRaises(tx.TransactionError):
                    tx.verify_append_only(self.live,target,{})

    def test_indexed_path_does_not_call_legacy_full_table_digest(self):
        self.clone()
        with patch.object(tx,'_sha3_projection',side_effect=AssertionError('no legacy retry')):
            p=tx.verify_append_only(self.live,self.candidate,{})
        self.assertIn('old_rows_and_counts',p['timings'])

    def test_verified_deadline_is_checked_during_sql_scan(self):
        self.clone()
        with self.assertRaises(TimeoutError):
            tx.verify_append_only(self.live,self.candidate,{},deadline=lambda:False)

    def test_manifest_other_key_and_manifest_rowid_changes_are_refused(self):
        self.clone()
        change(self.candidate, "UPDATE storage_manifest SET value='other' WHERE key='domain'")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})
        change(self.candidate, "UPDATE storage_manifest SET value='education' WHERE key='domain'")
        with closing(sqlite3.connect(self.candidate)) as c, c:
            generation = c.execute("SELECT value FROM storage_manifest WHERE key='generation'").fetchone()[0]
            c.execute("DELETE FROM storage_manifest WHERE key='generation'")
            c.execute('INSERT INTO storage_manifest VALUES(?,?)', ('generation', generation))
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_null_manifest_key_is_not_a_mutable_generation_key(self):
        change(self.live,'INSERT INTO storage_manifest VALUES(NULL,?)',('synthetic-old',))
        self.clone()
        change(self.candidate,"UPDATE storage_manifest SET value='synthetic-changed' WHERE key IS NULL")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_ddl_index_or_view_change_is_refused(self):
        self.clone()
        change(self.candidate, 'DROP INDEX base_label')
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_unexpected_increment_or_unknown_table_is_refused(self):
        self.clone()
        change(self.candidate, "INSERT INTO base VALUES(3,1,'new')")
        for delta in ({}, {'data.base': 2}, {'data.no_such_table': 1}, {'data.base': True}):
            with self.subTest(delta=delta), self.assertRaises(tx.TransactionError):
                tx.verify_append_only(self.live, self.candidate, delta)
        self.assertTrue(tx.verify_append_only(self.live, self.candidate, {'data': {'base': 1}})['ok'])

    def test_every_local_foreign_key_is_checked(self):
        self.clone()
        change(self.ca, 'INSERT INTO local_child VALUES(2,999)')
        with self.assertRaisesRegex(tx.TransactionError, '本地外键'):
            tx.verify_append_only(self.live, self.candidate, {'audit.local_child': 1})

    def test_query_database_local_foreign_key_is_checked_too(self):
        self.clone()
        change(self.candidate, 'INSERT INTO query_child VALUES(2,999)')
        with self.assertRaisesRegex(tx.TransactionError, '本地外键'):
            tx.verify_append_only(self.live, self.candidate, {'data.query_child': 1})

    def test_sqlite_backup_progress_itself_checks_deadline(self):
        calls = [0]
        def deadline():
            calls[0] += 1
            return calls[0] < 2
        destination = self.root / 'progress-only.sqlite'
        with self.assertRaises(TimeoutError):
            tx._backup(self.live, destination, deadline)
        self.assertEqual(calls[0], 2)  # first precheck, then real SQLite progress callback
        self.assertLiveUnchanged()

    def test_every_cross_store_foreign_key_is_checked(self):
        self.clone()
        change(self.ca, "INSERT INTO evidence VALUES(2,999,'synthetic')")
        with self.assertRaisesRegex(tx.TransactionError, '跨库外键'):
            tx.verify_append_only(self.live, self.candidate, {'audit.evidence': 1})

    def test_nullable_cross_store_fk_keeps_sqlite_null_semantics(self):
        self.clone()
        change(self.ca, "INSERT INTO evidence VALUES(2,NULL,'synthetic')")
        self.assertTrue(tx.verify_append_only(self.live, self.candidate, {'audit.evidence': 1})['ok'])

    def test_expired_clone_deadline_is_refused(self):
        with self.assertRaises(TimeoutError):
            tx.clone_pair(self.live, self.candidate, lambda: False)
        self.assertFalse(self.candidate.exists())
        self.assertLiveUnchanged()

    def test_backup_progress_checks_deadline_and_cleans_only_new_artifacts(self):
        calls = []
        def deadline():
            calls.append(1)
            return len(calls) < 8
        with patch.object(tx.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(TimeoutError):
                tx.clone_pair(self.live, self.candidate, deadline)
        self.assertFalse(self.candidate.exists())
        self.assertEqual(list(self.candidate.parent.glob('*.sqlite')), [])
        self.assertLiveUnchanged()

    def test_deadline_exception_is_sanitized(self):
        def deadline():
            raise ValueError('SYNTHETIC_PRIVATE_MARKER')
        with self.assertRaises(TimeoutError) as caught:
            tx.clone_pair(self.live, self.candidate, deadline)
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', str(caught.exception))

    def test_live_change_after_proof_blocks_publication(self):
        proof = self.append()
        change(self.live, "UPDATE base SET label='changed' WHERE id=1")
        new_sha = digest(self.live)
        with self.assertRaises(tx.TransactionError):
            tx.publish_pair(self.live, self.candidate, self.before[0], proof, {'suite': True}, lambda: True)
        self.assertEqual(digest(self.live), new_sha)
        self.assertTrue(self.audit.exists())

    def test_live_audit_change_also_blocks_publication(self):
        proof = self.append()
        change(self.audit, "UPDATE evidence SET note='changed' WHERE id=1")
        with self.assertRaises(tx.TransactionError):
            tx.publish_pair(self.live, self.candidate, self.before[0], proof, {'suite': True}, lambda: True)
        self.assertEqual(digest(self.live), self.before[0])

    def test_candidate_change_after_proof_blocks_publication(self):
        proof = self.append()
        change(self.candidate, "INSERT INTO base VALUES(4,4,'later')")
        with self.assertRaises(tx.TransactionError):
            tx.publish_pair(self.live, self.candidate, self.before[0], proof, {'suite': True}, lambda: True)
        self.assertLiveUnchanged()

    def test_missing_or_failed_individual_validation_is_refused(self):
        proof = self.append()
        for validation in ({}, {'ok': True}, {'suite': False}, {'ok': True, 'checks': {'suite': {'ok': False}}}):
            with self.subTest(validation=validation), self.assertRaises(tx.TransactionError):
                tx.publish_pair(self.live, self.candidate, self.before[0], proof, validation, lambda: True)
        self.assertLiveUnchanged()

    def test_publish_deadline_expiry_keeps_live_pair(self):
        proof = self.append()
        with self.assertRaises(TimeoutError):
            tx.publish_pair(self.live, self.candidate, self.before[0], proof, {'suite': True}, lambda: False)
        self.assertLiveUnchanged()

    def test_atomic_order_and_old_and_new_readers_have_complete_pairs(self):
        proof = self.append()
        old_reader = sqlite3.connect(self.live.as_uri() + '?mode=ro', uri=True)
        self.addCleanup(old_reader.close)
        old_reader.execute('BEGIN')
        self.assertEqual(old_reader.execute('SELECT count(*) FROM base').fetchone()[0], 2)
        events = []
        original_replace = tx.os.replace
        original_copy = tx._durable_copy
        original_fsync_dir = tx._fsync_dir
        def copying(source, target, expected, deadline):
            original_copy(source, target, expected, deadline)
            events.append('audit_fsynced' if source == self.ca else 'query_fsynced')
        def replacing(source, target):
            original_replace(source, target)
            events.append('query_replaced' if target == self.live.resolve() else 'audit_installed')
            # An opener at either observable rename sees a matching complete pair.
            q, a, generation = tx._pair(self.live)
            self.assertTrue(a.is_file())
            self.assertIn(generation, ('g1', proof['candidate']['generation']))
        def syncing(directory):
            original_fsync_dir(directory)
            events.append('directory_fsynced')
        with patch.object(tx, '_durable_copy', side_effect=copying), patch.object(tx.os, 'replace', side_effect=replacing), patch.object(tx, '_fsync_dir', side_effect=syncing):
            result = tx.publish_pair(self.live, self.candidate, self.before[0], proof,
                                     {'ok': True, 'checks': {'unittest': {'ok': True}, 'regression': True}}, lambda: True)
        self.assertTrue(result['ok'])
        self.assertLess(events.index('audit_fsynced'), events.index('audit_installed'))
        self.assertLess(events.index('audit_installed'), events.index('directory_fsynced'))
        self.assertLess(events.index('directory_fsynced'), events.index('query_replaced'))
        self.assertLess(events.index('query_fsynced'), events.index('query_replaced'))
        self.assertEqual(old_reader.execute('SELECT count(*) FROM base').fetchone()[0], 2)
        self.assertTrue(self.audit.exists())
        with closing(sqlite3.connect(self.live)) as new_reader:
            self.assertEqual(new_reader.execute('SELECT count(*) FROM base').fetchone()[0], 3)
        self.assertEqual(tx._pair(self.live)[2], proof['candidate']['generation'])

    def test_deadline_after_audit_install_never_replaces_query(self):
        proof = self.append()
        expired = [False]
        original_replace = tx.os.replace
        def replace(source, target):
            original_replace(source, target)
            if target != self.live.resolve():
                expired[0] = True
        with patch.object(tx.os, 'replace', side_effect=replace), self.assertRaises(TimeoutError):
            tx.publish_pair(self.live, self.candidate, self.before[0], proof, {'suite': True}, lambda: not expired[0])
        self.assertLiveUnchanged()
        self.assertEqual(tx._pair(self.live)[2], 'g1')


    def test_indexed_sqlite_optimization_is_typed_and_rowid_bound(self):
        self.clone()
        with patch.object(tx,'_byte_unchanged_tables',return_value=(set(),{'available':False})):
            proof = tx.verify_append_only(self.live, self.candidate, {})
        self.assertEqual(proof['tables']['data.base']['method'], 'indexed-typed-row-join')
        change(self.candidate, "UPDATE base SET val='1' WHERE id=1")
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live, self.candidate, {})

    def test_page_shortcut_proves_unchanged_table_and_keeps_changed_manifest_in_sql(self):
        self.clone()
        proof=tx.verify_append_only(self.live,self.candidate,{})
        if not proof['page_byte_guards']['data']['available']:
            self.skipTest('SQLite dbstat unavailable; typed SQL fallback already tested')
        self.assertEqual(proof['tables']['data.base']['method'],'sqlite-page-bytes')
        self.assertEqual(proof['tables']['data.storage_manifest']['method'],'indexed-typed-row-join')

    def test_changed_overflow_payload_is_not_hidden_by_unchanged_root_page(self):
        blob=b'A'*30000
        change(self.live,'UPDATE base SET val=? WHERE id=1',(blob,))
        self.clone()
        new=blob[:18000]+b'B'+blob[18001:]
        change(self.candidate,'UPDATE base SET val=? WHERE id=1',(new,))
        with closing(sqlite3.connect(self.live))as c:
            page=c.execute("select rootpage from sqlite_schema where name='base'").fetchone()[0]
            size=c.execute('pragma page_size').fetchone()[0]
        # This mutation specifically exercises overflow attribution, not merely
        # a changed record on the root/leaf page.
        with self.live.open('rb')as a,self.candidate.open('rb')as b:
            a.seek((page-1)*size);b.seek((page-1)*size)
            self.assertEqual(a.read(size),b.read(size))
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_same_schema_sql_but_swapped_roots_cannot_use_page_shortcut(self):
        change(self.live,'CREATE TABLE other(id INTEGER PRIMARY KEY,val,label TEXT COLLATE NOCASE)')
        change(self.live,"INSERT INTO other VALUES(1,999,'Different')")
        change(self.live,"INSERT INTO other VALUES(2,998,'Different2')")
        self.clone()
        with closing(sqlite3.connect(self.candidate))as c,c:
            roots=dict(c.execute("select name,rootpage from sqlite_schema where name in ('base','other')"))
            c.execute('PRAGMA writable_schema=ON')
            c.execute("update sqlite_schema set rootpage=? where name='base'",(roots['other'],))
            c.execute("update sqlite_schema set rootpage=? where name='other'",(roots['base'],))
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_reused_freelist_pages_are_attributed_to_the_new_owning_table(self):
        change(self.live,'CREATE TABLE filler(payload BLOB)')
        change(self.live,'INSERT INTO filler VALUES(?)',(b'F'*100000,))
        change(self.live,'DROP TABLE filler')
        self.clone()
        change(self.candidate,"INSERT INTO base VALUES(3,?,'new')",(b'N'*30000,))
        proof=tx.verify_append_only(self.live,self.candidate,{'data.base':1})
        self.assertEqual(proof['tables']['data.base']['new_rows'],3)
        self.assertEqual(proof['tables']['data.base']['method'],'indexed-typed-row-join')

    def test_page_format_encoding_or_rewrite_limit_falls_back(self):
        self.clone()
        changed=tx._changed_sqlite_pages(self.live,self.candidate,limit=0)
        self.assertIsNone(changed)
        copy=self.root/'encoding.sqlite';copy.write_bytes(self.live.read_bytes())
        with copy.open('r+b')as f:f.seek(56);f.write((2).to_bytes(4,'big'))
        self.assertIsNone(tx._changed_sqlite_pages(self.live,copy))
        change(self.candidate,'UPDATE base SET val=999 WHERE id=1')
        with patch.object(tx,'_changed_sqlite_pages',return_value=None),self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_reserved_bytes_and_page_size_changes_cannot_use_shortcut(self):
        for offset,value in [(20,b'\x01'),(16,(8192).to_bytes(2,'big'))]:
            target=self.root/('header-'+str(offset)+'.sqlite');target.write_bytes(self.live.read_bytes())
            with target.open('r+b')as f:f.seek(offset);f.write(value)
            self.assertIsNone(tx._changed_sqlite_pages(self.live,target))

    def test_dbstat_shell_missing_or_failed_never_claims_page_ownership(self):
        with patch.object(tx.shutil,'which',return_value=None):
            self.assertIsNone(tx._dbstat_page_owners(self.live,'1',None))
        failed=subprocess.Popen([sys.executable,'-c','import sys;sys.exit(1)'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        with patch.object(tx.subprocess,'Popen',return_value=failed):
            self.assertIsNone(tx._dbstat_page_owners(self.live,'1',None))

    def test_deadline_interruption_inside_sql_is_reported_as_timeout(self):
        with closing(sqlite3.connect(self.live))as c,c:
            c.executemany('INSERT INTO base VALUES(?,?,?)',((i,i,'synthetic')for i in range(10,50010)))
        self.clone();calls=[0]
        def deadline():calls[0]+=1;return calls[0]<20
        with patch.object(tx,'_byte_unchanged_tables',return_value=(set(),{'available':False})),self.assertRaises(TimeoutError):
            tx.verify_append_only(self.live,self.candidate,{},deadline=deadline)
        # SQLite reports an interruption; the outer handler rechecks/sanitizes
        # the expired callback once more rather than exposing its SQL error.
        self.assertGreaterEqual(calls[0],20)

    def test_page_scan_checks_its_own_deadline(self):
        self.clone()
        with self.assertRaises(TimeoutError):
            tx._changed_sqlite_pages(self.live,self.candidate,deadline=lambda:False)

    def test_generated_columns_keep_the_sql_evaluation_proof(self):
        change(self.live,'CREATE TABLE generated(id INTEGER PRIMARY KEY,a INTEGER,b INTEGER GENERATED ALWAYS AS(a+1) VIRTUAL)')
        change(self.live,'INSERT INTO generated(id,a) VALUES(1,7)')
        self.clone()
        proof=tx.verify_append_only(self.live,self.candidate,{})
        self.assertEqual(proof['tables']['data.generated']['method'],'indexed-typed-row-join')
        change(self.candidate,'UPDATE generated SET a=8 WHERE id=1')
        with self.assertRaises(tx.TransactionError):tx.verify_append_only(self.live,self.candidate,{})

    def test_trigger_name_collision_cannot_hide_changed_table_pages(self):
        change(self.live,'CREATE TRIGGER base AFTER INSERT ON query_child BEGIN SELECT 1; END')
        self.clone()
        change(self.candidate,'UPDATE base SET val=999 WHERE id=1')
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{})

    def test_without_rowid_words_in_a_literal_do_not_hide_changed_rowids(self):
        change(self.live,"CREATE TABLE literal(k TEXT PRIMARY KEY,label TEXT DEFAULT 'WITHOUT ROWID')")
        change(self.live,"INSERT INTO literal(k) VALUES('key')")
        self.clone();change(self.candidate,'UPDATE literal SET rowid=99')
        with self.assertRaises(tx.TransactionError):tx.verify_append_only(self.live,self.candidate,{})

    def test_comment_between_without_and_rowid_uses_real_sqlite_identity(self):
        change(self.live,'CREATE TABLE commented(k TEXT PRIMARY KEY,val) WITHOUT /* valid SQL */ ROWID')
        change(self.live,"INSERT INTO commented VALUES('key',7)")
        self.clone();proof=tx.verify_append_only(self.live,self.candidate,{})
        self.assertEqual(proof['tables']['data.commented']['identity'],'primary_key')
        change(self.candidate,'UPDATE commented SET val=8')
        with self.assertRaises(tx.TransactionError):tx.verify_append_only(self.live,self.candidate,{})

    def test_uppercase_rowid_column_does_not_hide_reassigned_real_identity(self):
        change(self.live,'CREATE TABLE shadowed(ROWID TEXT,val)')
        change(self.live,"INSERT INTO shadowed VALUES('business-key',7)")
        self.clone();change(self.candidate,'UPDATE shadowed SET _rowid_=99')
        with self.assertRaises(tx.TransactionError):tx.verify_append_only(self.live,self.candidate,{})

    def test_bound_fk_certificate_checks_added_children_and_issues_new_bound_certificate(self):
        certificate=self.baseline_certificate();self.clone()
        change(self.ca,"INSERT INTO evidence VALUES(2,2,'synthetic-new')")
        proof=tx.verify_append_only(self.live,self.candidate,{'audit.evidence':1},baseline_fk_certificate=certificate)
        checks=proof['foreign_key_checks']
        self.assertEqual(checks['method'],'inherited-old-plus-changed-child-tables')
        self.assertEqual(checks['external_links_scanned'],1)
        self.assertEqual(checks['local_tables_scanned'],1)
        self.assertEqual(proof['foreign_key_certificate']['fingerprints'],proof['candidate'])
        self.assertTrue(proof['foreign_key_certificate']['all_fk_valid'])

    def test_certificate_never_skips_a_broken_new_cross_store_child(self):
        certificate=self.baseline_certificate();self.clone()
        change(self.ca,"INSERT INTO evidence VALUES(2,999,'synthetic-new')")
        with self.assertRaisesRegex(tx.TransactionError,'跨库外键'):
            tx.verify_append_only(self.live,self.candidate,{'audit.evidence':1},baseline_fk_certificate=certificate)

    def test_certificate_never_skips_a_broken_new_local_child(self):
        certificate=self.baseline_certificate();self.clone()
        change(self.ca,'INSERT INTO local_child VALUES(2,999)')
        with self.assertRaisesRegex(tx.TransactionError,'本地外键'):
            tx.verify_append_only(self.live,self.candidate,{'audit.local_child':1},baseline_fk_certificate=certificate)

    def test_wrong_pair_or_schema_certificate_falls_back_to_full_scan(self):
        certificate=self.baseline_certificate();self.clone()
        for altered in [None,{'ok':True},dict(certificate,all_fk_valid=1),dict(certificate,fingerprints={}),dict(certificate,schema_sha256={}),dict(certificate,external_foreign_key_links=999)]:
            with self.subTest(kind=type(altered).__name__):
                proof=tx.verify_append_only(self.live,self.candidate,{},baseline_fk_certificate=altered)
                self.assertEqual(proof['foreign_key_checks']['method'],'full-scan')

    def test_broken_old_fk_with_missing_or_stale_certificate_still_fails(self):
        certificate=self.baseline_certificate()
        change(self.audit,'INSERT INTO local_child VALUES(2,999)')
        self.clone()
        for cert in [None,certificate]:
            with self.subTest(has_certificate=cert is not None),self.assertRaisesRegex(tx.TransactionError,'本地外键'):
                tx.verify_append_only(self.live,self.candidate,{},baseline_fk_certificate=cert)

    def test_certificate_does_not_exempt_modified_old_parent_from_typed_proof(self):
        certificate=self.baseline_certificate();self.clone()
        change(self.candidate,'UPDATE base SET id=999 WHERE id=1')
        with self.assertRaises(tx.TransactionError):
            tx.verify_append_only(self.live,self.candidate,{},baseline_fk_certificate=certificate)

    def test_new_external_fk_registration_must_check_existing_children(self):
        change(self.live,'CREATE TABLE unregistered(id INTEGER PRIMARY KEY,target INTEGER)')
        change(self.live,'INSERT INTO unregistered VALUES(1,999)')
        certificate=self.baseline_certificate();self.clone()
        change(self.candidate,'INSERT INTO storage_external_fk VALUES(?,?,?,?,?,?,?,?,?,?)',
               ('data','unregistered','["target"]','data','base','["id"]',0,'NO ACTION','NO ACTION','NONE'))
        with self.assertRaisesRegex(tx.TransactionError,'跨库外键'):
            tx.verify_append_only(self.live,self.candidate,{'data.storage_external_fk':1},baseline_fk_certificate=certificate)

    def test_incomplete_or_failed_proof_cannot_create_fk_certificate(self):
        for proof in [{},{'ok':True},{'ok':False,'protocol':tx._PROTOCOL}]:
            self.assertIsNone(tx.foreign_key_certificate(proof))

    def test_waiting_for_cooperative_writer_lock_obeys_deadline(self):
        calls = [0]
        def deadline():
            calls[0] += 1
            return calls[0] < 3
        def busy(_file, operation):
            if operation & tx.fcntl.LOCK_NB:
                raise BlockingIOError()
        with patch.object(tx.fcntl, 'flock', side_effect=busy), patch.object(tx.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                with tx._publish_lock(self.live, deadline):
                    self.fail('过期后不应取得锁')
        self.assertLiveUnchanged()


if __name__ == '__main__':
    unittest.main()

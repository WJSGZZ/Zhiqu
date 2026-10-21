"""Unified provenance schema and content-addressed public-original invariants."""
import csv
import hashlib
import shutil
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import validate_data as v

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.folder=self.root/'skills/zhiqu/data/testprovince';self.folder.mkdir(parents=True)
        self.originals=self.root/v.ORIGINALS_RELATIVE;self.originals.mkdir(parents=True)
        self.content=b'%PDF-1.4 public official original'
        self.sha=hashlib.sha256(self.content).hexdigest()
        self.relative=(v.ORIGINALS_RELATIVE/self.sha[:2]/(self.sha+'.pdf')).as_posix()
        original=self.root/self.relative;original.parent.mkdir();original.write_bytes(self.content)
        self.row=dict.fromkeys(v.SOURCE_FIELDS,'')
        self.row.update(source_id='official-2026',grade='官方',publisher='教育部',title='官方原表',
                        landing_url='https://www.moe.gov.cn/notice.html',file_url='https://www.moe.gov.cn/a.pdf',
                        retrieved='2026-10-20',archive_sha256=self.sha,archive_path=self.relative,archive_status='已存原件')
        self.index={'sha256':self.sha,'size':len(self.content),'media_type':'application/pdf',
                    'source_url':self.row['file_url'],'retrieved':'2026-10-20','source_id':self.row['source_id']}
        self.write()
    def csv(self,path,fields,rows):
        with path.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    def write(self,rows=None,index=None):
        self.csv(self.folder/'sources.csv',v.SOURCE_FIELDS,rows or [self.row])
        self.csv(self.originals/'index.csv',v.ORIGINAL_INDEX_FIELDS,index or [self.index])
        (self.folder/'physics_2026.csv').write_text('source_id\nofficial-2026\n')
    def check(self):return v.check_sources(self.folder,['physics_2026.csv'],self.root)[0]
    def check_index(self):return v.check_originals_index(self.root)[0]
    def test_git_attributes_preserve_original_bytes_without_becoming_an_original(self):
        (self.originals/'.gitattributes').write_bytes(b'*/* -text -diff -merge\n')
        self.assertEqual(self.check_index(),[])
    def test_git_attributes_cannot_install_a_content_transform(self):
        (self.originals/'.gitattributes').write_text('*/* filter=replace-original\n')
        self.assertTrue(any('Git属性' in x for x in self.check_index()))
    def image_asset(self, **changes):
        body=b'\x89PNG public score table';sha=hashlib.sha256(body).hexdigest()
        relative=(v.ORIGINALS_RELATIVE/sha[:2]/(sha+'.png')).as_posix()
        path=self.root/relative;path.parent.mkdir(exist_ok=True);path.write_bytes(body)
        asset=dict(source_id=self.row['source_id'],sha256=sha,path=relative,url='https://www.moe.gov.cn/image.png',role='data_image',retrieved='2026-10-20')
        asset.update(changes)
        self.csv(self.originals/'assets.csv',tuple(asset),[asset])
        member=dict(sha256=sha,size=len(body),media_type='image/png',source_url='https://www.moe.gov.cn/image.png',retrieved='2026-10-20',source_id=self.row['source_id'])
        self.write(index=[self.index,member]);return asset
    def test_source_can_register_multiple_exact_data_images(self):
        self.image_asset();self.assertEqual(self.check_index(),[])
    def test_data_image_must_have_official_source(self):
        self.image_asset(source_id='unregistered');self.assertTrue(any('没有官方来源' in x for x in self.check_index()))
    def test_data_image_membership_does_not_accept_other_url(self):
        self.image_asset(url='https://www.moe.gov.cn/wrong.png');self.assertTrue(any('未关联' in x for x in self.check_index()))
    def test_partial_source_keeps_real_members_without_claiming_complete(self):
        asset=self.image_asset()
        primary=dict(source_id=self.row['source_id'],sha256=self.sha,path=self.relative,url=self.row['file_url'],role='attachment',retrieved='2026-10-20')
        self.csv(self.originals/'assets.csv',tuple(asset),[asset,primary])
        self.row.update(archive_status='未取到',archive_path='')
        self.csv(self.folder/'sources.csv',v.SOURCE_FIELDS,[self.row])
        self.csv(self.originals/'sources.csv',v.SOURCE_FIELDS,[self.row])
        self.assertEqual(self.check_index(),[])
    def test_data_image_hash_is_checked(self):
        asset=self.image_asset();(self.root/asset['path']).write_bytes(b'changed')
        self.assertTrue(any('sha256' in x.lower() or 'size' in x for x in self.check_index()))
    def test_deleted_statuses_need_hash_and_empty_path_not_a_file(self):
        shutil.rmtree(self.originals)
        for status in v.DELETED_STATUSES:
            self.row.update(archive_status=status,archive_path='')
            self.csv(self.folder/'sources.csv',v.SOURCE_FIELDS,[self.row])
            with self.subTest(status=status):
                self.assertEqual(self.check(),[])
                self.assertEqual(self.check_index(),[])
    def test_deleted_status_requires_exact_fingerprint(self):
        for status in v.DELETED_STATUSES:
            for fingerprint in ['', 'abc', 'A'*64]:
                self.row.update(archive_status=status,archive_path='',archive_sha256=fingerprint);self.write()
                with self.subTest(status=status,fingerprint=fingerprint):
                    self.assertTrue(any('archive_sha256' in issue for issue in self.check()))
    def test_deleted_status_cannot_claim_file_path(self):
        for status in v.DELETED_STATUSES:
            self.row.update(archive_status=status);self.write()
            self.assertTrue(any('不得填写 archive_path' in issue for issue in self.check()))
    def test_absent_original_directory_still_checks_source_metadata(self):
        shutil.rmtree(self.originals)
        self.row.update(archive_status='未取到',archive_path='',file_url='',landing_url='',retrieved='2026-02-30')
        self.csv(self.folder/'sources.csv',v.SOURCE_FIELDS,[self.row])
        issues=self.check_index()
        self.assertTrue(any('至少须有' in issue for issue in issues))
        self.assertTrue(any('retrieved' in issue for issue in issues))
    def test_absent_directory_does_not_hide_stored_file_claim(self):
        shutil.rmtree(self.originals)
        self.assertTrue(any('不存在' in issue for issue in self.check_index()))
    def test_existing_legacy_directory_still_requires_index(self):
        (self.originals/'index.csv').unlink()
        self.assertTrue(any('缺 index.csv' in issue for issue in self.check_index()))
    def test_explicit_missing_legacy_index_is_not_ignored(self):
        shutil.rmtree(self.originals)
        self.assertTrue(any('缺 index.csv' in issue for issue in v.check_originals_index(self.root,index_path=self.originals/'index.csv')[0]))
    def test_exact_unified_source_fields(self):
        self.assertEqual(v.SOURCE_FIELDS,('source_id','grade','publisher','title','landing_url','file_url','published','retrieved','method','archive_sha256','archive_path','archive_status','wayback_url','note','citation','license','producer_revision'))
    def test_valid_source_and_index(self):
        self.assertEqual(self.check(),[]);self.assertEqual(self.check_index(),[])
    def test_original_unavailable_can_keep_known_hash_without_claiming_stored(self):
        self.row.update(archive_status='未取到',archive_path='');self.write()
        self.assertEqual(self.check(),[])
    def test_official_record_requires_at_least_one_original_url(self):
        self.row.update(landing_url='',file_url='',wayback_url='https://web.archive.org/web/20260101/https://www.moe.gov.cn/a.pdf');self.write()
        self.assertTrue(any('至少须有' in s for s in self.check()))
    def test_landing_only_official_record_passes(self):
        self.row['file_url']='';self.row.update(archive_status='未取到',archive_path='');self.write()
        self.assertEqual(self.check(),[])
    def test_archive_statuses_are_closed_with_legacy_stored_compatibility(self):
        for status in ['','已存','第三方备份']:
            self.row['archive_status']=status;self.write();self.assertTrue(any('archive_status' in s for s in self.check()))
        self.row['archive_status']='原链接失效·存档副本';self.write();self.assertEqual(self.check(),[])
    def test_missing_original_and_hash_tampering(self):
        (self.root/self.relative).write_bytes(b'changed')
        self.assertTrue(any('内容不符' in s for s in self.check()))
        (self.root/self.relative).unlink();self.assertTrue(any('不存在' in s for s in self.check()))
    def test_archived_hash_is_mandatory(self):
        self.row['archive_sha256']='';self.write();self.assertTrue(any('必须有 archive_sha256' in s for s in self.check()))
    def test_repository_relative_paths_must_not_escape(self):
        for path in ['/tmp/private.pdf','../private.pdf',self.relative.replace('/'+self.sha[:2]+'/', '/zz/'),self.relative.replace('/','\\')]:
            self.row['archive_path']=path;self.write();self.assertTrue(self.check(),path)
    def test_symlink_cannot_bring_outside_file_into_repository(self):
        source=self.root/self.relative;source.unlink()
        with tempfile.TemporaryDirectory() as outside:
            target=Path(outside)/'outside.pdf';target.write_bytes(self.content);source.symlink_to(target)
            self.assertTrue(any('越界' in s for s in self.check()))
    def test_unavailable_does_not_falsely_claim_original_path(self):
        self.row['archive_status']='未取到';self.write();self.assertTrue(any('不得填写 archive_path' in s for s in self.check()))
    def test_legacy_url_can_be_read_but_cannot_pass_new_schema(self):
        old={k:self.row.get(k,'') for k in v.LEGACY_SOURCE_FIELDS};old['url']=self.row['file_url']
        self.csv(self.folder/'sources.csv',v.LEGACY_SOURCE_FIELDS,[old])
        rows,_=v.read_sources(self.folder/'sources.csv');self.assertEqual(rows[0]['file_url'],self.row['file_url'])
        self.assertTrue(any('必须迁移' in s for s in self.check()))
    def test_nonpublic_or_malformed_url_rejected(self):
        for url in ['file:///tmp/local','https://','https://x:99999/a','https://u:p@www.moe.gov.cn/a','https://www.moe.gov.cn/a b']:
            self.row['file_url']=url;self.write();self.assertTrue(any('file_url' in s for s in self.check()))
    def test_same_sha_can_serve_multiple_official_source_ids(self):
        other=dict(self.row,source_id='official-copy');index=dict(self.index,source_id='official-copy')
        self.write([self.row,other],[self.index,index]);self.assertEqual(self.check_index(),[])
    def test_database_only_official_source_can_use_tracked_catalog(self):
        # No ignored database or public data source row is needed in CI.
        self.csv(self.folder/'sources.csv',v.SOURCE_FIELDS,[])
        self.csv(self.originals/'sources.csv',v.SOURCE_FIELDS,[self.row])
        self.assertEqual(self.check_index(),[])
    def test_catalog_must_be_official_stored_and_consistent_with_public_source(self):
        catalog=dict(self.row)
        self.csv(self.originals/'sources.csv',v.SOURCE_FIELDS,[catalog])
        self.assertEqual(self.check_index(),[])
        for field,value in [('grade','第三方整理'),('archive_status','未取到'),
                            ('archive_sha256','0'*64),('file_url','https://other.example/a.pdf')]:
            bad=dict(catalog);bad[field]=value
            if field=='file_url':bad['landing_url']='https://other.example/notice'
            self.csv(self.originals/'sources.csv',v.SOURCE_FIELDS,[bad])
            with self.subTest(field=field):self.assertTrue(any('catalog' in x for x in self.check_index()))
        self.csv(self.originals/'sources.csv',v.SOURCE_FIELDS,[dict(catalog,archive_status='未取到',archive_path='')])
        self.assertTrue(any('仅允许实际已存' in x for x in self.check_index()))
    def test_duplicate_pair_is_not_allowed(self):
        self.write(index=[self.index,self.index]);self.assertTrue(any('重复' in s for s in self.check_index()))
    def test_index_rejects_unknown_nonofficial_or_mismatched_source(self):
        self.index['source_id']='not-registered';self.write();self.assertTrue(any('未关联' in s for s in self.check_index()))
        self.index['source_id']=self.row['source_id'];self.row['grade']='第三方整理';self.write()
        self.assertTrue(any('未关联' in s for s in self.check_index()))
    def test_index_size_date_media_and_url_are_validated(self):
        for field,value,needle in [('size',5_000_001,'size'),('size',1,'size 与文件'),('retrieved','2026-02-30','retrieved'),
                                   ('media_type','','media_type'),('source_url','https://other.example/a','链接不符')]:
            old=self.index[field];self.index[field]=value;self.write()
            self.assertTrue(any(needle in s for s in self.check_index()),(field,self.check_index()))
            self.index[field]=old
    def test_source_stored_file_must_be_indexed(self):
        self.csv(self.originals/'index.csv',v.ORIGINAL_INDEX_FIELDS,[])
        self.assertTrue(any('缺原件库索引' in s for s in self.check_index()))
    def test_sha_must_have_exactly_one_extension_and_unindexed_files_fail(self):
        (self.root/self.relative).with_suffix('.html').write_bytes(self.content)
        self.assertTrue(any('恰好对应一份' in s for s in self.check_index()))
    def test_exact_five_million_byte_boundary_is_allowed(self):
        old=self.root/self.relative;old.unlink()
        body=b'X'*5_000_000;self.sha=hashlib.sha256(body).hexdigest()
        self.relative=(v.ORIGINALS_RELATIVE/self.sha[:2]/(self.sha+'.pdf')).as_posix()
        target=self.root/self.relative;target.parent.mkdir(exist_ok=True);target.write_bytes(body)
        self.row.update(archive_sha256=self.sha,archive_path=self.relative)
        self.index.update(sha256=self.sha,size=len(body));self.write()
        self.assertEqual(self.check(),[]);self.assertEqual(self.check_index(),[])
    def test_local_large_original_is_allowed_but_public_large_original_rejected(self):
        (self.root/self.relative).unlink()
        body=b"L"*5_000_001;sha=hashlib.sha256(body).hexdigest()
        for base in v.LOCAL_ORIGINALS_RELATIVE:
            relative=(base/sha[:2]/(sha+'.pdf')).as_posix()
            target=self.root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
            self.row.update(archive_sha256=sha,archive_path=relative);self.write()
            with self.subTest(base=base):self.assertEqual(self.check(),[])
        public=(v.ORIGINALS_RELATIVE/sha[:2]/(sha+'.pdf')).as_posix()
        target=self.root/public;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
        self.row['archive_path']=public;self.write()
        self.assertTrue(any('超过 5,000,000' in x for x in self.check()))
    def test_local_source_needs_no_public_index_but_requires_real_file_and_hash(self):
        original=self.root/self.relative
        relative=(v.LOCAL_ORIGINALS_RELATIVE[0]/self.sha[:2]/(self.sha+'.pdf')).as_posix()
        local=self.root/relative;local.parent.mkdir(parents=True);original.replace(local)
        self.row['archive_path']=relative;self.write(index=[])
        self.csv(self.originals/'index.csv',v.ORIGINAL_INDEX_FIELDS,[])
        self.assertEqual(self.check(),[]);self.assertEqual(self.check_index(),[])
        # A local proof must not be laundered into the tracked public catalog.
        self.csv(self.originals/'sources.csv',v.SOURCE_FIELDS,[self.row])
        self.assertTrue(any('不能登记本机' in x for x in self.check_index()))
        (self.originals/'sources.csv').unlink()
        local.write_bytes(b'tampered')
        self.assertTrue(any('内容不符' in x for x in self.check()))
        self.assertTrue(any('内容不符' in x for x in self.check_index()))
        local.unlink();self.assertTrue(any('不存在' in x for x in self.check()))
        self.assertTrue(any('不存在' in x for x in self.check_index()))
    def test_oversized_actual_original_fails_even_with_small_index_claim(self):
        source=self.root/self.relative
        with source.open('wb') as f:f.seek(5_000_000);f.write(b'x')
        self.assertTrue(any('超过 5,000,000' in s for s in self.check()))

if __name__=='__main__':unittest.main()

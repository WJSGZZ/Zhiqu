"""Offline public-catalogue routing. Synthetic JS pins never certify originals."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import kaoyan_hznu_catalog as hz
import kaoyan_on_demand as tool
from kaoyan_adapters import NeedsReview

IDENTITY={'name':hz.SCHOOL,'institution_id':hz.IID}
PROGRAM_ID='A'*32


def fixtures():
    row=dict(id='b'*32,zsnf='2026',zyId=PROGRAM_ID,yjfxXh='00',yjfx='不区分研究方向',xxfs='1',xwlb='1',
             tkme=25,tmme=3,tkmesm='以最终实际录取人数为准。',kskm='101思想政治理论；204英语（二）；333教育综合；817教育研究方法',
             ejxkdm='045108',ejxkmc='学科教学（英语）',sysOrgCode_dictText='合成教育学院',zyId_dictText='学科教学（英语）',
             xxfs_dictText='全日制',xwlb_dictText='专业学位',ksfs_dictText='统考',tydxs_dictText='是',jsggjh_dictText='否',
             tkbz='欢迎英语专业报考，不等于仅限英语。')
    api='https://yjsfw.hznu.edu.cn/dataapi/open/zsss/zsml?mllx=0&zsnf=2026&zyId='+PROGRAM_ID+'&pageNo=1&pageSize=10'
    data={hz.PARENT:('<html><title>杭州师范大学2026年硕士研究生招生简章</title><a href="'+hz.SERVICE+'">杭州师范大学2026年硕士研究生招生专业目录（点击查看）</a></html>').encode(),
          hz.SERVICE:b'<html><script src="/open/js/app.0e2179d6.js"></script></html>',hz.APP:b'synthetic runtime',hz.CHUNK:b'synthetic columns',
          hz.DICTIONARY:json.dumps({'success':True,'result':[{'id':PROGRAM_ID,'dm':'045108','mc':'学科教学（英语）'}]}).encode(),
          api:json.dumps({'success':True,'result':[row]}).encode()}
    return row,api,data


class HznuCatalogTests(unittest.TestCase):
    def setUp(self):
        self.row,self.api,self.data=fixtures();self.deadline=tool.Deadline(120)
        self.pins=patch.multiple(hz,APP_SHA=hz.sha(self.data[hz.APP]),CHUNK_SHA=hz.sha(self.data[hz.CHUNK]));self.pins.start();self.addCleanup(self.pins.stop)

    def bodies(self):
        return {u:({'body':b,'url':u},{'url':u,'http_status':200})for u,b in self.data.items()}

    def parse(self,bodies=None):
        return hz.advance(self.data[self.api],self.api,IDENTITY,2026,'catalog',['045108'],bodies or self.bodies(),self.deadline)

    def test_target_values_keep_inclusive_plan_and_unknown_special_scope(self):
        parsed=self.parse();row=parsed['manifest']['rows'][0]
        self.assertEqual(parsed['rows'],1);self.assertEqual(row['planned'],25);self.assertIsNone(row['tuimian']);self.assertIsNone(row['special_plan'])
        self.assertEqual(row['planned_scope'],'含推免；专项名额范围未明确')
        extra=json.loads(row['extra_json']);self.assertIn('欢迎',extra['remarks_raw']);self.assertEqual(extra['special_eligibility_raw']['是否接收退役大学生士兵'],'是')
        self.assertNotIn('tmme',row);self.assertEqual(parsed['proofs'][0]['sample_count'],1)
        self.assertEqual(parsed['manifest']['sources'][0]['file_url'],self.api)
        self.assertEqual(parsed['manifest']['sources'][0]['published'],'')

    def test_chain_requests_only_observed_public_get_sources(self):
        bodies={};seen=[]
        for u in [hz.PARENT,hz.SERVICE,hz.APP,hz.CHUNK,hz.DICTIONARY,self.api]:
            bodies[u]=({'body':self.data[u],'url':u},{})
            result=hz.advance(self.data[u],u,IDENTITY,2026,'catalog',['045108'],bodies,self.deadline)
            if 'next_urls'in result:seen.extend(result['next_urls'])
        self.assertEqual(seen,[hz.SERVICE,hz.APP,hz.CHUNK,hz.DICTIONARY,self.api]);self.assertEqual(result['rows'],1)

    def test_unknown_frontend_or_column_mapping_fails_closed(self):
        for u in [hz.APP,hz.CHUNK]:
            with self.subTest(u=u):
                bodies=self.bodies();bodies[u][0]['body']+=b' changed'
                with self.assertRaises(NeedsReview):self.parse(bodies)

    def test_parent_foreign_heading_wrong_year_or_broken_link_refused(self):
        for replacement in [self.data[hz.PARENT]+ '<h1>其他大学2026年硕士研究生招生简章</h1>'.encode(),
                            self.data[hz.PARENT].replace(b'2026',b'2025'),self.data[hz.PARENT].replace(b'ZsssTksList',b'Unknown')]:
            with self.subTest(replacement=replacement):
                bodies=self.bodies();bodies[hz.PARENT][0]['body']=replacement
                with self.assertRaises(NeedsReview):self.parse(bodies)

    def test_wrong_program_year_name_duplicate_direction_and_private_keys_refused(self):
        for key,value in [('zsnf','2025'),('ejxkdm','045109'),('zyId','C'*32),('ejxkmc','其他专业'),('zyId_dictText','其他专业'),('姓名','合成隐私哨兵'),('tkme',True),('tkme','25'),('ksfs_dictText','推免'),('xxfs','2'),('xwlb','0')]:
            with self.subTest(key=key):
                row=copy.deepcopy(self.row);row[key]=value;bodies=self.bodies();bodies[self.api][0]['body']=json.dumps({'success':True,'result':[row]}).encode()
                with self.assertRaises((NeedsReview,ValueError)):self.parse(bodies)
        bodies=self.bodies();bodies[self.api][0]['body']=json.dumps({'success':True,'result':[self.row,self.row]}).encode()
        with self.assertRaises(NeedsReview):self.parse(bodies)

    def test_duplicate_business_direction_with_another_id_is_refused(self):
        row=copy.deepcopy(self.row);row['id']='c'*32
        bodies=self.bodies();bodies[self.api][0]['body']=json.dumps({'success':True,'result':[self.row,row]}).encode()
        with self.assertRaises(NeedsReview):self.parse(bodies)

    def test_no_prefix_guess_and_unknown_layer_or_year_not_adapted(self):
        with self.assertRaises(NeedsReview):hz.advance(b'',hz.PARENT,IDENTITY,2026,'catalog',['0451'],{},self.deadline)
        self.assertIsNone(hz.advance(b'',hz.PARENT,IDENTITY,2025,'catalog',['045108'],{},self.deadline))
        self.assertIsNone(hz.advance(b'',hz.PARENT,IDENTITY,2026,'stats',['045108'],{},self.deadline))
        self.assertIsNone(hz.advance(b'',hz.PARENT,dict(name='其他大学',institution_id=hz.IID),2026,'catalog',['045108'],{},self.deadline))

    def test_duplicate_json_key_failed_response_missing_node_and_deadline_refused(self):
        with self.assertRaises(NeedsReview):hz.dual_json(b'{"success":true,"success":false,"result":[]}',self.deadline)
        with self.assertRaises(NeedsReview):hz.dual_json(b'{"success":false,"result":null}',self.deadline)
        with patch.object(hz.shutil,'which',return_value=None):
            with self.assertRaises(NeedsReview):self.parse()
        with patch.object(self.deadline,'remaining',return_value=0):
            with self.assertRaises(TimeoutError):self.parse()

    def test_redirect_to_unproven_payload_refused(self):
        bodies=self.bodies();bodies[self.api][0]['url']='https://other.edu.cn/login'
        with self.assertRaises(NeedsReview):self.parse(bodies)

    def test_dictionary_ambiguous_program_id_refused(self):
        for targets in [[],[{'id':'not-an-id','dm':'045108','mc':'学科教学（英语）'}],[{'id':PROGRAM_ID,'dm':'045108','mc':'学科教学（英语）'}]*2]:
            with self.subTest(targets=targets):
                bodies=self.bodies();bodies[hz.DICTIONARY][0]['body']=json.dumps({'success':True,'result':targets}).encode()
                with self.assertRaises(NeedsReview):self.parse(bodies)

    def test_real_orchestration_routes_and_publishes_synthetic_target(self):
        # Reuse the existing tiny-DB fixture, not another test runner/schema.
        from test_kaoyan_on_demand import OnDemandTests
        fixture=OnDemandTests('runTest');fixture.setUp();self.addCleanup(fixture.tearDown)
        req=dict(fixture.request,school=hz.SCHOOL,programs=['045108'],layers=['catalog'],entries=[hz.PARENT])
        cell=dict(year=2026,layer='catalog',program='045108',obtained=False,existing_rows=0,source_ids=[])
        calls=[]
        def fetch(u,deadline):
            calls.append(u);return {'body':self.data[u],'url':u},{'url':u,'http_status':200}
        pub=Mock(return_value={'ingest':[{'rows_inserted':1}]})
        with patch.object(tool,'resolve_school',return_value=(IDENTITY,{'graduate_site_url':'https://yjs.hznu.edu.cn'},[])):
            summary=tool.run_request(req,registry=[],lookup_fn=Mock(return_value=[cell]),fetch=fetch,publisher=pub)
        self.assertTrue(summary['published']);self.assertEqual(summary['outcomes'][0]['status'],'obtained')
        self.assertEqual(calls,[hz.PARENT,hz.SERVICE,hz.APP,hz.CHUNK,hz.DICTIONARY,self.api]);self.assertEqual(pub.call_count,1)
        rows=pub.call_args.args[1][0][1]['rows'];self.assertEqual(rows[0]['planned'],25)

    def test_known_stop_does_not_request_catalogue_or_publish(self):
        from test_kaoyan_on_demand import OnDemandTests
        fixture=OnDemandTests('runTest');fixture.setUp();self.addCleanup(fixture.tearDown)
        stop=fixture.root/'stop.json'
        req=dict(fixture.request,school=hz.SCHOOL,programs=['045108'],layers=['catalog'],entries=[hz.SERVICE],stop_ledger=str(stop))
        cell=dict(year=2026,layer='catalog',program='045108',obtained=False,existing_rows=0,source_ids=[])
        entry={'graduate_site_url':hz.SERVICE}
        self.assertTrue(tool.official_url(hz.SERVICE,entry))
        for category in ['http_block','login','verification']:
            with self.subTest(category=category):
                stop.write_text(json.dumps([{'url':hz.SERVICE,'stop_category':category}]))
                fetch=Mock();pub=Mock();req['output']=str(fixture.root/category)
                with patch.object(tool,'resolve_school',return_value=(IDENTITY,entry,[])):
                    summary=tool.run_request(req,registry=[],lookup_fn=Mock(return_value=[cell]),fetch=fetch,publisher=pub)
                self.assertFalse(summary['published']);fetch.assert_not_called();pub.assert_not_called()
        stop.write_text('[]');req['output']=str(fixture.root/'no-old-stop')
        fetch=Mock(return_value=(None,{'url':hz.SERVICE,'stop_category':'http_block'}));pub=Mock()
        # Same valid domain is reachable without the old stop; the new block
        # then stops its host before any catalogue scripts/API are requested.
        with patch.object(tool,'resolve_school',return_value=(IDENTITY,entry,[])):
            summary=tool.run_request(req,registry=[],lookup_fn=Mock(return_value=[cell]),fetch=fetch,publisher=pub)
        self.assertEqual(fetch.call_count,1);pub.assert_not_called();self.assertFalse(summary['published'])

    def test_obtained_target_returns_cache_without_fetch_or_publish(self):
        from test_kaoyan_on_demand import OnDemandTests
        fixture=OnDemandTests('runTest');fixture.setUp();self.addCleanup(fixture.tearDown)
        req=dict(fixture.request,school=hz.SCHOOL,programs=['045108'],layers=['catalog'],entries=[hz.PARENT])
        cell=dict(year=2026,layer='catalog',program='045108',obtained=True,existing_rows=1,source_ids=[])
        fetch=Mock();pub=Mock()
        with patch.object(tool,'resolve_school',return_value=(IDENTITY,{'graduate_site_url':'https://yjs.hznu.edu.cn'},[])):
            summary=tool.run_request(req,registry=[],lookup_fn=Mock(return_value=[cell]),fetch=fetch,publisher=pub)
        self.assertEqual(summary['outcomes'][0]['status'],'obtained');fetch.assert_not_called();pub.assert_not_called()

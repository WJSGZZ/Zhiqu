"""Synthetic public campus-position blocks; no real contacts or applicants."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
S=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts';sys.path.insert(0,str(S))
import career_on_demand as m
import career_positions as p
from test_career_on_demand import database,metadata

def entry():return {'publisher':'郑州航空工业管理学院','url':'https://zhjyb.zua.edu.cn/module/position_details/id-12/nid-34'}
def request():return dict(region='郑州市',direction='财务',years=[2027],stage='graduate',layers=['duties','requirements','pay','schedule'],seconds=120,database='unused',entries=[entry()])
def body(city='郑州',stage='校招',req='2027届全日制应届毕业生，会计相关专业，本科及以上学历。初级会计资格证优先。'):
    cells=['职位名称：财务助理','职位类别：财务专员/助理','工作性质：'+stage,'月薪范围：4K-6K','学历要求：本科','工作城市：'+city,'招聘人数：2 人','招聘单位：合成企业','联系人：合成人员','联系电话：13812345678']
    return ('<html><title>财务助理-郑州航空工业管理学院 就业信息网</title><div class="job-information"><div class="info-details">'+''.join('<span>'+v+'</span><br>'for v in cells)+'</div></div><div class="describe-details"><p>任职要求</p><p>'+req+'</p></div><div class="job-time"><span>2026/09/12</span><span>发布于合成企业</span></div><footer>单位地址：杭州市</footer></html>').encode()
def result():return p.parse_position(body(),entry(),request())
class CampusPositionTests(unittest.TestCase):
    def test_year_is_explicit_cohort_not_publication_and_fields_stay_raw(self):
        x=result();r=x['rows'][0];p.validate_campus_proof(r,x['proofs'][0]);self.assertEqual((r['year'],r['published'],r['recruitment_year']),(2027,'2026-09-12',2027));self.assertEqual(r['fields']['pay'],'月薪范围：4K-6K');self.assertIn('优先',r['fields']['requirements']);self.assertEqual(r['education_summary_raw'],'学历要求：本科');self.assertIn('本科及以上',r['fields']['requirements']);self.assertIsNone(r['fields']['duties']);self.assertIsNone(r['fields']['schedule']);self.assertIn('非雇主自有官网',r['source_scope']);self.assertEqual(r['employer_raw'],'合成企业')
    def test_contacts_are_not_serialized_even_when_in_metadata_block(self):
        text=json.dumps(result(),ensure_ascii=False);self.assertNotIn('13812345678',text);self.assertNotIn('合成人员',text);self.assertNotIn('联系人',text)
    def test_missing_and_mixed_cohort_or_wrong_scope_are_rejected(self):
        for req in ['本科以上，职位发布于2027年。','2026届全日制应届毕业生。','2027届应届毕业生及2028届应届毕业生。']:
            with self.subTest(req=req),self.assertRaises(m.Gap):p.parse_position(body(req=req),entry(),request())
        for changed in [body(city='杭州'),body(city='郑州、杭州'),body(stage='社招')]:
            with self.assertRaises(m.Gap):p.parse_position(changed,entry(),request())
        q=request();q['stage']='internship'
        with self.assertRaises(m.Gap):p.parse_position(body(),entry(),q)
    def test_wrong_publisher_and_homepage_and_hidden_are_not_accepted(self):
        for e in [dict(entry(),publisher='合成企业'),dict(entry(),url='https://zhjyb.zua.edu.cn/')]:
            with self.assertRaises(m.Gap):p.parse_position(body(),e,request())
        with self.assertRaises(m.Gap):p.parse_position(body().replace(b'class="describe-details"',b'class="describe-details" style="display:none"'),entry(),request())
    def test_retained_privacy_and_dual_disagreement_stop_whole_position(self):
        with self.assertRaises(m.Gap):p.parse_position(body(req='2027届应届毕业生，请联系13812345678。'),entry(),request())
        original=p.CampusBlocks.handle_data
        def altered(self,text):return original(self,text.replace('4K-6K','9K-9K'))
        with patch.object(p.CampusBlocks,'handle_data',altered),self.assertRaises(m.Gap):p.parse_position(body(),entry(),request())
    def test_changed_values_scope_and_locators_fail_readback_proof(self):
        x=result()
        for field,value in [('region','杭州市'),('year',2026),('stage_raw','社招'),('source_scope','雇主官方认证'),('employer_raw','别的企业'),('published','2026-09-13')]:
            r=copy.deepcopy(x['rows'][0]);r[field]=value
            with self.subTest(field=field),self.assertRaises(m.Gap):p.validate_campus_proof(r,x['proofs'][0])
        r=copy.deepcopy(x['rows'][0]);r['fields']['pay']='月薪范围：9K-9K'
        with self.assertRaises(m.Gap):p.validate_campus_proof(r,x['proofs'][0])
        r=copy.deepcopy(x['rows'][0]);r['field_locators']['pay']=[]
        with self.assertRaises(m.Gap):p.validate_campus_proof(r,dict(x['proofs'][0],field_locators=r['field_locators']))
    def test_fixed_single_position_scope_and_counts_cannot_be_changed(self):
        x=result()
        for group,key in [('row','src_table'),('row','src_row'),('proof','src_table'),('proof','original_rows'),('proof','loaded_rows')]:
            for value in [0,9,True,'1']:
                with self.subTest(group=group,key=key,value=value):
                    r=copy.deepcopy(x['rows'][0]);f=copy.deepcopy(x['proofs'][0]);(r if group=='row'else f)[key]=value
                    with self.assertRaises(m.Gap):p.validate_campus_proof(r,f)

    def test_actual_request_publish_and_cache_preserve_platform_scope(self):
        q=request()
        with tempfile.TemporaryDirectory()as tmp:
            db=Path(tmp)/'employment.sqlite';database(db);q['database']=str(db)
            def fetch(url,deadline):return {'url':url,'body':body()},{'status':'retrieved','raw_original_written':False}
            x=m.run_request(q,fetch=fetch,lookup_fn=lambda *_:[]);self.assertEqual(len(x['candidates']),1)
            receipt=m.publish_result(x,db,Path(tmp)/'publication',m.Deadline(120),metadata_builder=metadata,validator=lambda *_:0);self.assertTrue(receipt['published']);self.assertEqual(receipt['rows'],1)
            cached=m.lookup(db,q);self.assertEqual(len(cached),4);self.assertEqual(cached[0]['metadata']['source_scope'],p.CAMPUS_SCOPE);self.assertEqual(cached[0]['metadata']['employer_raw'],'合成企业')
            m.validate_candidate(db,x)

"""Independent boundary audit: valid proofs must pass and mismatches fail closed."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from claim_guards import personal_probability_errors
from official_source_audit import official_domain_for_url
from source_authentication import official_source_errors
from unit_validation import errors as unit_errors


class FingerprintBoundaries(unittest.TestCase):
    def setUp(self):
        self.item={'id':'F1','grade':'官方','status':'verified','source':{
            'organization':'教育部官方机构','url':'https://www.moe.gov.cn/boundary.html',
            'sha256':'a'*64}}
    def check(self):
        domains={'moe.gov.cn':{'domain':'moe.gov.cn','organization':'教育部','evidence':'official URL'}}
        with patch('source_authentication.official_domain_for_url',side_effect=lambda u:official_domain_for_url(u,domains)):
            return official_source_errors(self.item)
    def test_source_fingerprint_needs_no_local_file(self):
        self.assertEqual(self.check(),[])
        self.assertNotIn('original_file',self.item['source'])
        self.assertNotIn('receipt_file',self.item['source'])
    def test_official_institution_is_not_a_third_party_provider(self):
        for name in ['教育部官方机构','政府所属机构','国家教育考试机构']:
            self.item['source']['organization']=name
            self.assertEqual(self.check(),[])
    def test_missing_verified_fingerprint_is_rejected(self):
        self.item['source'].pop('sha256')
        self.assertTrue(any('须记录原文指纹' in x for x in self.check()))
    def test_invalid_fingerprint_is_rejected_even_for_unretrieved(self):
        self.item['status']='unretrieved'
        for sha in ['a'*63,'g'*64,123,False,{},['a'*64]]:
            self.item['source']['sha256']=sha
            self.assertTrue(any('64位' in x for x in self.check()))
    def test_explicit_gap_may_lack_fingerprint(self):
        self.item.update(status='unretrieved',value=None,gap='当届公告未取到')
        self.item['source'].pop('sha256')
        self.assertEqual(self.check(),[])
    def test_unretrieved_value_cannot_support_affirmative_fact(self):
        self.item.update(status='unretrieved',value=123)
        self.assertTrue(any('不能以确定值支持肯定事实' in x for x in self.check()))
    def test_explicit_third_party_identity_is_rejected(self):
        self.item['source']['organization']='第三方整理平台'
        self.assertTrue(any('不得标官方' in x for x in self.check()))


class SharedOssBoundaries(unittest.TestCase):
    def setUp(self):
        self.host='proof-bucket.oss-cn-beijing.aliyuncs.com'
        self.url='http://'+self.host+'/reviewed/attachment.pdf'
        self.domains={self.host:{'domain':self.host,'organization':'官方附件，非整桶',
            'evidence':'official parent original | allowed_url='+self.url+' | linked exact object'}}
    def test_only_exact_shared_bucket_object_is_official(self):
        self.assertIsNotNone(official_domain_for_url(self.url,self.domains))
        for url in (self.url+'.evil',self.url+'?replacement=1',self.url.replace('/reviewed/','/other/'),
                    self.url.replace('http:','https:'),self.url.replace(self.host,'other.'+self.host)):
            with self.subTest(url=url):self.assertIsNone(official_domain_for_url(url,self.domains))
    def test_fragment_does_not_change_document_bytes(self):
        self.assertIsNotNone(official_domain_for_url(self.url+'#page=2',self.domains))
    def test_shared_bucket_without_exact_url_is_rejected(self):
        self.domains[self.host]['evidence']='official parent page, no exact linked object'
        self.assertIsNone(official_domain_for_url(self.url,self.domains))


class UnitPrefixBoundaries(unittest.TestCase):
    def case(self,unit):
        return {'case.json':{},'evidence.json':{'items':[{'id':'U','value':1200,'unit':unit}]}}
    def test_currency_prefix_and_suffix_both_agree(self):
        for unit,text in [('港元/年','HK${{e:U#/value}}港币/年'),
                          ('元/月','人民币{{e:U#/value}}元/月'),
                          ('万元/年','{{e:U#/value}}万元/年')]:
            with self.subTest(text=text):self.assertFalse(unit_errors(self.case(unit),text))
    def test_currency_and_scale_prefix_mismatches(self):
        for unit,text in [('元','HK${{e:U#/value}}元'),('港元','人民币{{e:U#/value}}港币'),
                          ('元','{{e:U#/value}}万元'),('元','万元{{e:U#/value}}')]:
            with self.subTest(text=text):self.assertTrue(unit_errors(self.case(unit),text))
    def test_year_month_prefix_is_not_silently_ignored(self):
        for unit,text in [('元/年','每月{{e:U#/value}}元'),
                          ('元/月','每年{{e:U#/value}}元'),
                          ('元/年','月度{{e:U#/value}}元')]:
            with self.subTest(text=text):self.assertTrue(unit_errors(self.case(unit),text))
    def test_year_month_prefix_must_not_conflict_with_explicit_suffix(self):
        self.assertTrue(unit_errors(self.case('元/年'),'每月{{e:U#/value}}元/年'))
        self.assertTrue(unit_errors(self.case('元/月'),'每年{{e:U#/value}}元/月'))


class ClaimPhraseBoundaries(unittest.TestCase):
    def test_explicit_denial_is_not_an_affirmative_personal_probability(self):
        self.assertFalse(personal_probability_errors('群体比例80%不意味着你有80%的录取机会。'))
    def test_probability_as_decimal_ratio_is_still_personal(self):
        self.assertTrue(personal_probability_errors('你录取的概率为0.8。'))
    def test_group_ratio_and_reader_research_task_are_not_personal_probability(self):
        self.assertFalse(personal_probability_errors('你需要核对该群体80%的学生获得实习机会的统计口径。'))

if __name__=='__main__':unittest.main()

class HznuPublicServiceDomain(unittest.TestCase):
    def test_actual_official_catalogue_service_has_a_narrow_verified_row(self):
        row=official_domain_for_url('https://yjsfw.hznu.edu.cn/dataapi/open/zsss/zsml?mllx=0&zsnf=2026')
        self.assertIsNotNone(row)
        self.assertEqual(row['domain'],'yjsfw.hznu.edu.cn')
        self.assertIn('https://yjs.hznu.edu.cn/c/2025-09-28/3113195.shtml',row['evidence'])
        self.assertIsNone(official_domain_for_url('https://yjsfw.hznu.edu.cn.attacker.example/catalog'))
        self.assertIsNone(official_domain_for_url('https://yjsfw.hznu.edu.cn@attacker.example/catalog'))

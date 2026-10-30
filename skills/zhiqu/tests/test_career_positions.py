"""Offline fixtures imitate observed structure, not real applicants or contacts."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'
sys.path.insert(0,str(SCRIPTS))
import career_on_demand as m
import career_positions as p
from test_career_on_demand import database,metadata


def query(region='宁波市'):
    return dict(region=region,direction='开发',years=[2026],stage='internship',layers=['duties','requirements','pay','schedule'],
                seconds=120,database='unused',entries=[entry()])


def entry():return dict(url='https://www.eitech.edu.cn/notice.htm',publisher='合成大学')


def article(location=True):
    paras=['一、所属部门','合成部门','二、实习内容','开发页面和测试','三、实习目标','完成明确任务','具体实习周期、每周到岗时间和任务安排面议。','四、任职要求','本科在读。'+('能够到宁波东方理工大学校内参与实习。'if location else ''),'五、你将获得','项目经验','六、薪酬与福利待遇','具体薪酬面议。','七、应聘方式','不保留申请材料']
    return ('<html><title>AI开发实习生（合成课题组）</title><body>合成大学 发布时间：2026-09-01<div class="wp_articlecontent">'+''.join('<p>'+s+'</p>'for s in paras)+'</div><footer>地址：宁波市</footer></body></html>').encode()


def popup(city='杭州',title='后端开发实习生'):
    paras=['2026 年 9 月 24 日','中国·'+city+' |','关于这个岗位','','你将参与的工作 开发系统','','任职要求 本科在读，每周4天，连续4个月。','','技术要求 Java','','素质要求 认真','','加分项 数据库']
    return '<div class="fl-button-lightbox-content mfp-hide"><h1>'+title+'</h1><div>'+''.join('<p>'+s+'</p>'for s in paras)+'</div></div>'


def tngbody():return ('<html><title>Careers</title><body>TNG Digital Sdn Bhd'+popup()+popup('武汉','前端开发实习生')+'</body></html>').encode()


class PositionTests(unittest.TestCase):
    def test_article_retains_anonymous_fields_and_historical_date(self):
        result=p.parse_position(article(),entry(),query());row=result['rows'][0]
        p.validate_position_proof(row,result['proofs'][0])
        self.assertEqual(row['year_basis'],'publication_date');self.assertIsNone(row['recruitment_year'])
        self.assertEqual(row['position'],'AI开发实习生');self.assertEqual(row['fields']['pay'],'具体薪酬面议。')
        self.assertNotIn('合成课题组',json.dumps(result,ensure_ascii=False));self.assertNotIn('申请材料',json.dumps(result,ensure_ascii=False))

    def test_footer_address_not_position_city(self):
        with self.assertRaises(m.Gap):p.parse_position(article(False),entry(),query())

    def test_date_not_graduate_eligibility(self):
        q=query();q['stage']='graduate'
        with self.assertRaises(m.Gap):p.parse_position(article(),entry(),q)

    def test_stage_not_inferred_from_requirements(self):
        with self.assertRaises(m.Gap):p.parse_position(article().replace('开发实习生'.encode(),'开发工程师'.encode()),entry(),query())

    def test_contacts_in_retained_field_rejected(self):
        with self.assertRaises(m.Gap):p.parse_position(article().replace('具体薪酬面议。'.encode(),'请联系，电话13812345678'.encode()),entry(),query())

    def test_two_read_disagreement_rejected(self):
        original=p.BodyReader.handle_data
        def damaged(self,text):return original(self,text.replace('开发页面','错误页面'))
        with patch.object(p.BodyReader,'handle_data',damaged),self.assertRaises(m.Gap):p.parse_position(article(),entry(),query())

    def test_boden_no_year_not_guessed(self):
        with self.assertRaisesRegex(m.Gap,'未提供招聘年度'):
            p.parse_position(b'<title>Careers</title><div class="career-card-container">2026 copyright</div>',dict(url='https://www.bodenai.com/careers',publisher='合成单位'),query())

    def test_tng_popup_positions_never_cross_city(self):
        q=query('杭州市');e=dict(url='https://www.tngdigital.com.cn/tngd_career/',publisher='TNG Digital Sdn Bhd')
        result=p.parse_position(tngbody(),e,q)
        self.assertEqual([r['position']for r in result['rows']],['后端开发实习生'])
        self.assertIsNone(result['rows'][0]['fields']['pay'])
        p.validate_position_proof(result['rows'][0],result['proofs'][0])
        self.assertEqual(result['proofs'][0]['visibility_basis'],'inline_lightbox_static_html')

    def test_body_proof_cannot_relabel_work_city(self):
        q=query('杭州市');e=dict(url='https://www.tngdigital.com.cn/tngd_career/',publisher='TNG Digital Sdn Bhd')
        r=p.parse_position(tngbody(),e,q);r['rows'][0]['region']='宁波市'
        with self.assertRaises(m.Gap):p.validate_position_proof(r['rows'][0],r['proofs'][0])

    def test_body_date_cannot_be_invalid(self):
        r=p.parse_position(article(),entry(),query());r['rows'][0]['published']='2026-99-99'
        with self.assertRaises(m.Gap):p.validate_position_proof(r['rows'][0],r['proofs'][0])

    def test_incomplete_field_locator_rejected(self):
        r=p.parse_position(article(),entry(),query());r['proofs'][0]['sample_rows'].remove(4)
        with self.assertRaises(m.Gap):p.validate_position_proof(r['rows'][0],r['proofs'][0])

    def test_publish_and_cache_keep_year_and_field_proofs(self):
        q=query()
        with patch.object(m,'publisher_matches',return_value=True):
            r=m.run_request(q,lookup_fn=lambda *_:[],fetch=lambda url,_:(dict(url=url,body=article()),{}))
            self.assertEqual(len(r['candidates']),1)
            with tempfile.TemporaryDirectory()as td:
                root=Path(td);db=root/'employment.sqlite';database(db)
                m.publish_result(r,db,root/'run',m.Deadline(120),metadata_builder=metadata,validator=lambda _:0)
                cached=m.lookup(db,q)
                self.assertEqual(len(cached),4)
                self.assertEqual(cached[0]['metadata']['year_basis'],'publication_date')
                self.assertTrue(cached[0]['metadata']['field_locators'])
                found=m.zhiqu_db.query_jobs(region='宁波市',year=2026,db=db)
                row=found['sections'][0]['rows'][0]
                self.assertEqual(row['career_scope']['year_basis'],'publication_date')
                self.assertIn('公告发布',row['context']['年份口径'])
                self.assertEqual(row['career_scope']['field_locators'],cached[0]['metadata']['field_locators'])


if __name__=='__main__':unittest.main()

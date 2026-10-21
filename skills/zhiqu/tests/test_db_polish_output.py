"""Presentation contracts: scope is retained; compact output does not mutate data."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts/zhiqu_db.py'
spec=importlib.util.spec_from_file_location('db_polish_output',SCRIPT)
db=importlib.util.module_from_spec(spec);spec.loader.exec_module(db)


def value(raw, source='a'):
    return {'value':raw,'unit':'','grade':'第三方整理','publisher':'汇编',
            'source_id':source,'value_status':{'status':'第三方整理未核'}}


def row(raw, source='a', context=None):
    return {'context':context or {},'values':{'recommend_rate':value(raw,source)},
            'source':{'source_id':source,'publisher':'汇编','title':'地区汇编',
                      'landing_url':'https://example.edu.cn/'+source},
            'locator':{'src_sheet':'主表','src_row':3}}


def result(rows, table='institution_profile', total=None):
    return {'query':'school','sections':[{'table':table,'title':'学校概况',
             'total':len(rows) if total is None else total,'offset':0,
             'returned':len(rows),'truncated':0,'rows':rows}]}


class PolishOutput(unittest.TestCase):
    def test_compact_skips_missing_numbers_and_keeps_full_scope_in_full(self):
        item=row(0,context={'year':2025,'record_type':'internal_type','scope_raw':'[["适用","普通计划"]]'})
        item['values']['min_score']=value(None)
        item['values']['min_score']['value_status']={'status':'来源未提供'}
        data=result([item],'gk_official_cutoff')
        short=db.render_text(data);full=db.render_text(data,full=True)
        self.assertNotIn('最低分：',short)
        self.assertIn('最低分：',full)
        self.assertNotIn('internal_type',short)
        self.assertIn('internal_type',full)
        self.assertIn('保研比例：0',short)
        self.assertIn('普通计划',short)

    def test_missing_only_row_groups_absence_but_does_not_hide_missing_original(self):
        item=row(None)
        item['values']={k:{**value(None),'value_status':{'status':'来源未提供'}} for k in ['planned','min_score','min_rank','admitted']}
        short=db.render_text(result([item],'gk_official_cutoff'))
        self.assertIn('等4项：来源未提供',short)
        self.assertEqual(short.count('：来源未提供〔'),1)
        item['values']['min_score']['value_status']={'status':'原件缺失'}
        self.assertIn('原件缺失〔',db.render_text(result([item],'gk_official_cutoff')))

    def test_profile_same_field_value_once_with_all_source_ids(self):
        text=db.render_text(result([row(.128,'a'),row(.128,'b')]))
        self.assertEqual(text.count('保研比例：0.128'),1)
        self.assertIn('出处：a',text);self.assertIn('出处：b',text)
        self.assertNotIn('来源之间不一致',text)

    def test_conflicting_profile_values_parallel_with_their_sources(self):
        text=db.render_text(result([row(.128,'a'),row(.149,'b')]))
        self.assertIn('0.128〔第三方整理｜汇编｜S1',text)
        self.assertIn('0.149〔第三方整理｜汇编｜S2',text)
        self.assertEqual(text.count('来源之间不一致'),1)
        self.assertEqual(sum('保研比例：' in line for line in text.splitlines()),1)

    def test_default_ten_rows_and_full_expands_current_page_only(self):
        data=result([row(i,context={'year':2025,'province':'江苏'}) for i in range(15)],'gk_official_cutoff',30)
        data['sections'][0]['truncated']=15
        short=db.render_text(data);full=db.render_text(data,full=True)
        self.assertEqual(short.count('省份：江苏'),10)
        self.assertEqual(sum('省份：江苏' in line and ' | ' in line for line in full.splitlines()),15)
        self.assertIn('后续20行未显示',short);self.assertIn('后续15行未显示',full)

    def test_score_scopes_never_collapsed_like_profiles(self):
        rows=[row(600,context={'year':2025,'province':province,'plan_type':plan})
              for province,plan in [('江苏','普通'),('浙江','中外合作')]]
        text=db.render_text(result(rows,'gk_official_cutoff'))
        self.assertEqual(text.count('保研比例：600'),2)
        self.assertIn('省份：江苏',text);self.assertIn('省份：浙江',text)
        self.assertIn('计划类型：中外合作',text)

    def test_list_count_only_when_structured_or_unambiguous(self):
        for raw in (['哲学','法学'],'["哲学", "法学"]','哲学；法学','哲学\n法学'):
            with self.subTest(raw=raw):
                text=db.render_text(result([{'context':{'master_list':raw},'values':{}}]))
                self.assertIn('硕士点：2 个（--full 查看名单）',text)
                self.assertNotIn('法学',text)

    def test_ambiguous_list_not_counted_by_commas_or_guessed(self):
        text=db.render_text(result([{'context':{'phd_list':'哲学,法学（含方向说明）'},'values':{}}]))
        self.assertIn('原名单待核',text);self.assertNotIn('2 个',text)

    def test_full_shows_list_original_and_long_cell(self):
        raw='哲学；'+'学科甲'*100
        data=result([{'context':{'master_list':raw},'values':{}}])
        self.assertIn(raw,db.render_text(data,full=True))
        self.assertNotIn('学科甲',db.render_text(data))

    def test_profile_context_tags_levels_are_not_lost(self):
        data=result([{'context':{'school_tags':'双一流','degree_level':'本科','master_list':'甲；乙'},'values':{}}])
        text=db.render_text(data)
        self.assertIn('双一流',text);self.assertIn('本科',text);self.assertIn('2 个',text)

    def test_sources_come_after_rows_not_dictionary_repr(self):
        text=db.render_text(result([row(.128)]))
        self.assertLess(text.index('保研比例：'),text.index('来源详情：'))
        self.assertIn('网页：https://example.edu.cn/a',text)
        self.assertNotIn("{'source_id'",text)
        self.assertNotIn('landing_url：',text)

    def test_query_data_not_mutated_including_nested_source_objects(self):
        data=result([row(.128),row(.128,'b')]);before=copy.deepcopy(data)
        db.render_text(data);db.render_text(data,full=True)
        self.assertEqual(data,before)

    def test_normalized_attribute_table_multiple_source_interface(self):
        r=row(.128);r['sources']=[{'source':{'source_id':'b','grade':'官方','publisher':'学校'},'locator':{'src_row':8}}]
        text=db.render_text(result([r],'school_attribute_fact'))
        self.assertIn('出处：b',text);self.assertIn('行：8',text)

    def test_explicit_conflict_annotation(self):
        r=row(.128);r['source_conflict']='来源之间不一致'
        self.assertIn('来源之间不一致',db.render_text(result([r],'school_attribute_fact')))


    def test_conflict_group_not_cut_by_ten_row_cap(self):
        rows=[{'context':{},'values':{'field'+str(i):value(i)},'source':{'source_id':'a'}} for i in range(9)]
        rows.extend([row(.128,'a'),row(.149,'b')])
        text=db.render_text(result(rows,'school_attribute_fact'))
        self.assertIn('0.128',text);self.assertIn('0.149',text)
        self.assertEqual(sum(' | ' in line and '〔' in line for line in text.splitlines()),10)

    def test_declared_list_count_without_guessing_comma_split(self):
        raw='哲学,法学（含其他说明）'
        r={'context':{},'values':{'master_list':dict(value(raw),declared_count=88)}}
        text=db.render_text(result([r],'school_attribute_fact'))
        self.assertIn('88 个（原表数量；--full 查看名单）',text)
        self.assertNotIn(raw,text);self.assertIn(raw,db.render_text(result([r],'school_attribute_fact'),full=True))

    def test_invalid_declared_count_does_not_invent_list_count(self):
        for declared in (-1,'88',True,None):
            r={'context':{},'values':{'master_list':dict(value('哲学,法学'),declared_count=declared)}}
            self.assertIn('原名单待核',db.render_text(result([r],'school_attribute_fact')))

    def test_short_reference_scope_resets_each_section(self):
        data=result([row(.128,'long-vendor-sha-abc')]);data['sections'].append(result([row(.149,'other-vendor')])['sections'][0])
        text=db.render_text(data)
        self.assertEqual(text.count('汇编｜S1；'),2)
        self.assertIn('[S1] 来源：出处：long-vendor-sha-abc',text)
        self.assertIn('[S1] 来源：出处：other-vendor',text)

    def test_context_field_conflict_all_values_visible(self):
        data=result([{'context':{'school_tags':'双一流'},'values':{}},{'context':{'school_tags':'省重点'},'values':{}}])
        text=db.render_text(data)
        self.assertIn('双一流',text);self.assertIn('省重点',text)
        self.assertEqual(sum('来源之间不一致' in line for line in text.splitlines()),1)


    def test_default_source_rows_capped_and_internal_json_hidden(self):
        huge='{"members":['+'{"note":"internal-member"},'*2000+']}';r=row(.128)
        r['source'].update(title='标题'*200,note=huge,citation=huge)
        r['sources']=[{'source':{'source_id':'extra'+str(i),'publisher':'整理方','title':'普通标题','note':huge,'citation':huge},'locator':{'src_row':i+3}} for i in range(14)]
        data=result([r]);before=copy.deepcopy(data)
        text=db.render_text(data);full=db.render_text(data,full=True)
        self.assertNotIn('internal-member',text);self.assertNotIn('members',text)
        self.assertLess(len(text),7000)
        self.assertEqual(sum('来源：出处：' in line for line in text.splitlines()),10)
        self.assertIn('另5条来源未展开',text)
        self.assertIn('internal-member',full);self.assertEqual(data,before)
        line=next(line for line in text.splitlines() if '标题：' in line)
        self.assertLessEqual(len(line.split('标题：',1)[1].split('；',1)[0]),60)

    def test_many_rows_same_source_one_line_with_noncontinuous_warning(self):
        rows=[row(.128) for _ in range(4)]
        for i,r in enumerate(rows):r['locator']={'src_row':i*10+1,'src_sheet':'主表'}
        text=db.render_text(result(rows))
        self.assertEqual(sum('来源：出处：' in line for line in text.splitlines()),1)
        self.assertIn('可能不连续',text)

    def test_existing_locator_summary_not_reported_as_continuous_rows(self):
        r=row(.128);r['locator']={'src_sheet':'表','first_row':1,'last_row':100,'matched_rows':3}
        text=db.render_text(result([r]))
        self.assertIn('行边界：1—100（可能不连续；匹配3行',text)
        self.assertIn('全部逐行关联保留在库中，此处为边界摘要',text)
        self.assertNotIn('逐行位置见--full/--json',text)

    def test_profile_header_counts_fields_separately_from_distinct_values(self):
        data=result([row(.128),row(.149,'b')],'school_attribute_fact')
        data['sections'][0].update(total=1,fact_count=2)
        text=db.render_text(data)
        self.assertIn('共1字段（2个不同值）；本页1字段',text)

    def test_full_does_not_change_cli_pagination_or_json(self):
        data=result([row(.128)])
        with patch.object(db,'query_school',return_value=data) as query:
            out=io.StringIO()
            with contextlib.redirect_stdout(out):db.main(['school','甲大学','--full','--json','--limit','3','--offset','4'])
            self.assertEqual(json.loads(out.getvalue()),data)
            self.assertEqual(query.call_args.kwargs['limit'],3)
            self.assertEqual(query.call_args.kwargs['offset'],4)
            self.assertNotIn('full',query.call_args.kwargs)


if __name__=='__main__':unittest.main()

"""Contract, provenance and publication regression tests on the two complete cases."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from planning_workflow import PlanningCase,FILES,read,dump,sha
from planning_report import assemble,generate,node_markdown
from operator_check import selected_evidence,generate as checklist,validate_operator,MARKER,fingerprint
from check_report import check_planning_contract
from case_check import run

SKILLS=SCRIPTS.parents[1]

class PlanningWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.roots={}
        for kind in ('grad','career'):
            dest=Path(self.temp.name)/kind
            shutil.copytree(SKILLS/f'zhiqu-{kind}/examples/demo_2027',dest)
            self.roots[kind]=dest

    def change(self,root,file,fn):
        obj=read(root/file);fn(obj);dump(root/file,obj)

    def entry(self,root,slot,sid='01'):
        c=PlanningCase(root)
        e=next(x for x in c.nodes()[sid] if x['slot']==slot)
        f,_,path=e['ref'].partition('#')
        return f,path,c.get_node(e['ref'])

    def mutate_node(self,root,slot,fn,sid='01'):
        f,path,node=self.entry(root,slot,sid)
        def update(obj):
            from planning_workflow import pointer
            fn(pointer(obj,path))
        self.change(root,f,update)

    def test_complete_cases_and_existing_calculations_pass(self):
        for kind,root in self.roots.items():
            with self.subTest(kind=kind):
                self.assertEqual(run(root,8).errors,[])
                self.assertEqual(check_planning_contract(root),[])

    def test_each_kind_rejects_missing_required_component(self):
        for root in self.roots.values():
            self.change(root,'judgment.json',lambda j:j['presentation']['01'].__setitem__(slice(None),[x for x in j['presentation']['01'] if x['slot']!='kpis']))
            self.assertTrue(any('01.kpis' in e for e in check_planning_contract(root)))

    def test_each_kind_rejects_untraceable_factual_number(self):
        for root in self.roots.values():
            self.mutate_node(root,'lead',lambda n:n['content'].update(text='学费为 19,999 元。'))
            self.assertTrue(any('19,999' in e for e in check_planning_contract(root)))

    def test_each_kind_rejects_undated_summary_actions(self):
        for root in self.roots.values():
            self.mutate_node(root,'actions',lambda n:n['content']['items'][0].pop('date'))
            self.assertTrue(any('事项缺有效日期' in e for e in check_planning_contract(root)))

    def test_structural_three_things_and_registered_target_year_are_allowed(self):
        for root in self.roots.values():
            self.mutate_node(root,'lead',lambda n:n['content'].update(text='先办好三件事，再核对两条路；目标为2027年。第 1 个志愿另核。[1]'))
            self.assertEqual(check_planning_contract(root),[])

    def test_personal_values_are_directly_allowed_but_policy_cannot_use_registration(self):
        for root in self.roots.values():
            c=PlanningCase(root)
            self.assertEqual(c.numeric_errors('目标{{k:/target_year}}年，专业{{p:/fields/1/value}}。'),[])
            self.assertTrue(c.numeric_errors('学费{{k:/budget/annual_tuition}}元。'))
            self.assertTrue(c.numeric_errors('学费2027元。'))
            self.assertTrue(c.numeric_errors('报名日期2026-10-24。'))
            self.assertTrue(c.numeric_errors('{{p:/fields/0/quote}}'))

    def test_unused_stage_reference_is_also_checked(self):
        root=self.roots['grad']
        self.change(root,'judgment.json',lambda j:j['candidates'][0].update(evidence_refs=['E404']))
        self.assertTrue(any('引用不存在' in e for e in run(root,5).errors))

    def test_rule_stage_cannot_be_skipped_with_empty_items(self):
        root=self.roots['career'];self.change(root,'rules_check.json',lambda r:r.update(items=[]))
        self.assertTrue(any('缺用到的规则' in e for e in run(root,3).errors))

    def test_inferred_profile_value_cannot_become_fact(self):
        root=self.roots['grad'];self.change(root,'profile_parse.json',lambda p:p['fields'][0].update(status='inferred'))
        self.assertTrue(PlanningCase(root).numeric_errors('{{p:/fields/0/value}}'))
        self.assertTrue(any('须列missing' in e for e in run(root,1).errors))

    def test_dangling_ref_unknown_format_and_raw_json_number_are_rejected(self):
        c=PlanningCase(self.roots['grad'])
        for text in ('{{e:E9999#/value}}','{{c:/annual_cost|wrong}}','{{c:/absent}}'):
            self.assertTrue(c.numeric_errors(text))
        self.assertTrue(c.numeric_tree({'amount':12},'test'))

    def test_contract_cannot_read_an_unregistered_subtree(self):
        root=self.roots['grad'];self.change(root,'narrative.json',lambda n:n.update(secret=n['sections']['01']['lead']))
        self.change(root,'judgment.json',lambda j:j['presentation']['01'][0].update(ref='narrative.json#/secret'))
        self.assertTrue(any('位置' in e for e in check_planning_contract(root)))

    def test_no_handwritten_chapter_table_or_component_in_narrative(self):
        root=self.roots['grad']
        for text in ('## 新章节','| 表 | 数据 |','::: bars 绕过'):
            self.mutate_node(root,'lead',lambda n:n['content'].update(text=text))
            self.assertTrue(any('叙述包含' in e for e in check_planning_contract(root)))

    def test_matrix_threshold_uses_strict_more_than(self):
        c=PlanningCase(self.roots['grad']);slot={'condition':'matrix_unknown_ratio_gt_0_7'}
        c.data['judgment.json']['matrix']['cells']=[{'status':'unknown'}]*7+[{'status':'supported'}]*3
        self.assertFalse(c.active(slot))
        c.data['judgment.json']['matrix']['cells'][7]['status']='unknown'
        self.assertTrue(c.active(slot))

    def test_matrix_missing_cell_and_unknown_explanation_are_rejected(self):
        root=self.roots['career'];self.change(root,'judgment.json',lambda j:j['matrix']['cells'].pop())
        self.assertTrue(any('缺失行列格' in e for e in check_planning_contract(root)))
        self.change(root,'judgment.json',lambda j:j['presentation']['05'].__setitem__(slice(None),[x for x in j['presentation']['05'] if x['slot']!='unknown_explanation']))
        self.assertTrue(any('unknown_explanation' in e for e in check_planning_contract(root)))

    def test_rule_requires_current_official_original(self):
        root=self.roots['grad'];rule=read(root/'rules_check.json')['items'][0]
        self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']==rule['evidence_refs'][0]).update(status='unretrieved',gap='拦截'))
        self.assertTrue(any('官方原文' in e for e in run(root,3).errors))
        self.change(root,'rules_check.json',lambda r:r['items'][0].update(verified_on='2025-01-01'))
        self.assertTrue(any('及时复核' in e for e in run(root,3).errors))

    def test_unknown_eligibility_cannot_be_marked_met(self):
        root=self.roots['grad']
        def fail(c):
            x=c['school_programs'][2];x['hard_conditions'][0]['status']='met';x['status']='verified'
        self.change(root,'candidates.json',fail)
        self.assertTrue(any('met缺' in e for e in run(root,4).errors))

    def test_case_input_source_and_calculation_must_match(self):
        root=self.roots['grad'];self.change(root,'case.json',lambda c:c['budget'].update(annual_tuition=9000))
        errors=run(root,6).errors
        self.assertTrue(any('复算' in e for e in errors));self.assertTrue(any('输入与来源' in e for e in errors))

    def test_generic_registered_operations_accept_only_recomputed_results(self):
        root=self.roots['grad'];c=PlanningCase(root)
        c.case['calculation_plan']={'operations':[{'output':'amount','algorithm':'sum','inputs':['{{k:/budget/annual_limit}}','{{k:/budget/annual_limit}}']}],
                                  'scenarios':[{'baseline_output':'amount','changed_inputs':{'{{k:/budget/annual_limit}}':'{{k:/budget/monthly_living_assumption}}'},'why':'A','output_ref':'{{c:/scenario_a}}'},{'baseline_output':'amount','changed_inputs':{'{{k:/budget/annual_limit}}':'{{p:/fields/4/value/cet4}}'},'why':'B','output_ref':'{{c:/scenario_b}}'}]}
        c.data['calculations.json']={'amount':60000,'scenario_a':2600,'scenario_b':930};c.stage6();self.assertEqual(c.errors,[])
        c.case['calculation_plan']['operations'][0]['algorithm']='__import__'
        with self.assertRaises(ValueError):c.stage6()

    def test_duplicate_or_unregistered_scenario_rejected(self):
        root=self.roots['career']
        def fail(c):c['calculation_plan']['scenarios'][1]=copy.deepcopy(c['calculation_plan']['scenarios'][0])
        self.change(root,'case.json',fail)
        self.assertTrue(any('情景重复' in e for e in run(root,6).errors))

    def test_unconfirmed_numeric_weights_are_rejected(self):
        root=self.roots['career'];self.change(root,'judgment.json',lambda j:j['preferences'].update(method='numeric',weights={'salary':1},confirmed=False))
        self.assertTrue(any('权重未经确认' in e for e in run(root,7).errors))

    def test_operator_union_and_indirect_main_dependencies(self):
        def evidence(eid,**kw):
            return dict(id=eid,grade='官方',status='verified',review_due='2027-08-01',**kw)
        items=[evidence('normal'),evidence('nonofficial'),evidence('blocked'),evidence('soon'),evidence('main')]
        items[1]['grade']='单人说法';items[2]['status']='unretrieved';items[3]['review_due']='2026-10-25'
        j={'recommendation':{'primary':['C1']},'candidates':[{'candidate_id':'C1','calc_refs':['c:/amount']} ]}
        result=selected_evidence(items,'2026-10-19',j,30,{'c:/amount':['main']})
        self.assertEqual({e['id'] for e,r in result},{'nonofficial','blocked','soon','main'})
        self.assertIn('影响主结论',dict((e['id'],r) for e,r in result)['main'])

    def test_operator_text_is_practical_and_no_confirmations_are_fabricated(self):
        for root in self.roots.values():
            text=checklist(root).read_text()
            self.assertNotIn('{{',text)
            for _,body in ((json.loads(m[1]),m[2]) for m in MARKER.finditer(text)):
                self.assertTrue(all(k in body for k in ('核什么：','去哪里核：','核完填：')))
            self.assertEqual(validate_operator(root),[])
            self.assertTrue(validate_operator(root,True))

    def test_operator_preserves_unchanged_human_entry_and_resets_changed_fact(self):
        root=self.roots['grad'];p=checklist(root);text=p.read_text();first=next(MARKER.finditer(text));eid=json.loads(first[1])['id']
        edited=first[2].replace('- [ ]','- [x]').replace('___','已核')
        p.write_text(text[:first.start(2)]+edited+text[first.end(2):]);checklist(root)
        self.assertIn('- [x]',p.read_text())
        self.change(root,'evidence.json',lambda data:next(x for x in data['items'] if x['id']==eid).update(claim='条件已改变'))
        self.assertTrue(validate_operator(root));checklist(root)
        first=next(MARKER.finditer(p.read_text()));self.assertNotIn('- [x]',first[2])

    def test_operator_detects_removed_required_item(self):
        root=self.roots['career'];p=checklist(root);text=p.read_text();m=next(MARKER.finditer(text));p.write_text(text[:m.start()]+text[m.end():])
        self.assertTrue(validate_operator(root))

    def test_gaokao_adapter_never_changes_existing_inputs(self):
        root=Path(self.temp.name)/'gaokao';root.mkdir();report={'sources':[['规则','https://example.edu.cn/rule']]}
        dump(root/'report.json',report);dump(root/'result.json',{'probability':0.3})
        before={p.name:sha(p) for p in root.iterdir()};checklist(root)
        self.assertEqual(before,{n:sha(root/n) for n in before});self.assertEqual(validate_operator(root),[])

    def test_assembly_is_deterministic_and_content_remains_stage_bound(self):
        for root in self.roots.values():
            c=PlanningCase(root);a,trace=assemble(c);b,_=assemble(c)
            self.assertEqual(a,b);self.assertTrue(trace);self.assertNotIn('{{',a)
            self.assertEqual(len(__import__('re').findall(r'^## \d{2} ',a,__import__('re').M)),12)

    def test_actions_display_typed_date_even_without_date_in_text(self):
        text=node_markdown({'type':'dated_actions','content':{'items':[{'text':'核对资格','date':'2026-10-21'}]}},str,{})
        self.assertIn('2026-10-21',text)

    def test_failed_content_or_render_gate_does_not_replace_previous_outputs(self):
        root=self.roots['grad'];names=('report.md','report.html','report.pdf','report_trace.json','operator_check.md');before={n:(root/n).read_bytes() for n in names}
        with patch('render_report.render',side_effect=ValueError('渲染故障')):
            with self.assertRaises(ValueError):generate(root,html_only=True)
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})
        self.mutate_node(root,'lead',lambda n:n['content'].update(text='学费999999元'))
        with self.assertRaises(ValueError):generate(root,html_only=True)
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})

    def test_pdf_layout_and_operator_failure_do_not_publish_partial_files(self):
        from types import SimpleNamespace
        root=self.roots['career'];names=('report.md','report.html','report.pdf','report_trace.json','operator_check.md');before={n:(root/n).read_bytes() for n in names}
        def render_pdf(cmd,**kw):
            Path(cmd[-1]).write_bytes(b'prepared-only');return SimpleNamespace(returncode=0,stdout='',stderr='')
        with patch('subprocess.run',side_effect=render_pdf),patch('check_layout.check_pdf',return_value=['版面挤压']):
            with self.assertRaises(ValueError):generate(root)
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})
        with patch('operator_check.generate',side_effect=ValueError('核查单生成失败')):
            with self.assertRaises(ValueError):generate(root,html_only=True)
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})

    def test_filesystem_replacement_failure_rolls_back(self):
        root=self.roots['grad'];names=('report.md','report.html','report_trace.json','operator_check.md');before={n:(root/n).read_bytes() for n in names}
        import os
        replace=os.replace;calls=[]
        def fail_second(a,b):
            calls.append(b)
            if len(calls)==2:raise OSError('磁盘写入失败')
            return replace(a,b)
        with patch('planning_report.os.replace',side_effect=fail_second):
            with self.assertRaises(OSError):generate(root,html_only=True)
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})

    def test_only_human_completed_items_can_pass_completion(self):
        root=self.roots['career'];p=checklist(root);text=p.read_text().replace('- [ ]','- [x]')
        text=text.replace('核查人：___','核查人：测试人员').replace('核查日期：___','核查日期：2026-10-19').replace('结果（确认/不符/仍未知）：___','结果（确认/不符/仍未知）：确认').replace('原文依据与范围：___','原文依据与范围：原件对应条款').replace('对建议的处理：___','对建议的处理：保持条件判断')
        p.write_text(text);self.assertEqual(validate_operator(root,True),[])
        p.write_text(text.replace('：确认；','：仍未知；',1));self.assertTrue(validate_operator(root,True))

    def test_html_generation_records_hashes_and_detects_stale_inputs(self):
        root=self.roots['career'];generate(root,html_only=True)
        c=PlanningCase(root);self.assertEqual(c.trace_errors(),[])
        self.change(root,'case.json',lambda x:x.update(version='变更'))
        self.assertTrue(PlanningCase(root).trace_errors())

    def test_self_assessment_passes_without_claiming_delivery_approval(self):
        from planning_workflow import RUBRIC,review_errors
        root=self.roots['grad'];generate(root,html_only=True)
        files=(*FILES,'profile.txt','report.md','report.html','report.pdf','report_trace.json','operator_check.md')
        review={'status':'awaiting_independent_review','independent':False,
                'self_assessment':{'rubric':{'items':[{'id':key,'score':1 if key=='traceability' else 2,'reason':'测试用自评理由'} for key in RUBRIC]}},
                'snapshot':{f:sha(root/f) for f in files}}
        dump(root/'review.json',review)
        self.assertEqual(review_errors(root),[])
        self.assertTrue(review_errors(root,True))
        self.assertEqual(run(root,10).errors,[])
        self.change(root,'case.json',lambda x:x.update(version='新版'))
        self.assertTrue(any('失效' in e for e in review_errors(root)))

    def test_zero_or_below_contract_review_score_is_rejected(self):
        from planning_workflow import RUBRIC,review_errors
        root=self.roots['career']
        review={'rubric':{'items':[{'id':key,'score':1,'reason':'待补核'} for key in RUBRIC]},'snapshot':{}}
        dump(root/'review.json',review)
        self.assertTrue(any('评分未达标' in e for e in review_errors(root)))
        review['rubric']['items'][0]['score']=0;dump(root/'review.json',review)
        self.assertTrue(any('评分未达标' in e for e in review_errors(root)))

    def test_inactive_income_components_emit_explicit_gap_instead_of_zero_chart(self):
        root=self.roots['career'];c=PlanningCase(root);c.case['context']['offer_basis']='none'
        text,_=assemble(c)
        self.assertNotIn('::: bars',text)
        self.assertIn('当前没有真实offer',text)
        # Changing the real input case this way would be rejected by the stage gate.
        self.change(root,'case.json',lambda x:x['context'].update(offer_basis='none'))
        self.assertTrue(any('跳过收入图' in e for e in run(root,0).errors))

if __name__=='__main__':unittest.main()

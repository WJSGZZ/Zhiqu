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
DEMO={'grad':'2027-YJ-S01','career':'2027-QZ-S01'}

class PlanningWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.roots={}
        for kind in ('grad','career'):
            dest=Path(self.temp.name)/DEMO[kind]
            shutil.copytree(SKILLS/f'zhiqu-{kind}/examples'/DEMO[kind],dest)
            self.roots[kind]=dest

    def change(self,root,file,fn):
        obj=read(root/file);fn(obj);dump(root/file,obj)

    def test_duplicate_profile_labels_rejected_even_when_values_agree(self):
        for kind in ('grad','career'):
            root=self.roots[kind];original=read(root/'profile_parse.json')
            for same_value in (True,False):
                obj=copy.deepcopy(original);duplicate=copy.deepcopy(obj['fields'][0])
                if not same_value:duplicate['value']='不同的合成值'
                obj['fields'].append(duplicate);dump(root/'profile_parse.json',obj)
                errors=PlanningCase(root).check(1)
                self.assertTrue(any('字段名重复' in e for e in errors))
            dump(root/'profile_parse.json',original)

    def test_duplicate_label_whitespace_and_generation_gate(self):
        root=self.roots['grad'];p=read(root/'profile_parse.json');duplicate=copy.deepcopy(p['fields'][0]);duplicate['field']=' '+duplicate['field']+' '
        p['fields'].append(duplicate);dump(root/'profile_parse.json',p)
        self.assertTrue(any('字段名重复' in e for e in PlanningCase(root).check(1)))
        before=(root/'report.md').read_bytes()
        with self.assertRaisesRegex(ValueError,'字段名重复'):generate(root,html_only=True,profile_version='profile.txt')
        self.assertEqual((root/'report.md').read_bytes(),before)

    def test_distinct_labels_with_equal_values_are_allowed(self):
        root=self.roots['grad'];p=read(root/'profile_parse.json');duplicate=copy.deepcopy(p['fields'][0]);duplicate['field']='另一个有区分的含义'
        p['fields'].append(duplicate);dump(root/'profile_parse.json',p)
        self.assertFalse(any('字段名重复' in e for e in PlanningCase(root).check(1)))

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

    def test_timeline_does_not_silently_hide_consequences_in_marker_column(self):
        for value in ('未核不付款','个人节点','{{k:/context/personal_dates/checkpoint}}'):
            with self.subTest(value=value):
                root=self.roots['grad']
                self.mutate_node(root,'timeline',lambda n:n['content']['rows'][0].__setitem__(3,value),'07')
                self.assertTrue(any('不会显示的标记列' in e for e in PlanningCase(root).contract_errors()))

    def test_timeline_visible_note_and_standard_marker_pass(self):
        root=self.roots['grad']
        for marker in ('','普通','检查点'):
            self.mutate_node(root,'timeline',lambda n:n['content']['rows'][0].__setitem__(3,marker),'07')
            self.assertFalse(any('时间线第' in e for e in PlanningCase(root).contract_errors()))
        self.mutate_node(root,'timeline',lambda n:n['content']['rows'][0].__setitem__(2,'未核到资格就暂停付款'),'07')
        markdown,_=assemble(PlanningCase(root))
        self.assertIn('未核到资格就暂停付款',markdown)

    def test_timeline_delimiters_cannot_turn_visible_note_into_hidden_marker(self):
        root=self.roots['grad']
        for value in ('完成核对 | 未核不付款','完成核对\n未核不付款','完成核对\r未核不付款'):
            with self.subTest(value=value):
                self.mutate_node(root,'timeline',lambda n:n['content']['rows'][0].__setitem__(2,value),'07')
                self.assertTrue(any('展开后含分隔符或换行' in e for e in PlanningCase(root).contract_errors()))
        self.change(root,'case.json',lambda c:c['context']['personal_dates'].update(hidden_test_note='完成核对 | 未核不付款'))
        self.mutate_node(root,'timeline',lambda n:n['content']['rows'][0].__setitem__(2,'{{k:/context/personal_dates/hidden_test_note}}'),'07')
        self.assertTrue(any('展开后含分隔符或换行' in e for e in PlanningCase(root).contract_errors()))

    def test_timeline_extra_columns_are_not_silently_dropped(self):
        root=self.roots['grad']
        self.mutate_node(root,'timeline',lambda n:n['content']['rows'][0].append('不应消失的后果'),'07')
        self.assertTrue(any('不能多列或少列' in e for e in PlanningCase(root).contract_errors()))

    def test_personal_input_without_official_source_is_allowed(self):
        for root in self.roots.values():
            self.assertFalse(any('personal_input' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_personal_input_official_url_is_rejected(self):
        root=self.roots['grad']
        self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']=='E0901')['source'].update(url='https://www.moe.gov.cn/notice'))
        self.assertTrue(any('不得带官方网址' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_personal_input_official_institution_is_rejected(self):
        root=self.roots['career']
        self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']=='E0901')['source'].update(organization='教育部'))
        self.assertTrue(any('不得带官方网址' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_scalar_evidence_value_is_allowed(self):
        c=PlanningCase(self.roots['grad'])
        self.assertEqual(c.evidence['E0008']['value'],8000)
        self.assertFalse(any('单个值' in e for e in c.evidence_integrity_errors()))

    def test_dictionary_and_list_evidence_values_are_rejected(self):
        for value in ({'fee':8000},[8000]):
            root=self.roots['grad']
            self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']=='E0008').update(value=value))
            self.assertTrue(any('单个值' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_registered_personal_input_has_exact_pointer(self):
        c=PlanningCase(self.roots['grad'])
        self.assertEqual(next(e for e in c.personal_inputs() if e['id']=='E0901')['registration_ref'],'profile_parse.json#/fields/8/value')
        self.assertFalse(any('必须精确对应' in e for e in c.evidence_integrity_errors()))

    def test_unregistered_or_mismatched_personal_value_is_rejected(self):
        root=self.roots['grad']
        for changes in ({'value':30001},{'registration_ref':'case.json#/budget/annual_tuition'},{'registration_ref':'profile_parse.json#/fields/999/value'}):
            self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']=='E0901').update(**changes))
            self.assertTrue(any('必须精确对应' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_atomic_claim_is_allowed(self):
        for root in self.roots.values():
            self.assertFalse(any('.claim' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_report_sentence_cannot_be_an_evidence_claim(self):
        root=self.roots['grad'];sentence=next(line for line in (root/'report.md').read_text().splitlines() if line.startswith('**'))
        self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']=='E0901').update(claim=sentence))
        self.assertTrue(any('不能复制报告原句' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_official_value_in_original_excerpt_is_allowed(self):
        for root in self.roots.values():
            self.assertFalse(any('.excerpt' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_official_value_missing_from_excerpt_is_rejected(self):
        root=self.roots['grad']
        self.change(root,'evidence.json',lambda e:next(x for x in e['items'] if x['id']=='E0008').update(excerpt='学校另行公布学费。'))
        self.assertTrue(any('未出现在原文摘录' in e for e in PlanningCase(root).evidence_integrity_errors()))

    def test_personal_date_is_one_registered_value(self):
        c=PlanningCase(self.roots['grad'])
        self.assertEqual(c.expand('{{k:/context/personal_dates/action0|md}}'),'10 月 21 日')
        self.assertEqual(c.numeric_errors('{{k:/context/personal_dates/action0|md}}前核对科目。'),[])

    def test_checklist_groups_sources_and_profiles_with_report_positions(self):
        from operator_check import checklist_groups
        for root in self.roots.values():
            groups,_,_=checklist_groups(root)
            self.assertTrue(15<=len(groups)<=25)
            self.assertEqual(sum(g['id']=='PROFILE' for g in groups),1)
            urls=[g['source'].get('url') for g in groups if g['source'].get('url')]
            self.assertEqual(len(urls),len(set(urls)))
            self.assertTrue(any('第 9 节' in check for g in groups for check in g['checks']))

    def test_checklist_program_length_does_not_claim_to_feed_annual_cost(self):
        from operator_check import checklist_groups
        groups,_,_=checklist_groups(self.roots['grad'])
        fee=next(g for g in groups if g['id']=='E0008')
        duration=next(check for check in fee['checks'] if check.startswith('华工非定向全日制能源动力学制'))
        self.assertNotIn('年度费用',duration)
        tuition=next(check for check in fee['checks'] if check.startswith('华工非定向全日制能源动力年度学费'))
        self.assertIn('第 1 节',tuition);self.assertIn('年度费用',tuition)

    def test_ordinary_month_and_wage_conversion_are_calculations(self):
        c=PlanningCase(self.roots['career'])
        self.assertEqual(c.data['calculations.json']['offer_b_ordinary_month']['remaining_cash'],1967)
        self.assertEqual(c.data['calculations.json']['reference_wages_cny']['会计专业人员']['p10'],42000)
        self.assertFalse(any(e.get('value') in (1967,42000,'1,967','42,000') for e in c.evidence.values()))

    def test_sentence_judgments_remain_whole_in_verification_appendix(self):
        from verify_report import planning_materials
        for kind,root in self.roots.items():
            with self.subTest(kind=kind):
                obj=read(root/'judgment.json');candidate=obj['candidates'][0]
                candidate['supports']='已有明确的本人经历线索'
                candidate['counters']='具体岗位原文尚未取得'
                obj['recommendation']['conditions']='只有书面条件核清后才重新比较'
                dump(root/'judgment.json',obj)
                case=PlanningCase(root);self.assertFalse(case.check(7),case.errors)
                _,refs=assemble(case)
                trace=read(root/'report_trace.json')
                materials=planning_materials(case,refs,trace['report_profile'])
                self.assertEqual(materials['shared_conditions'],['只有书面条件核清后才重新比较'])
                row=materials['limitations'][0]
                self.assertEqual(row['claim'],'具体岗位原文尚未取得')
                self.assertEqual(row['reason'],'已有明确的本人经历线索')
                self.assertNotIn('；',row['claim'])

    def test_judgment_text_fields_reject_non_text_containers(self):
        for field in ('supports','counters','conditions'):
            for bad in ([1],[''],{'text':'不是文字列表'},True):
                for kind,root in self.roots.items():
                    with self.subTest(kind=kind,field=field,bad=bad):
                        obj=read(root/'judgment.json')
                        original=copy.deepcopy(obj)
                        if field=='conditions':obj['recommendation'][field]=bad
                        else:obj['candidates'][0][field]=bad
                        dump(root/'judgment.json',obj)
                        try:
                            errors=PlanningCase(root).check(7)
                            self.assertTrue(any(field in e and '非空文字' in e for e in errors),errors)
                        finally:dump(root/'judgment.json',original)

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

    def test_unrequested_source_stays_a_gap_not_verified_fact(self):
        for kind,root in self.roots.items():
            def mark(j):
                item=j['items'][0];item.update(availability='not_requested',status='unretrieved',gap='尚未请求；当前只列调查入口')
            self.change(root,'evidence.json',mark)
            self.assertFalse(any('尚未请求的来源' in e for e in run(root,5).errors))
            self.change(root,'evidence.json',lambda j:j['items'][0].update(status='verified'))
            self.assertTrue(any('尚未请求的来源' in e for e in run(root,5).errors))
            self.change(root,'evidence.json',lambda j:j['items'][0].update(availability='made_up'))
            self.assertTrue(any('来源可得状态' in e for e in run(root,5).errors))

    def test_generation_warns_about_unpresented_narrative_without_inserting_it(self):
        from planning_report import warn_unpresented_narrative, assemble
        from contextlib import redirect_stderr
        from io import StringIO
        for kind,root in self.roots.items():
            self.change(root,'narrative.json',lambda j:j['sections']['03']['analysis'].append(
                {'type':'analysis','content':{'text':'这段新增但还没登记展示的文字'},'evidence_refs':[]}))
            case=PlanningCase(root);index=len(case.data['narrative.json']['sections']['03']['analysis'])-1
            ref='narrative.json#/sections/03/analysis/'+str(index)
            out=StringIO()
            with redirect_stderr(out):unused=warn_unpresented_narrative(case)
            self.assertIn(ref,unused);self.assertIn(ref,out.getvalue())
            self.assertIn('未进入报告',out.getvalue());self.assertNotIn('这段新增但还没登记展示的文字',assemble(case)[0])
            self.change(root,'judgment.json',lambda j:j['presentation']['03'].append({'slot':'analysis','ref':ref}))
            with redirect_stderr(StringIO()):self.assertNotIn(ref,warn_unpresented_narrative(PlanningCase(root)))

    def test_unpresented_warning_includes_inactive_narrative_slots(self):
        from planning_report import warn_unpresented_narrative
        from contextlib import redirect_stderr
        from io import StringIO
        for kind,root in self.roots.items():
            sid='04' if kind=='grad' else '05'
            ref='narrative.json#/sections/'+sid+'/unknown_explanation'
            self.change(root,'narrative.json',lambda j:j['sections'][sid].update(unknown_explanation={
                'type':'unknown_explanation','content':{'missing_information':'待核','retrieval_plan':'查原文','decision_changes':'补后重评'},'evidence_refs':[]}))
            def inactive(j):
                j['presentation'][sid]=[e for e in j['presentation'][sid] if e['slot']!='unknown_explanation']+[{'slot':'unknown_explanation','ref':ref}]
                for cell in j['matrix']['cells']:cell['status']='known'
            self.change(root,'judgment.json',inactive)
            with redirect_stderr(StringIO()):self.assertIn(ref,warn_unpresented_narrative(PlanningCase(root)))
            self.change(root,'judgment.json',lambda j:[cell.update(status='unknown') for cell in j['matrix']['cells']])
            with redirect_stderr(StringIO()):self.assertNotIn(ref,warn_unpresented_narrative(PlanningCase(root)))

    def test_unconfirmed_numeric_weights_are_rejected(self):
        for kind,root in self.roots.items():
            for confirmed in (False, None, 'false', '未确认', 1, ['已确认'], {'value': True}):
                with self.subTest(kind=kind,confirmed=confirmed):
                    self.change(root,'judgment.json',lambda j:j['preferences'].update(
                        method='numeric',weights={'salary':1},confirmed=confirmed))
                    self.assertTrue(any('权重未经确认' in e for e in run(root,7).errors))

    def test_explicit_boolean_confirmation_keeps_numeric_weights_usable(self):
        for kind,root in self.roots.items():
            with self.subTest(kind=kind):
                self.change(root,'judgment.json',lambda j:j['preferences'].update(
                    method='numeric',weights={'salary':1},confirmed=True))
                self.assertEqual(run(root,7).errors,[])

    def test_numeric_weights_reject_bad_values_and_containers(self):
        invalid=(None, {}, [], [1], '1', True,
                 {'salary': True}, {'salary': '1'}, {'salary': None}, {'salary': []},
                 {'salary': float('nan')}, {'salary': float('inf')},
                 {'salary': -1, 'cost': 2}, {'salary': 10**400},
                 {'salary': .5}, {'salary': 0})
        for kind,root in self.roots.items():
            for weights in invalid:
                with self.subTest(kind=kind,weights=weights):
                    self.change(root,'judgment.json',lambda j:j['preferences'].update(
                        method='numeric',weights=weights,confirmed=True))
                    self.assertTrue(any('非空非负有限数值字典且合计为1' in e for e in run(root,7).errors))

    def test_confirmed_zero_and_fractional_weights_remain_valid(self):
        for kind,root in self.roots.items():
            for weights in ({'salary': 1, 'cost': 0}, {'salary': .6, 'cost': .4}):
                with self.subTest(kind=kind,weights=weights):
                    self.change(root,'judgment.json',lambda j:j['preferences'].update(
                        method='numeric',weights=weights,confirmed=True))
                    self.assertEqual(run(root,7).errors,[])

    def test_operator_numeric_inputs_keep_transitive_source_locations(self):
        from operator_check import checklist_groups
        from verification_calculations import _registered
        root=self.roots['grad']
        for literal in (0, -2, 0.5):
            with self.subTest(literal=literal):
                case=read(root/'case.json')
                case['calculation_plan']={'engine':'registered_operations','operations':[
                    {'output':'base','algorithm':'sum','inputs':[literal,'{{e:E0008#/value}}']},
                    {'output':'result','algorithm':'difference','inputs':['{{c:/base}}','{{e:E0008#/value}}']}],
                    'scenarios':[{'baseline_output':'result','changed_inputs':{'{{e:E0008#/value}}':0},
                                  'output_ref':'{{c:/zero_cost}}','why':'取消一个数值费用'}]}
                # Numeric operations and zero-valued scenario replacements are legal.
                dump(root/'case.json',case)
                values,_=_registered(case,read(root/'profile_parse.json'),read(root/'evidence.json'))
                dump(root/'calculations.json',values)
                with patch('operator_check.report_locations',return_value={
                        'c:/result':['第 9 节，合成基准位置'],
                        'c:/zero_cost':['第 9 节，合成零费用情景']}):
                    groups,_,_=checklist_groups(root)
                fee=next(g for g in groups if g['id']=='E0008')
                tuition=next(x for x in fee['checks']if x.startswith('华工非定向全日制能源动力年度学费'))
                self.assertIn('合成基准位置',tuition)
                self.assertIn('合成零费用情景',tuition)

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

    def test_gaokao_checklist_keeps_each_official_file_and_report_position(self):
        from operator_check import checklist_groups
        root=Path(self.temp.name)/'legacy';root.mkdir()
        report={'sources':[['规则','https://example.edu.cn/a；https://example.edu.cn/b']],
                'news':[['计划 20 人','2026-10-19','https://example.edu.cn/b','待核']]}
        dump(root/'report.json',report)
        groups,_,_=checklist_groups(root)
        self.assertEqual({g['source']['url'] for g in groups},{'https://example.edu.cn/a','https://example.edu.cn/b'})
        self.assertTrue(any('计划 20 人 → 第 8 节' in check for g in groups for check in g['checks']))

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

    def test_generate_without_selected_profile_is_rejected_before_publication(self):
        root=self.roots['grad'];before=(root/'case.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'明确指定'):
            generate(root,html_only=True)
        self.assertEqual((root/'case.json').read_bytes(),before)

    def test_failed_content_or_render_gate_does_not_replace_previous_outputs(self):
        root=self.roots['grad'];names=('report.md','report.html','2027-YJ-S01-report.pdf','report_trace.json','operator_check.md');before={n:(root/n).read_bytes() for n in names}
        with patch('render_report.render',side_effect=ValueError('渲染故障')):
            with self.assertRaises(ValueError):generate(root,html_only=True,profile_version="profile.txt")
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})
        self.mutate_node(root,'lead',lambda n:n['content'].update(text='学费999999元'))
        with self.assertRaises(ValueError):generate(root,html_only=True,profile_version="profile.txt")
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})

    def test_pdf_layout_and_operator_failure_do_not_publish_partial_files(self):
        root=self.roots['career'];names=('report.md','report.html','2027-QZ-S01-report.pdf','report_trace.json','operator_check.md');before={n:(root/n).read_bytes() for n in names}
        def render_pdf(document,path):
            Path(path).write_bytes(b'prepared-only')
        with patch('render_report._print_pdf',side_effect=render_pdf),patch('check_layout.check_pdf',return_value=['版面挤压']):
            with self.assertRaises(ValueError):generate(root,profile_version="profile.txt")
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})
        with patch('operator_check.generate',side_effect=ValueError('核查单生成失败')):
            with self.assertRaises(ValueError):generate(root,html_only=True,profile_version="profile.txt")
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
            with self.assertRaises(OSError):generate(root,html_only=True,profile_version="profile.txt")
        self.assertEqual(before,{n:(root/n).read_bytes() for n in names})

    def test_only_human_completed_items_can_pass_completion(self):
        root=self.roots['career'];p=checklist(root);text=p.read_text().replace('- [ ]','- [x]')
        text=text.replace('核查人：___','核查人：测试人员').replace('核查日期：___','核查日期：2026-10-19').replace('结果（确认/不符/仍未知）：___','结果（确认/不符/仍未知）：确认').replace('原文依据与范围：___','原文依据与范围：原件对应条款').replace('对建议的处理：___','对建议的处理：保持条件判断')
        p.write_text(text);self.assertEqual(validate_operator(root,True),[])
        p.write_text(text.replace('：确认；','：仍未知；',1));self.assertTrue(validate_operator(root,True))

    def test_html_generation_records_hashes_and_detects_stale_inputs(self):
        root=self.roots['career'];generate(root,html_only=True,profile_version="profile.txt")
        c=PlanningCase(root);self.assertEqual(c.trace_errors(),[])
        trace=read(root/'report_trace.json')
        self.assertEqual(trace['authoring'],{'model':'未记录'})
        self.assertIn('render_report.py',trace['renderer']['files_sha256'])
        self.assertTrue(trace['renderer']['version'].startswith('sha256:'))
        self.change(root,'case.json',lambda x:x.update(version='变更'))
        self.assertTrue(PlanningCase(root).trace_errors())

    def test_self_assessment_passes_without_claiming_delivery_approval(self):
        from planning_workflow import RUBRIC,review_errors
        root=self.roots['grad'];generate(root,html_only=True,profile_version="profile.txt")
        files=(*FILES,'profile.txt','report.md','report.html','2027-YJ-S01-report.pdf','report_trace.json','operator_check.md','claim_check.json')
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
        self.assertNotIn('当前没有真实offer',text)
        self.assertTrue('尚无' in text or '还没有拿到可核的录用或实习条件' in text)
        # Changing the real input case this way would be rejected by the stage gate.
        self.change(root,'case.json',lambda x:x['context'].update(offer_basis='none'))
        self.assertTrue(any('跳过收入图' in e for e in run(root,0).errors))


class NoOfferNoticeTests(unittest.TestCase):
    def notice(self,text,active=False):
        from types import SimpleNamespace
        from planning_report import offer_gap_notice
        case=SimpleNamespace(contract={'sections':[{'id':'09','slots':[{'otherwise':'explicit_no_offer_and_input_gaps'}]}]},
            active=lambda slot:active,nodes=lambda:{'09':[{'ref':'n'}]},get_node=lambda ref:{'content':{'text':text}})
        return offer_gap_notice(case,'09',text)

    def test_internship_and_compensation_gap_is_already_explained(self):
        self.assertEqual(self.notice('尚无实习通知，报酬和支付时间未取得，不能比较到手现金。'),'')

    def test_partial_gap_still_gets_neutral_notice(self):
        for text in ['没有房租报价，生活支出待核。','尚无实习通知，先了解所在地。']:
            with self.subTest(text=text):
                note=self.notice(text);self.assertIn('录用或实习条件',note);self.assertNotIn('社保公积金',note)
        self.assertEqual(self.notice('条件齐全',active=True),'')

    def test_hidden_explanation_cannot_suppress_rendered_notice(self):
        from types import SimpleNamespace
        text='尚无实习通知，报酬和支付时间未取得，不能比较到手现金。'
        for comment,inactive in [(True,False),(False,True),(False,False)]:
            with self.subTest(comment=comment,inactive=inactive):
                content={'kind':'comment'if comment else'paragraph','text':text}
                slots=[{'key':'body'},{'key':'income','otherwise':'explicit_no_offer_and_input_gaps'}]
                c=SimpleNamespace(case={'report_meta':{},'mode':'simulation'},evidence={},trace=[],
                    data={'evidence.json':{'source_groups':[]},'narrative.json':{'sections':{'09':{}}}},
                    contract={'sections':[{'id':'09','default_title':'收入比较','slots':slots}]},
                    nodes=lambda:{'09':[{'slot':'income'if inactive else'body','ref':'n'}]},
                    active=lambda slot:slot['key']!='income',get_node=lambda ref:{'type':'analysis','content':content},expand=lambda value,where:value)
                rendered,_=assemble(c)
                self.assertEqual('还没有拿到可核的录用或实习条件'in rendered,comment or inactive)
                self.assertEqual(text in rendered,not(comment or inactive))
                from claim_check import extract
                previous_trace=c.trace
                claims=extract(c)
                notices=[x for x in claims if x['location'].startswith('planning_report.py#offer_gap_notice')]
                self.assertEqual(bool(notices),comment or inactive)
                self.assertIs(c.trace,previous_trace)


class DomainPolicySnapshotTests(unittest.TestCase):
    """报告追踪只记本报告证据命中的域名行：别的案例加域名不让旧报告失效。"""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.csv=self.root/'domains.csv'
        dump(self.root/'evidence.json',{'schema_version':1,'items':[
            {'id':'E001','source':{'url':'https://yz.example-univ.edu.cn/a.html'}},
            {'id':'E002','source':{'url':'https://www.unlisted.example.org/b'}}],'source_groups':[]})
        self.write([('example-univ.edu.cn','示例大学','https://example-univ.edu.cn | 单位：示例大学')])

    def write(self,rows):
        import csv
        with self.csv.open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f);w.writerow(['domain','organization','evidence']);w.writerows(rows)

    def snap(self):
        from planning_workflow import policy_snapshot
        return policy_snapshot(self.root,domain_csv=self.csv)

    def test_unrelated_domain_keeps_snapshot_but_used_or_newly_matching_rows_change_it(self):
        base=self.snap()
        self.assertEqual(list(base['official_domain_rows']),['example-univ.edu.cn'])
        self.assertNotIn('zhiqu-shared/references/official-domains.csv',base['policy_sha256'])
        hit=('example-univ.edu.cn','示例大学','https://example-univ.edu.cn | 单位：示例大学')
        self.write([hit,('other-city.gov.cn','别的市政府','https://other-city.gov.cn | 单位：别的市政府')])
        self.assertEqual(self.snap(),base)
        self.write([('example-univ.edu.cn','示例大学研究生院','https://example-univ.edu.cn | 单位：示例大学')])
        self.assertNotEqual(self.snap(),base)
        # A new row that now classifies one of this report's URLs changes what the report relied on.
        self.write([hit,('unlisted.example.org','某机构','https://unlisted.example.org | 单位：某机构')])
        self.assertNotEqual(self.snap(),base)

class RecommendationEligibilityTests(unittest.TestCase):
    """Synthetic eligibility gates, without reading or copying personal cases."""

    def synthetic_case(self,kind,pool,condition='failed',status='ineligible'):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        dump(root/'case.json',{'kind':kind,'context':{'takes_kaoyan':False}})
        evidence={'id':'E_SYNTHETIC','grade':'官方','status':'verified'}
        dump(root/'evidence.json',{'items':[evidence]})
        def candidate(cid,hc='met',state='verified'):
            return {'id':cid,'status':state,'hard_conditions':[
                {'name':'虚构学历门槛','status':hc,'evidence_refs':['E_SYNTHETIC']}],
                'excluded_reason':'虚构岗位仅限本科，虚构申请人学历为专科' if hc=='failed' else ''}
        candidates={'school_programs':[candidate('SYN_SCHOOL')],
                    'job_types':[candidate('SYN_TYPE_A'),candidate('SYN_TYPE_B'),candidate('SYN_TYPE_C')],
                    'paths':[candidate('SYN_PATH')],'jobs':[candidate('SYN_JOB')]}
        target=candidates[pool][0]
        target.update(candidate(target['id'],condition,status))
        dump(root/'candidates.json',candidates)
        judgment={'preferences':{'quote':'虚构偏好：先核资格','profile_refs':['synthetic']},
                  'candidates':[{'candidate_id':target['id'],**{key:'虚构判断依据' for key in (
                      'supports','counters','costs','fallback','switch_conditions','checkpoint')}}],
                  'recommendation':{'primary':['SYN_TYPE_B'],'backup':['SYN_TYPE_C'],
                                    'conditions':'未核实条件只作调查，符合后再行动'},
                  'checkpoint':'虚构复核节点'}
        dump(root/'judgment.json',judgment)
        return root,target['id']

    def test_failed_candidate_cannot_be_primary_or_backup(self):
        for kind,pools in (('grad',('school_programs','paths')),('career',('job_types','jobs','paths'))):
            for pool in pools:
                for slot in ('primary','backup'):
                    with self.subTest(kind=kind,pool=pool,slot=slot):
                        root,cid=self.synthetic_case(kind,pool)
                        case=PlanningCase(root);case.stage4()
                        self.assertEqual(case.errors,[],case.errors)
                        judgment=read(root/'judgment.json')
                        judgment['recommendation'][slot]=[cid]
                        dump(root/'judgment.json',judgment)
                        case=PlanningCase(root);case.stage7()
                        self.assertTrue(any(cid in error and 'recommendation' in error for error in case.errors),case.errors)

    def test_pending_direction_and_unselected_exclusion_remain_allowed(self):
        for condition,status,selected in (('unknown','pending',True),('failed','ineligible',False)):
            with self.subTest(condition=condition,status=status,selected=selected):
                root,cid=self.synthetic_case('career','job_types',condition,status)
                if selected:
                    judgment=read(root/'judgment.json');judgment['recommendation']['primary']=[cid]
                    dump(root/'judgment.json',judgment)
                case=PlanningCase(root);case.stage4();case.stage7()
                self.assertEqual(case.errors,[],case.errors)

    def test_either_failed_condition_or_ineligible_status_blocks_recommendation(self):
        for condition,status in (('failed','verified'),('met','ineligible')):
            with self.subTest(condition=condition,status=status):
                root,cid=self.synthetic_case('career','jobs',condition,status)
                judgment=read(root/'judgment.json');judgment['recommendation']['primary']=[cid]
                dump(root/'judgment.json',judgment)
                case=PlanningCase(root);case.stage7()
                self.assertTrue(any(cid in error and 'recommendation.primary' in error for error in case.errors),case.errors)

    def test_failed_duplicate_is_not_hidden_by_another_pool_or_order(self):
        for failed_pool in ('job_types','jobs'):
            with self.subTest(failed_pool=failed_pool):
                root,cid=self.synthetic_case('career',failed_pool)
                candidates=read(root/'candidates.json')
                other_pool='jobs' if failed_pool=='job_types' else 'job_types'
                candidates[other_pool][0]['id']=cid
                dump(root/'candidates.json',candidates)
                judgment=read(root/'judgment.json');judgment['recommendation']['backup']=[cid]
                dump(root/'judgment.json',judgment)
                case=PlanningCase(root);case.stage7()
                self.assertTrue(any(cid in error and 'recommendation.backup' in error for error in case.errors),case.errors)

    def test_empty_hard_conditions_still_fail_candidate_gate(self):
        root,cid=self.synthetic_case('career','jobs','met','verified')
        candidates=read(root/'candidates.json');candidates['jobs'][0]['hard_conditions']=[]
        dump(root/'candidates.json',candidates)
        case=PlanningCase(root);case.stage4()
        self.assertTrue(any(cid in error and '硬条件为空' in error for error in case.errors),case.errors)

    def test_case_check_and_report_generation_reach_eligibility_gate(self):
        root,cid=self.synthetic_case('career','jobs')
        judgment=read(root/'judgment.json');judgment['recommendation']['primary']=[cid]
        dump(root/'judgment.json',judgment)
        # Unrelated missing synthetic stages are expected; eligibility must still be checked.
        errors=run(root,7).errors
        self.assertTrue(any(cid in error and 'recommendation.primary' in error for error in errors),errors)
        # Bypass profile binding only. Run the real report preflight and all workflow gates.
        with patch('verify_report.bind_profile',return_value=({}, {}, None)):
            with self.assertRaises(ValueError) as caught:
                generate(root,html_only=True,profile_version='synthetic')
        self.assertIn('recommendation.primary',str(caught.exception))
        self.assertIn(cid,str(caught.exception))

if __name__=='__main__':unittest.main()

"""Fake, local-only JSON questionnaire archives and backwards-compatible profiles."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import profile_store as store


HEADERS = {'gaokao': '【高考志愿 · 自我盘点】', 'grad': '【读研 · 自我盘点】', 'career': '【求职 · 自我盘点】'}


def document(kind='grad', stamp='2026-10-19T12:00:00+08:00', form='a1', items=None, rank=None):
    """A fictional questionnaire, including explicit unknown and declined answers."""
    return {
        'zhiqu': kind, 'schema': 1, '问卷': HEADERS[kind], 'form': form,
        'filled_at': stamp,
        'sections': [{'title': '模拟登记', 'items': items if items is not None else [
            {'id': 'major', 'q': '专业', 'a': '计算机（模拟）'},
            {'id': 'grade', 'q': '目前年级', 'a': '大三'},
        ]}],
        'rank': rank if rank is not None else [], 'derived': {}, '未填的必答题': [],
    }


def profile(**kwargs):
    # Preserve formatting too: archive must not reserialize the user's original JSON.
    return json.dumps(document(**kwargs), ensure_ascii=False, indent=2) + '\n'


def legacy_profile(kind='grad', stamp='2026-10-19T12:00:00+08:00', answers=None):
    data = {'zhiqu': kind, 'form': 'legacy', 'filled_at': stamp,
            'answers': answers or {'text': {'major': '数学（模拟）'}, 'radio': {}, 'check': {}, 'rank': []}}
    return HEADERS[kind] + '\n模拟旧版画像\n' + json.dumps(data, ensure_ascii=False)


class ProfileStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.case = '2027-YJ-0001'

    def tearDown(self):
        self.temp.cleanup()

    def snapshot_path(self, info):
        """Metadata may expose an absolute path, relative path, or just basename."""
        path = Path(info['file'])
        if path.is_absolute():
            return path
        direct = self.root / path
        if direct.exists():
            return direct
        return self.root / self.case / 'profiles' / path.name

    def folder(self, kind='grad', case_id=None):
        folder = self.root / (case_id or self.case)
        folder.mkdir(exist_ok=True)
        (folder / 'case.json').write_text(json.dumps({'kind': kind}), encoding='utf-8')
        return folder

    def test_ingest_json_preserves_exact_original_private_and_idempotent(self):
        raw = profile()
        info = store.ingest(self.root, self.case, raw)
        self.assertTrue({'case_id', 'file', 'filled_at', 'form', 'sha256', 'status'} <= set(info))
        self.assertEqual(info['case_id'], self.case)
        self.assertEqual(info['form'], 'a1')
        self.assertEqual(info['sha256'], hashlib.sha256(raw.encode()).hexdigest())
        path = self.snapshot_path(info)
        self.assertEqual(path.suffix, '.json')
        self.assertEqual(path.parent, self.root / self.case / 'profiles')
        self.assertEqual(path.read_text(encoding='utf-8'), raw)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(store.latest(self.root, self.case), (info, raw))
        self.assertEqual(store.ingest(self.root, self.case, raw), info)
        self.assertEqual(len(list(path.parent.iterdir())), 1)
        self.assertEqual(list(path.parent.glob('*.txt')), [])

    def test_ingest_plain_keeps_text_without_guessing_or_forging_answers(self):
        raw = HEADERS['grad'] + '\n模拟：可能想换专业，没有承诺任何成绩。'
        info = store.ingest(self.root, self.case, raw, now=datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertIn('无数据', info['status'])
        self.assertIn('人工解析', info['status'])
        self.assertEqual(store.latest(self.root, self.case)[1], raw)
        self.assertIsNone(store.parse_profile(raw))

    def test_reject_case_path_kind_invalid_time_and_filename_collision(self):
        for cid in ('../../secret', '2027-YJ-1', '2027-YJ-0001/../../secret', '2027-GK-0001'):
            with self.subTest(case_id=cid), self.assertRaises(ValueError):
                store.ingest(self.root, cid, profile())
        for stamp in ('2026-02-30T00:00:00Z', '2026-10-19', '2026-10-19T12:00:00', 123):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                store.ingest(self.root, self.case, profile(stamp=stamp))
        original = profile()
        store.ingest(self.root, self.case, original)
        changed = profile(items=[{'id': 'major', 'q': '专业', 'a': '不同的模拟专业'}])
        with self.assertRaisesRegex(ValueError, '覆盖|冲突|已有'):
            store.ingest(self.root, self.case, changed)
        self.assertEqual(store.latest(self.root, self.case)[1], original)

    def test_windows_safe_archive_names_preserve_offset_and_fraction(self):
        for stamp, expected in (
            ('2026-10-19T22:37:22+08:00','2026-10-19T22-37-22+0800.json'),
            ('2026-10-19T22:37:22.123456Z','2026-10-19T22-37-22.123456+0000.json'),
            ('2026-10-19T22:37:22-05:30','2026-10-19T22-37-22-0530.json'),
        ):
            with self.subTest(stamp=stamp):
                name = store.archive_filename(stamp)
                self.assertEqual(name, expected)
                self.assertNotIn(':', name)
                self.assertEqual(store.timestamp(store.parse_filename_stamp(name)), store.timestamp(stamp))
        info = store.ingest(self.root, self.case, profile())
        self.assertNotIn(':', Path(info['file']).name)

    def test_legacy_colon_archive_read_and_reingest_do_not_duplicate(self):
        raw = profile();folder = self.folder();archive = folder/'profiles';archive.mkdir()
        old = archive/'2026-10-19T12:00:00+08:00.json';old.write_text(raw)
        info, current = store.latest(self.root, self.case)
        self.assertEqual(current, raw)
        self.assertEqual(info['file'], 'profiles/'+old.name)
        self.assertEqual(store.ingest(self.root, self.case, raw)['file'], info['file'])
        self.assertEqual(len(list(archive.glob('*.json'))), 1)
        new = store.ingest(self.root, self.case, profile(stamp='2026-10-20T12:00:00+08:00', items=[{'id':'major','q':'专业','a':'数学'}]))
        result = store.diff(self.root, self.case, old=old.name, new=new['file'])
        self.assertIn('major', result['modified'])
        # ISO selectors stay accepted even though new archive names are now safe.
        self.assertEqual(result, store.diff(self.root, self.case, old='2026-10-19T12:00:00+08:00', new='2026-10-20T12:00:00+08:00'))

    def test_safe_and_legacy_text_archive_latest_preserves_timestamp(self):
        store.ingest(self.root, self.case, profile())
        info = store.ingest(self.root, self.case, HEADERS['grad']+'\n旧文字', now=datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertNotIn(':', Path(info['file']).name)
        latest, raw = store.latest(self.root, self.case)
        self.assertEqual(latest['filled_at'], info['filled_at'])
        path = self.snapshot_path(info);old = path.with_name(info['filled_at']+'.txt');path.rename(old)
        self.assertEqual(store.latest(self.root,self.case)[1],raw)
        self.assertEqual(store.diff(self.root,self.case)['new_text'], raw)
        with self.assertRaises(ValueError):store.parse_filename_stamp('not-a-timestamp.json')

    def test_reject_nonignored_repository_destination(self):
        repo = Path(__file__).resolve().parents[3]
        with self.assertRaisesRegex(ValueError, '忽略目录|本机|入库'):
            store.ingest(repo / 'skills', self.case, profile())

    def test_latest_uses_filled_at_instant_not_arrival_or_timezone_text(self):
        store.ingest(self.root, self.case, profile(stamp='2026-10-19T06:00:00Z'))
        store.ingest(self.root, self.case, profile(stamp='2026-10-19T12:00:00+08:00'))
        self.assertEqual(store.latest(self.root, self.case)[0]['filled_at'], '2026-10-19T06:00:00Z')
        with self.assertRaisesRegex(ValueError, '还没有|没有画像|不存在'):
            store.latest(self.root, '2027-YJ-0002')

    def test_diff_uses_stable_item_id_and_warns_on_form_change(self):
        old = store.ingest(self.root, self.case, profile(items=[
            {'id': 'major', 'q': '原来的专业题干', 'a': '数学'},
            {'id': 'gone', 'q': '删去的题', 'a': '模拟旧回答'},
        ]))
        new = store.ingest(self.root, self.case, profile(stamp='2026-10-20T12:00:00+08:00', form='b2', items=[
            {'id': 'major', 'q': '措辞改了，稳定编号未改', 'a': '统计'},
            {'id': 'new_item', 'q': '新增题', 'a': '模拟新回答', 'followup_of': 'major'},
        ]))
        result = store.diff(self.root, self.case)
        self.assertEqual(result['added'], {'new_item': '模拟新回答'})
        self.assertEqual(result['deleted'], {'gone': '模拟旧回答'})
        self.assertEqual(result['modified'], {'major': {'old': '数学', 'new': '统计'}})
        self.assertTrue(any('题目版本不同，部分题可能对不上' in x for x in result['warnings']))
        # Explicit archive filenames can select versions; no traversal or other case allowed.
        self.assertEqual(store.diff(self.root, self.case, old=old['file'], new=new['file'])['modified'], result['modified'])
        with self.assertRaises(ValueError):
            store.diff(self.root, self.case, old='../another-case/profile.json')

    def test_same_answers_rephrased_questions_do_not_become_modified(self):
        store.ingest(self.root, self.case, profile(items=[{'id': 'major', 'q': '专业', 'a': '数学'}]))
        store.ingest(self.root, self.case, profile(stamp='2026-10-20T12:00:00+08:00', form='b2', items=[
            {'id': 'major', 'q': '你的主修专业是什么', 'a': '数学'},
        ]))
        result = store.diff(self.root, self.case)
        self.assertEqual(result['added'], {})
        self.assertEqual(result['deleted'], {})
        self.assertEqual(result['modified'], {})

    def test_diff_rank_change_keeps_the_exact_order(self):
        store.ingest(self.root, self.case, profile(rank=['费用', '城市']))
        store.ingest(self.root, self.case, profile(stamp='2026-10-20T12:00:00+08:00', rank=['城市', '费用']))
        result = store.diff(self.root, self.case)
        self.assertEqual(result['modified']['rank'], {'old': ['费用', '城市'], 'new': ['城市', '费用']})

    def test_diff_requires_two_versions_and_does_not_infer_plain_deleted_answers(self):
        store.ingest(self.root, self.case, profile())
        with self.assertRaisesRegex(ValueError, '至少|两版'):
            store.diff(self.root, self.case)
        store.ingest(self.root, self.case, HEADERS['grad'] + '\n模拟旧文字', now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        result = store.diff(self.root, self.case)
        self.assertFalse(result['deleted'])
        self.assertTrue(any('人工解析' in x for x in result['warnings']))

    def test_visible_required_omissions_outside_main_fields_are_retained(self):
        for kind in ('grad','career','gaokao'):
            with self.subTest(kind=kind):
                data=document(kind=kind,items=[{'id':'major','q':'专业','a':'软件工程','status':'已答'},
                    {'id':'available_time','q':'能投入多少时间？','required':True,'status':'未填'},
                    {'id':'optional_note','q':'其他说明','status':'未填'}])
                data.update(collapsed=['hidden_question'],counts={'visible':3,'answered':1})
                data['checksum']=store.checksum(data)
                parsed=store.build_parse(json.dumps(data,ensure_ascii=False),kind)
                self.assertIn('能投入多少时间？',str(parsed['missing']))
                self.assertNotIn('其他说明',str(parsed['missing']))
                self.assertNotIn('hidden_question',str(parsed['missing']))
                if kind!='gaokao':
                    row=next(m for m in parsed['missing'] if m['field']=='能投入多少时间？')
                    self.assertEqual(row['answer_refs'],['available_time'])

    def test_required_gap_details_keep_mapped_questions_and_all_ids(self):
        cases={'grad':[('gpa','你的均分和满分分别是多少？')],
               'career':[('salary_known','你是否知道最低月薪？')],
               'gaokao':[('money','每年学费上限是多少？'),('four_year_budget','本科总预算是多少？')]}
        for kind,pairs in cases.items():
            with self.subTest(kind=kind):
                data=document(kind=kind,items=[dict(id=k,q=q,required=True,status='未填') for k,q in pairs])
                data.update(collapsed=[],counts={'visible':len(pairs),'answered':0});data['checksum']=store.checksum(data)
                parsed=store.build_parse(json.dumps(data,ensure_ascii=False),kind)
                self.assertEqual(parsed['required_gaps'],[{'id':k,'question':q,'section':'模拟登记'}for k,q in pairs])
                if kind!='gaokao':self.assertTrue(any(q in m['question'] for m in parsed['missing'] for k,q in pairs))
                else:self.assertTrue(all(isinstance(m,str)for m in parsed['missing']))

    def test_alignment_rejects_erasing_required_question_gaps(self):
        data=document(items=[{'id':'major','q':'专业','a':'软件工程','status':'已答'},
            {'id':'available_time','q':'能投入多少时间？','required':True,'status':'未填'}])
        data.update(collapsed=[],counts={'visible':2,'answered':1});data['checksum']=store.checksum(data)
        store.ingest(self.root,self.case,json.dumps(data,ensure_ascii=False));folder=self.root/self.case
        store.prepare(folder);self.assertEqual(store.alignment_errors(folder),[])
        parsed=json.loads((folder/'profile_parse.json').read_text());parsed['missing']=[m for m in parsed['missing'] if m['field']!='能投入多少时间？']
        store.dump(folder/'profile_parse.json',parsed)
        self.assertTrue(any('可见必答' in e for e in store.alignment_errors(folder)))

    def test_grad_income_deadline_is_independent_verbatim_and_appended(self):
        from planning_workflow import PlanningCase
        from planning_report import node_markdown
        for answer in ('2029','2029年毕业前','毕业前先开始挣钱'):
            with self.subTest(answer=answer):
                data=document(items=[{'id':'worst','q':'退路','a':['直接工作']},
                    {'id':'earning_year','q':'最迟哪年挣钱？','a':answer}])
                raw=json.dumps(data,ensure_ascii=False);parsed=store.build_parse(raw,'grad')
                no_income=document(items=[{'id':'worst','q':'退路','a':['直接工作']}])
                ordinary=store.build_parse(json.dumps(no_income,ensure_ascii=False),'grad')
                self.assertEqual([f['field'] for f in parsed['fields'][:11]],[f['field'] for f in ordinary['fields']])
                self.assertEqual(parsed['fields'][9]['value'],{'worst':['直接工作'],'earning_year':answer})
                field=parsed['fields'][11]
                self.assertEqual((field['field'],field['category'],field['status'],field['value']),('最迟开始挣钱年份','constraint','given',answer))
                self.assertEqual(field['answer_refs'],['earning_year']);self.assertIn(answer,field['quote'])
                # The same given value reaches a report input without year/pay inference.
                folder=self.folder();store.dump(folder/'case.json',{'kind':'grad'});store.dump(folder/'profile_parse.json',parsed)
                case=PlanningCase(folder)
                text=node_markdown({'type':'analysis','content':{'text':'挣钱时点原答：{{p:/fields/11/value}}'}},case.expand,{})
                self.assertEqual(text,'挣钱时点原答：'+answer)

    def test_grad_uncertain_or_refused_income_does_not_become_a_year(self):
        for answer in ('不想说','没想好。二战的话家里应该能支持一年，但我自己不太想。','还没想好，2029年毕业','不确定收入含义，但提到2030年','暂时不想说','不愿透露','拒绝回答','没有想好，等毕业再说','尚未想好','暂不确定','目前还没想好什么时候挣钱','没想好但家里可以支持一年','没想好，但家里可以支持一年','没想好要不要二战','没想好具体哪年开始挣钱','不清楚自己什么时候能经济独立'):
            with self.subTest(answer=answer):
                parsed=store.build_parse(profile(items=[{'id':'earning_year','q':'最迟哪年挣钱？','a':answer}]),'grad')
                field=parsed['fields'][-1]
                self.assertEqual(field['field'],'最迟开始挣钱年份');self.assertEqual(field['status'],'unknown');self.assertIsNone(field['value'])
                self.assertIn(answer,field['quote']);self.assertIn('最迟开始挣钱年份',{x['field']for x in parsed['missing']})

    def test_income_refusal_words_do_not_capture_unrelated_prefixes(self):
        for answer in ('不想说服父母，2029必须开始挣钱','不确定性比较大，但2029年前要挣钱','待定价方案与我的收入无关，毕业前挣钱','不方便说服父母，但2029年前必须挣钱','没想到2029年就必须挣钱'):
            with self.subTest(answer=answer):
                parsed=store.build_parse(profile(items=[{'id':'earning_year','q':'最迟哪年挣钱？','a':answer}]),'grad')
                self.assertEqual(parsed['fields'][-1]['value'],answer)
                self.assertEqual(parsed['fields'][-1]['status'],'given')

    def test_grad_new_income_projection_cannot_be_erased(self):
        for checked in (False,True):
            data=document(items=[{'id':'earning_year','q':'最迟哪年挣钱？','a':'2029','status':'已答'}])
            if checked:
                data.update(collapsed=[],counts={'visible':1,'answered':1});data['checksum']=store.checksum(data)
            else:data['sections'][0]['items'][0].pop('status')
            root=self.root/('checked' if checked else 'plain');root.mkdir();store.ingest(root,self.case,json.dumps(data,ensure_ascii=False));folder=root/self.case;store.prepare(folder)
            self.assertEqual(store.alignment_errors(folder),[])
            parsed=json.loads((folder/'profile_parse.json').read_text());parsed['fields']=[f for f in parsed['fields'] if f['field']!='最迟开始挣钱年份'];store.dump(folder/'profile_parse.json',parsed)
            self.assertTrue(any('最迟开始挣钱年份' in e for e in store.alignment_errors(folder)))

    def test_only_unresolved_historic_migration_keeps_the_combined_income_projection(self):
        data=document(items=[{'id':'earning_year','q':'最迟哪年挣钱？','a':'没想好。家里说可再支持一年。'}])
        store.ingest(self.root,self.case,json.dumps(data,ensure_ascii=False));folder=self.root/self.case;store.prepare(folder)
        parsed=json.loads((folder/'profile_parse.json').read_text());legacy=[f for f in parsed['fields'] if f['field']!='最迟开始挣钱年份']
        parsed['questionnaire_fields']=legacy;parsed['fields']=legacy;store.dump(folder/'profile_parse.json',parsed)
        self.assertEqual(store.alignment_errors(folder),[])
        # That exception cannot mask a supplied deadline in a migrated projection.
        newer=document(stamp='2026-10-20T12:00:00+08:00',items=[{'id':'earning_year','q':'最迟哪年挣钱？','a':'2029'}])
        store.ingest(self.root,self.case,json.dumps(newer,ensure_ascii=False));store.prepare(folder,replace=True)
        parsed=json.loads((folder/'profile_parse.json').read_text());legacy=[f for f in parsed['fields'] if f['field']!='最迟开始挣钱年份'];parsed.update(fields=legacy,questionnaire_fields=legacy);store.dump(folder/'profile_parse.json',parsed)
        self.assertTrue(any('最迟开始挣钱年份' in e for e in store.alignment_errors(folder)))

    def test_parse_json_returns_exact_data_and_supports_old_data_line(self):
        data = document(items=[{'id': 'money', 'q': '年度预算', 'a': '不想说'}])
        data['derived'] = {'bazi': '模拟排盘文字，不用于现实资格'}
        self.assertEqual(store.parse_profile(json.dumps(data, ensure_ascii=False)), data)
        old = legacy_profile()
        parsed = store.parse_profile(old)
        self.assertEqual(next(i['a'] for sec in parsed['sections'] for i in sec['items'] if i['id']=='major'), '数学（模拟）')
        self.assertIsNone(store.parse_profile(HEADERS['grad'] + '\n模拟旧画像，无数据行'))

    def test_parse_rejects_damaged_wrong_types_duplicate_ids_and_ambiguous_lines(self):
        damaged = [profile()[:-5], '{"zhiqu":', legacy_profile() + '\n' + legacy_profile().splitlines()[-1]]
        for raw in damaged:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                store.parse_profile(raw)
        modifications = [
            ('zhiqu', 'unknown'), ('schema', 2), ('form', ''), ('form', 123),
            ('filled_at', '2026-10-19T12:00:00'), ('sections', {}),
        ]
        for key, value in modifications:
            bad = document(); bad[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                store.parse_profile(json.dumps(bad, ensure_ascii=False))
        bad_items = [
            [{'id': '../../secret', 'q': '模拟题', 'a': '值'}],
            [{'id': 'major', 'q': ['不是题干字符串'], 'a': '值'}],
            [{'id': 'same', 'q': '模拟题一', 'a': '值'}, {'id': 'same', 'q': '模拟题二', 'a': '值'}],
        ]
        for items in bad_items:
            with self.subTest(items=items), self.assertRaises(ValueError):
                store.parse_profile(profile(items=items))

    def test_prepare_preserves_given_values_and_unknowns_without_negative_inference(self):
        folder = self.folder()
        raw = profile(items=[{'id': 'major', 'q': '专业', 'a': '数学'},
                             {'id': 'rank_in_major', 'q': '专业名次与人数', 'a': '10/100'},
                             {'id': 'new_question', 'q': '模拟敏感题', 'a': '不想说'}])
        store.ingest(self.root, self.case, raw)
        self.assertTrue(store.alignment_errors(folder))
        store.prepare(folder)
        self.assertFalse(store.alignment_errors(folder))
        parsed = json.loads((folder / 'profile_parse.json').read_text(encoding='utf-8'))
        fields = {row['field']: row for row in parsed['fields']}
        self.assertEqual(fields['专业']['value'], '数学')
        self.assertEqual(fields['专业']['status'], 'given')
        self.assertEqual(fields['均分或排名']['value'], '10/100')
        self.assertEqual(fields['预算']['status'], 'unknown')
        self.assertIsNone(fields['预算']['value'])
        self.assertIn('不想说', json.dumps(parsed, ensure_ascii=False))
        self.assertEqual(store.latest(self.root, self.case)[1], raw)

    def test_prepare_latest_and_alignment_reject_stale_or_forged_fields(self):
        folder = self.folder()
        store.ingest(self.root, self.case, profile())
        store.prepare(folder)
        (folder / 'directions.json').write_text('unchanged', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '已有|覆盖'):
            store.prepare(folder)
        store.ingest(self.root, self.case, profile(stamp='2026-10-20T12:00:00+08:00', items=[
            {'id': 'major', 'q': '专业', 'a': '统计'},
        ]))
        self.assertTrue(any('画像已更新' in x or '最新' in x for x in store.alignment_errors(folder)))
        store.prepare(folder, replace=True)
        self.assertFalse(store.alignment_errors(folder))
        self.assertEqual((folder / 'directions.json').read_text(encoding='utf-8'), 'unchanged')
        path = folder / 'profile_parse.json'
        parsed = json.loads(path.read_text(encoding='utf-8'))
        next(f for f in parsed['fields'] if f['field'] == '专业')['value'] = '伪造专业'
        path.write_text(json.dumps(parsed, ensure_ascii=False), encoding='utf-8')
        self.assertTrue(any('不一致' in x or '伪造' in x for x in store.alignment_errors(folder)))

    def test_alignment_rejects_making_an_unknown_field_look_given(self):
        folder = self.folder()
        store.ingest(self.root, self.case, profile())
        store.prepare(folder)
        path = folder / 'profile_parse.json'
        parsed = json.loads(path.read_text(encoding='utf-8'))
        budget = next(f for f in parsed['fields'] if f['field'] == '预算')
        self.assertEqual(budget['status'], 'unknown')
        budget['value'] = '凭空编出的预算'
        budget['status'] = 'given'
        path.write_text(json.dumps(parsed, ensure_ascii=False), encoding='utf-8')
        self.assertTrue(store.alignment_errors(folder))

    def test_prepare_plain_returns_manual_and_preserves_existing_sources(self):
        folder = self.folder()
        raw = HEADERS['grad'] + '\n模拟旧画像：没有可用的结构化作答。'
        (folder / 'profile.txt').write_text(raw, encoding='utf-8')
        prior = '{"manual":true,"note":"模拟人工解析"}'
        (folder / 'profile_parse.json').write_text(prior, encoding='utf-8')
        self.assertIn('人工解析', store.prepare(folder)['status'])
        self.assertEqual((folder / 'profile.txt').read_text(encoding='utf-8'), raw)
        self.assertEqual((folder / 'profile_parse.json').read_text(encoding='utf-8'), prior)
        self.assertFalse(store.alignment_errors(folder))

    def test_tampering_and_symlink_are_rejected(self):
        info = store.ingest(self.root, self.case, profile())
        path = self.snapshot_path(info)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['sections'][0]['items'][0]['a'] = '改动后的模拟回答'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '不一致|摘要|损坏'):
            store.latest(self.root, self.case)
        (self.root / '2027-YJ-0002').symlink_to(self.root / self.case)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            store.ingest(self.root, '2027-YJ-0002', profile())

    def test_new_id_reserves_unique_numbers_in_one_total_registry(self):
        first = store.new_id(self.root, 'grad', 2027)
        second = store.new_id(self.root, 'grad', 2027)
        career = store.new_id(self.root, 'career', 2027)
        self.assertEqual(first, '2027-YJ-0001')
        self.assertEqual(second, '2027-YJ-0002')
        self.assertEqual(career, '2027-QZ-0001')
        registry = self.root / 'cases.json'
        self.assertTrue(registry.is_file())
        text = registry.read_text(encoding='utf-8')
        for case_id in (first, second, career):
            self.assertIn(case_id, text)
        self.assertEqual(registry.stat().st_mode & 0o777, 0o600)
        for kind, year, mode in [('unknown', 2027, 'formal'), ('grad', 'bad', 'formal'), ('grad', 2027, 'unknown')]:
            with self.subTest(kind=kind, year=year, mode=mode), self.assertRaises(ValueError):
                store.new_id(self.root, kind, year, mode=mode)

    def test_new_id_atomic_reservations_do_not_duplicate(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: store.new_id(self.root, 'grad', 2027), range(8)))
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(set(ids), {f'2027-YJ-{n:04d}' for n in range(1, 9)})
        json.loads((self.root / 'cases.json').read_text(encoding='utf-8'))

    def test_report_versions_record_hashes_and_do_not_mutate_profiles(self):
        case_id = store.new_id(self.root, 'grad', 2027)
        raw = profile()
        store.ingest(self.root, case_id, raw)
        folder = self.root / case_id
        path = folder / f'{case_id}-report.pdf'
        first = b'%PDF-1.4\nfictional report version one\n'
        second = b'%PDF-1.4\nfictional report version two\n'
        path.write_bytes(first)
        store.record_report(self.root, case_id, path, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        path.write_bytes(second)
        store.record_report(self.root, case_id, path, now=datetime(2026, 10, 21, tzinfo=timezone.utc))
        registry = (self.root / 'cases.json').read_text(encoding='utf-8')
        self.assertIn(hashlib.sha256(first).hexdigest(), registry)
        self.assertIn(hashlib.sha256(second).hexdigest(), registry)
        self.assertIn(f'{case_id}-report.pdf', registry)
        self.assertEqual(store.latest(self.root, case_id)[1], raw)
        with self.assertRaises((ValueError, FileNotFoundError)):
            store.record_report(self.root, case_id, folder / 'missing.pdf')

    def test_declined_multiselect_is_unknown_not_a_known_health_constraint(self):
        data = store.build_parse(profile(kind='gaokao', items=[{'id':'body','q':'身体条件','a':['不想说']}]), 'gaokao')
        body = next(f for f in data['fields'] if f['field']=='体检')
        self.assertEqual(body['status'], 'unknown')
        self.assertIsNone(body['value'])
        self.assertIn('不想说', body['quote'])

    def test_career_questionnaire_controls_map_to_their_questions(self):
        mapping = store.QuestionMap(); mapping.feed((store.REPO / 'career.html').read_text(encoding='utf-8'))
        # Per-exam language controls belong to the one language question; the old shared ones are gone.
        for key in ('cet4_score', 'cet4_status', 'cet4_month', 'cet6_score', 'cet6_status', 'cet6_month',
                    'other_language', 'other_language_status', 'other_language_month'):
            self.assertEqual(mapping.mapping[key], 'cet4_score', key)
        for gone in ('language_status', 'language_month', 'certs_detail'):
            self.assertNotIn(gone, mapping.mapping)
        self.assertEqual(mapping.mapping['has_offer'], 'has_offer')

    def test_career_offer_folds_into_stage_and_cert_note_is_gone(self):
        self.assertNotIn('certs_detail', json.dumps(store.FIELD_MAP['career'], ensure_ascii=False))
        raw = profile(kind='career', items=[
            {'id': 'job_stage', 'q': '求职进行到哪一步？', 'a': '已经在面试'},
            {'id': 'has_offer', 'q': '手里现在有 offer 吗', 'a': '谈着还没定'},
            {'id': 'certs', 'q': '证书与技能', 'a': {'多选': ['其他']}},
        ])
        fields = {row['field']: row for row in store.build_parse(raw, 'career')['fields']}
        self.assertEqual(fields['求职阶段']['value'], {'job_stage': '已经在面试', 'has_offer': '谈着还没定'})
        self.assertEqual(fields['证书']['answer_refs'], ['certs'])
        # An older profile without the new question keeps the same single value.
        old = profile(kind='career', items=[{'id': 'job_stage', 'q': '求职进行到哪一步？', 'a': '还没开始'}])
        fields = {row['field']: row for row in store.build_parse(old, 'career')['fields']}
        self.assertEqual(fields['求职阶段']['value'], '还没开始')

    def test_career_parent_questions_preserve_salary_and_income_month(self):
        # The exporter groups nested controls under their parent question ID.
        salary={'选择':'有大致底线','最低到手月薪':'5500'}
        deadline={'选择':'有明确月份','最晚稳定收入年月':'2027-08'}
        data=document(kind='career',items=[
            {'id':'salary_known','q':'最低到手月薪（选填）','a':salary,'status':'已答'},
            {'id':'income_deadline_status','q':'最晚需要稳定收入的年月（选填）','a':deadline,'status':'已答'}])
        data.update(collapsed=[],counts={'visible':2,'answered':2})
        data['checksum']=store.checksum(data)
        parsed=store.build_parse(json.dumps(data,ensure_ascii=False),'career')
        fields={row['field']:row for row in parsed['fields']}
        for name,expected,owner in [('收入底线',salary,'salary_known'),
                                    ('多快需要收入',deadline,'income_deadline_status')]:
            self.assertEqual(fields[name]['status'],'given')
            self.assertEqual(fields[name]['value'],expected)
            self.assertEqual(fields[name]['answer_refs'],[owner])
            self.assertNotIn(name,{row['field'] for row in parsed['missing']})

    def test_all_three_questionnaires_roundtrip_without_guessing(self):
        for kind, code in [('gaokao', 'GK'), ('grad', 'YJ'), ('career', 'QZ')]:
            with self.subTest(kind=kind):
                case_id = f'2027-{code}-0001'
                raw = profile(kind=kind, items=[{'id': 'money', 'q': '费用预算', 'a': '不想说'}])
                store.ingest(self.root, case_id, raw)
                self.assertEqual(store.latest(self.root, case_id)[1], raw)
                data = store.parse_profile(raw)
                self.assertEqual(data['sections'][0]['items'][0]['a'], '不想说')
                self.assertEqual(data['derived'], {})


if __name__ == '__main__':
    unittest.main()

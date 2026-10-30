"""Independent synthetic small cases: no candidate-level input or production change."""
import itertools,json,math,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import kaoyan_backtest as kb
import kaoyan_position as kp

def dist(values):
    return dict(n=len(values),**{k:kb.quantile(values,p) for k,p in kb.QUANTILES})

class TestKaoyanBacktest(unittest.TestCase):
    def test_count_bounds_cover_every_sorted_integer_small_case(self):
        # Exhaust every sorted length-four vector over five marks; inclusive quartiles
        # constrain order statistics but do not pretend to identify every score.
        for values in itertools.combinations_with_replacement(range(5),4):
            d=dist(values)
            for a,b in itertools.combinations(range(-1,7),2):
                low,high=kb.count_bounds(d,a,b)
                actual=sum(a<=x<b for x in values)
                self.assertLessEqual(low,actual,(values,a,b,low,high))
                self.assertLessEqual(actual,high,(values,a,b,low,high))
    def test_all_tied_marks_are_exactly_identified(self):
        d=dist([300]*10)
        self.assertEqual(kb.count_bounds(d,300,301),(10,10))
        self.assertEqual(kb.count_bounds(d,299,300),(0,0))
        self.assertEqual(kb.count_bounds(d,math.inf,math.inf),(0,0))
    def test_no_two_training_years_means_no_steady(self):
        d=dist(list(range(300,310)))
        self.assertEqual(kb.total_only_analysis(500,d),'够一够')
        self.assertEqual(kb.total_only_analysis(300,d),'冒险')
        self.assertEqual(kb.total_only_analysis(500,d,d),'相对稳妥')
    def test_threshold_matches_existing_rule_on_eligible_synthetic_case(self):
        d=dist(list(range(300,320)));old=dist(list(range(310,330)))
        program=dict(id='synthetic',name='虚构方法例',subjects=['科目甲'],years={'2023':{'admitted':old},'2024':{'admitted':d}})
        for score in range(290,341):
            actual=kp.place(dict(total=score,complete=True,subjects=['科目甲'],singles={}),program)['tier']
            self.assertEqual(kb.total_only_analysis(score,d,old),actual)
    def test_cluster_bootstrap_is_reproducible_and_resamples_whole_cluster(self):
        points=[dict(cluster='A',hit=0)]*10+[dict(cluster='B',hit=1)]*10
        first=kb.bootstrap_rate(points,'hit',1000,42)
        self.assertEqual(first,kb.bootstrap_rate(points,'hit',1000,42))
        self.assertEqual(first[:2],(0,1))
        self.assertEqual(kb.bootstrap_rate(points[:10],'hit')[0:2],(None,None))
    def test_run_temporal_split_uses_actual_prior_years_and_separates_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'fixture.sqlite';c=sqlite3.connect(db)
            c.execute('CREATE TABLE v_usable (record_id,institution_id,program_code,college,study_mode,admission_route,special_plan,year,n,min,q1,median,q3,max,scope,source_id,school,list_type,degree_type,direction)')
            for year,base in [(2023,300),(2024,310),(2025,320)]:
                d=dist(list(range(base,base+10)))
                c.execute('INSERT INTO v_usable VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(year),'4100000001','081200','虚构学院','全日制','一志愿','普通计划',year,d['n'],d['min'],d['q1'],d['median'],d['q3'],d['max'],'普通统考','fixture'+str(year),'虚构学校','拟录取','学术',''))
            c.execute('CREATE TABLE v_usable_line (institution_id,program_code,college,year,line_total,grade,source_id,src_row)')
            for year in (2024,2025):c.execute('INSERT INTO v_usable_line VALUES(?,?,?,?,?,?,?,?)',('4100000001','081200','虚构学院',year,315,'官方','fixture','2'))
            for table in ['v_usable','v_usable_line']:
                cols={r[1]for r in c.execute('PRAGMA table_info('+table+')')}
                for field in ['study_mode','admission_route','special_plan','degree_type','direction','joint_program','grade','scope','quantile_method','quantile_rounding']:
                    if field not in cols:c.execute('ALTER TABLE '+table+' ADD COLUMN '+field)
                values={'study_mode':'全日制','admission_route':'一志愿','special_plan':'普通计划','degree_type':'学术','direction':'不分方向','joint_program':'非联培','grade':'官方','scope':'普通统考','quantile_method':'inclusive_linear','quantile_rounding':0}
                for k,v in values.items():c.execute('UPDATE '+table+' SET '+k+'=?',(v,))
            c.commit();c.close()
            coverage=kb.run(db,root/'result',100,42)
            self.assertEqual(coverage['consecutive_pairs'],2)
            self.assertEqual(coverage['pairs_with_two_training_years'],1)
            self.assertEqual(coverage['strict_n10_pairs'],2)
            import csv
            with (root/'result'/'evaluation_points.csv').open(encoding='utf-8-sig') as f:result=list(csv.DictReader(f))
            self.assertTrue(all(r['tier']!='相对稳妥' for r in result if r['year']=='2024'))
            self.assertTrue(any(r['tier']=='相对稳妥' for r in result if r['year']=='2025'))
            self.assertEqual({r['unit'] for r in result},{'published_quantile_anchor','integer_grid'})
            self.assertTrue(all(r['source_previous']=='fixture'+str(int(r['year'])-1) for r in result))
            c=sqlite3.connect(db);c.execute("UPDATE v_usable SET degree_type='专业' WHERE year=2025");c.commit();c.close()
            changed=kb.run(db,root/'mixed_degree',100,42)
            self.assertEqual(changed['consecutive_pairs'],1)
            self.assertEqual(changed['pairs_with_two_training_years'],0)
    def test_current_small_n_policy_is_preserved(self):
        for n in [1,2,4]:
            with self.subTest(n=n):self.assertIsNone(kb.total_only_analysis(500,dist(list(range(300,300+n))),dist(list(range(300,320)))))
        for n in [5,9]:
            self.assertEqual(kb.total_only_analysis(500,dist(list(range(300,300+n))),dist(list(range(300,320)))),'够一够')
            self.assertEqual(kb.total_only_analysis(500,dist(list(range(300,320))),dist(list(range(300,300+n)))),'够一够')

    def test_joint_plan_and_known_line_scope_cannot_be_mixed(self):
        r=dict(study_mode='全日制',admission_route='一志愿',special_plan='普通计划',degree_type='学术',direction='不分方向',joint_program='非联培',scope='普通统考',grade='官方',quantile_method='inclusive_linear',quantile_rounding=0)
        self.assertIn('joint_program',kb.KEY)
        self.assertEqual(kb.line_compatibility(r,r),(True,[]))
        for field in ['joint_program','direction','special_plan','study_mode','admission_route','degree_type']:
            self.assertFalse(kb.line_compatibility(r,{**r,field:'明确另一范围'})[0])
        self.assertTrue(kb.line_compatibility(r,{**r,'direction':None})[0])
        self.assertTrue(kb.line_compatibility(r,{**r,'direction':None})[1])
        self.assertEqual(kb.scope_risks(r),[])

    def test_unknown_quantile_contract_does_not_get_count_bounds(self):
        r=dist(list(range(300,320)))
        self.assertFalse(kb.identification_available(r))
        self.assertFalse(kb.identification_available({**r,'quantile_method':'inclusive_linear','quantile_rounding':False}))
        self.assertFalse(kb.identification_available({**r,'quantile_method':'inclusive_linear','quantile_rounding':.1}))
        self.assertTrue(kb.identification_available({**r,'quantile_method':'inclusive_linear','quantile_rounding':0}))
        for n in [True,0,1.5,float('nan')]:self.assertFalse(kb.complete({**r,'n':n}))

    def test_small_training_sample_never_gets_a_steady_count_interval(self):
        old=dist(list(range(300,320)));small=dist(list(range(300,305)))
        self.assertEqual(kb.tier_intervals(small,old)[2],('相对稳妥',math.inf,math.inf))
        self.assertEqual(kb.count_bounds(old,*kb.tier_intervals(small,old)[2][1:]),(0,0))

    def test_nonempty_wal_is_rejected_without_checkpoint_or_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'live.sqlite';writer=sqlite3.connect(db)
            try:
                writer.execute('PRAGMA journal_mode=WAL');writer.execute('CREATE TABLE marker(value)');writer.execute('INSERT INTO marker VALUES(1)');writer.commit()
                wal=Path(str(db)+'-wal');before=wal.read_bytes()
                with self.assertRaisesRegex(ValueError,'WAL'):kb.run(db,root/'result',100,42)
                self.assertEqual(wal.read_bytes(),before)
                self.assertFalse((root/'result').exists())
            finally:writer.close()

    def test_scope_unknown_is_excluded_from_strict(self):
        self.assertIn('专项范围未明确',kb.scope_risks(dict(study_mode='全日制',special_plan='普通/未注明',scope='无备注，无法区分专项')))

    def test_run_scope_precision_and_tiny_reference_guards(self):
        # End-to-end guards: helper-only tests missed strict eligibility and the
        # removal of a known tiny Y-2 before the temporal grouping step.
        import csv
        base=dict(institution_id='4100000001',program_code='081200',college='虚构学院',
                  study_mode='全日制',admission_route='一志愿',special_plan='普通计划',
                  degree_type='学术',direction='不分方向',joint_program='非联培',
                  scope='范围甲',grade='官方',quantile_method='inclusive_linear',
                  quantile_rounding=0,school='虚构学校',list_type='拟录取',
                  **dist(list(range(300,310))))
        cases=[('changed_scope',1),('missing_scope',0),('unknown_scope',0),('older_tiny',0),
               ('known_nonzero_precision',2),('unknown_precision',0),
               ('negative_precision',0),('infinite_precision',0),('changed_precision',1)]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for case,expected_strict in cases:
                with self.subTest(case=case):
                    db=root/(case+'.sqlite');con=sqlite3.connect(db)
                    fields=['record_id','year','source_id','src_row',*base]
                    con.execute('CREATE TABLE v_usable ('+','.join(fields)+')')
                    con.execute('CREATE TABLE v_usable_line ('+','.join(fields+['line_total'])+')')
                    for year in [2023,2024,2025]:
                        row=dict(base,record_id=str(year),year=year,source_id='fixture'+str(year),src_row=1)
                        if case=='changed_scope' and year==2025:row['scope']='范围乙'
                        if case=='missing_scope':row['scope']=None
                        if case=='unknown_scope':row['scope']='未注明'
                        if case=='older_tiny' and year==2023:row.update(dist([300,301,302]))
                        if case=='known_nonzero_precision':row['quantile_rounding']=.1
                        if case=='unknown_precision':row['quantile_rounding']='待核'
                        if case=='negative_precision':row['quantile_rounding']=-1
                        if case=='infinite_precision':row['quantile_rounding']=math.inf
                        if case=='changed_precision':row['quantile_rounding']=.2 if year==2025 else .1
                        for table,record in [('v_usable',row),('v_usable_line',{**row,'line_total':300})]:
                            con.execute('INSERT INTO '+table+' ('+','.join(record)+') VALUES ('+','.join('?'for _ in record)+')',list(record.values()))
                    con.commit();con.close()
                    output=root/case;coverage=kb.run(db,output,100,42)
                    self.assertEqual(coverage['strict_n10_pairs'],expected_strict)
                    if case=='older_tiny':
                        self.assertEqual(coverage['consecutive_pairs'],0)
                        self.assertEqual(coverage['evaluation_points'],0)
                        self.assertEqual(coverage['bounds_identified_pairs'],0)
                    if case=='known_nonzero_precision':
                        self.assertEqual(coverage['bounds_identified_pairs'],0)
                        with (output/'quantile_identification_bounds.csv').open(encoding='utf-8-sig') as f:
                            bounds=list(csv.DictReader(f))
                        self.assertTrue(bounds)
                        self.assertTrue(all(r['count_lower']==r['count_upper']=='' for r in bounds))

    def test_boolean_or_unknown_precision_is_not_a_confirmed_contract(self):
        row=dict(study_mode='全日制',admission_route='一志愿',special_plan='普通计划',
                 degree_type='学术',direction='不分方向',joint_program='非联培',
                 scope='普通统考',grade='官方',quantile_method='inclusive_linear')
        for precision in [False,True,-1,math.inf,math.nan,'待核',None]:
            with self.subTest(precision=precision):
                self.assertTrue(kb.scope_risks({**row,'quantile_rounding':precision}))
        self.assertEqual(kb.scope_risks({**row,'quantile_rounding':.1}),[])

if __name__=='__main__':unittest.main()

"""检验共享校准、时间边界与可确认的偏好计分。"""
import csv
import math
import os
import sys
import tempfile
import unittest

SCRIPTS=os.path.join(os.path.dirname(os.path.dirname(__file__)),'scripts')
sys.path.insert(0,SCRIPTS)
import optimize
import evaluate_models as em
import preferences


class TestSharedModel(unittest.TestCase):
    def test_missing_year_weights_match_loader(self):
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,'a.csv')
            with open(p,'w',newline='') as f:
                w=csv.writer(f);w.writerow(['id','name','utility','rank_2025','rank_2024','rank_2023'])
                w.writerow(['a','某校',60,20000,'',30000])
            for rule in ('v2','legacy'):
                rows,_=optimize.load_candidates(p,True,.1,.25,-60,drift=.02,target_year=2026,sigma_rule=rule)
                mu,sigma,_=optimize.model_parameters([20000*math.exp(.02),None,30000*math.exp(.06)],sigma_rule=rule)
                self.assertAlmostEqual(rows[0]['mu'],mu)
                self.assertAlmostEqual(rows[0]['sigma'],sigma)

    def test_drift_has_no_target_year_input(self):
        def row(v): return dict(rank=v,full=True)
        d={2022:{'a':row(10000)},2023:{'a':row(11000)},2024:{'a':row(12000)}}
        original=em.yearly_errors(d)[2024]
        d[2024]['a']['rank']=90000
        changed=em.yearly_errors(d)[2024]
        self.assertEqual(original[0],changed[0])
        self.assertNotEqual(original[1],changed[1])

    def test_history_series_never_reads_physics_rows(self):
        from unittest.mock import patch
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'guangdong';folder.mkdir()
            (folder/'history_2025.csv').write_text('code,name,group,rank\n10564,示例校,201,10000\n')
            (folder/'physics_2025.csv').write_text('code,name,group,rank\n10564,示例校,201,90000\n')
            with patch.object(em,'DATA',d): data=em.load_series('guangdong_history')
            self.assertEqual(next(iter(data[2025].values()))['rank'],10000)

    def test_scale_for_earlier_year_does_not_use_later_errors(self):
        from unittest.mock import patch
        def row(v): return dict(rank=v,full=True)
        d={2022:{'a':row(10000)},2023:{'a':row(11000)},2024:{'a':row(12000)},2025:{'a':row(13000)},2026:{'a':row(14000)}}
        with patch.object(em,'load_series',return_value=d): before=em.review('zhejiang',2026)
        d[2025]['a']['rank']=90000
        with patch.object(em,'load_series',return_value=d): after=em.review('zhejiang',2026)
        early=lambda rows:[r for r in rows if r.get('target_year')==2024]
        self.assertEqual(early(before),early(after))

    def test_two_year_series_is_evaluated_without_tuning_on_holdout(self):
        from unittest.mock import patch
        data={2025:{'a':dict(rank=10000,full=True)},2026:{'a':dict(rank=11000,full=True)}}
        with patch.object(em,'load_series',return_value=data): rows=em.review('hunan_history',2026)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['sigma_scale']==1.0 and r['n']==1 for r in rows))
        self.assertTrue(all(r['category']=='history' for r in rows))

    def test_heavy_tail_improves_extreme_loss_but_not_guaranteed_central(self):
        normal=em.score([(2,.1)],1,'normal')['nll']
        thick=em.score([(2,.1)],1,'mixture')['nll']
        self.assertLess(thick,normal)
        self.assertGreater(em.score([(0,.1)],1,'mixture')['nll'],em.score([(0,.1)],1,'normal')['nll'])


class TestSchoolAlias(unittest.TestCase):
    def test_official_rename_keeps_metadata_not_provincial_code(self):
        import pool
        codes,names=pool.schools()
        for old,new in (("湖州师范学院","湖州师范大学"),("浙江科技学院","浙江科技大学")):
            self.assertEqual(pool.lookup("9999",new,codes,names)["code"],names[old]["code"])
            self.assertTrue(pool.lookup("9999",new,codes,names)["province"])

    def test_admissions_code_collision_cannot_override_school_name(self):
        import pool
        codes,names=pool.schools()
        self.assertEqual(pool.lookup("14001","聊城大学东昌学院",codes,names)["name"],"聊城大学东昌学院")
        self.assertEqual(pool.lookup("14001","聊城大学东昌学院",codes,names)["province"],"山东省")
        self.assertEqual(pool.lookup("14001","未核实新学院",codes,names),{})
        self.assertEqual(pool.lookup("","北京大学未核实新学院",codes,names),{})


class TestPreferenceChecks(unittest.TestCase):
    def config(self):
        attrs=preferences.ATTRS
        return {'scenarios':{'student':{'confirmed':True,'priority':list(attrs),
                'anchors':{'low':{'name':'底线','scores':dict.fromkeys(attrs,2)},
                           'high':{'name':'梦校','scores':dict.fromkeys(attrs,9)}}}}}

    def rows(self):
        return [dict(id='a',name='甲',school_score=8,major_score=3,city_score=5,outlook_score=5),
                dict(id='b',name='乙',school_score=3,major_score=8,city_score=5,outlook_score=5)]

    def test_anchors_do_not_move_with_candidate_pool(self):
        config=self.config();rows=self.rows()
        a,_=preferences.evaluate(rows,config,'student')
        b,_=preferences.evaluate(rows+[dict(id='c',name='丙',**{x+'_score':10 for x in preferences.ATTRS})],config,'student')
        self.assertEqual(a[0]['utility'],b[0]['utility'])
        self.assertGreater(b[-1]['utility'],100)

    def test_conflicting_choice_is_reported_not_overwritten(self):
        config=self.config();config['scenarios']['student']['checks']=[dict(a='a',b='b',choice='b')]
        scored,review=preferences.evaluate(self.rows(),config,'student')
        self.assertGreater(scored[0]['utility'],scored[1]['utility'])
        self.assertEqual(review['warnings'][0]['choice'],'b')

    def test_unconfirmed_and_unknown_scores_fail(self):
        config=self.config();config['scenarios']['student']['confirmed']=False
        with self.assertRaises(ValueError): preferences.evaluate(self.rows(),config,'student')
        config['scenarios']['student']['confirmed']=True
        rows=self.rows();rows[0]['major_score']='未知'
        with self.assertRaises(ValueError): preferences.evaluate(rows,config,'student')


if __name__=='__main__': unittest.main()

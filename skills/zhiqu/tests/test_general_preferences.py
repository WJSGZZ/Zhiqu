import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from preferences import evaluate


class GeneralPreferenceAnchors(unittest.TestCase):
    def test_unrelated_candidate_does_not_change_grad_or_career_utility(self):
        for attrs in [('training', 'affordability'), ('remaining_cash', 'contract', 'growth')]:
            config = {'attributes':attrs, 'scenarios':{'self':{'confirmed':True, 'priority':attrs,
                      'anchors':{'low':{'scores':dict.fromkeys(attrs,2)}, 'high':{'scores':dict.fromkeys(attrs,8)}}}}}
            row = dict(id='A', **{a+'_score':5 for a in attrs})
            before = evaluate([row], config, 'self')[0][0]['utility']
            after = evaluate([row, dict(id='B', **{a+'_score':10 for a in attrs})], config, 'self')[0][0]['utility']
            self.assertEqual(before, after)
            unknown = dict(row, **{attrs[0]+'_score':None})
            with self.assertRaises(ValueError): evaluate([unknown], config, 'self')
            unconfirmed = copy.deepcopy(config); unconfirmed['scenarios']['self']['confirmed'] = False
            with self.assertRaises(ValueError): evaluate([row], unconfirmed, 'self')

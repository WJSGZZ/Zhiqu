import copy
import csv
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from serve_report import ReportApplication, make_server, validate_changes
from check_report import check_report


class InteractiveReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads((ROOT/'examples/report_demo.json').read_text())
        cls.defaults={'rank':22000,'slots':6,'u_fall':-60}
        cls.app=ReportApplication(ROOT/'examples/candidates_demo.csv',cls.original,cls.defaults)
        cls.server=make_server(cls.app,0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)

    def request(self, method='POST', payload=None, headers=None, path='/api/recompute'):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=15)
        supplied={'Content-Type':'application/json','X-Zhiqu-Token':self.app.token}
        if headers is not None:supplied.update(headers)
        body=json.dumps(payload if payload is not None else {'selected':[0],'params':{}})
        connection.request(method,path,body if method=='POST' else None,supplied)
        response=connection.getresponse();status=response.status;content=response.read();connection.close()
        return status,content

    def test_http_recompute_matches_actual_command_line_model(self):
        status,body=self.request(payload={'selected':list(range(len(self.app.rows))),'params':{}})
        self.assertEqual(status,200,body)
        actual=json.loads(body)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            completed=subprocess.run([sys.executable,str(ROOT/'scripts/optimize.py'),str(ROOT/'examples/candidates_demo.csv'),'--rank','22000','--slots','6','--u-fall','-60','--json',str(path)],capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            expected=json.loads(path.read_text())
        for key in ('expected_utility','p_fall','stress','list'):
            self.assertEqual(actual['result'][key],expected[key])
        self.assertEqual(check_report(actual['report'],actual['result'],actual['report_html']),[])
        self.assertNotIn('37%',actual['report']['summary']['headline'])
        self.assertNotIn('sensitivity',actual['report'])

    def test_selection_and_changed_parameters_are_recomputed(self):
        status,body=self.request(payload={'selected':[0],'params':{'rank':1000,'rho':0.1,'sigma_scale':1.7,'u_fall':-100}})
        self.assertEqual(status,200,body);data=json.loads(body)
        self.assertEqual(len(data['result']['list']),1)
        self.assertEqual(data['result']['list'][0]['id'],'A1')
        self.assertEqual(data['result']['params']['rank'],1000)
        self.assertEqual(data['result']['params']['sigma_scale'],1.7)
        self.assertEqual(data['report']['meta']['rank'],1000)
        self.assertEqual(check_report(data['report'],data['result'],data['report_html']),[])

    def test_request_cannot_select_paths_or_inject_command_arguments(self):
        invalid=[{'selected':[0],'params':{},'path':'/etc/passwd'},
                 {'selected':[0],'params':{'rank':'$(touch /tmp/never)'}},
                 {'selected':[0],'params':{'drift':0.1}},
                 {'selected':[-1],'params':{}},{'selected':[True],'params':{}},
                 {'selected':[0,0],'params':{}},{'selected':[],'params':{}},
                 {'selected':[0],'params':{'rho':float('nan')}}]
        for payload in invalid:
            with self.subTest(payload=payload):
                status,_=self.request(payload=payload)
                self.assertEqual(status,400)
        self.assertEqual(self.request(method='GET',path='/../scripts/optimize.py')[0],404)
        self.assertEqual(self.request(headers={'Content-Length':'40000'})[0],400)

    def test_only_loopback_host_and_authorized_same_origin_session(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        for headers in ({'X-Zhiqu-Token':''},{'X-Zhiqu-Token':'é'},{'Origin':'https://evil.example'}, {'Host':'evil.example'}):
            self.assertEqual(self.request(headers=headers)[0],403)
        self.app.lock.acquire()
        try:self.assertEqual(self.request()[0],409)
        finally:self.app.lock.release()

    def test_ui_escapes_candidate_names_and_requires_major_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'candidates.csv'
            path.write_text('id,name,utility,rank_2026\nx,<script>alert(1)</script>,80,20000\n')
            app=ReportApplication(path,self.original,self.defaults)
            self.assertNotIn('<script>alert(1)</script>',app.page())
            self.assertIn('&lt;script&gt;',app.page())
            path.write_text('id,name,majors,rank_2026\nx,示例组,专业:80:20000,20000\n')
            with self.assertRaisesRegex(ValueError,'majors_complete'):ReportApplication(path,self.original,self.defaults)

    def test_numeric_inputs_have_finite_bounded_types(self):
        for params in ({'rho':1},{'sigma_scale':0},{'slots':1.2},{'rank':-1},{'max_fall':2},{'rank':True}):
            with self.assertRaises(ValueError):validate_changes(params)
        self.assertEqual(validate_changes({'max_fall':None}),{'max_fall':None})


if __name__=='__main__':
    unittest.main()

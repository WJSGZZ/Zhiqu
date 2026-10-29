"""RAM-only transport protocol tests: no DNS, HTTP, credentials or raw files."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'zhiqu-shared/scripts'))
import kaoyan_public_http as http

class PublicHTTPTests(unittest.TestCase):
    def test_curl_body_and_headers_use_anonymous_pipes_only(self):
        body=b'synthetic-private-123456789012345'
        meta=json.dumps({'http_code':200,'content_type':'text/html'}).encode()
        fake=SimpleNamespace(resolve_public=Mock(return_value='93.184.216.34'),DNS_METHODS={},
                             Unretrieved=ValueError,ResolutionError=ValueError,TransportError=ValueError)
        called=[]
        def run(args,**kw):
            called.append(args)
            self.assertTrue(kw['capture_output'])
            return subprocess.CompletedProcess(args,0,body,b'HTTP/1.1 200 OK\r\nSet-Cookie: synthetic-secret\r\n'+http.MARK+meta)
        captured=io.StringIO()
        with patch.object(http.subprocess,'run',side_effect=run),patch.object(Path,'write_bytes',side_effect=AssertionError('raw write')),redirect_stdout(captured),redirect_stderr(captured):
            result=http.memory_curl_adapter(fake)('https://fixture.edu.cn/a',headers={},form=None,max_bytes=1000,timeout=20)
        self.assertEqual(result['body'],body)
        self.assertEqual(result['headers']['set-cookie'],'[present]')
        self.assertEqual(captured.getvalue(),'')
        args=called[0]
        self.assertEqual(args[args.index('--output')+1],'-')
        self.assertEqual(args[args.index('--dump-header')+1],'/dev/stderr')
        for prohibited in ['--insecure','-k','--cookie','--cookie-jar','-L']:
            self.assertNotIn(prohibited,args)

    def test_every_redirect_target_is_checked_before_dns_and_http(self):
        for url in ['https://fixture.edu.cn/new?candidate_name=synthetic_sentinel',
                    'https://fixture.edu.cn/sso/start', 'https://fixture.edu.cn/captcha/start',
                    'https://fixture.edu.cn/a?ksbh=synthetic_sentinel',
                    'https://user:pass@fixture.edu.cn/redirect']:
            fake = SimpleNamespace(resolve_public=Mock(), TargetValidationError=ValueError)
            with patch.object(http.subprocess, 'run') as send:
                with self.assertRaisesRegex(ValueError, '拒绝不符合公开取文规则'):
                    http.memory_curl_adapter(fake)(url, headers={}, form=None, max_bytes=1000, timeout=20)
            fake.resolve_public.assert_not_called()
            send.assert_not_called()

    def test_public_receipt_never_contains_body_private_header_or_reason(self):
        raw=b'synthetic-private-123456789012345'
        item={'body':raw,'headers':{'authorization':'synthetic-secret'}}
        out=http.public_receipt('https://fixture.edu.cn/a',item,[{'url':'https://fixture.edu.cn/a','http_status':200,'body':raw,'header':'synthetic-secret'}],'synthetic-private')
        encoded=json.dumps(out)
        self.assertNotIn('synthetic',encoded)
        self.assertEqual(out['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertFalse(out['raw_original_written'])

    def test_private_queries_credentials_and_restricted_paths_rejected(self):
        for url in ['https://user:pass@fixture.edu.cn/a','https://fixture.edu.cn/login',
                    'https://fixture.edu.cn/a?candidate_name=synthetic',
                    'https://fixture.edu.cn/a?candidate_number=123456789012345',
                    'https://fixture.edu.cn/a?access_token=synthetic',
                    'https://fixture.edu.cn/a?%E5%A7%93%E5%90%8D=synthetic']:
            with self.subTest(kind=url.split('?')[-1].split('=')[0]):
                with self.assertRaises(http.SafeStop):http.safe_url(url)

    def test_failure_digits_in_fingerprint_or_url_are_not_http_status(self):
        for reason in ['transfer failed sha256=abc412def403xyz',
                       'TLS error https://fixture.edu.cn/202403/notice.html',
                       'transfer failed https://fixture.edu.cn/a?tag=429401']:
            with self.subTest(reason=reason):
                self.assertNotIn(http.stop_category(reason),
                                 {'http_block','login','rate_limit'})
        self.assertEqual(http.stop_category('TLS error https://fixture.edu.cn/202403/a'),'tls')

    def test_structured_http_status_and_explicit_challenge_stop(self):
        for code,category in [(401,'login'),(403,'http_block'),(412,'http_block'),(429,'rate_limit')]:
            with self.subTest(code=code):
                self.assertEqual(http.stop_category('transfer failed',code),category)
                self.assertEqual(http.stop_category('HTTP '+str(code)),category)
        self.assertEqual(http.stop_category('浏览器环境检测',200),'verification')
        self.assertEqual(http.stop_category('浏览器校验页（需确认交互）',200),'verification')
        self.assertEqual(http.stop_category('请求保护暂停 site_hour_budget',200),'shared_guard')

    def test_receipt_uses_actual_status_and_success_has_no_stop_category(self):
        url='https://fixture.edu.cn/202403/a'
        attempts=[{'url':url,'http_status':200,'body_sha256':'abc412def'}]
        ok=http.public_receipt(url,{'body':b'anonymous'},attempts,'sha256=abc412def')
        self.assertIsNone(ok['stop_category'])
        failed=http.public_receipt(url,None,attempts,'TLS error')
        self.assertEqual(failed['stop_category'],'tls')
        attempts[0]['http_status']=412
        self.assertEqual(http.public_receipt(url,None,attempts,None)['stop_category'],'http_block')

    def test_original_retrieve_owns_guard_and_restores_transport(self):
        original=Mock()
        crawler=SimpleNamespace(curl_once=original)
        crawler.retrieve=Mock(return_value=(None,[],'403'))
        with patch.object(http,'memory_curl_adapter',return_value=Mock()):
            http.retrieve_memory('https://fixture.edu.cn/a',max_attempts=1,crawler=crawler)
        self.assertIs(crawler.curl_once,original)
        kw=crawler.retrieve.call_args.kwargs
        self.assertFalse(kw['fallback'])
        self.assertFalse(kw['allow_http_redirect'])
        self.assertEqual(kw['max_attempts'],1)
        self.assertEqual(kw['transport'],'plain')

if __name__=='__main__':unittest.main()

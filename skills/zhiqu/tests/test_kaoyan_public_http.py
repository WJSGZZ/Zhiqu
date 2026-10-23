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

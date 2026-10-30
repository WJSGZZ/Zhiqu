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
        receipt=http.public_receipt('https://fixture.edu.cn/a',result,[],None)
        self.assertEqual(receipt['format_hint']['declared_mime'],'text/html')
        self.assertNotIn('synthetic',json.dumps(receipt))
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

    def test_rejected_private_redirect_has_anonymous_stop_receipt(self):
        url = 'https://fixture.edu.cn/start'
        rejected = url+'?candidate_name=synthetic_private_sentinel'
        receipt = http.public_receipt(url, None, [
            {'url': url, 'http_status': 302},
            {'url': rejected, 'origin_attempted': False, 'reason': 'fixed local rejection'},
        ], 'fixed local rejection')
        self.assertEqual(receipt['stop_category'], 'restricted_redirect')
        self.assertEqual(receipt['attempts'][-1]['url'], url)
        self.assertFalse(receipt['attempts'][-1]['origin_attempted'])
        self.assertNotIn('synthetic_private_sentinel', json.dumps(receipt))
        self.assertNotIn('candidate_name', json.dumps(receipt))

    def test_login_endpoint_file_extensions_are_rejected_before_transport(self):
        fake = SimpleNamespace(resolve_public=Mock(), TargetValidationError=ValueError)
        for path in ['/Open/Master/signin.aspx', '/Login.jsp', '/login.html', '/sso.php', '/captcha.do']:
            with self.subTest(path=path), patch.object(http.subprocess, 'run') as send:
                with self.assertRaises(http.SafeStop):http.safe_url('https://fixture.edu.cn'+path)
                with self.assertRaises(ValueError):
                    http.memory_curl_adapter(fake)('https://fixture.edu.cn'+path, headers={}, form=None, max_bytes=1000, timeout=20)
                send.assert_not_called()
        fake.resolve_public.assert_not_called()
        for path in ['/news/login-policy.html', '/guide/signing.html', '/catalog.aspx']:
            self.assertEqual(http.safe_url('https://fixture.edu.cn'+path), 'https://fixture.edu.cn'+path)

    def test_internal_public_dns_name_stays_on_native_transport_only_for_bound_host(self):
        resolver = 'https://cloudflare-dns.com/dns-query?name=fixture.edu.cn&type=A'
        original = Mock(return_value={'body': b'public DNS reply'})
        memory = Mock(return_value={'body': b'public source in RAM'})
        crawler = SimpleNamespace(curl_once=original)
        helper = dict(headers={'Accept':'application/dns-json'}, form=None,
                      max_bytes=65536, timeout=8, resolved_ip='1.1.1.1')
        def retrieve(url, **kwargs):
            self.assertEqual(crawler.curl_once(resolver, **helper)['body'], b'public DNS reply')
            self.assertEqual(crawler.curl_once(url, headers={}, form=None, max_bytes=1000, timeout=20)['body'], b'public source in RAM')
            return None, [], 'offline'
        crawler.retrieve = Mock(side_effect=retrieve)
        with patch.object(http, 'memory_curl_adapter', return_value=memory):
            http.retrieve_memory('https://fixture.edu.cn/notice', crawler=crawler)
        original.assert_called_once_with(resolver, **helper)
        self.assertEqual(memory.call_count, 1)
        self.assertIs(crawler.curl_once, original)

    def test_dns_helper_contract_never_exempts_an_unbound_or_private_business_query(self):
        resolver = 'https://cloudflare-dns.com/dns-query?name=fixture.edu.cn&type=A'
        helper = dict(headers={'Accept':'application/dns-json'}, form=None,
                      max_bytes=65536, timeout=8, resolved_ip='1.1.1.1')
        cases = [(resolver.replace('fixture.edu.cn','other.edu.cn'), {}),
                 (resolver+'&extra=1', {}), (resolver.replace('type=A','type=AAAA'), {}),
                 (resolver, {'resolved_ip':'8.8.8.8'}), (resolver, {'form':{'key':'value'}}),
                 (resolver, {'headers':{}}), (resolver, {'max_bytes':65537}),
                 ('https://fixture.edu.cn/notice?name=synthetic_private', {})]
        for target, updates in cases:
            with self.subTest(kind=target.split('?')[0], changes=list(updates)):
                original = Mock()
                crawler = SimpleNamespace(curl_once=original, TargetValidationError=ValueError)
                def retrieve(url, **kwargs):
                    with self.assertRaises(ValueError):crawler.curl_once(target, **dict(helper, **updates))
                    return None, [], 'offline'
                crawler.retrieve = Mock(side_effect=retrieve)
                http.retrieve_memory('https://fixture.edu.cn/notice', crawler=crawler)
                original.assert_not_called()
        with self.assertRaises(http.SafeStop):
            http.retrieve_memory(resolver, crawler=crawler)

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



class ReceiptFormatHintTests(unittest.TestCase):
    def receipt(self,body,mime=None):
        return http.public_receipt('https://fixture.edu.cn/download',{'body':body,'content_type':mime,'headers':{'set-cookie':'synthetic-secret'}},[],None)

    def test_html_returned_for_spreadsheet_has_signals_not_a_block_verdict(self):
        body=b'<script>var privateValue="synthetic-secret";</script><form></form>'
        out=self.receipt(body,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        hint=out['format_hint'];self.assertEqual(hint['body_signature'],'html_prefix');self.assertTrue(hint['html_tags']['script']);self.assertTrue(hint['html_tags']['form']);self.assertFalse(hint['html_tags']['title'])
        self.assertEqual(out['status'],'retrieved');self.assertIsNone(out['stop_category']);self.assertEqual(out['sha256'],hashlib.sha256(body).hexdigest());self.assertNotIn('synthetic',json.dumps(out));self.assertFalse(out['raw_original_written'])

    def test_finite_mime_drops_parameters_unknown_values_and_bad_types(self):
        cases=[(' TEXT/HTML ; filename=synthetic-secret','text/html'),('application/x-synthetic-secret','unrecognized'),('text/html\r\nSecret: synthetic-secret','unrecognized'),(None,'not_provided'),('','not_provided'),({},'unrecognized'),(False,'unrecognized')]
        for mime,expected in cases:
            with self.subTest(mime_type=type(mime).__name__):
                out=self.receipt(b'opaque',mime);self.assertEqual(out['format_hint']['declared_mime'],expected);self.assertNotIn('synthetic',json.dumps(out))

    def test_binary_signatures_are_only_container_prefix_hints(self):
        fixtures=[(b'%PDF-1.7','pdf'),(b'PK\x03\x04','zip'),(b'PK\x05\x06','zip'),(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1','ole_compound'),(b'\x89PNG\r\n\x1a\n','png'),(b'\xff\xd8\xff','jpeg'),(b'GIF89a','gif'),(b'RIFF1234WEBP','webp'),(b'','empty'),(b'opaque','unknown')]
        for body,expected in fixtures:
            with self.subTest(expected=expected):
                hint=self.receipt(body,'application/octet-stream')['format_hint'];self.assertEqual(hint['body_signature'],expected);self.assertIn('not_business_verification',hint['scope']);self.assertIsNone(hint['html_tags']);self.assertNotIn('header_bytes',hint)

    def test_prefix_limit_does_not_claim_missing_later_tags(self):
        body=b'<html>'+b' '*(http.FORMAT_HINT_PREFIX_BYTES)+b'<script>synthetic-secret</script>'
        hint=self.receipt(body,'text/html')['format_hint'];self.assertEqual(hint['inspected_bytes'],http.FORMAT_HINT_PREFIX_BYTES);self.assertTrue(hint['prefix_truncated']);self.assertFalse(hint['html_tags']['script']);self.assertIn('prefix_only',hint['scope'])

    def test_comments_and_script_literals_do_not_create_title_or_table(self):
        body=b'<html><!-- <title>synthetic-secret</title> --><script>var x="<table></table>";</script></html>'
        hint=self.receipt(body,'text/html')['format_hint'];self.assertFalse(hint['html_tags']['title']);self.assertFalse(hint['html_tags']['table']);self.assertTrue(hint['html_tags']['script']);self.assertNotIn('synthetic',json.dumps(hint))

    def test_title_and_textarea_literals_do_not_create_form_or_table(self):
        body=b'<html><title>synthetic-secret <form></form></title><textarea><table></table></textarea><img></html>'
        hint=self.receipt(body,'text/html')['format_hint']
        self.assertTrue(hint['html_tags']['title_has_nonspace_text'])
        self.assertFalse(hint['html_tags']['form']);self.assertFalse(hint['html_tags']['table'])
        self.assertTrue(hint['html_tags']['img']);self.assertNotIn('synthetic',json.dumps(hint))

    def test_utf16_bom_structure_never_keeps_title_text_or_attributes(self):
        body='<html><title>synthetic-secret</title><iframe src="synthetic-private"></iframe></html>'.encode('utf-16')
        hint=self.receipt(body,'text/html')['format_hint'];self.assertEqual(hint['body_signature'],'html_prefix');self.assertTrue(hint['html_tags']['title_has_nonspace_text']);self.assertTrue(hint['html_tags']['iframe']);self.assertNotIn('synthetic',json.dumps(hint))

    def test_unretrieved_body_cannot_be_reconstructed_from_attempt_payload(self):
        out=http.public_receipt('https://fixture.edu.cn/a',None,[{'url':'https://fixture.edu.cn/a','http_status':403,'body':b'synthetic-secret','content_type':'text/html'}],'HTTP 403')
        self.assertIsNone(out['format_hint']);self.assertEqual(out['stop_category'],'http_block');self.assertNotIn('synthetic',json.dumps(out))

if __name__=='__main__':unittest.main()

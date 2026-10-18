"""fetch_source.py：用本机临时服务器检验取文、拦截页识别与来源记录。"""
import hashlib
import http.server
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "zhiqu-shared" / "scripts" / "fetch_source.py"
spec = importlib.util.spec_from_file_location("fetch_source", SCRIPT)
fetch_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_source)

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
CAPTCHA = b"<!doctype html><html><head><title>\xe5\xae\x89\xe5\x85\xa8\xe9\xaa\x8c\xe8\xaf\x81</title></head><body></body></html>"
LOGIN = b"<html><head><title>Portal</title></head><body><form><input type='password' name='p'></form></body></html>"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        routes = {
            "/notice.pdf": (200, PDF, "application/pdf"),
            "/fake.pdf": (200, b"<html><body>not a pdf</body></html>", "text/html"),
            "/captcha": (200, CAPTCHA, "text/html; charset=utf-8"),
            "/login": (200, LOGIN, "text/html"),
            "/limited": (429, b"slow down", "text/plain"),
            "/big.pdf": (200, PDF + b"0" * 4096, "application/pdf"),
        }
        if self.path == "/ua-only":
            ok = "Chrome" in self.headers.get("User-Agent", "")
            return self.send(200 if ok else 412, b"<html><body>ok</body></html>" if ok else b"blocked", "text/html")
        code, body, ctype = routes.get(self.path, (404, b"missing", "text/plain"))
        self.send(code, body, ctype)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        form = self.rfile.read(size).decode()
        self.send(200, ("<html><body>" + form + "</body></html>").encode(), "text/html")


class TestFetchSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        fetch_source.RETRY_PAUSE = 0  # 测试不等待重试间隔

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "file"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        with redirect_stdout(io.StringIO()) as buf:
            code = fetch_source.main([*args, "--output", str(self.out)])
        receipt = json.loads(Path(str(self.out) + ".source.json").read_text(encoding="utf-8"))
        return code, receipt, buf.getvalue()

    def test_pdf_saved_with_matching_hash(self):
        code, receipt, _ = self.run_cli(self.base + "/notice.pdf")
        self.assertEqual(code, 0)
        self.assertEqual(self.out.read_bytes(), PDF)
        self.assertEqual(receipt["status"], "retrieved")
        self.assertEqual(receipt["schema_version"], "source-receipt-v1")
        self.assertEqual(receipt["sha256"], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(receipt["bytes"], len(PDF))

    def test_html_posing_as_pdf_is_rejected(self):
        code, receipt, _ = self.run_cli(self.base + "/fake.pdf")
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertEqual(receipt["status"], "unretrieved")
        self.assertIn("文件头", receipt["reason"])

    def test_captcha_and_login_pages_are_not_saved(self):
        code, receipt, _ = self.run_cli(self.base + "/captcha")
        self.assertEqual((code, receipt["next_action"]), (2, "manual_download"))
        self.assertFalse(self.out.exists())
        self.tearDown(); self.setUp()
        code, receipt, _ = self.run_cli(self.base + "/login")
        self.assertEqual((code, receipt["next_action"]), (2, "stop_login"))

    def test_rate_limit_stops_without_retry(self):
        code, receipt, _ = self.run_cli(self.base + "/limited")
        self.assertEqual((code, receipt["next_action"]), (2, "stop_rate_limited"))
        self.assertEqual(receipt["attempts"], [])

    def test_common_ua_retry_after_412(self):
        code, receipt, _ = self.run_cli(self.base + "/ua-only")
        self.assertEqual(code, 0)
        self.assertEqual([a["method"] for a in receipt["attempts"]], ["own_ua", "common_ua"])

    def test_missing_page_records_all_attempts(self):
        code, receipt, _ = self.run_cli(self.base + "/nothing")
        self.assertEqual(code, 2)
        self.assertEqual(len(receipt["attempts"]), 2)
        self.assertIn("HTTP 404", receipt["reason"])

    def test_size_limit(self):
        code, receipt, _ = self.run_cli(self.base + "/big.pdf", "--max-mb", "0.001")
        self.assertEqual((code, receipt["next_action"]), (2, "review_budget"))

    def test_post_form_for_public_query(self):
        code, receipt, _ = self.run_cli(self.base + "/query", "--form", "mkxh=1", "--form", "tzid=16559")
        self.assertEqual(code, 0)
        self.assertIn(b"mkxh=1&tzid=16559", self.out.read_bytes())

    def test_refuses_overwrite_and_bad_scheme(self):
        self.out.write_bytes(b"old")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fetch_source.main([self.base + "/notice.pdf", "--output", str(self.out)])
        self.assertEqual(self.out.read_bytes(), b"old")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            fetch_source.main(["file:///etc/passwd", "--output", str(self.out) + "2"])

    def test_https_falls_back_to_http_only_for_get(self):
        plans = []
        real = fetch_source.once
        fetch_source.once = lambda url, **kw: plans.append((url, kw["data"])) or {"error": "网络错误"}
        try:
            with self.assertRaises(fetch_source.Unretrieved):
                fetch_source.retrieve("https://example.gov.cn/a.pdf")
            self.assertEqual(plans[-1][0], "http://example.gov.cn/a.pdf")
            plans.clear()
            with self.assertRaises(fetch_source.Unretrieved):
                fetch_source.retrieve("https://example.gov.cn/q", form=[("a", "1")])
            self.assertTrue(all(u.startswith("https://") for u, _ in plans))
        finally:
            fetch_source.once = real


if __name__ == "__main__":
    unittest.main()

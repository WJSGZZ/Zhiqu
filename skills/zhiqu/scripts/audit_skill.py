#!/usr/bin/env python3
"""检查技能文档本地链接、脚本入口与公开案例重现；外链只测公开可达性。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import ssl
import sys
import tempfile
import urllib.request
import urllib.error
from check_report import check_report

ROOT = Path(__file__).resolve().parents[1]


def local_links(root=ROOT):
    errors, urls = [], set()
    for doc in root.rglob('*.md'):
        text = doc.read_text(encoding='utf-8')
        urls.update(url.rstrip(").,;").split("#")[0] for url in re.findall(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", text))
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text):
            target = target.strip('<>')
            if target.startswith(('https://', 'http://')):
                urls.add(target.split('#')[0])
            elif not target.startswith(('mailto:', '#')):
                path = target.split('#')[0]
                if path and not (doc.parent / path).exists():
                    errors.append(f'{doc.relative_to(root)}: 无效本地链接 {target}')
    return errors, urls


def public_url(url, context=None):
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'Zhiqu-public-link-audit/1.0'})
        with urllib.request.urlopen(request, timeout=12, context=context) as response:
            return url, str(response.status)
    except (urllib.error.URLError, OSError) as exc:
        return url, f'未确认: {exc}'


def reproduce_cases(dest):
    errors = []
    for directory in ('case_b_zhejiang_2027', 'case_c_guangdong_e2e'):
        case = ROOT / 'examples' / directory
        old = json.loads((case / 'result.json').read_text(encoding='utf-8'))
        args = [sys.executable, str(ROOT / 'scripts/optimize.py'), str(case / 'candidates.csv')]
        for key, value in old['params'].items():
            if key in ('csv', 'json') or value is None or value is False:
                continue
            flag = '--' + key.replace('_', '-')
            if value is True:
                args.append(flag)
            else:
                for item in value if isinstance(value, list) else [value]:
                    args.extend([flag, str(item)])
        output = dest / (directory + '.json')
        args.extend(['--json', str(output)])
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            errors.append(f'{directory}: 重现失败 {result.stderr.strip()}')
            continue
        new = json.loads(output.read_text(encoding='utf-8'))
        html = dest / (directory + '.html')
        generated = subprocess.run([sys.executable, str(ROOT / 'scripts/report.py'), str(case / 'report.json'), '--opt', str(output), '--out', str(html)], capture_output=True, text=True)
        if generated.returncode:
            errors.append(f'{directory}: 报告生成失败 {generated.stderr.strip()}')
        else:
            rep = json.loads((case / 'report.json').read_text(encoding='utf-8'))
            errors.extend(f'{directory}: {error}' for error in check_report(rep, new, html.read_text(encoding='utf-8')))
        for key in ('expected_utility', 'p_fall', 'stress', 'n_core', 'list', 'baseline_top_utility', 'baseline_safest'):
            if old[key] != new[key]:
                errors.append(f'{directory}: {key} 与保存结果不同，须复核模型或重现参数')
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--external', action='store_true', help='用普通公开 HTTP 请求检查外链；不绕过验证')
    ap.add_argument('--ca-file', help='可选本机 CA 证书包路径；不禁用证书验证')
    ap.add_argument('--examples', action='store_true', help='在临时目录重现两个公开案例并严格对照 result.json')
    args = ap.parse_args()
    errors, urls = local_links()
    for script in sorted((ROOT / 'scripts').glob('*.py')):
        completed = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
        if completed.returncode:
            errors.append(f'{script.name}: --help 失败 {completed.stderr.strip()}')
    if args.examples:
        with tempfile.TemporaryDirectory(prefix='zhiqu-audit-') as tmp:
            errors.extend(reproduce_cases(Path(tmp)))
    if args.external:
        context = ssl.create_default_context(cafile=args.ca_file)
        with ThreadPoolExecutor(max_workers=6) as executor:
            for url, status in executor.map(lambda url: public_url(url, context), sorted(urls)):
                print(f'{status}\t{url}')
                if status.startswith('未确认:'):
                    errors.append(f'外链未确认 {url}: {status}')
    if errors:
        ap.exit(1, '\n'.join(errors) + '\n')
    print(f'审计通过：本地文件链接、脚本 --help' + ('、公开案例重现' if args.examples else '') + f'；文档列有 {len(urls)} 个外链')
    if not args.external:
        print('外链尚未请求；如需可达性核验，添加 --external。片段锚点与自然语言断言须人工复核。')


if __name__ == '__main__':
    main()

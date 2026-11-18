#!/usr/bin/env python3
"""第三方秋招聚合的发现入口：列出"哪些单位在招"，再回单位官网核公告。

数据取自 xixicc186/xixicc2027 的 jobs.json（第三方整理，每日更新，仓库未声明
许可证）。运行时现取、只在内存里筛，不写进本项目；--file 读本机已有的副本。

    python3 skills/zhiqu-shared/scripts/campus_feed.py --cohort 2027届 --city 杭州
    python3 skills/zhiqu-shared/scripts/campus_feed.py --industry 央国企,银行/金融 --days 14 --json

每条都标“第三方聚合·待回官网核”：截止日、岗位和投递链接以单位官网公告为准；
没有投递链接的条目只说明“有人收录过”，不说明当前仍在招。
"""
import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# Same file from the repository, its GitHub Pages site and two CDNs; tried in
# order, because any one of them can be unreachable from a given network.
FEEDS = ('https://raw.githubusercontent.com/xixicc186/xixicc2027/main/jobs.json',
         'https://xixicc186.github.io/xixicc2027/jobs.json',
         'https://fastly.jsdelivr.net/gh/xixicc186/xixicc2027@main/jobs.json',
         'https://cdn.jsdelivr.net/gh/xixicc186/xixicc2027@main/jobs.json')
SOURCE = 'xixicc186/xixicc2027 jobs.json（第三方聚合）'
GRADE = '第三方聚合·待回官网核'


def _download(url, timeout):
    """System curl first (it uses the OS certificate store; python.org builds on
    macOS often lack one), then urllib."""
    curl = shutil.which('curl')
    if curl:
        done = subprocess.run([curl, '-fsSL', '--proto', '=https', '--max-time', str(timeout), url],
                              capture_output=True, timeout=timeout + 5)
        if done.returncode == 0:
            return done.stdout
    req = urllib.request.Request(url, headers={'User-Agent': 'zhiqu-campus-feed'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(urls=FEEDS, timeout=30, download=None):
    """First mirror that returns JSON wins; report only the failure kinds."""
    download = download or _download
    failures = []
    for url in urls:
        try:
            data = json.loads(download(url, timeout).decode('utf-8'))
            if isinstance(data, (list, dict)):
                return data
            failures.append('格式不符')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            failures.append(type(exc).__name__)
    raise SystemExit('未取到秋招聚合（' + '、'.join(failures) + '）；网络恢复后重试，或用 --file 读本机副本')


def parse_day(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def select(items, *, cohort=None, industries=(), city=None, keyword=None, days=None, today=None, stale_days=30):
    """Filter and annotate. Never drop the honesty fields; add them."""
    today = today or dt.date.today()
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get('company'):
            continue
        if cohort and item.get('cohort') != cohort:
            continue
        if industries and item.get('industry') not in industries:
            continue
        locations = item.get('locations') or []
        if city and not any(city in str(x) for x in locations):
            continue
        text = json.dumps(item, ensure_ascii=False)
        if keyword and keyword not in text:
            continue
        deadline = parse_day(item.get('deadline'))
        if deadline and deadline < today:
            continue
        if days is not None and (deadline is None or (deadline - today).days > days):
            continue
        last_seen = parse_day(item.get('last_seen'))
        notes = []
        if not item.get('apply_url'):
            notes.append('无投递链接：只说明被收录过，先找单位官网公告')
        if deadline is None:
            notes.append('未列截止日')
        if last_seen and (today - last_seen).days > stale_days:
            notes.append(f'最近一次收录在{(today - last_seen).days}天前，可能已结束')
        if not locations:
            notes.append('未列工作地点')
        out.append({
            'company': item['company'], 'cohort': item.get('cohort'), 'industry': item.get('industry'),
            'batch': item.get('batch'), 'positions': item.get('positions') or [], 'locations': locations,
            'deadline': item.get('deadline'), 'apply_url': item.get('apply_url'),
            'last_seen': item.get('last_seen'), 'confirmed_by': item.get('confirmed_by'),
            'grade': GRADE, 'notes': notes,
        })
    out.sort(key=lambda r: (r['deadline'] is None, r['deadline'] or '', r['company']))
    return out


def text_report(rows, total):
    lines = [f'来源：{SOURCE}；共 {total} 条，筛后 {len(rows)} 条。以下只是发现线索，投递前回单位官网核公告。']
    for r in rows:
        head = f"- {r['company']}（{r['industry'] or '未分类'}，{r['cohort'] or '届别未列'}）"
        detail = '；'.join(x for x in [
            '截止 ' + r['deadline'] if r['deadline'] else '',
            '地点 ' + '、'.join(r['locations']) if r['locations'] else '',
            '岗位 ' + '、'.join(map(str, r['positions'][:5])) if r['positions'] else '',
            r['apply_url'] or '',
        ] if x)
        lines.append(head + ('：' + detail if detail else ''))
        if r['notes']:
            lines.append('  ⚠ ' + '；'.join(r['notes']))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--file', help='本机已有的 jobs.json，不联网')
    ap.add_argument('--cohort', help='届别原文，如 2027届')
    ap.add_argument('--industry', help='行业，逗号分隔，如 央国企,银行/金融')
    ap.add_argument('--city', help='工作地点包含的文字，如 杭州')
    ap.add_argument('--keyword', help='公司或岗位关键词')
    ap.add_argument('--days', type=int, help='只看 N 天内截止的（无截止日的不列）')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    a = ap.parse_args(argv)
    data = json.loads(Path(a.file).read_text(encoding='utf-8')) if a.file else fetch()
    items = data if isinstance(data, list) else data.get('jobs', []) if isinstance(data, dict) else []
    industries = tuple(x for x in (a.industry or '').split(',') if x)
    rows = select(items, cohort=a.cohort, industries=industries, city=a.city, keyword=a.keyword, days=a.days)
    if a.json:
        print(json.dumps({'source': SOURCE, 'grade': GRADE, 'retrieved': dt.date.today().isoformat(),
                          'total': len(items), 'rows': rows}, ensure_ascii=False, indent=1))
    else:
        print(text_report(rows, len(items)))


if __name__ == '__main__':
    sys.exit(main())

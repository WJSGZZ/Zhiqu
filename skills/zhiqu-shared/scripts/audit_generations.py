#!/usr/bin/env python3
"""检查教育库目录里堆积的审计库（audit-<代号>.sqlite）。

每次发布新一代会写一份新的审计库，查询库原子替换后旧审计库就没有对应的查询库了。
旧审计库只在两种情况下有用：
  1. 它是回滚快照（snapshots/*/）里某个查询库的配对文件——快照目录自带一份，目录里这份是重复；
  2. 刚被替换，可能还有读者在用——保留最新的 --keep-previous 份。
其余都是孤儿，每份约 6 GB。

用法（在仓库根目录）：
  python3 skills/zhiqu-shared/scripts/audit_generations.py            # 只检查，有可清理文件则退出码 1
  python3 skills/zhiqu-shared/scripts/audit_generations.py --trash    # 把可清理文件移进废纸篓（不永久删除）
数据目录不进 git；目录不存在时直接通过。
"""
import argparse
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

PATTERN = re.compile(r'audit-[a-z0-9-]+\.sqlite')
RECENT_SECONDS = 600


def manifest_audit(query):
    """查询库 storage_manifest 里登记的审计文件名；读不到返回 None。"""
    try:
        with sqlite3.connect(f'{query.resolve().as_uri()}?mode=ro', uri=True) as c:
            return dict(c.execute('SELECT key,value FROM storage_manifest')).get('audit_file')
    except sqlite3.Error:
        return None


def snapshot_pairs(snapshot_roots):
    """快照目录里 查询库→审计库 的配对（审计库必须真实存在于同目录）。"""
    held = {}
    for root in snapshot_roots:
        for query in sorted(root.glob('*/education.sqlite')):
            name = manifest_audit(query)
            if name and (query.parent / name).is_file():
                held[name] = query.parent
    return held


def classify(data_dir, snapshot_roots, keep_previous=1):
    """返回 {'current','held','recent','removable'}：文件名列表（removable 为 (名, 原因)）。"""
    data_dir = Path(data_dir)
    audits = sorted((p for p in data_dir.iterdir() if PATTERN.fullmatch(p.name)), key=lambda p: p.stat().st_mtime)
    current = manifest_audit(data_dir / 'education.sqlite')
    if current is None and audits:
        raise RuntimeError('读不到 education.sqlite 的 storage_manifest，无法判断当前代，拒绝给出清理清单')
    held = snapshot_pairs(snapshot_roots)
    result = {'current': [], 'held': [], 'recent': [], 'removable': []}
    others = [p for p in audits if p.name != current and p.name not in held]
    previous = {p.name for p in others[-keep_previous:]} if keep_previous > 0 else set()
    for p in audits:
        if p.name == current:
            result['current'].append(p.name)
        elif p.name in held:
            result['removable'].append((p.name, f'与快照 {held[p.name].name}/ 内的配对文件重复'))
        elif p.name in previous:
            result['recent'].append(p.name)
        else:
            result['removable'].append((p.name, '孤儿：没有任何查询库引用'))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parents[1] / 'data'
    ap.add_argument('--data-dir', type=Path, default=root / 'education')
    ap.add_argument('--snapshots', type=Path, nargs='*', default=[root / 'data_complete' / 'snapshots'])
    ap.add_argument('--keep-previous', type=int, default=1, help='除当前代外保留最新几份，默认 1')
    ap.add_argument('--trash', action='store_true', help='把可清理文件移进 ~/.Trash')
    args = ap.parse_args(argv)
    if not args.data_dir.is_dir():
        print(f'{args.data_dir} 不存在，跳过')
        return 0
    result = classify(args.data_dir, args.snapshots, args.keep_previous)
    size = lambda n: (args.data_dir / n).stat().st_size
    print(f"当前代: {result['current']}；保留最近: {result['recent']}")
    total = 0
    for name, why in result['removable']:
        total += size(name)
        print(f'可清理 {size(name) / 2**30:.2f} GB  {name}  {why}')
    print(f"可清理 {len(result['removable'])} 份，共 {total / 2**30:.1f} GB")
    if args.trash and result['removable']:
        now = time.time()
        busy = [n for n, _ in result['removable'] if now - (args.data_dir / n).stat().st_mtime < RECENT_SECONDS]
        if busy:
            print(f'有文件 {RECENT_SECONDS // 60} 分钟内刚写过，可能正在发布，拒绝清理: {busy}', file=sys.stderr)
            return 2
        trash = Path.home() / '.Trash'
        for name, _ in result['removable']:
            shutil.move(str(args.data_dir / name), str(trash / name))
        print(f'已移入 {trash}')
        return 0
    return 1 if result['removable'] else 0


if __name__ == '__main__':
    sys.exit(main())

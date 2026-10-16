#!/usr/bin/env python3
"""知衢 · 回溯判定：把只用往年数据做出的志愿表，放到目标年的真实投档线上看落点。

只判断投档这一层：从第 1 个志愿往下走，第一个"目标年有唯一记录且投档最低位次 ≥ 本人位次"
的志愿即落点。落点之前遇到目标年没有记录（撤销、改名、未满额）或记录不唯一的志愿，
结果为"无法判定"并写明是哪一条，不跳过；全表都不够才是滑档。退档、体检、章程限制不在
判定范围内。另报每个志愿的预测过线概率与实际是否过线（Brier 分数）。

用法：
  python3 scripts/retro_judge.py result.json --target data/zhejiang/general_2026.csv --rank 33000
  可加 --json out.json 保存结果。
"""
import argparse
import csv
import json
from collections import defaultdict


def target_index(path, key):
    """(院校代码, 专业名或组号) → 目标年位次列表；没有位次的行记为 None。"""
    idx = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (r["code"].strip(), (r.get("major") if key == "major" else r.get("group") or "").strip())
            rank = r.get("rank", "").strip()
            idx[k].append(int(float(rank)) if rank else None)
    return idx


def judge(result, idx, rank, key):
    rows, landing, status, blocker = [], None, None, None
    for item in result["list"]:
        k = (item.get("code", "").strip(), (item["id"].split("-", 1)[1] if key == "major" else item.get("group", "")).strip())
        recs = idx.get(k, [])
        if len(recs) == 1 and recs[0] is not None:
            actual, cleared, note = recs[0], recs[0] >= rank, ""
        else:
            actual, cleared = None, None
            note = "目标年无此条目" if not recs else ("目标年记录不唯一" if len(recs) > 1 else "目标年无位次（可能未满额）")
        rows.append(dict(order=item["order"], id=item["id"], name=item["name"], tag=item.get("tag", ""),
                         p_clear=item["p_clear"], expected_cut_rank=item.get("expected_cut_rank"),
                         actual_rank=actual, cleared=cleared, note=note))
        if status is None:
            if cleared is None:
                status, blocker = "无法判定", item["order"]
            elif cleared:
                status, landing = "投档", item["order"]
    if status is None:
        status = "滑档"
    scored = [r for r in rows if r["cleared"] is not None]
    brier = sum((r["p_clear"] - r["cleared"]) ** 2 for r in scored) / len(scored) if scored else None
    land = next((r for r in rows if r["order"] == landing), None)
    return dict(rank=rank, status=status, landing_order=landing, blocker_order=blocker,
                landing=land["name"] if land else None,
                landing_utility=next((i["utility"] for i in result["list"] if i["order"] == landing), None),
                expected_utility=result.get("expected_utility"), n_slots=len(rows),
                n_observed=len(scored), brier=brier, rows=rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("result")
    ap.add_argument("--target", required=True, help="目标年官方投档 CSV")
    ap.add_argument("--rank", type=int, required=True)
    ap.add_argument("--key", choices=["major", "group"], default="major")
    ap.add_argument("--json")
    a = ap.parse_args()
    with open(a.result, encoding="utf-8") as f:
        result = json.load(f)
    out = judge(result, target_index(a.target, a.key), a.rank, a.key)
    print(f"位次 {a.rank}：{out['status']}" + (f"，第 {out['landing_order']} 个志愿 {out['landing']}" if out["landing"] else "")
          + (f"（第 {out['blocker_order']} 个志愿在目标年无法对应）" if out["blocker_order"] else ""))
    print("| 序 | 志愿 | 标签 | 预测过线概率 | 预测线 | 实际线 | 实际过线 | 说明 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in out["rows"]:
        print(f"| {r['order']} | {r['name']} | {r['tag']} | {r['p_clear']:.0%} | {r['expected_cut_rank'] or ''} | "
              f"{r['actual_rank'] or ''} | {'' if r['cleared'] is None else ('是' if r['cleared'] else '否')} | {r['note']} |")
    if out["brier"] is not None:
        print(f"\n可对照 {out['n_observed']}/{out['n_slots']} 条，Brier 分数 {out['brier']:.3f}（越小越准；全猜 50% 为 0.25）")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

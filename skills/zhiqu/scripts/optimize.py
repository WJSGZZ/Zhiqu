#!/usr/bin/env python3
"""知衢 · 平行志愿组合优化器（仅用 Python 标准库，3.8+）。

模型（详见 references/volunteer-game.md）：
- 平行志愿按"分数优先、遵循志愿、一次投档"：考生落到表中第一个"位次过线"的志愿。
  因此在已选定的志愿集合内，按效用从高到低排列是最优顺序；真正要优化的是"选哪几个"。
- 今年各志愿的最低录取位次 C_j 未知：log C_j ~ Normal(mu_j, sigma_j)，
  mu_j 为历年位次对数的近期加权平均（再乘人工校正 adj），各志愿通过共同因子相关（rho）。
- 过线后仍可能进不了所填专业（p_adjust）：服从调剂得 utility_adjusted；不服从则退档，等同滑档。
- 目标：最大化期望效用 E[U]；可另加"滑档概率上限"硬约束。
- 组合选择：边际改进贪心（独立情形下由 Chade & Smith 2006 证明最优），再做有限的单点替换。
- 补位：基准模型认为"已无增益"后，剩余位置在压力情景（波动 ×stress）下继续贪心补满，
  只接受不降低基准期望效用的补位，用来对冲历史数据没见过的大波动。

用法：
  python3 optimize.py candidates.csv --rank 23500 --slots 45 --u-fall -60
  python3 optimize.py candidates.csv --rank 23500 --slots 45 --u-fall -60 --max-fall 0.01 --json out.json
"""
import argparse
import csv
import json
import math
import random
import sys

try:
    (0).bit_count()

    def popcount(x):
        return x.bit_count()
except AttributeError:  # Python < 3.10
    def popcount(x):
        return bin(x).count("1")

RECENCY_WEIGHTS = [1.0, 0.7, 0.5, 0.35, 0.25]
JUMP_WARN = math.log(1.4)  # 相邻年份位次变化超过约 40% 视为不稳定


def parse_float(v, default=None):
    if v is None:
        return default
    v = str(v).strip()
    if v == "":
        return default
    return float(v)


def load_candidates(path, default_obey, sigma_floor, sigma_single, u_fall, require_utility=True):
    rows, skipped = [], []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rank_cols = sorted(
            [c for c in reader.fieldnames or [] if c and c.strip().lower().startswith("rank_")],
            reverse=True,  # rank_2025 > rank_2024 ... 最近的在前
        )
        if not rank_cols:
            sys.exit("CSV 缺少历年位次列，例如 rank_2025, rank_2024, rank_2023")
        for i, r in enumerate(reader, start=2):
            name = (r.get("name") or r.get("id") or f"第{i}行").strip()
            hist = [parse_float(r.get(c)) for c in rank_cols]
            pts = [(k, x) for k, x in enumerate(hist) if x and x > 0]
            u = parse_float(r.get("utility"))
            if not require_utility and u is None:
                u = 0.0
            if not pts or u is None:
                skipped.append(f"{name}（缺{'位次' if not pts else '效用'}）")
                continue
            ws = [RECENCY_WEIGHTS[min(k, len(RECENCY_WEIGHTS) - 1)] for k, _ in pts]
            logs = [math.log(x) for _, x in pts]
            mu = sum(w * l for w, l in zip(ws, logs)) / sum(ws)
            mu += math.log(parse_float(r.get("adj"), 1.0))
            if len(logs) >= 2:
                m = sum(logs) / len(logs)
                sd = math.sqrt(sum((l - m) ** 2 for l in logs) / (len(logs) - 1))
                sigma = max(sd, sigma_floor)
            else:
                sigma = sigma_single
            # 相邻年份位次变化过大（>约40%），多半是组内专业、招生条件或组号含义变了
            jumps = [abs(logs[k] - logs[k + 1]) for k in range(len(logs) - 1)]
            unstable = bool(jumps) and max(jumps) > JUMP_WARN
            if unstable:
                sigma = max(sigma, max(jumps))
            sigma = parse_float(r.get("sigma"), sigma)
            obey_raw = (r.get("obey") or "").strip()
            obey = default_obey if obey_raw == "" else obey_raw in ("1", "是", "y", "yes", "true")
            p_adj = parse_float(r.get("p_adjust"), 0.0)
            ua = parse_float(r.get("utility_adjusted"))
            if not obey:
                ua = u_fall  # 不服从调剂 → 退档，等同滑档
            elif ua is None:
                ua = u if p_adj == 0 else 0.0
            rows.append({
                "id": (r.get("id") or "").strip() or name,
                "name": name,
                "u": u,
                "ua": ua,
                "p_adj": p_adj,
                "obey": obey,
                "mu": mu,
                "sigma": sigma,
                "expected_cut": math.exp(mu),
                "n_years": len(pts),
                "unstable": unstable,
                "note": (r.get("note") or "").strip(),
                "raw": r,
            })
    return rows, skipped


def simulate(rows, rank, rank_sd, rho, n, seed, sigma_mult=1.0):
    """为每个志愿生成一个 n 位的位掩码：第 s 位 = 1 表示第 s 次模拟中过线。"""
    rng = random.Random(seed)
    a = math.sqrt(rho)
    b = math.sqrt(1 - rho)
    admit = [0] * len(rows)
    adjust = [0] * len(rows)
    log_rank = math.log(rank)
    for s in range(n):
        z0 = rng.gauss(0, 1)
        lr = log_rank + (rank_sd * rng.gauss(0, 1) if rank_sd > 0 else 0.0)
        bit = 1 << s
        for j, row in enumerate(rows):
            log_cut = row["mu"] + sigma_mult * row["sigma"] * (a * z0 + b * rng.gauss(0, 1))
            if lr <= log_cut:
                admit[j] |= bit
            if row["p_adj"] > 0 and rng.random() < row["p_adj"]:
                adjust[j] |= bit
    return admit, adjust


class Evaluator:
    def __init__(self, rows, admit, adjust, n, u_fall, max_fall, penalty):
        self.rows, self.admit, self.adjust = rows, admit, adjust
        self.n, self.full = n, (1 << n) - 1
        self.u_fall, self.max_fall, self.penalty = u_fall, max_fall, penalty

    def order(self, sel):
        return sorted(sel, key=lambda j: (-self.rows[j]["u"], j))

    def evaluate(self, sel, detail=False):
        rem, total, land = self.full, 0.0, {}
        for j in self.order(sel):
            hit = rem & self.admit[j]
            if hit:
                adj = hit & self.adjust[j]
                k_adj = popcount(adj)
                k = popcount(hit)
                total += self.rows[j]["u"] * (k - k_adj) + self.rows[j]["ua"] * k_adj
                if detail:
                    land[j] = (k - k_adj, k_adj)
                rem &= ~self.admit[j]
            elif detail:
                land[j] = (0, 0)
        k_fall = popcount(rem)
        total += self.u_fall * k_fall
        eu, p_fall = total / self.n, k_fall / self.n
        obj = eu
        if self.max_fall is not None and p_fall > self.max_fall:
            obj -= self.penalty * (p_fall - self.max_fall)
        if detail:
            return eu, p_fall, obj, land
        return eu, p_fall, obj


def greedy(ev, m, slots, max_evals):
    sel, best = [], ev.evaluate([])[2]
    for _ in range(slots):
        cand, cand_obj = None, best
        for j in range(m):
            if j in sel:
                continue
            obj = ev.evaluate(sel + [j])[2]
            if obj > cand_obj + 1e-12:
                cand, cand_obj = j, obj
        if cand is None:
            break
        sel.append(cand)
        best = cand_obj
    # 有限的单点替换：贪心在相关情形下不保证最优，用替换再挤一挤
    evals, improved = 0, True
    while improved and evals < max_evals:
        improved = False
        for i in list(sel):
            for j in range(m):
                if j in sel or evals >= max_evals:
                    continue
                trial = [x for x in sel if x != i] + [j]
                obj = ev.evaluate(trial)[2]
                evals += 1
                if obj > best + 1e-9:
                    sel, best, improved = trial, obj, True
                    break
            if improved:
                break
    return ev.order(sel)


def fill_under_stress(ev, stress_ev, sel, m, slots):
    """基准已无增益时，用压力情景继续补位；补位不得降低基准目标值。"""
    sel = list(sel)
    base_obj = ev.evaluate(sel)[2]
    while len(sel) < slots:
        cur = stress_ev.evaluate(sel)[2]
        cand, cand_obj = None, cur
        for j in range(m):
            if j in sel:
                continue
            trial = sel + [j]
            obj = stress_ev.evaluate(trial)[2]
            if obj > cand_obj + 1e-12 and ev.evaluate(trial)[2] >= base_obj - 1e-9:
                cand, cand_obj = j, obj
        if cand is None:
            break
        sel.append(cand)
        base_obj = ev.evaluate(sel)[2]
    return ev.order(sel)


def label(p):
    if p < 0.4:
        return "冲"
    if p < 0.85:
        return "稳"
    return "保"


def main():
    ap = argparse.ArgumentParser(description="知衢 · 平行志愿期望效用优化")
    ap.add_argument("csv", help="候选志愿 CSV（UTF-8），列说明见 references/volunteer-game.md")
    ap.add_argument("--rank", type=float, required=True, help="考生今年全省位次（同科类/同首选科目）")
    ap.add_argument("--slots", type=int, required=True, help="本批次可填志愿数（以本省当年官方规则为准）")
    ap.add_argument("--u-fall", type=float, required=True, help="滑档/退档结局的效用，与 utility 同一刻度")
    ap.add_argument("--max-fall", type=float, default=None, help="滑档概率硬上限，如 0.01")
    ap.add_argument("--rho", type=float, default=0.3, help="各志愿录取线的共同波动相关系数，默认 0.3")
    ap.add_argument("--rank-sd", type=float, default=0.0, help="考生位次本身的不确定性（对数尺度），出分后为 0")
    ap.add_argument("--sigma-floor", type=float, default=0.10, help="位次对数波动的下限，默认 0.10（约 ±10%%）")
    ap.add_argument("--sigma-single", type=float, default=0.25, help="只有一年数据时的波动，默认 0.25")
    ap.add_argument("--no-obey", action="store_true", help="默认所有志愿不服从调剂（可被 CSV 的 obey 列逐行覆盖）")
    ap.add_argument("--stress", type=float, default=2.0, help="补位用的压力情景波动倍数，默认 2；设 1 关闭补位")
    ap.add_argument("--sims", type=int, default=4000, help="模拟次数，默认 4000")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-swap-evals", type=int, default=20000)
    ap.add_argument("--json", help="另存完整结果为 JSON")
    args = ap.parse_args()

    if not 0 <= args.rho < 1:
        sys.exit("--rho 应在 [0, 1) 内")
    rows, skipped = load_candidates(args.csv, not args.no_obey, args.sigma_floor, args.sigma_single, args.u_fall)
    if not rows:
        sys.exit("没有可用的候选志愿")
    admit, adjust = simulate(rows, args.rank, args.rank_sd, args.rho, args.sims, args.seed)
    ev = Evaluator(rows, admit, adjust, args.sims, args.u_fall, args.max_fall, penalty=1e4)
    p_clear = [popcount(a) / args.sims for a in admit]

    best = greedy(ev, len(rows), args.slots, args.max_swap_evals)
    n_core = len(best)
    s_admit, s_adjust = simulate(rows, args.rank, args.rank_sd, args.rho, args.sims, args.seed + 1, args.stress)
    stress_ev = Evaluator(rows, s_admit, s_adjust, args.sims, args.u_fall, args.max_fall, penalty=1e4)
    if args.stress > 1 and len(best) < args.slots:
        best = fill_under_stress(ev, stress_ev, best, len(rows), args.slots)
    eu, p_fall, _, land = ev.evaluate(best, detail=True)
    s_eu, s_fall, _ = stress_ev.evaluate(best)

    by_u = sorted(range(len(rows)), key=lambda j: -rows[j]["u"])[: args.slots]
    by_p = sorted(range(len(rows)), key=lambda j: (-p_clear[j], -rows[j]["u"]))[: args.slots]
    base_u, base_p = ev.evaluate(by_u), ev.evaluate(by_p)
    sb_u, sb_p = stress_ev.evaluate(by_u), stress_ev.evaluate(by_p)

    out = []
    p = print
    p("# 知衢 · 志愿组合优化结果\n")
    p(f"- 考生位次 {args.rank:.0f}｜可填 {args.slots} 个｜候选 {len(rows)} 个｜模拟 {args.sims} 次｜rho={args.rho}")
    p(f"- 滑档效用 {args.u_fall}｜滑档上限 {args.max_fall if args.max_fall is not None else '未设'}")
    if skipped:
        p(f"- 跳过：{'、'.join(skipped)}")
    shaky = [r["name"] for r in rows if r["unstable"]]
    if shaky:
        p(f"- ⚠ 历年位次跳变超过约 40%，已自动放大波动，请查招生章程与专业组组成：{'、'.join(shaky)}")
    p("")
    p("## 推荐志愿表（已按效用从高到低排好，即填报顺序）\n")
    p("| 序 | 志愿 | 效用 | 单独过线概率 | 最终落在此处 | 其中被调剂 | 标签 | 预估最低位次 |")
    p("|---|---|---|---|---|---|---|---|")
    for k, j in enumerate(best, 1):
        r = rows[j]
        a, b = land.get(j, (0, 0))
        lp = (a + b) / args.sims
        p(f"| {k} | {r['name']} | {r['u']:g} | {p_clear[j]:.0%} | {lp:.1%} | {b / args.sims:.1%} | {label(p_clear[j])} | {r['expected_cut']:.0f} |")
        out.append({"order": k, "id": r["id"], "name": r["name"], "utility": r["u"],
                    "p_clear": p_clear[j], "p_land": lp, "p_adjusted": b / args.sims,
                    "tag": label(p_clear[j]), "expected_cut_rank": round(r["expected_cut"]),
                    "sigma": r["sigma"], "obey": r["obey"], "n_years": r["n_years"]})
    p("")
    p("## 汇总\n")
    p(f"- 期望效用 E[U] = **{eu:.1f}**；滑档（含退档）概率 = **{p_fall:.2%}**")
    p(f"- 压力情景（波动 ×{args.stress:g}）：E[U] = {s_eu:.1f}，滑档概率 = {s_fall:.2%}")
    if len(best) > n_core:
        p(f"- 前 {n_core} 个由基准模型选出；其余 {len(best) - n_core} 个是压力情景补位（基准下几乎用不到，用来防大波动）")
    if len(best) < args.slots:
        p(f"- 只填了 {len(best)}/{args.slots} 个：候选池里再加任何一个都没有增益，可以扩充候选池后重算")
    for cut in (90, 75, 60):  # 按主结局效用计，不含被调剂的部分
        prob = sum(land.get(j, (0, 0))[0] for j in best if rows[j]["u"] >= cut) / args.sims
        p(f"- 以原专业录取、且效用 ≥ {cut} 的概率：{prob:.0%}")
    p("")
    p("## 对照：两种常见直觉填法\n")
    p("| 填法 | 期望效用 | 滑档概率 | 压力情景滑档概率 |")
    p("|---|---|---|---|")
    p(f"| 本优化结果 | {eu:.1f} | {p_fall:.2%} | {s_fall:.2%} |")
    p(f"| 只挑效用最高的 {len(by_u)} 个（只冲不保） | {base_u[0]:.1f} | {base_u[1]:.2%} | {sb_u[1]:.2%} |")
    p(f"| 只挑最稳的 {len(by_p)} 个（只保不冲） | {base_p[0]:.1f} | {base_p[1]:.2%} | {sb_p[1]:.2%} |")
    left = [j for j in sorted(range(len(rows)), key=lambda j: -rows[j]["u"]) if j not in best][:5]
    if left:
        p("\n## 未入选但效用较高的候选（供人工复核）\n")
        for j in left:
            p(f"- {rows[j]['name']}：效用 {rows[j]['u']:g}，单独过线概率 {p_clear[j]:.0%}")
    p("\n> 概率来自历年位次的统计外推，不是官方录取率；招生计划、选科要求、章程限制变化时必须重算。")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"params": vars(args), "expected_utility": eu, "p_fall": p_fall,
                       "stress": {"expected_utility": s_eu, "p_fall": s_fall}, "n_core": n_core,
                       "list": out, "baseline_top_utility": base_u[:2],
                       "baseline_safest": base_p[:2], "skipped": skipped}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

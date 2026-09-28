# 案例 B：2027 年浙江，想学计算机（虚构考生）

完整演示一次从候选池到决策报告的流程。考生是虚构的，历年投档位次来自浙江省教育考试院官方数据（见 `data/zhejiang/`）。

| 文件 | 内容 |
|---|---|
| `candidates.csv` | 候选池：浙江 2022—2026 年计算机相关专业的历年位次与偏好分（打分依据在 `note` 列） |
| `result.json` | `optimize.py` 的输出 |
| `report.json` | 报告内容 |
| `report.pdf` | 生成的决策报告 |

重现：

```bash
python3 scripts/optimize.py examples/case_b_zhejiang_2027/candidates.csv --rank 28000 --slots 80 \
  --u-fall -60 --max-fall 0.01 --drift 0.015 --target-year 2027 --sigma-floor 0.15 \
  --json examples/case_b_zhejiang_2027/result.json
python3 scripts/report.py examples/case_b_zhejiang_2027/report.json \
  --opt examples/case_b_zhejiang_2027/result.json --out examples/case_b_zhejiang_2027/report.pdf
```

`--drift 0.015` 与 `--sigma-floor 0.15` 来自浙江回测：近三年全省位次平均每年放松约 1.5%；2027 年选考要求改版，参照 2024 年改版时的实测波动放大下限。

敏感性表最后一行是前景悲观情景：把名称含"人工智能""数据科学""智能科学""大数据"的候选效用各减 25 分（下限 0），用同样的参数重跑 `optimize.py` 得到重排后的 75.9；"仍按原表填报"的 70.3 是用原表每一格的落点概率乘以下调后的效用算出的。

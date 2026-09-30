# 排盘接口与输出契约

## 输入 JSON

调用 `scripts/calculate_bazi.py`。日期时间必须是出生地当地钟表时间，不附带 UTC 偏移。

```json
{
  "birth_datetime_local": "1988-02-15T23:30:00",
  "timezone": "Asia/Shanghai",
  "longitude": 121.4737,
  "time_basis": "compare",
  "day_boundary": "both",
  "late_zi_hour_stem": "both",
  "traditional_gender_parameter": "both",
  "fold": null,
  "uncertainty_minutes": 15,
  "luck_start_sect": 2,
  "dayun_count": 8,
  "include_liunian": true
}
```

字段约束：

- `timezone`：IANA 名称；历史夏令时由系统时区数据库处理。
- `longitude`：东经为正；仅在平太阳时、真太阳时或比较模式下必填。
- `time_basis`：`civil`、`mean_solar`、`apparent_solar` 或 `compare`。
- `day_boundary`：`zi_initial`、`midnight` 或 `both`。
- `late_zi_hour_stem`：晚子时选择 `follow_day`、`next_day` 或 `both`。默认让时干随所选日干重算。
- `traditional_gender_parameter`：`male`、`female` 或 `both`。它只服务传统顺逆规则，不等同身份判断。
- `fold`：夏令时回拨重复时段可指定 `0` 或 `1`；省略则两者都算。
- `uncertainty_minutes`：以报告时刻为中心的正负误差，最大七天。
- `luck_start_sect`：`1` 为日／时辰折算，`2` 为精确分钟折算；必须在解读中声明。

## 调用

```bash
python3 scripts/calculate_bazi.py input.json > chart.json
python3 scripts/calculate_bazi.py input.json --format markdown
```

从标准输入调用：

```bash
python3 scripts/calculate_bazi.py - < input.json
```

## 输出边界

输出包含引擎版本、原始输入、警告、候选盘、校正时间、四柱、藏干、十神、纳音、十二长生、传统旺相休囚死、可检测的干支关系、前后节、大运与流年。

程序只陈述可机械计算的结构，不自动判定：

- 身强身弱；
- 格局成败；
- 调候用神；
- 从格、化气是否成立；
- 吉凶事件或职业、关系、健康结论。

这些判断必须按 `analysis-protocol.md` 分轨推导，并引用 `schools.md` 中固定的成立与失败条件。

## 候选盘含义

每个候选由时间口径、夏令时 fold、换日规则、晚子时干规则及用户误差范围共同生成。`sampled_effective_time_ranges_by_basis` 表示各时间口径在扫描区间中得到该结构的有效时间范围，不是新的出生事实；若多个口径得到同一结构，见 `compatible_conventions`，不要把它们重复解读为多个命盘。

若候选很多：

1. 先列共同结构；
2. 再列只有哪些柱或起运时刻发生变化；
3. 只分析足以翻转结论的差异；
4. 不用性格套话事后选择最像的一盘。

## 实现边界

- 历法核心固定为 vendored `lunar-python 1.4.8`，提交 `000c8a3d74eed098d6256a28fdd51b869324c559`，许可证见 `scripts/vendor/LUNAR_PYTHON_LICENSE.txt`。
- 真太阳时均时差使用 NOAA 近似式，用于流派口径敏感性分析；若出生时刻距离边界近到算法误差可能改变柱，必须再用独立天文历表核验。
- 当前干支关系检测只报告组合存在，不宣称合化、冲去、刑伤等结果已经成立。

# 证据裁决与预测验证协议

## 目录

1. [三种不同的正确](#三种不同的正确)
2. [规则状态](#规则状态)
3. [从规则到可检验预测](#从规则到可检验预测)
4. [JSONL 数据契约](#jsonl-数据契约)
5. [冻结与揭盲](#冻结与揭盲)
6. [裁决与计分](#裁决与计分)
7. [模型比较](#模型比较)
8. [最低报告标准](#最低报告标准)

## 三种不同的正确

始终分开回答三类问题：

1. **文献事实**：某句话是否见于可定位的版本、正文还是注本。它只证明“有人这样主张过”。
2. **体系内效度**：结论是否由一套预先固定、前后一致的规则推出。它不证明现实预测有效。
3. **经验效度**：事前预测在未参与规则整理的案例中是否优于明确基线，并且保持校准、特异性与可复现性。

不得用其中一类代替另一类。把原文、原注、后注、现代解释和当前综合判断分栏记录。

## 规则状态

每条规则只使用下列状态之一；状态是当前证据标签，不是永久真值：

| 状态 | 最低条件 | 禁止外推 |
|---|---|---|
| `text_attested` 文献可证 | 可定位到具体版本、卷章页及文本层次 | 不代表作者归属无疑，也不代表有效 |
| `internally_coherent` 体系内成立 | 定义、输入、推导、适用和失败条件均固定；无内部矛盾 | 不代表跨流派共识或现实有效 |
| `cross_text_consensus` 跨文本共识 | 至少两个相互独立的文本传统在同义且同条件下支持 | 不以晚出抄袭文本重复计数 |
| `provisionally_supported` 经验上暂有支持 | 预注册留出集上优于基线；报告样本量、Brier、校准与失败 | 不称“已证实” |
| `unresolved` 未决 | 证据不足或竞争解释暂不可区分 | 不强选唯一结论 |
| `counterexample_present` 存在反例 | 至少一例满足适用条件却违背预期，且资料足以裁决 | 不因单一反例自动否定概率规则 |
| `currently_rejected` 已被当前测试否定 | 预先写明的失败阈值被触发，或稳定不优于基线 | 不称逻辑上永远不可能 |

规则卡必须包含：`rule_id`、版本、定义、输入字段、适用条件、排除条件、推导步骤、可区分的现实预测、失败阈值、来源层级、当前状态、状态日期。不得在看见结果后改用神、改格局或补口诀；修改后必须升版本，并在新留出集上重新开始。

## 从规则到可检验预测

一条可评分预测必须在结果未知时写清：

- 唯一 `prediction_id` 与匿名 `case_id`；验证库不得含姓名、出生信息或可回溯身份的备注。
- 使用的 `rule_id`/版本、流派或模型标识。
- 一个事先定义的事件类别、方向、起止时间窗、概率和触发条件。
- 资料截止时间 `information_cutoff`，以及当时允许使用的输入摘要哈希。
- 特异性三个分量：时间、类别、方向，均为 `[0,1]`，冻结后不得修改。
- 复杂度分量：规则数、附加条件数、例外数、自由参数数。

将互斥结果拆成彼此独立、可判真的命题，但不得把同一判断拆成大量近义命题来放大命中数。同一案例的相关预测在报告中按 `case_id` 聚类；不能把它们当作完全独立样本。

### 特异性锚点

- `temporal`：`0` 无时间窗；`0.25` 十年以上；`0.5` 三至十年；`0.75` 一至三年；`1` 一年以内。
- `categorical`：`0` 泛指“有变化”；`0.5` 领域级；`0.75` 预定义事件族；`1` 单一可核验事件。
- `directional`：`0` 无方向或两面下注；`0.5` 有宽泛方向；`1` 有排他的方向或二元结果。

总体特异性是三者算术平均。锚点只能在冻结前选择；跨项目修改锚点必须新建 `protocol_id`。

## JSONL 数据契约

每行是独立 JSON 对象，UTF-8，无注释。冻结脚本会校验必填字段并以键排序、紧凑 JSON 重新序列化。

### 预测记录 `bazi-prediction-v1`

```json
{"schema_version":"bazi-prediction-v1","prediction_id":"P-DEMO-001","protocol_id":"PROTO-DEMO-1","case_id":"CASE-SYNTH-001","created_at":"2026-01-01T00:00:00Z","information_cutoff":"2026-01-01T00:00:00Z","model_id":"model-a@1","rule_ids":["rule-a@1"],"event_category":"career_change","direction":"present","window":{"start":"2026-01-01","end":"2026-12-31"},"probability":0.7,"conditions":["predefined condition"],"specificity":{"temporal":1.0,"categorical":1.0,"directional":1.0},"complexity":{"rule_count":1,"condition_count":1,"exception_count":0,"free_parameter_count":0},"input_digest":"sha256:0000000000000000000000000000000000000000000000000000000000000000"}
```

`direction` 是项目预定义的字符串；脚本不替领域裁决含义。`probability` 表示该命题为真的主观概率，而非“语气强度”。日期采用 ISO 8601；窗口结束不得早于开始。

### 结果记录 `bazi-outcome-v1`

```json
{"schema_version":"bazi-outcome-v1","prediction_id":"P-DEMO-001","adjudication":"hit","observed":1,"adjudicated_at":"2027-01-15T00:00:00Z","evidence_refs":["PUBLIC-SYNTHETIC-RECORD-001"],"rationale":"预定义事件在窗口内发生。","adjudicator":"demo-reviewer","protocol_deviation":false}
```

`adjudication` 只能是 `hit`、`fail`、`ambiguous`、`unjudgeable`：

- `hit` 必须有 `observed: 1`；`fail` 必须有 `observed: 0`。
- `ambiguous` 表示证据允许相反裁决，省略 `observed`。
- `unjudgeable` 表示资料缺失、定义在现实中无法操作化或时间窗未结束，省略 `observed`。

任何协议偏离均设 `protocol_deviation: true` 并解释，主分析排除、敏感性分析另报。

## 冻结与揭盲

使用脚本完成不可含糊的操作：

```bash
python scripts/evaluate_predictions.py freeze draft.jsonl --output frozen.jsonl
python scripts/evaluate_predictions.py verify frozen.jsonl
python scripts/evaluate_predictions.py score frozen.jsonl outcomes.jsonl --output report.json
```

`freeze` 创建规范化只读文件及 `frozen.jsonl.manifest.json`，记录 SHA-256、记录数、冻结时间和协议集合；拒绝覆盖已有文件。将冻结文件和清单提交到有历史记录的存储。`verify` 同时核对哈希、字节数、记录数与协议集合。

结果资料必须在冻结之后才揭盲。若修正预测，保留旧冻结件，创建新 `prediction_id` 或新协议版本，不能原地覆盖。哈希只能证明文件自冻结后未改变，不能证明当时没有看到结果；需结合可信时间戳或版本历史。

## 裁决与计分

先按冻结定义裁决，再看模型名称。边界案例最好由不知道模型输出的两名裁决者独立判断；不一致记为 `ambiguous`，除非协议预先指定第三方仲裁。

脚本输出：

- `hit/fail/ambiguous/unjudgeable` 数量及占比；协议偏离单列。
- **严格准确率**：`hit / (hit + fail)`；模糊与不可判不进入分母，防止伪装成半命中。
- **覆盖率**：`(hit + fail) / 全部已配对预测`。准确率必须和覆盖率并报。
- **Brier 分数**：只对无协议偏离的 `hit/fail` 计算 `mean((p-observed)^2)`，越低越好。
- **校准表与 ECE**：默认十个概率区间；每箱报告数量、平均预测概率和实际命中率。样本很小时只作描述。
- **特异性**：报告全部冻结预测及可判预测的平均值；不能用低特异性换取高命中而不披露。
- **复杂度点数**：每条预测 `rule + 0.5*condition + 2*exception + free_parameter`，报告均值；不把它武断合成“总分”。

没有配对结果、存在重复 ID、哈希失败或结果语义不合法时，脚本失败而非猜测。

## 模型比较

只在相同案例、相同信息截止点、相同事件本体与裁决协议上比较。至少并列：

1. 八字模型；
2. 类别基础率或恒定概率基线；
3. 若可行，除去八字输入的非命理基线。

以案例为重采样或推断单位，避免把同一人的大量预测当作大量独立证据。优先比较 Brier、校准与预注册主要指标；准确率只有在决策阈值预先固定时才具有清楚含义。样本不足时报告区间和原始计数，不下“优于”结论。

规则若依赖大量例外、自由参数或事后条件，即使命中率相同也应降级。复杂度是透明度与过拟合风险记录，不是经过科学验证的统一惩罚公式。

## 最低报告标准

每次验证至少公开：协议版本、冻结清单哈希、纳入与排除流程、样本与案例数、类别基础率、全部四类裁决、覆盖率、Brier、校准表、特异性、复杂度、协议偏离、失败案例、规则修改历史和未解决限制。

不得只展示命中案例，不得把 `ambiguous` 算半命中后隐藏，不得以叙事贴合替代冻结命题。达到 `provisionally_supported` 也只说明“在该协议与样本下暂有支持”；第一版不得宣称八字已获科学证实。

# 一键流程演示（完全虚构）

本目录用合成数据演示 `pool → predict → optimize → report`，不是实际志愿方案。三份 `admissions_年份.csv` 由上一级 `candidates_demo.csv` 拆分；`preferences.csv` 保留原演示效用与调剂偏好，`id` 改为 pool 的“院校代码-专业名”键。空历史保持为空，演示学校不会匹配教育部名单。

在技能目录运行：

```bash
python3 scripts/pipeline.py examples/pipeline_demo/config.json --out-dir /tmp/zhiqu-pipeline-demo
python3 scripts/check_report.py examples/pipeline_demo/report.json --opt /tmp/zhiqu-pipeline-demo/result.json --html /tmp/zhiqu-pipeline-demo/report.html
```

输出目录须为空；生成物不写回本目录。报告保留固定 12 节，省略部分明确说明原因。该目录只保存可重现输入，不保存重复 PDF/HTML 或中间结果。正式使用前须替换为已核实的官方数据、考生确认的偏好与报告内容。完整参数和核验覆盖范围见 [报告指南](../../references/report-guide.md)。

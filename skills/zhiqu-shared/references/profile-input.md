# 画像输入与本机存档

<!-- 核实：2026-10-19；复核期限：2027-10-19 -->

问卷交付一个 JSON 对象，前后无说明文字。`zhiqu` 为 `gaokao` / `grad` / `career`，`schema` 为 1；`问卷` 记录名称，`form` 是含题干、选项与字段类型的题目指纹，`filled_at` 是带时区的填写时间。`sections` 按节列出 `{title, items}`；每题有稳定英文 `id`、题目原文 `q` 和作答 `a`。单选与填空为字符串，多选为数组，多格题为以每格小标题作键的对象。追问带 `followup_of` 并排在所属题之后。只输出可见且已作答的题；空选填不输出，漏答必答仅记在 `未填的必答题`。`rank` 保留排序；`derived.bazi` 只在提供出生信息时出现，不进入现实资格或计分。

直接按稳定 id 生成 `profile_parse.json` 的已知字段，保留原始 JSON 作答与定位。拒答和不清楚保留为未知；缺少批次、排名口径等关键条件时另列缺项，不从别题推定。已有报告迁移时，旧 `fields` 与计算引用保持原值，直接读取 JSON 的映射放 `questionnaire_fields`；两者连同补充原话由操控者逐项核对。新案例的自动解析直接写 `fields`，不从补充猜测缺项。原始作答、解析和结论有区别：解析完成还要分清事实、偏好、约束与本人判断，核对相互矛盾之处。多格题不把费用范围取中点，不把成绩字符串猜成名次。

本机命令（仓库根目录运行）：

```bash
python3 skills/zhiqu/scripts/profile_store.py new-id grad 2027 --mode formal
python3 skills/zhiqu/scripts/profile_store.py ingest 2027-YJ-0001 pasted.json
python3 skills/zhiqu/scripts/profile_store.py latest 2027-YJ-0001
python3 skills/zhiqu/scripts/profile_store.py diff 2027-YJ-0001
python3 skills/zhiqu/scripts/case_check.py cases/2027-YJ-0001 --stage 1 --parse-profile
python3 skills/zhiqu/scripts/profile_store.py report 2027-YJ-0001 cases/2027-YJ-0001/report.pdf
```

案例号由 `new-id` 在带锁的本机总登记表 `cases.json`（位于本机 cases 目录） 中分配，不重复使用。登记表保存类型、真实/模拟模式、建立时间、各版画像与报告的时间和指纹。画像原样保留在 `cases/<编号>/profiles/<filled_at>.json`，同一时间已有不同内容则拒绝覆盖。`case.json.profile` 记录当前采用文件与题目指纹；最新填写时间优先，不按文件修改时间选。工具默认只写本机忽略目录，文件权限仅限当前用户；不上传这些案例或登记表。报告指纹用 `report` 登记，不改变报告内容。

`diff` 按 id 列出新增、修改、删除及排序变化；题目指纹不同时提示“题目版本不同，部分题可能对不上”。收到新画像后重新生成解析并核对后续判断，不能继续交付旧快照。已有解析时须明确使用 `--replace-profile`（或 `profile_store.py parse --replace`）才替换，不自动改旧分析和计算。

旧文字画像仍可用：原文存 `.txt`；若末尾有旧版作答数据行，另存转换后的 JSON；纯文字不臆造结构化作答，标“无数据，需人工解析”，仍按文字与节名解析。模拟人物的 JSON 是画像，口语自述另存为“问卷之外的补充”；补充中的线索仍要区分本人事实和判断。

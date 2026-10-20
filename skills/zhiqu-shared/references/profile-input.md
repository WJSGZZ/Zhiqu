# 画像输入与本机存档

<!-- 核实：2026-10-19；复核期限：2027-10-19 -->

问卷主按钮在配置的所属网址上交付以 `ZQ1:` 开头的一行加密文本；按钮下的“复制未加密版本”始终交付 JSON。其他网址或本地副本默认明文，并说明尚未配置接收人公钥。剪贴板不可用时，备用文本框显示与本次复制完全相同的内容，提示“长按全选复制”。公钥、接收人显示名与所属网址集中配置在 `assets/profile-recipient.js`，私钥不随网页分发。

明文是一个 JSON 对象，前后无说明文字。`zhiqu` 为 `gaokao` / `grad` / `career`，`schema` 为 1；`问卷` 记录名称，`form` 是含题干、选项与字段类型的题目指纹，`filled_at` 是带时区的填写时间。`sections` 按节列出 `{title, items}`；所有可见题均保留稳定英文 `id`、题目原文 `q` 和 `status`（“已答”或“未填”）。已答题有 `a`，未填题不写 `a`；必答题加 `required: true`，不另列漏答清单。单选与填空为字符串，多选为数组，多格题为以每格小标题作键的对象。追问带 `followup_of` 并排在所属题之后。收起题只把 id 列在 `collapsed`；`counts.visible` 为可见条目数，`counts.answered` 为已答条目数。`rank` 保留排序；`derived.bazi` 只在提供出生信息时出现，不进入现实资格或计分。

`checksum` 是规范化内容（排除 `checksum` 自身）的 SHA-256。接收时核对校验值、条目数量和每题状态；加密串还须成功解密、解压，任一失败均停止并提示“画像可能被改动或不完整，请让对方重新复制”。不要手工修改复制结果。旧版没有 `checksum` 的 JSON 仍可接收，标为“无校验”；这与新版校验通过不同。校验用于发现内容变动，不替代操控者对事实、偏好与矛盾的核查。

加密前先压缩 JSON，再用随机 AES-GCM 密钥加密内容；网页公钥通过 RSA-OAEP 加密这把随机密钥。仅 `profile_store.py` 的钥匙生成和解密功能导入 `cryptography`，其他本机脚本仍用标准库。

直接按稳定 id 生成 `profile_parse.json` 的已知字段，保留原始 JSON 作答与定位。拒答和不清楚保留为未知；缺少批次、排名口径等关键条件时另列缺项，不从别题推定。已有报告迁移时，旧 `fields` 与计算引用保持原值，直接读取 JSON 的映射放 `questionnaire_fields`；两者连同补充原话由操控者逐项核对。新案例的自动解析直接写 `fields`，不从补充猜测缺项。原始作答、解析和结论有区别：解析完成还要分清事实、偏好、约束与本人判断，核对相互矛盾之处。多格题不把费用范围取中点，不把成绩字符串猜成名次。

本机命令（仓库根目录运行）：

```bash
python3 skills/zhiqu/scripts/profile_store.py new-id grad 2027 --mode formal
python3 skills/zhiqu/scripts/profile_store.py ingest 2027-YJ-0001 pasted.json
# 收到加密文本时，用仓库外的私钥解密后存明文
python3 skills/zhiqu/scripts/profile_store.py ingest 2027-YJ-0001 received.txt --private-key /绝对路径/仓库外/recipient-private.pem
python3 skills/zhiqu/scripts/profile_store.py latest 2027-YJ-0001
python3 skills/zhiqu/scripts/profile_store.py diff 2027-YJ-0001
python3 skills/zhiqu/scripts/case_check.py cases/2027-YJ-0001 --stage 1 --parse-profile
python3 skills/zhiqu/scripts/profile_store.py report 2027-YJ-0001 cases/2027-YJ-0001/2027-YJ-0001-report.pdf
```

案例号由 `new-id` 在带锁的本机总登记表 `cases.json`（位于本机 cases 目录） 中分配，不重复使用。登记表保存类型、真实/模拟模式、建立时间、各版画像与报告的时间和指纹。明文 JSON 原样保留；加密输入解密后以明文 JSON 保留在 `cases/<编号>/profiles/<安全时间戳>.json`，文件名使用 `2026-10-19T22-37-22+0800.json` 这类无冒号格式（保留小数秒），兼容 Windows；旧的含冒号文件名仍能读取。同一时间已有不同内容则拒绝覆盖。`case.json.profile` 记录当前采用文件与题目指纹；最新填写时间优先，不按文件修改时间选。工具默认只写本机忽略目录，文件权限仅限当前用户；不上传这些案例或登记表。报告指纹用 `report` 登记，不改变报告内容。

`diff` 按 id 列出新增、修改、删除及排序变化；题目指纹不同时提示“题目版本不同，部分题可能对不上”。收到新画像后重新生成解析并核对后续判断，不能继续交付旧快照。已有解析时须明确使用 `--replace-profile`（或 `profile_store.py parse --replace`）才替换，不自动改旧分析和计算。

旧文字画像仍可用：原文存 `.txt`；若末尾有旧版作答数据行，另存转换后的 JSON；纯文字不臆造结构化作答，标“无数据，需人工解析”，仍按文字与节名解析。模拟人物的 JSON 是画像，口语自述另存为“问卷之外的补充”；补充中的线索仍要区分本人事实和判断。

## 接收人钥匙

在仓库外选择私钥路径，生成公钥配置：

```bash
python3 -m pip install cryptography
python3 skills/zhiqu/scripts/profile_store.py keygen \
  --private-key /绝对路径/仓库外/recipient-private.pem \
  --public-config assets/profile-recipient.js \
  --recipient-name "知衢顾问" --hostname wjsgzz.github.io
```

发布的是公钥配置，私钥只在接收端使用。`ingest --private-key` 或环境变量 `ZHIQU_PRIVATE_KEY` 指向私钥路径；没有安装解密依赖时，工具会提示安装。私钥要备份到自己控制的加密存储，不提交、不随画像发送。丢失只影响尚未解密的消息；已存的明文档案不受影响。换公钥后仍要保留旧私钥，以接收尚未处理的旧消息。

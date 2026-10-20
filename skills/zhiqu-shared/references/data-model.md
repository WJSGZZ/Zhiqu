# 数据模型：高考与考研共用

高考、考研的数据本质相同：某校某专业某年，招多少人、线是多少、录取分数怎么分布、数从哪来、核对过没有。两边按同一套规则存放，报告程序只读“可直接使用”的视图。求职数据（岗位表、工资价位）以后按同样的来源与核对规则接入。

## 一、两层存放

| 层 | 放什么 | 格式 | 是否进 Git |
|---|---|---|---|
| 公开层 | 自己从官网取的官方数据 | 整洁 CSV（一行一条记录），每个目录配 `sources.csv` | 进 |
| 本机库 | 公开层的全部数据 + 购买或第三方整理的数据 + 核对结果 | 每个领域一个 SQLite：`skills/zhiqu/data/purchased/purchased.sqlite`（高考）、`skills/zhiqu-grad/data/purchased/kaoyan.sqlite`（考研） | 不进（`.git/info/exclude`） |

本机库由可重跑的 `ingest.py` 从公开层和原件生成，不手改；每次入库前留快照到 `snapshots/`。公开示例报告只能用公开层数据，真实客户报告可以用本机库。

## 二、共同约定

- **列名**用英文 snake_case，值可以是中文；年份为整数，日期 ISO（YYYY-MM-DD），分数为数值，原文写法另存 `*_raw`。
- **学校身份**：以教育部《全国普通高等学校名单》的 10 位标识码为主键 `institution_id`（见 `skills/zhiqu/data/schools.csv` 的 `id`）；各种校名写法、曾用名、各省招生代码、研招单位代码都进别名表，不在业务表里用校名做连接。对不上的列入问题表，不猜。
- **专业身份**：本科用《普通高等学校本科专业目录》代码，研究生用《研究生教育学科专业目录》代码（门类 2 位、一级学科／专业学位类别 4 位、专业 6 位），各自一张字典表。
- **来源**：每条数据都带 `source_id` 和原始 `src_row`；PDF/图片另带 `src_page`、`src_table`。字段与原件保留规则见下文「来源与原件」，不以整理CSV的行号冒称原件页行。
- **核对**：与官方原文抽查的结果统一记在 `check_sample`，结论只用四种：一致、不一致、口径不同、未取到。
- **可直接使用的视图** `v_usable_*`：官方数据优先；第三方与官方不一致时用官方值并注明；没核对过的标“第三方整理，未核”。报告和模型只读这些视图。

## 三、共用的表

| 表 | 主键／要点 | 说明 |
|---|---|---|
| `meta`、`ingest` | 入库批次、脚本 sha256、时间 | 可追溯每批数据由哪个版本的脚本生成 |
| `source` | `source_id` | 见上 |
| `institution`、`institution_alias` | `institution_id`；别名含 `kind`（校名／曾用名／省招生代码／研招单位代码）、适用省份与年份 | 两个领域共用同一份学校身份 |
| `discipline` | `level`（本科／研究生）＋`code` | 专业字典 |
| `check_sample` | 表名、行键、字段、库内值、官方值、官方 `source_id`、结论、核对日期 | 抽查记录 |
| `ingest_issue` | 文件、行、问题类型、列、原值 | 解析不了或对不上的行 |

## 四、各领域的业务表

两边的“一年一行”和“分数分布”同形，只多出各自特有的列。

| 概念 | 高考 | 考研 |
|---|---|---|
| 招生单位 | `plan_entry`：省份、年份、科类、批次、学校、专业组、专业、计划数、学费、选科 | `program_year`：学校、学院、专业代码、年份、学位类型、全日制与否、招生人数、推免人数、考试科目 |
| 线 | `result`：最低分、最低位次、平均、最高、录取数 | `program_year.line_total` 及单科线；`national_line` |
| 分布 | 一分一段表 `yfyd`（分数→累计人数） | `score_dist`：名单类型（复试／拟录取）、一志愿或调剂、专项排除数、n、min、q1、median、q3、max |
| 官方表 | `official_cutoff`、`official_yfyd` | `official_line`、`official_dist` |

分位数统一用含端点线性插值；排除了哪些专项、是否含调剂，必须在行里写明。

## 五、查询

每个库配一个 `query.py`：输入学校（任何写法）和专业，列出历年招生、线和分布，并标明每个数的等级与来源。报告程序不直接读原始表。

## 六、现状与迁移

- 考研库按本规范新建。
- 高考库已按本规范迁移：公开层各省目录配 `sources.csv`，每行带 `source_id`（`validate_data.py` 检查）；本机库新增 `source`、`institution`、`institution_alias`、`discipline`（本科专业目录，[undergrad_majors.csv](../../zhiqu/data/undergrad_majors.csv)），官方表 `official_cutoff`、`official_yfyd` 带 `source_id` 和 `institution_id`，`check_sample` 结论统一为四种。原有表名、视图名不变，原有列只增不删。
- 高考本机库重建：`python3 skills/zhiqu/data/purchased/ingest.py rebuild`（先快照，再按公开层与原件重算官方层、共用表与核对表，最后自检）；查询用同目录 `query.py`。
- 学校身份按校名、曾用名对上教育部名单；对不上的（军队、港澳院校，学校下属医学院，名单外的旧校名、简称和识别错字）记入 `ingest_issue`，不按招生代码猜。补全曾用名在 [school-name-changes.csv](../../zhiqu/data/school-name-changes.csv)。

## 七、来源与原件

`source` 与公开层 `sources.csv` 使用同一顺序的14列：`source_id`、`grade`、`publisher`、`title`、`landing_url`（公告页）、`file_url`（原件附件直链，无则空）、`published`、`retrieved`、`method`、`archive_sha256`、`archive_path`、`archive_status`、`wayback_url`（可空）、`note`。等级仍只用官方／第三方整理，发布单位与等级分开。旧url按实际类型迁移，旧文件名、SHA及其他元数据在本机 `source_legacy` 原样保留；此表是迁移凭据，不是原件。官方来源至少有公告页或附件网址；栏目、首页只作为入口，不证明数字已取得。

`archive_status` 仅用「已存原件」「原链接失效·存档副本」「未取到」。指纹必须对实际保存的完整字节计算，不能用整理表、摘要、收据或网页标题冒充原件。未取到可以保留历史指纹，但路径为空；已存状态必须有可读文件且SHA一致。DNS、限额、302预算不足与验证码都不能证明原链接已失效。采用官方其他入口或Wayback时，note保留旧网址→发现入口→存档网址、正文适用年份及核对情况，wayback_url只记实际取得的存档，不猜。

公开官方原件且不超过5,000,000字节的，保存到 `skills/zhiqu-shared/originals/<sha前2位>/<sha>.<扩展名>`，进Git，逐字节原样保存，不重新打包。index.csv记录sha256、size、media_type、source_url、retrieved、source_id；同一字节可关联多个来源，(sha256,source_id)不重复。该目录sources.csv是两库已存公开官方原件的可分发来源目录，解决未安装本机库时的离线索引校验；重复source_id须与公开层声明兼容。单个原件可直接容纳未来从既有ZIP释放的成员，必须先核字节指纹、官方身份与隐私，不以ZIP自身指纹代替成员。超过上限的官方原件、所有购买原件，只存本机 purchased/originals/同样指纹路径，不进Git。含考生身份信息的名单不进入公开原件库。

业务 `src_row` 原样保留，`src_page` 是原件物理页（从1起），`src_table` 为工作表名/表名/图表标识，`locator_method` 包括「读图」；无法定位页表就留空并用 `locator_status` 记缺口。整理CSV行只辅助检索，不能伪造为原件行。多原件汇编或分位数来源应注明原文件成员、工作表及统计范围；原件已删的历史数据仍显示缺口。query每个数字分别输出值、等级、发布单位、公告页、附件直链、指纹、原件路径、页／表／行；官方替换只能追溯该字段实际匹配的官方行，非唯一时列候选，不把其他字段一并升级。

抽查在check_sample逐项记录实际库值、原文值、source_id、页表行及一致／不一致／口径不同／未取到，不修改业务数字。下载成功不等于数字一致，扫描件需实际读图或核实OCR；没有可靠原文时不能仅因出现相同数字就判一致。check_links.py按需经本机爬虫限额体检，各URL结果写link_check：source_id、checked、http_status、final_url、body_matches_archive，另记具体URL、状态与原因；无两端指纹时一致性为空，不用HTTP200替代正文核验，不自动定时运行。

每次入库先快照，写独立候选库，核对全部原业务字段/行数与原库一致、外键与完整性检查通过后fsync并原子替换。两库的datapackage.json采用Frictionless Data Package格式，记录schema/列说明/单位/实际主外键/来源列表/数据库SHA及版本；已知业务连接但未定义SQL外键的另作说明，不伪造约束。README数据字典从该文件生成，CHANGELOG按实际入库SHA记录批次，同库指纹重跑不重复写日志。公开CSV校验同时检查14列与原件索引，默认离线运行。

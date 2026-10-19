"""check_family.py 的自动测试（只用标准库）。

运行：在 skills/zhiqu 目录下执行
  python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # skills/zhiqu
SCRIPTS = os.path.join(ROOT, "scripts")
REPO_ROOT = os.path.dirname(os.path.dirname(ROOT))  # 仓库根目录

sys.path.insert(0, SCRIPTS)

import check_family as cf  # noqa: E402


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def make_min_repo(tmp):
    """搭一个最小的仓库骨架：三个技能 + 两个 html + README。"""
    write(os.path.join(tmp, "README.md"), "# README\n")
    write(os.path.join(tmp, "grad.html"),
          "<div data-title=\"优先级排序\"></div>\n"
          "<script>STORE_KEY='zhiqu_grad_v1'</script>\n")
    write(os.path.join(tmp, "career.html"),
          "<div data-title=\"优先级排序\"></div>\n"
          "<script>STORE_KEY='zhiqu_career_v1'</script>\n")
    write(os.path.join(tmp, "gaokao.html"),
          "<script>STORE_KEY='zhiqu_gaokao_v1'</script>\n")
    write(os.path.join(tmp, "skills/zhiqu/SKILL.md"), "# zhiqu\n")
    write(os.path.join(tmp, "skills/zhiqu-grad/SKILL.md"), "# zhiqu-grad\n")
    write(os.path.join(tmp, "skills/zhiqu-career/SKILL.md"), "# zhiqu-career\n")


class TestCheckLinks(unittest.TestCase):
    def test_pass_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"), "见 `b.md`\n")
            write(os.path.join(tmp, "skills/zhiqu/references/b.md"), "内容\n")
            issues = cf.check_links(tmp)
            self.assertEqual(issues, [])

    def test_fail_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"),
                  "见 [说明](references/not-exist.md)\n")
            issues = cf.check_links(tmp)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0][0], cf.ERROR)
            self.assertIn("not-exist.md", issues[0][3])

    def test_skip_placeholder_and_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"),
                  "参考 [在线版](https://example.com/x.md) 和 `<占位>.md` 与 `examples/xxx....md`\n")
            issues = cf.check_links(tmp)
            self.assertEqual(issues, [])


class TestCheckSectionNames(unittest.TestCase):
    def test_pass_known_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu-grad/SKILL.md"),
                  "回到「优先级排序」一节看\n")
            issues = cf.check_section_names(tmp)
            self.assertEqual(issues, [])

    def test_fail_unknown_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu-grad/SKILL.md"),
                  "回到「不存在的节」一节看\n")
            issues = cf.check_section_names(tmp)
            self.assertTrue(any(i[0] == cf.ERROR for i in issues))

    def test_fail_numeric_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu-career/SKILL.md"),
                  "回到第九节的优先级排序\n")
            issues = cf.check_section_names(tmp)
            self.assertTrue(any(i[0] == cf.ERROR and "第九节" in i[3] for i in issues))

    def test_numeric_reference_exempt_with_own_file_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu-grad/SKILL.md"),
                  "见本文件第五节\n")
            issues = cf.check_section_names(tmp)
            self.assertEqual(issues, [])

    def test_shared_file_warns_when_title_only_in_one_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            # grad.html 额外加一个只属于 grad 的节名
            write(os.path.join(tmp, "grad.html"),
                  "<div data-title=\"优先级排序\"></div>\n"
                  "<div data-title=\"专业方向\"></div>\n"
                  "<script>STORE_KEY='zhiqu_grad_v1'</script>\n")
            write(os.path.join(tmp, "skills/zhiqu-grad/references/direction-and-state.md"),
                  "回到「专业方向」一节\n")
            issues = cf.check_section_names(tmp)
            self.assertTrue(any(i[0] == cf.WARN for i in issues))
            self.assertFalse(any(i[0] == cf.ERROR for i in issues))


class TestCheckReportGuide(unittest.TestCase):
    def _table(self, nums):
        lines = ["| 节 | 内容 |", "|---|---|"]
        for n in nums:
            lines.append(f"| {n} xx | yy |")
        return "\n".join(lines) + "\n"

    def test_pass_complete_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            nums = [f"{i:02d}" for i in range(1, 13)]
            write(os.path.join(tmp, "skills/zhiqu-grad/references/report-guide.md"),
                  self._table(nums))
            write(os.path.join(tmp, "skills/zhiqu-career/references/report-guide.md"),
                  self._table(nums))
            issues = cf.check_report_guide(tmp)
            self.assertEqual(issues, [])

    def test_fail_missing_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            nums = [f"{i:02d}" for i in range(1, 13) if i != 7]
            write(os.path.join(tmp, "skills/zhiqu-grad/references/report-guide.md"),
                  self._table(nums))
            write(os.path.join(tmp, "skills/zhiqu-career/references/report-guide.md"),
                  self._table([f"{i:02d}" for i in range(1, 13)]))
            issues = cf.check_report_guide(tmp)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0][0], cf.ERROR)
            self.assertIn("zhiqu-grad", issues[0][1])


class TestCheckPortrait(unittest.TestCase):
    def _json_repo(self, tmp):
        """新问卷只复制 JSON，不再靠旧文字标题识别。"""
        make_min_repo(tmp)
        for kind in ("grad", "career", "gaokao"):
            write(os.path.join(tmp, kind + ".html"),
                  "<script>STORE_KEY='zhiqu_" + kind + "_v1';"
                  "zhiquCopy(zhiquProfile('" + kind + "'));</script>\n")
        write(os.path.join(tmp, "assets/questionnaire.js"),
              "function zhiquProfile(kind){return {zhiqu:kind,schema:1};}\n")
        write(os.path.join(tmp, "README.md"),
              '问卷复制 JSON，以 "zhiqu" 字段识别高考、读研或求职。\n')

    def test_pass_json_profiles_with_shared_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._json_repo(tmp)
            self.assertEqual(cf.check_portrait_consistency(tmp), [])

    def test_fail_json_profile_wrong_type(self):
        for kind, wrong_kind in (("grad", "career"), ("career", "gaokao"),
                                 ("gaokao", "grad")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                self._json_repo(tmp)
                write(os.path.join(tmp, kind + ".html"),
                      "<script>STORE_KEY='zhiqu_" + kind + "_v1';"
                      "zhiquCopy(zhiquProfile('" + wrong_kind + "'));</script>\n")
                issues = cf.check_portrait_consistency(tmp)
                self.assertTrue(any(i[0] == cf.ERROR and i[1] == kind + ".html"
                                    and "未接入 JSON 画像" in i[3] for i in issues))

    def test_fail_json_profile_missing_shared_generator(self):
        for serializer in (None, "function anotherProfile(){return {schema:1};}",
                           "function zhiquProfile(kind){return {schema:2};}"):
            with self.subTest(serializer=serializer), tempfile.TemporaryDirectory() as tmp:
                self._json_repo(tmp)
                shared = os.path.join(tmp, "assets/questionnaire.js")
                if serializer is None:
                    os.remove(shared)
                else:
                    write(shared, serializer)
                issues = cf.check_portrait_consistency(tmp)
                self.assertEqual({i[1] for i in issues if i[0] == cf.ERROR
                                  and "缺共用 schema=1 JSON 画像生成器" in i[3]},
                                 {"gaokao.html", "grad.html", "career.html"})

    def test_fail_json_profile_readme_still_uses_old_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._json_repo(tmp)
            write(os.path.join(tmp, "README.md"),
                  "画像以【读研 · 自我盘点】【求职 · 自我盘点】"
                  "【高考志愿 · 自我盘点】开头。\n")
            issues = cf.check_portrait_consistency(tmp)
            self.assertTrue(any(i[0] == cf.ERROR and i[1] == "README.md"
                                and "须同步 JSON 画像格式" in i[3] for i in issues))

    def test_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "grad.html"),
                  "<title>【读研 · 自我盘点】</title>\n"
                  "<script>STORE_KEY='zhiqu_grad_v1'</script>\n")
            write(os.path.join(tmp, "career.html"),
                  "<title>【求职 · 自我盘点】</title>\n"
                  "<script>STORE_KEY='zhiqu_career_v1'</script>\n")
            write(os.path.join(tmp, "gaokao.html"),
                  "<title>【高考志愿 · 自我盘点】</title>\n"
                  "<script>STORE_KEY='zhiqu_gaokao_v1'</script>\n")
            write(os.path.join(tmp, "README.md"),
                  "【读研 · 自我盘点】【求职 · 自我盘点】【高考志愿 · 自我盘点】\n")
            issues = cf.check_portrait_consistency(tmp)
            self.assertEqual(issues, [])

    def test_fail_duplicate_store_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "grad.html"),
                  "<title>【读研 · 自我盘点】</title>\n"
                  "<script>STORE_KEY='same_key'</script>\n")
            write(os.path.join(tmp, "career.html"),
                  "<title>【求职 · 自我盘点】</title>\n"
                  "<script>STORE_KEY='same_key'</script>\n")
            write(os.path.join(tmp, "gaokao.html"),
                  "<title>【高考志愿 · 自我盘点】</title>\n"
                  "<script>STORE_KEY='zhiqu_gaokao_v1'</script>\n")
            write(os.path.join(tmp, "README.md"),
                  "【读研 · 自我盘点】【求职 · 自我盘点】【高考志愿 · 自我盘点】\n")
            issues = cf.check_portrait_consistency(tmp)
            self.assertTrue(any("STORE_KEY" in i[3] for i in issues))


class TestCheckReviewDeadline(unittest.TestCase):
    def test_pass_far_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"),
                  "一些事实\n<!-- 核实：2026-01-01；复核期限：2099-01-01 -->\n")
            issues = cf.check_review_deadline(tmp, date(2026, 9, 30))
            self.assertEqual(issues, [])

    def test_fail_expired_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"),
                  "一些事实\n<!-- 核实：2020-01-01；复核期限：2020-06-01 -->\n")
            issues = cf.check_review_deadline(tmp, date(2026, 9, 30))
            self.assertTrue(any(i[0] == cf.ERROR for i in issues))

    def test_warn_expiring_fact_without_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"),
                  "2025 年的规定是这样，尚无复核标记\n")
            issues = cf.check_review_deadline(tmp, date(2026, 9, 30))
            self.assertTrue(any(i[0] == cf.WARN for i in issues))


class TestCheckDuplicateParagraphs(unittest.TestCase):
    def test_pass_unique_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"), "短句子\n")
            write(os.path.join(tmp, "skills/zhiqu/references/b.md"), "另一句完全不同的短句子\n")
            issues = cf.check_duplicate_paragraphs(tmp)
            self.assertEqual(issues, [])

    def test_fail_duplicate_across_files(self):
        long_line = "这是一段足够长的重复内容用来测试跨文件重复检测的功能是否正常工作没有问题这句话还要再长一点点\n"
        self.assertGreaterEqual(cf.count_cjk(long_line), 40)
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"), long_line)
            write(os.path.join(tmp, "skills/zhiqu/references/b.md"), long_line)
            issues = cf.check_duplicate_paragraphs(tmp)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0][0], cf.WARN)


class TestCheckFileSize(unittest.TestCase):
    def test_pass_small_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/a.md"), "小文件\n")
            issues = cf.check_file_size(tmp)
            self.assertEqual(issues, [])

    def test_fail_large_skill_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/SKILL.md"), "x" * 20001)
            issues = cf.check_file_size(tmp)
            self.assertTrue(any(i[0] == cf.WARN and "SKILL.md" in i[1] for i in issues))

    def test_fail_large_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_min_repo(tmp)
            write(os.path.join(tmp, "skills/zhiqu/references/big.md"), "x" * 30001)
            issues = cf.check_file_size(tmp)
            self.assertTrue(any(i[0] == cf.WARN and "big.md" in i[1] for i in issues))


class TestRealRepo(unittest.TestCase):
    def test_no_hard_errors_on_real_repo(self):
        """真实仓库：引用文件存在、报告目录完整、画像输入一致 三项检查不应有错误。
        问卷节名引用、复核期限 这两项目前允许有错误/提醒（文档待作者本人修订）。"""
        result = cf.run_all(REPO_ROOT, date(2026, 9, 30))
        for name in ("引用的文件存在", "报告目录完整", "画像输入一致"):
            errors = [i for i in result[name] if i[0] == cf.ERROR]
            self.assertEqual(errors, [], f"{name} 不应有错误，实际：{errors}")



class TestPersonaNames(unittest.TestCase):
    def record(self,tmp,cid,name,**extra):
        import json
        write(os.path.join(tmp,'skills/zhiqu/examples',cid,'case.json'),
              json.dumps({'case_id':cid,'candidate':name+'（模拟）',**extra},ensure_ascii=False))

    def test_distinct_short_names_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.record(tmp,'A','小明');self.record(tmp,'B','小红')
            self.assertEqual(cf.check_persona_names(tmp),[])

    def test_duplicate_or_long_names_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.record(tmp,'A','小明');self.record(tmp,'B','小明');self.record(tmp,'C','小明明')
            issues=cf.check_persona_names(tmp)
            self.assertTrue(any('不同人物重名' in x[3] for x in issues))
            self.assertTrue(any('一个汉字' in x[3] for x in issues))

    def test_same_person_scenarios_need_explicit_valid_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.record(tmp,'A','小明');self.record(tmp,'B','小明',persona_ref='../A/case.json')
            self.assertEqual(cf.check_persona_names(tmp),[])
            self.record(tmp,'B','小红',persona_ref='../A/case.json')
            self.assertTrue(any('场景姓名不一致' in x[3] for x in cf.check_persona_names(tmp)))


if __name__ == "__main__":
    unittest.main()

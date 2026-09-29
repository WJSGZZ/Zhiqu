"""统计省考职位表中，每个本科专业能报考的职位数和录用人数。

适用于按"专业名称(代码)"列出要求的职位表（如广东省考：本科专业代码 B+6 位，专业类 B+4 位，门类 B+2 位）。
某专业可报 = 职位学历含本科，且本科专业要求列出了该专业、其所属专业类或门类。"不限专业"的职位单独统计，不计入各专业。
usage: python3 scripts/civil_service.py 职位表.xls 专业参考目录.xls 输出.csv
"""
import csv, re, sys
import xlrd


def positions(path):
    out = []
    for sh in xlrd.open_workbook(path).sheets():
        hi = next(i for i in range(6) if "招考单位" in sh.row_values(i))
        H = [str(c).replace("\n", "") for c in sh.row_values(hi)]
        col = lambda k: next(i for i, c in enumerate(H) if c.startswith(k))
        for i in range(hi + 1, sh.nrows):
            r = sh.row_values(i)
            try:
                n = int(float(r[col("录用人数")]))
            except ValueError:
                continue
            out.append((str(r[col("学历")]), str(r[col("本科专业")]).strip(), n))
    return out


def majors(path):
    sh = xlrd.open_workbook(path).sheet_by_index(1)
    cls, maj, last = {}, {}, ""
    for i in range(4, sh.nrows):
        r = sh.row_values(i)
        if str(r[7]).startswith("B"):
            last = str(r[7]).strip()
            cls[last] = str(r[8]).strip()
        if str(r[9]).startswith("B"):
            maj[str(r[9]).strip()] = (str(r[10]).strip(), last)
    return cls, maj


def main():
    pos_path, cat_path, out = sys.argv[1:4]
    ug = [(set(re.findall(r"B\d+", req)), n, req) for edu, req, n in positions(pos_path) if "本科" in edu]
    open_n = sum(n for _, n, req in ug if req in ("", "不限"))
    total = sum(n for _, n, _ in ug)
    cls, maj = majors(cat_path)
    rows = []
    for code, (name, cc) in maj.items():
        hit = [n for s, n, req in ug if code in s or code[:5] in s or code[:3] in s]
        rows.append((name, code, cls.get(cc, cc), sum(hit), len(hit), f"{sum(hit) / total:.1%}"))
    rows.sort(key=lambda x: -x[3])
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["专业", "代码", "专业类代码或名称", "可报录用人数", "可报职位数", "占本科可报总人数"])
        w.writerows(rows)
    print(f"本科可报职位录用 {total} 人，其中不限专业 {open_n} 人（{open_n / total:.1%}）；已写出 {out}")


if __name__ == "__main__":
    main()

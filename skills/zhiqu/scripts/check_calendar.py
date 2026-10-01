#!/usr/bin/env python3
"""Compare installed lunar-javascript with the vendored Python engine and web helper.

Developer check: --js-library /path/to/lunar-javascript --node node.
No runtime dependency is added to the skills. Requires the public JS library.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
CASES = ['2004-11-02T14:20:00', '2004-11-02T22:59:00', '2004-11-02T23:00:00',
         '2004-11-02T23:59:00', '2004-11-03T00:00:00',
         '2026-02-04T04:02:07', '2026-02-04T04:02:08', '2026-02-04T04:02:09']
JS = r'''
const fs=require('fs'),vm=require('vm'),lunar=require(process.argv[1]);
const ctx=vm.createContext({...lunar,Date});
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
const result=cases.flatMap(time=>[0,1].map(gender=>{
 const n=time.split(/\D/).map(Number),ec=ctx.baziEightChar(...n);
 const yun=ctx.baziYun(ec,gender);
 return {pillars:[ec.getYear(),ec.getMonth(),ec.getDay(),ec.getTime()].join(' '),
         start:yun.getStartSolar().toYmdHms(),forward:yun.isForward()};
}));
if(!ctx.computeBaziBlock('2026-02-04','03:52','浙江省','女').lines.join('\n').includes('节气临界'))throw Error('term boundary not warned');
if(!ctx.computeBaziBlock('2004-11-02','','广东省','女').lines.join('\n').includes('年柱'))throw Error('date-only failed');
delete ctx.Solar;
if(!ctx.computeBaziBlock('2004-11-02','14:20','','女').lines.join('\n').includes('未加载'))throw Error('offline fallback failed');
console.log(JSON.stringify(result));
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--node', default='node'); ap.add_argument('--js-library', required=True)
    args = ap.parse_args()
    actual = json.loads(subprocess.check_output([args.node, '-e', JS, str(Path(args.js_library).resolve()),
                                               str(ROOT / 'assets/questionnaire.js')], input=json.dumps(CASES), text=True))
    for (when, gender), js in zip(((when, gender) for when in CASES for gender in ('female', 'male')), actual):
        data = dict(birth_datetime_local=when, timezone='Asia/Shanghai', time_basis='civil',
                    day_boundary='midnight', late_zi_hour_stem='next_day', traditional_gender_parameter=gender,
                    uncertainty_minutes=0, luck_start_sect=2, dayun_count=1, include_liunian=False)
        py = json.loads(subprocess.check_output([sys.executable, str(ROOT / 'skills/bazi/scripts/calculate_bazi.py'), '-'],
                                               input=json.dumps(data), text=True))['candidates'][0]
        luck = py['luck'][0]
        assert js == dict(pillars=py['pillars_text'], start=luck['start_datetime_beijing_clock'],
                          forward=luck['direction']=='forward'), (when, js, py['pillars_text'])
    print(f'{len(CASES)*2} calendar cases: pillars, exact luck start and direction agree; term, date-only and offline checks passed')


if __name__ == '__main__': main()

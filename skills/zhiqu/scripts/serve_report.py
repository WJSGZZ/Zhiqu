#!/usr/bin/env python3
"""显式启动仅绑定 127.0.0.1 的交互重算报告；调用现有 optimize.py，不另写概率模型。"""
import argparse
import copy
import csv
from datetime import date
import html
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading

from check_report import check_report
import report

SCRIPTS = Path(__file__).resolve().parent
DEFAULTS = {'rank':None, 'slots':None, 'u_fall':None, 'max_fall':None, 'rho':0.3,
            'rank_sd':0.0, 'sigma_floor':0.10, 'sigma_single':0.25, 'sigma_scale':1.0,
            'sigma_rule':'v2', 'no_obey':False, 'stress':2.0, 'drift':0.0,
            'target_year':None, 'cohort':[], 'cohort_now':None, 'sims':4000,
            'seed':42, 'max_swap_evals':20000}
EDITABLE = {'rank','slots','u_fall','rho','sigma_scale','max_fall'}
LIMITS = {'rank':(1,10000000), 'slots':(1,1000), 'u_fall':(-10000,10000),
          'max_fall':(0,1), 'rho':(0,0.999), 'sigma_scale':(0.01,10)}
MAX_REQUEST = 32768


def validate_changes(changes):
    if not isinstance(changes, dict) or set(changes) - EDITABLE:
        raise ValueError('仅可调整位次、志愿数、滑档效用、相关系数、波动倍数与滑档上限')
    for key, value in changes.items():
        if key == 'max_fall' and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
            raise ValueError(key + ' 须为有限数字')
        lo, hi = LIMITS[key]
        if not lo <= value <= hi or (key == 'slots' and int(value) != value):
            raise ValueError(f'{key} 须在 [{lo:g}, {hi:g}] 范围' + ('且为整数' if key == 'slots' else ''))
    return changes


def load_candidates(path, maximum):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        fields, rows = reader.fieldnames, list(reader)
    if not fields or not rows or len(rows) > maximum:
        raise ValueError(f'候选表必须非空，且不超过 {maximum} 行')
    if any(not key for key in fields) or len(set(fields)) != len(fields) or any(None in row for row in rows):
        raise ValueError('候选 CSV 有空/重复表头或超出表头的字段')
    if not any(key.startswith('rank_') for key in fields):
        raise ValueError('候选表缺少 rank_年份 历史位次')
    seen=set()
    for row in rows:
        identifier=(row.get('id') or row.get('name') or '').strip()
        if not identifier or identifier in seen:
            raise ValueError('候选 id/name 为空或重复，先核对候选表')
        seen.add(identifier)
        try:
            history=[float(row[k]) for k in fields if k.startswith('rank_') and row.get(k)]
            utility=float(row['utility']) if row.get('utility') else None
        except (ValueError,TypeError):
            raise ValueError(identifier+' 的历史位次或效用格式无效')
        if not any(math.isfinite(x) and x>0 for x in history) or (not row.get('majors') and (utility is None or not math.isfinite(utility))):
            raise ValueError(identifier+' 缺少有效历史位次或已确认效用')
        if row.get('majors') and row.get('majors_complete') not in ('0','1'):
            raise ValueError('含 majors 的候选必须显式填写 majors_complete=0/1，不能默认视为完整目录')
    return fields, rows


def calculation_report(original, result, candidate_count):
    """重算只呈现当前计算及固定输入来源，不沿用可能失效的旧预测正文。"""
    meta = copy.deepcopy(original.get('meta', {}))
    meta.update(title='志愿交互重算报告', subtitle='按当前参数实际运行现有优化模型；模拟结果不是官方录取率',
                rank=result['params']['rank'], slots=result['params']['slots'])
    meta['score'] = '本次未换算分数'
    meta['date'] = date.today().isoformat()
    if float(meta['rank']).is_integer():
        meta['rank'] = int(meta['rank'])
    params = result['params']
    return {'meta':meta, 'summary':{'headline':'本次建议来自你勾选的候选及当前参数。数值已与本次优化结果核对。',
            'points':[f'本次输入 {candidate_count} 个已确认的候选，模型给出 {len(result["list"])} 个志愿。',
                      '原报告的摘要、排序理由和敏感性文字没有自动沿用，请结合本次结果重新审核。'],
            'actions':['实际填报前再次核实资格、选科、章程、代码与完整专业目录。']},
            'profile':{'intro':'本次只重算已确认候选和效用，不重新判断你的兴趣或修改专业评分。'},
            'stress_mult':params['stress'],
            'assumptions':[[key,str(value),'本次运行参数'] for key,value in params.items() if key in DEFAULTS],
            'sources':copy.deepcopy(original.get('sources', [])),
            'omitted':{key:'本次只生成交互重算的数值报告；原报告的该节内容需要另行核对，未自动沿用。'
                       for key in ('directions','research','todo','ask_me','hindsight')}}


class ReportApplication:
    def __init__(self, candidates, original, defaults, timeout=90, maximum=1000):
        if not isinstance(original,dict) or not isinstance(defaults,dict):
            raise ValueError('原报告和默认参数必须为 JSON 对象')
        self.fields, self.rows = load_candidates(candidates, maximum)
        self.candidate_name = Path(candidates).name
        self.candidate_digest = hashlib.sha256(json.dumps({'fields':self.fields,'rows':self.rows},sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
        self.original = original
        self.defaults = copy.deepcopy(DEFAULTS)
        self.defaults.update({k:v for k,v in defaults.items() if k in DEFAULTS})
        validate_changes({k:self.defaults[k] for k in EDITABLE})
        if not isinstance(self.defaults['sims'], int) or not 100 <= self.defaults['sims'] <= 20000:
            raise ValueError('固定模拟次数须为 100–20000 的整数')
        if self.defaults['sigma_rule'] not in ('v2','legacy'):
            raise ValueError('固定波动规则须为 v2 或 legacy')
        self.timeout = timeout
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    def recompute(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'selected','params'}:
            raise ValueError('请求必须且只能含 selected 和 params；不接受文件路径或命令')
        selected = payload['selected']
        if not isinstance(selected, list) or not selected or len(selected) > len(self.rows):
            raise ValueError('至少选择一个已载入候选')
        if any(isinstance(i,bool) or not isinstance(i,int) or not 0 <= i < len(self.rows) for i in selected) or len(set(selected)) != len(selected):
            raise ValueError('候选索引无效或重复')
        params = dict(self.defaults, **validate_changes(payload['params']))
        params['slots'] = int(params['slots'])
        selected_rows = [self.rows[i] for i in sorted(selected)]
        with tempfile.TemporaryDirectory(prefix='zhiqu-interactive-') as tmp:
            tmpdir = Path(tmp)
            csv_path, result_path = tmpdir/'candidates.csv', tmpdir/'result.json'
            with csv_path.open('w',encoding='utf-8',newline='') as fh:
                writer=csv.DictWriter(fh,fieldnames=self.fields);writer.writeheader();writer.writerows(selected_rows)
            command=[sys.executable,str(SCRIPTS/'optimize.py'),str(csv_path)]
            for key,value in params.items():
                flag='--'+key.replace('_','-')
                if value is True:
                    command.append(flag)
                elif value is not False and value is not None:
                    for item in value if isinstance(value,list) else [value]:
                        command.extend([flag,str(item)])
            command.extend(['--json',str(result_path)])
            completed=subprocess.run(command,capture_output=True,text=True,timeout=self.timeout,check=False)
            if completed.returncode:
                raise ValueError('现有优化脚本拒绝输入：' + completed.stderr.strip()[:1200])
            result=json.loads(result_path.read_text(encoding='utf-8'))
            rep=calculation_report(self.original,result,len(selected_rows))
            document=report.build(rep,result)
            errors=check_report(rep,result,document)
            if errors:
                raise ValueError('本次报告数字核验失败：'+'；'.join(errors))
            # 临时文件在返回前删除；下载 JSON 使用会话标识，不能当文件入口。
            result['params']['csv']='selected-candidates.csv'
            result['params']['json']='result.json'
            result['interactive_input']={'candidate_file':self.candidate_name,'selected_indices':sorted(selected),'parsed_table_sha256':self.candidate_digest}
            return {'result':result,'report':rep,'report_html':document}

    def page(self):
        controls=''.join(f'<label>{label}<input name="{key}" type="number" step="{step}" min="{LIMITS[key][0]}" max="{LIMITS[key][1]}" value="{html.escape(str(self.defaults[key] if self.defaults[key] is not None else ""),quote=True)}"></label>'
                         for key,label,step in [('rank','考生位次','any'),('slots','可填志愿数','1'),('u_fall','滑档结局的效用','any'),('rho','录取线共同波动程度','any'),('sigma_scale','录取线波动倍数','any'),('max_fall','滑档概率上限（空白表示不设）','any')])
        choices=''.join(f'<label class="candidate"><input type="checkbox" value="{i}" checked><span>{html.escape(row.get("name") or row.get("id") or str(i+1))}</span><small>偏好 {html.escape(row.get("utility") or "按组内专业计算")}</small></label>' for i,row in enumerate(self.rows))
        page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知衢 · 交互重算</title>
<style>body{margin:0;background:#fbf8ed;color:#20251f;font:15px system-ui,sans-serif}header{padding:22px 28px;border-bottom:1px solid #d7d1bb}h1{margin:0 0 10px;font-size:25px}p{line-height:1.6}main{display:grid;grid-template-columns:minmax(280px,390px) 1fr;gap:22px;padding:22px}section{background:#fffdf6;border:1px solid #d7d1bb;border-radius:8px;padding:18px}label{display:block;margin:12px 0}input[type=number],input[type=search]{display:block;box-sizing:border-box;width:100%;padding:8px;margin-top:6px;border:1px solid #999;border-radius:4px}button,a.download{display:inline-block;padding:9px 14px;background:#2f4937;color:white;border:0;border-radius:5px;text-decoration:none;cursor:pointer;margin:4px 4px 4px 0}button:disabled{opacity:.55}.choices{max-height:420px;overflow:auto}.candidate{display:flex;align-items:flex-start;gap:8px;border-top:1px solid #e1ddce;padding:9px 0;margin:0}.candidate small{margin-left:auto;color:#62695e;font-size:12px;max-width:100px}.candidate[hidden]{display:none}.candidate input{flex:none;margin-top:4px}#status{min-height:2em;white-space:pre-wrap}iframe{width:100%;height:80vh;border:1px solid #d7d1bb;background:#fff}small{color:#62695e}@media(max-width:850px){main{display:block;padding:12px}section{margin-bottom:16px}}</style>
<header><h1>知衢 · 交互重算</h1><p>选择愿意就读的候选，调整参数后按“重算”。后台运行现有优化模型，报告显示本次模拟结果。原报告文字不会随参数自动变成有效结论。</p><small>仅在本机运行 · 输入文件在启动时固定 · 资格与效用须事先核实 · 不保证录取</small></header>
<main><section><h2>当前参数</h2><form id="parameters">__CONTROLS__</form><small>波动倍数使用现有 --sigma-scale；固定漂移、模拟次数及其余参数保留启动值。手填 sigma 的条目不受此倍数影响。</small><h2>候选选择</h2><input id="search" type="search" placeholder="按名称筛选显示"><p><button id="all" type="button">全选全部候选</button><button id="none" type="button">取消全部</button><span id="count"></span></p><div class="choices">__CHOICES__</div><p><button id="compute" type="button">按当前选择重算</button></p></section>
<section><h2>本次报告</h2><p id="status" role="status">尚未重算。参数和候选不会自动上传到外部服务。</p><div id="downloads" hidden><a class="download" id="htmlDownload" download="zhiqu-recomputed-report.html">下载报告 HTML</a><a class="download" id="jsonDownload" download="zhiqu-recomputed-result.json">下载结果 JSON</a></div><iframe id="preview" title="本次重算报告" sandbox=""></iframe></section></main>
<script>
const token=__TOKEN__,form=document.getElementById('parameters'),checks=[...document.querySelectorAll('.candidate input')],status=document.getElementById('status'),compute=document.getElementById('compute');let ran=false,urls=[];
function changed(){document.getElementById('count').textContent=`已选 ${checks.filter(x=>x.checked).length}/${checks.length}`;if(ran){status.textContent='参数或选择已改动；下面仍是上次结果，请按重算更新。';document.getElementById('downloads').hidden=true;}}
checks.forEach(x=>x.addEventListener('change',changed));form.addEventListener('input',changed);document.getElementById('all').onclick=()=>{checks.forEach(x=>x.checked=true);changed();};document.getElementById('none').onclick=()=>{checks.forEach(x=>x.checked=false);changed();};
document.getElementById('search').oninput=e=>{const query=e.target.value.toLowerCase();checks.forEach(x=>x.parentElement.hidden=!x.parentElement.textContent.toLowerCase().includes(query));};
compute.onclick=async()=>{if(!form.reportValidity())return;const params={};for(const input of form.elements)params[input.name]=input.value===''?null:Number(input.value);const selected=checks.filter(x=>x.checked).map(x=>Number(x.value));compute.disabled=true;[...form.elements,...checks,document.getElementById('all'),document.getElementById('none')].forEach(x=>x.disabled=true);status.textContent='正在运行模型并核验数字……';document.getElementById('downloads').hidden=true;
try{const response=await fetch('/api/recompute',{method:'POST',headers:{'Content-Type':'application/json','X-Zhiqu-Token':token},body:JSON.stringify({selected,params})});const data=await response.json();if(!response.ok)throw Error(data.error);document.getElementById('preview').srcdoc=data.report_html;urls.forEach(URL.revokeObjectURL);urls=[URL.createObjectURL(new Blob([data.report_html],{type:'text/html;charset=utf-8'})),URL.createObjectURL(new Blob([JSON.stringify(data.result,null,2)],{type:'application/json;charset=utf-8'}))];document.getElementById('htmlDownload').href=urls[0];document.getElementById('jsonDownload').href=urls[1];document.getElementById('downloads').hidden=false;const result=data.result;status.textContent=`本次重算完成，数字核验通过。平均满意度 ${result.expected_utility.toFixed(1)}，滑档概率 ${result.p_fall===0?'小于 '+(100/result.params.sims).toPrecision(2)+'%':(100*result.p_fall).toFixed(2)+'%'}。以报告内的模拟精度提示为准。`;ran=true;}catch(error){status.textContent='重算未完成：'+error.message;}finally{compute.disabled=false;[...form.elements,...checks,document.getElementById('all'),document.getElementById('none')].forEach(x=>x.disabled=false);}};changed();
</script></html>'''
        return page.replace('__CONTROLS__',controls).replace('__CHOICES__',choices).replace('__TOKEN__',json.dumps(self.token))


def make_server(application, port=8765):
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def respond(self, status, data, content_type='application/json; charset=utf-8'):
            body=data.encode('utf-8') if isinstance(data,str) else json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.valid_host():
                self.respond(403,{'error':'只接受固定本机 Host'});return
            if self.path!='/':
                self.respond(404,{'error':'没有该资源；服务不提供本地文件读取'});return
            self.respond(200,application.page(),'text/html; charset=utf-8')

        def do_POST(self):
            if not self.valid_host():
                self.respond(403,{'error':'只接受固定本机 Host'});return
            origin=self.headers.get('Origin')
            if origin and origin!=f'http://127.0.0.1:{self.server.server_port}':
                self.respond(403,{'error':'拒绝外部 Origin'});return
            token=self.headers.get('X-Zhiqu-Token','')
            if not token.isascii() or not secrets.compare_digest(token,application.token):
                self.respond(403,{'error':'本机页面会话令牌缺失或错误'});return
            if self.path!='/api/recompute':
                self.respond(404,{'error':'没有该接口'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= MAX_REQUEST or self.headers.get('Transfer-Encoding'):
                    raise ValueError('请求体过大、为空或传输格式不支持')
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                    raise ValueError('仅接受 JSON 请求')
                self.connection.settimeout(5)
                payload=json.loads(self.rfile.read(length))
            except (ValueError,OSError) as exc:
                self.respond(400,{'error':str(exc)});return
            if not application.lock.acquire(blocking=False):
                self.respond(409,{'error':'已有重算在运行，请待其完成后再试'});return
            try:
                data=application.recompute(payload)
                self.respond(200,data)
            except ValueError as exc:
                self.respond(400,{'error':str(exc)})
            except subprocess.TimeoutExpired:
                self.respond(408,{'error':'优化超时，本次没有新结果；请减少候选或使用命令行核算'})
            finally:
                application.lock.release()

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=False
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidates',help='启动时固定的人工核实候选 CSV')
    parser.add_argument('--report',required=True,help='仅取原报告的身份信息与来源，重算文字另生成')
    parser.add_argument('--result',help='从已有 result.json 读取固定运行参数')
    for key in ('rank','slots','u-fall'):
        parser.add_argument('--'+key,type=int if key=='slots' else float,help='启动参数，可覆盖已有 result')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--timeout',type=int,default=90,help='每次实际优化的超时秒数，默认 90')
    parser.add_argument('--max-candidates',type=int,default=1000)
    args=parser.parse_args()
    try:
        if not 0 <= args.port <= 65535 or not 1 <= args.timeout <= 300 or not 1 <= args.max_candidates <= 2000:
            raise ValueError('端口、超时或候选上限不在支持范围')
        original=json.loads(Path(args.report).resolve().read_text(encoding='utf-8'))
        defaults=json.loads(Path(args.result).resolve().read_text(encoding='utf-8'))['params'] if args.result else {}
        for key in ('rank','slots','u_fall'):
            if getattr(args,key) is not None:defaults[key]=getattr(args,key)
        application=ReportApplication(Path(args.candidates).resolve(),original,defaults,args.timeout,args.max_candidates)
        server=make_server(application,args.port)
    except (ValueError,OSError,KeyError) as exc:
        parser.error(str(exc))
    print(f'交互报告仅在本机：http://127.0.0.1:{server.server_port}/\n在终端按 Ctrl+C 关闭。原文件不会修改；每次重算使用随后删除的临时文件。',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()

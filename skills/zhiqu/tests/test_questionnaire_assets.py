"""Shared questionnaire schema and serialization guards; no browser or network."""
from collections import Counter
from html.parser import HTMLParser
import json
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
PAGES = ('gaokao', 'grad', 'career')


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.assets = []
        self.questions = []
        self.labels = {}
        self.conditions = []
        self.stack = []
        self.inline_styles = []
        self.style_tags = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        target = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' else None
        if target and target.startswith('assets/'):
            self.assets.append(target)
        if 'style' in attrs:
            self.inline_styles.append(attrs['style'])
        if tag == 'style':
            self.style_tags += 1
        if tag == 'div':
            self.stack.append(attrs)
            if 'q' in attrs.get('class', '').split():
                self.questions.append(attrs)
            if 'q-label' in attrs.get('class', '').split():
                parent = next((item for item in reversed(self.stack[:-1]) if 'q' in item.get('class', '').split()), None)
                key = parent.get('data-profile-id') if parent else None
                if key is not None and key not in self.labels:
                    self.labels[key] = ''
                    attrs['_capture_label'] = key
        for key in ('data-show-when', 'data-hide-when', 'data-when'):
            if key in attrs:
                self.conditions.append(attrs[key])

    def handle_endtag(self, tag):
        if tag == 'div':
            self.stack.pop()

    def handle_data(self, data):
        label = next((item for item in reversed(self.stack) if '_capture_label' in item), None)
        if label:
            self.labels[label['_capture_label']] += data



# A deliberately small DOM implementation supports only selectors used by the
# shared serializer. It never evaluates page scripts, invokes a browser or fetches.
NODE_DOM = r'''
const fs = require('fs');
const vm = require('vm');
const {webcrypto}=require('crypto');
const {TextEncoder}=require('util');
class Element {
  constructor(tag, attrs={}, text='') {
    this.tagName=tag.toUpperCase(); this.attrs=attrs; this._text=text;
    this.children=[]; this.parentElement=null; this.previousElementSibling=null;
    this.id=attrs.id||''; this.name=attrs.name||''; this.type=attrs.type||'';
    this.value=attrs.value||''; this.checked=!!attrs.checked; this.hidden=!!attrs.hidden;
    this.classList={contains:(v)=>(attrs.class||'').split(' ').includes(v),add:()=>{},remove:()=>{}};
  }
  append(...elements){elements.forEach(e=>{e.previousElementSibling=this.children.at(-1)||null;e.parentElement=this;this.children.push(e);});return this;}
  get textContent(){return this._text+this.children.map(e=>e.textContent).join('');}
  set textContent(value){this._text=value;this.children=[];}
  scrollIntoView(){}
  get lastElementChild(){return this.children.at(-1)||null;}
  get offsetParent(){return this.hidden||this.parentElement&&this.parentElement.offsetParent===null?null:{};}
  getAttribute(key){return this.attrs[key]??null;}
  matches(selector){
    if(selector.startsWith('.'))return this.classList.contains(selector.slice(1));
    if(selector.startsWith('['))return Object.hasOwn(this.attrs,selector.slice(1,-1));
    const label=/^label\[for="([^"]+)"\]$/.exec(selector);
    if(label)return this.tagName==='LABEL'&&this.attrs.for===label[1];
    return this.tagName.toLowerCase()===selector;
  }
  closest(selectors){for(let e=this;e;e=e.parentElement){if(selectors.split(',').some(s=>e.matches(s)))return e;}return null;}
  querySelectorAll(selectors){const result=[];function walk(e){e.children.forEach(c=>{if(selectors.split(',').some(s=>c.matches(s)))result.push(c);walk(c);});}walk(this);return result;}
  querySelector(selectors){return this.querySelectorAll(selectors)[0]||null;}
}
const E=(tag,attrs,text)=>new Element(tag,attrs,text);
const root=E('main');
root.append(E('div',{id:'copyDone'}),E('div',{id:'output'}),E('textarea',{id:'summary'}));
let clipboardText='';
const section=E('section',{class:'section','data-title':'模拟基本信息'});root.append(section);
function question(id,label,controls=[],attrs={}){
  const q=E('div',{'class':'q','data-profile-id':id,...attrs});
  q.append(E('div',{class:'q-label'},label),...controls);return q;
}
const month=E('input',{id:'grad_time',type:'month','data-profile-label':'毕业年月'});
const monthQ=question('grad_time','毕业年月（必答）',[month],{class:'q req'});section.append(monthQ);
const hiddenInput=E('input',{id:'hidden_answer',type:'text',value:'不应导出的隐藏作答'});
section.append(question('hidden_question','已收起的题',[hiddenInput],{hidden:true,class:'q req'}));
const route=E('input',{name:'route',type:'checkbox',value:'考公',checked:true});
const routeQ=question('route','想走哪条路',[route]);section.append(routeQ);
const wrapper=E('div',{'data-show-when':'route=考公'});
const followQ=question('detail','计划在哪个省',[E('input',{id:'detail',type:'text',value:'江苏'})]);
wrapper.append(followQ);section.append(wrapper);
const rank=E('div',{class:'rank'});
const rankNumber=E('span',{class:'rank-num'},'–');
rank.append(E('button',{class:'rank-item','data-id':'收入'}).append(rankNumber,E('span',{},'收入')));
rank.append(E('button',{class:'rank-item','data-id':'城市'}).append(E('span',{class:'rank-num'},'–'),E('span',{},'城市')));
section.append(question('priority','按重要程度排序',[rank]));
const missingQ=question('missing','尚未填写的核心题',[E('input',{id:'missing',type:'text'})],{class:'q req'});section.append(missingQ);
const context={document:{querySelectorAll:s=>root.querySelectorAll(s),querySelector:s=>root.querySelector(s),getElementById:id=>root.querySelectorAll('input,textarea,select,div').find(e=>e.id===id)||null},navigator:{clipboard:{writeText:value=>{clipboardText=value;return process.argv[2]==='fallback'?Promise.reject(new Error('clipboard denied')):Promise.resolve();}}},rankOrder:[],isAnswered:q=>q.querySelectorAll('input,textarea,select').some(e=>e.type==='radio'||e.type==='checkbox'?e.checked:!!e.value.trim())};
Object.assign(context,{crypto:webcrypto,TextEncoder,Blob,Response,CompressionStream,location:{hostname:'localhost'},window:{ZHIQU_RECIPIENT:{name:'知衢顾问',hostname:'wjsgzz.github.io',spki:'unused-off-host'}}});
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
const initialHash=context.zhiquFormHash();
month.value='2027-06';
const answerHash=context.zhiquFormHash();
context.rankOrder=['城市','收入'];rankNumber.textContent='2';
const rankHash=context.zhiquFormHash();
monthQ.querySelector('.q-label').textContent='预计何时取得毕业证？';
const wordingHash=context.zhiquFormHash();
monthQ.querySelector('.q-label').textContent='毕业年月（必答）';
section.attrs['data-title']='修改后的节名';
const sectionHash=context.zhiquFormHash();section.attrs['data-title']='模拟基本信息';
const data=context.zhiquProfile('career');
await context.zhiquCopy(data);
console.log(JSON.stringify({initialHash,answerHash,rankHash,wordingHash,sectionHash,data,clipboardText,summaryText:context.document.getElementById('summary').value,notice:context.document.getElementById('copyDone').textContent,recipient:context.zhiquRecipient()}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''


# Conditional display: a minimal DOM where hidden attributes and the followup
# "show" class decide visibility, exactly as the stylesheet does.
CONDITIONS_DOM = r'''
const fs=require('fs'),vm=require('vm');
class El{
  constructor(tag,attrs={}){this.tagName=tag.toUpperCase();this.attrs=attrs;this.children=[];this.parentElement=null;
    this.id=attrs.id||'';this.name=attrs.name||'';this.type=attrs.type||'';this.value=attrs.value||'';this.checked=!!attrs.checked;this.hidden=false;
    const set=new Set((attrs.class||'').split(' ').filter(Boolean));
    this.classList={contains:v=>set.has(v),add:v=>set.add(v),remove:v=>set.delete(v)};}
  append(...k){k.forEach(e=>{e.parentElement=this;this.children.push(e);});return this;}
  hasAttribute(k){return Object.hasOwn(this.attrs,k);}
  getAttribute(k){return this.attrs[k]??null;}
  get offsetParent(){if(this.hidden||(this.classList.contains('followup')&&!this.classList.contains('show')))return null;return this.parentElement?this.parentElement.offsetParent:{};}
  matches(sel){const m=/^(\w+)?((?:\.[\w-]+)*)((?:\[[\w-]+\])*)$/.exec(sel.trim());if(!m)return false;
    if(m[1]&&this.tagName.toLowerCase()!==m[1])return false;
    if(m[2]&&!m[2].split('.').filter(Boolean).every(c=>this.classList.contains(c)))return false;
    return !m[3]||m[3].slice(1,-1).split('][').every(a=>this.hasAttribute(a));}
  querySelectorAll(sels){const out=[];const walk=e=>e.children.forEach(c=>{if(sels.split(',').some(s=>c.matches(s)))out.push(c);walk(c);});walk(this);return out;}
}
const E=(t,a)=>new El(t,a);
const root=E('main');
const a1=E('input',{type:'radio',name:'a',value:'1',checked:true}),a2=E('input',{type:'radio',name:'a',value:'2'});
// W is placed before the followup that holds its trigger: a single pass would wrongly clear it.
const w=E('div',{'data-show-when':'b=x'}),wText=E('input',{type:'text',id:'w',value:'保留'});w.append(wText);
const f=E('div',{class:'followup','data-when':'a=1'}),bx=E('input',{type:'radio',name:'b',value:'x',checked:true});f.append(bx,E('input',{type:'radio',name:'b',value:'y'}));
const g=E('div',{'data-show-when':'a=2'}),gText=E('input',{type:'month',id:'g',value:'2026-06'}),gRadio=E('input',{type:'radio',name:'c',value:'在考',checked:true});g.append(gText,gRadio);
const h=E('div',{'data-hide-when':'a=1'}),hArea=E('textarea',{id:'h',value:'过时'});h.append(hArea);
root.append(a1,a2,w,f,g,h);
const ctx={document:{querySelectorAll:s=>root.querySelectorAll(s),querySelector:s=>root.querySelectorAll(s)[0]||null,getElementById:()=>null}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const snap=()=>({w:[w.hidden,wText.value],f:[f.classList.contains('show'),bx.checked],g:[g.hidden,gText.value,gRadio.checked],h:[h.hidden,hArea.value]});
ctx.refreshConditions();const first=snap();
a1.checked=false;a2.checked=true;ctx.refreshConditions();const switched=snap();
a2.checked=false;a1.checked=true;ctx.refreshConditions();const back=snap();
console.log(JSON.stringify({first,switched,back}));
'''


def condition_groups(cond):
    for group in cond.split(';'):
        name, _, values = group.partition('=')
        yield name.strip(), values.split('|')


class QuestionnaireAssets(unittest.TestCase):
    def test_every_display_condition_names_a_real_choice(self):
        for name in PAGES:
            with self.subTest(name=name):
                raw = (ROOT / (name + '.html')).read_text(encoding='utf-8')
                choices = {}
                for field, value in re.findall(r'<input[^>]*?name="([^"]+)"[^>]*?value="([^"]+)"', raw):
                    choices.setdefault(field, set()).add(value)
                page = Elements(); page.feed(raw)
                self.assertTrue(page.conditions)
                for cond in page.conditions:
                    for field, values in condition_groups(cond):
                        self.assertIn(field, choices, cond)
                        for value in values:
                            self.assertIn(value, choices[field], cond)
                self.assertRegex(raw, r'function refreshFollowups\(\)\{ refreshConditions\(\); \}')

    def test_conditions_settle_before_clearing_and_hidden_answers_are_cleared(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js unavailable')
        result = json.loads(subprocess.run([node, '-e', CONDITIONS_DOM, str(ROOT / 'assets/questionnaire.js')],
                                           check=True, capture_output=True, text=True, timeout=15).stdout)
        # Trigger inside a followup that is shown later in the same refresh: kept.
        self.assertEqual(result['first'], {'w': [False, '保留'], 'f': [True, True],
                                           'g': [True, '', False], 'h': [True, '']})
        # Switching the parent choice hides the followup and everything that depended on it, and clears them.
        self.assertEqual(result['switched'], {'w': [True, ''], 'f': [False, False],
                                              'g': [False, '', False], 'h': [False, '']})
        # Switching back does not resurrect old answers.
        self.assertEqual(result['back'], {'w': [True, ''], 'f': [True, False],
                                          'g': [True, '', False], 'h': [True, '']})

    def test_no_duplicate_dom_ids_and_shared_assets_exist(self):
        for name in PAGES:
            with self.subTest(name=name):
                p = Elements(); p.feed((ROOT / (name + '.html')).read_text(encoding='utf-8'))
                self.assertFalse([key for key, n in Counter(p.ids).items() if n > 1])
                for asset in ('questionnaire.css', 'questionnaire.js', 'profile-recipient.js'):
                    self.assertTrue(any(re.fullmatch(r'assets/' + re.escape(asset) + r'\?v=[A-Za-z0-9._-]+', target) for target in p.assets))
                for target in p.assets:
                    self.assertTrue((ROOT / target.split('?', 1)[0]).is_file())

    def test_stable_question_ids_and_shared_json_copy_only(self):
        for name in PAGES:
            with self.subTest(name=name):
                raw = (ROOT / (name + '.html')).read_text(encoding='utf-8')
                page = Elements(); page.feed(raw)
                keys = [q.get('data-profile-id') for q in page.questions]
                self.assertTrue(keys)
                self.assertTrue(all(key and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', key) for key in keys))
                self.assertEqual(len(keys), len(set(keys)))
                self.assertRegex(raw, rf"zhiquCopy\(zhiquProfile\(['\"]{name}['\"]\)\)")
                self.assertNotRegex(raw, r'function\s+(?:answerOf|buildProfile|buildSummary)\s*\(')
                self.assertNotRegex(raw, r'\bL\.push\(')
                self.assertEqual(page.inline_styles, [])
                self.assertEqual(page.style_tags, 0)
                self.assertNotIn('.style.cssText', raw)

    def test_browser_copied_fictional_profiles_match_the_current_questions(self):
        fixtures = Path(__file__).parent / 'fixtures'
        for kind in PAGES:
            with self.subTest(kind=kind):
                data = json.loads((fixtures / ('questionnaire-' + kind + '.json')).read_text(encoding='utf-8'))
                self.assertEqual(data['zhiqu'], kind)
                self.assertEqual(data['schema'], 1)
                self.assertEqual(set(data), {'zhiqu', 'schema', '问卷', 'form', 'filled_at', 'sections', 'rank', 'derived', '未填的必答题'})
                self.assertRegex(data['form'], r'^[0-9a-f]{8}$')
                self.assertTrue(data['rank'])
                self.assertEqual(data['未填的必答题'], [])
                page = Elements(); page.feed((ROOT / (kind + '.html')).read_text(encoding='utf-8'))
                labels = {key: re.sub(r'\s+', ' ', value.strip()) for key, value in page.labels.items()}
                items = [item for section in data['sections'] for item in section['items']]
                self.assertGreater(len(items), 40)
                ids = [item['id'] for item in items]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(next(item for item in items if item['id'] == 'name')['a'], '模拟作答_name')
                for index, item in enumerate(items):
                    self.assertEqual(item['q'], labels[item['id']])
                    self.assertNotIn(item['a'], (None, '', [], {}))
                    if 'followup_of' in item:
                        self.assertIn(item['followup_of'], ids[:index])
                by_id = {item['id']: item for item in items}
                # The copied cases use ordinary domestic students: qualifications
                # that belong to a different selected route must never leak in.
                if kind == 'career':
                    for key in ('degree_other', 'stage_other', 'degree_country', 'bachelor_tier', 'party_regular_month'):
                        self.assertNotIn(key, by_id)
                    self.assertIn('archive_status', by_id)
                    self.assertEqual(by_id['grad_time']['a'], '2027-06')
                elif kind == 'grad':
                    for key in ('offers', 'work_offer'):
                        self.assertNotIn(key, by_id)

    def node_result(self, mode='normal'):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js unavailable; static questionnaire guards still run')
        result = subprocess.run([node, '-e', NODE_DOM, str(ROOT / 'assets/questionnaire.js'), mode],
                                check=True, capture_output=True, text=True, timeout=15)
        return json.loads(result.stdout)

    def test_shared_hash_changes_for_questions_but_not_answers_or_rank_badges(self):
        result = self.node_result()
        self.assertEqual(result['initialHash'], result['answerHash'])
        self.assertEqual(result['initialHash'], result['rankHash'])
        self.assertNotEqual(result['initialHash'], result['wordingHash'])
        self.assertNotEqual(result['initialHash'], result['sectionHash'])

    def test_copy_exports_only_one_json_document_and_the_fallback_matches(self):
        result = self.node_result()
        self.assertEqual(json.loads(result['clipboardText']), result['data'])
        self.assertEqual(result['summaryText'], result['clipboardText'])
        self.assertTrue(result['clipboardText'].lstrip().startswith('{'))
        self.assertNotIn('【以下是给 AI 读的数据', result['clipboardText'])

    def test_off_host_defaults_to_plaintext_and_clipboard_failure_keeps_identical_text(self):
        result = self.node_result('fallback')
        self.assertIsNone(result['recipient'])
        self.assertTrue(result['clipboardText'].startswith('{'))
        self.assertEqual(result['summaryText'], result['clipboardText'])
        self.assertIn('长按全选复制', result['notice'])
        self.assertEqual(json.loads(result['summaryText']), result['data'])

    def test_shared_serializer_includes_month_and_omits_hidden_answers(self):
        data = self.node_result()['data']
        self.assertEqual(data['zhiqu'], 'career')
        self.assertEqual(data['schema'], 1)
        self.assertEqual(data['问卷'], '知衢 · 求职 · 自我盘点')
        self.assertRegex(data['filled_at'], r'^\d{4}-\d\d-\d\dT.*[+-]\d\d:\d\d$')
        items = [item for section in data['sections'] for item in section['items']]
        by_id = {item['id']: item for item in items}
        self.assertEqual(by_id['grad_time']['a'], '2027-06')
        self.assertEqual(by_id['grad_time']['q'], '毕业年月（必答）')
        self.assertNotIn('hidden_question', by_id)
        self.assertNotIn('hidden_answer', json.dumps(data, ensure_ascii=False))
        self.assertNotIn('不应导出的隐藏作答', json.dumps(data, ensure_ascii=False))
        self.assertEqual(by_id['detail']['followup_of'], 'route')
        self.assertEqual([x['id'] for x in items].index('detail'), [x['id'] for x in items].index('route') + 1)
        self.assertEqual(data['rank'], ['城市', '收入'])
        self.assertEqual(by_id['priority']['a'], ['城市', '收入'])
        self.assertNotIn('未填的必答题', data)
        self.assertEqual(by_id['missing']['status'], '未填')
        self.assertTrue(by_id['missing']['required'])
        self.assertNotIn('a', by_id['missing'])
        self.assertEqual(by_id['grad_time']['status'], '已答')
        self.assertEqual(data['collapsed'], ['hidden_question'])
        self.assertEqual(data['counts'], {'visible': len(items), 'answered': sum(item['status'] == '已答' for item in items)})
        self.assertRegex(data['checksum'], r'^[0-9a-f]{64}$')
        content = {key: value for key, value in data.items() if key != 'checksum'}
        normalized = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        self.assertEqual(data['checksum'], hashlib.sha256(normalized.encode()).hexdigest())
        self.assertEqual(data['derived'], {})


if __name__ == '__main__':
    unittest.main()

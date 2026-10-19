"""Shared questionnaire schema and serialization guards; no browser or network."""
from collections import Counter
from html.parser import HTMLParser
import json
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
const context={document:{querySelectorAll:s=>root.querySelectorAll(s),querySelector:s=>root.querySelector(s),getElementById:id=>root.querySelectorAll('input,textarea,select,div').find(e=>e.id===id)||null},navigator:{clipboard:{writeText:value=>{clipboardText=value;return {then:fn=>{fn();return {catch:()=>{}};}};}}},rankOrder:[],isAnswered:q=>q.querySelectorAll('input,textarea,select').some(e=>e.type==='radio'||e.type==='checkbox'?e.checked:!!e.value.trim())};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
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
context.zhiquCopy(data);
console.log(JSON.stringify({initialHash,answerHash,rankHash,wordingHash,sectionHash,data,clipboardText,summaryText:context.document.getElementById('summary').value}));
'''


class QuestionnaireAssets(unittest.TestCase):
    def test_no_duplicate_dom_ids_and_shared_assets_exist(self):
        for name in PAGES:
            with self.subTest(name=name):
                p = Elements(); p.feed((ROOT / (name + '.html')).read_text(encoding='utf-8'))
                self.assertFalse([key for key, n in Counter(p.ids).items() if n > 1])
                self.assertIn('assets/questionnaire.css', p.assets)
                self.assertIn('assets/questionnaire.js', p.assets)
                for target in p.assets:
                    self.assertTrue((ROOT / target).is_file())

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

    def node_result(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js unavailable; static questionnaire guards still run')
        result = subprocess.run([node, '-e', NODE_DOM, str(ROOT / 'assets/questionnaire.js')],
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
        self.assertEqual(data['未填的必答题'], ['尚未填写的核心题'])
        self.assertEqual(data['derived'], {})


if __name__ == '__main__':
    unittest.main()

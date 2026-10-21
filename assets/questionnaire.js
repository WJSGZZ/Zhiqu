  /* 节名：优先 data-title，没有就读页面上的节标题（去掉“（可选）”这类小注） */
  function secTitle(sec){
    var t=sec.getAttribute('data-title'); if(t) return t;
    var el=sec.querySelector('.sec-title'); if(!el) return '';
    var c=el.cloneNode(true); c.querySelectorAll('.opt-note').forEach(function(n){n.remove();});
    return c.textContent.replace(/\s+/g,' ').trim();
  }

  function val(id){var el=document.getElementById(id);return el&&isVisible(el)&&el.value?el.value.trim():'';}
  function radio(name){var el=document.querySelector('input[name="'+name+'"]:checked');return el&&isVisible(el)?el.value:'';}
  function checks(name){var n=document.querySelectorAll('input[name="'+name+'"]:checked'),o=[];for(var i=0;i<n.length;i++)if(isVisible(n[i]))o.push(n[i].value);return o.join('、');}
  function f(v){return(v&&v.length)?v:'（未填）';}
  function isVisible(el){return !!(el&&el.offsetParent!==null);}

  /* ===== 八字（传统视角，选填）排盘 =====
     口径：按填入的北京时间计算，不做真太阳时校正；子时按 lunar-javascript 默认规则处理。
     只填日期：只能排出年/月/日三柱（三柱六字）；分别用当天 00:00 与 23:59 各算一次，
       若年/月/日某柱不同，则该柱显示"甲子/乙丑（需出生时间才能确定）"。
     填了出生时间：排四柱八字；若时间在时辰边界（奇数整点：23/01/03/05/07/09/11/13/15/17/19/21 时）
       前后 15 分钟内，标注"时辰临界"，并用 ±15 分钟重算，若有柱变化则给出对照。
     大运：仅当填了出生时间、且性别为"男"或"女"时才计算（1=男，0=女，与库的 getYun 参数一致），取前 8 步。
     若 lunar-javascript 未加载成功（离线/被拦截等），仅输出原始出生信息 + 提示 AI 按信息排盘，不阻断问卷。
  */
  function baziLibReady(){ return (typeof Solar!=='undefined') && (typeof Solar.fromYmdHms==='function'); }
  function baziEightChar(y,m,d,hh,mi,ss){ return Solar.fromYmdHms(y,m,d,hh,mi,ss||0).getLunar().getEightChar(); }
  function baziYun(ec,genderFlag){return ec.getYun(genderFlag,2);}
  function baziBoundaryNear(hh,mi){
    var boundaries=[23,1,3,5,7,9,11,13,15,17,19,21];
    var totalMin=hh*60+mi, near=false;
    boundaries.forEach(function(bh){
      var bmin=bh*60;
      var diff=Math.min(Math.abs(totalMin-bmin),1440-Math.abs(totalMin-bmin));
      if(diff<=15) near=true;
    });
    return near;
  }
  function baziShiftMinutes(y,m,d,hh,mi,delta){
    var dt=new Date(Date.UTC(y,m-1,d,hh,mi));
    dt=new Date(dt.getTime()+delta*60000);
    return {y:dt.getUTCFullYear(),m:dt.getUTCMonth()+1,d:dt.getUTCDate(),hh:dt.getUTCHours(),mi:dt.getUTCMinutes()};
  }
  /* bdt: 'YYYY-MM-DD'  btm: 'HH:MM' 或空  bpl: 出生地文本或空  sexVal: '男'/'女'/其他 */
  function computeBaziBlock(bdt,btm,bpl,sexVal){
    if(!bdt) return {lines:[],preview:''};
    var p=bdt.split('-'); var y=+p[0],m=+p[1],d=+p[2];
    if(!baziLibReady()){
      var offlineTxt='（排盘库未加载，请 AI 按出生信息排盘）';
      return {lines:['八字（传统视角，选填）：'+offlineTxt],preview:offlineTxt};
    }
    try{
      var lines=[],preview='';
      if(btm){
        var tp=btm.split(':'); var hh=+tp[0],mi=+tp[1];
        var ec=baziEightChar(y,m,d,hh,mi);
        var pillars='年柱 '+ec.getYear()+'　月柱 '+ec.getMonth()+'　日柱 '+ec.getDay()+'　时柱 '+ec.getTime();
        var dayZhu='日主 '+ec.getDayGan()+'（'+ec.getDayWuXing().charAt(0)+'）';
        preview=pillars+'　'+dayZhu;
        lines.push('八字（传统视角，选填）：'+pillars+'　'+dayZhu);
        lines.push('  · 口径：北京时间，未做真太阳时校正；日柱零点换日，晚子时时干按次日；起运按精确分钟折算。');
        lines.push('  · 十神：年干 '+ec.getYearShiShenGan()+'　月干 '+ec.getMonthShiShenGan()+'　时干 '+ec.getTimeShiShenGan()+'（日干为日主，不计十神）');
        var minus=baziShiftMinutes(y,m,d,hh,mi,-15), plus=baziShiftMinutes(y,m,d,hh,mi,15);
        var left=baziEightChar(minus.y,minus.m,minus.d,minus.hh,minus.mi), right=baziEightChar(plus.y,plus.m,plus.d,plus.hh,plus.mi);
        var nearTerm=left.getYear()!==right.getYear()||left.getMonth()!==right.getMonth();
        if(baziBoundaryNear(hh,mi)||nearTerm){
          var s1=baziShiftMinutes(y,m,d,hh,mi,-15), s2=baziShiftMinutes(y,m,d,hh,mi,15);
          var ec1=baziEightChar(s1.y,s1.m,s1.d,s1.hh,s1.mi), ec2=baziEightChar(s2.y,s2.m,s2.d,s2.hh,s2.mi);
          var changed = ec1.getYear()!==ec.getYear()||ec1.getMonth()!==ec.getMonth()||ec1.getDay()!==ec.getDay()||ec1.getTime()!==ec.getTime()
                     || ec2.getYear()!==ec.getYear()||ec2.getMonth()!==ec.getMonth()||ec2.getDay()!==ec.getDay()||ec2.getTime()!==ec.getTime();
          var noteTail=changed?('　－15分：'+ec1.getYear()+' '+ec1.getMonth()+' '+ec1.getDay()+' '+ec1.getTime()+'　＋15分：'+ec2.getYear()+' '+ec2.getMonth()+' '+ec2.getDay()+' '+ec2.getTime()):'';
          lines.push('  · （'+(nearTerm?'节气临界：出生时间误差可能改变年柱或月柱':'时辰临界：出生时间误差可能改变时柱')+'）'+noteTail);
          preview+=nearTerm?'（节气临界）':'（时辰临界）';
        }
        if(sexVal==='男'||sexVal==='女'){
          var genderFlag=(sexVal==='男')?1:0;
          var yun=baziYun(ec,genderFlag);
          var list=yun.getDaYun(9); // index0=起运前，1..8为前8步大运
          var first=list[1];
          var arr=[];
          for(var i=1;i<list.length;i++){ arr.push(list[i].getGanZhi()+'('+list[i].getStartYear()+')'); }
          lines.push('  · 大运：'+first.getStartAge()+' 岁起运（'+first.getStartYear()+' 年），'+(yun.isForward()?'顺行':'逆行')+'；'+arr.join(' '));
        }
      } else {
        var ec0=baziEightChar(y,m,d,0,0), ec1d=baziEightChar(y,m,d,23,59);
        var yTxt = ec0.getYear()===ec1d.getYear() ? ec0.getYear() : (ec0.getYear()+'/'+ec1d.getYear()+'（需出生时间才能确定）');
        var mTxt = ec0.getMonth()===ec1d.getMonth() ? ec0.getMonth() : (ec0.getMonth()+'/'+ec1d.getMonth()+'（需出生时间才能确定）');
        var dTxt = ec0.getDay()===ec1d.getDay() ? ec0.getDay() : (ec0.getDay()+'/'+ec1d.getDay()+'（需出生时间才能确定）');
        var pillars3='年柱 '+yTxt+'　月柱 '+mTxt+'　日柱 '+dTxt;
        preview=pillars3;
        lines.push('八字（传统视角，选填）：'+pillars3+'　日主 '+ec0.getDayGan()+'（'+ec0.getDayWuXing().charAt(0)+'）');
        lines.push('  · 口径：北京时间，未做真太阳时校正；日柱零点换日，晚子时时干按次日；起运按精确分钟折算。只填了日期，只能排年/月/日三柱；填出生时间可排完整四柱与大运。');
      }
      if(bpl) lines.push('  · 出生地：'+bpl+'（未用于校正，AI 可复核真太阳时）');
      return {lines:lines,preview:preview};
    }catch(e){
      var errTxt='（排盘计算出错，请 AI 按出生信息排盘）';
      return {lines:['八字（传统视角，选填）：'+errTxt],preview:errTxt};
    }
  }

  /* ===== 按阶段收起不用填的题 =====
     data-hide-when="name=值|值"：条件成立时收起（并清空其中作答）；data-show-when 相反，只在条件成立时显示。 */
  function condOn(cond){
    // 分号连接不同题的“或”；竖线连接同题可触发的值。只读当前可见的选择。
    return cond.split(';').some(function(group){
      var eq=group.indexOf('='),name=group.slice(0,eq).trim();
      if(eq<1) return false;
      var values=group.slice(eq+1).split('|');
      return Array.prototype.some.call(document.querySelectorAll('input'),function(el){
        return el.name===name&&el.checked&&values.indexOf(el.value)>=0&&isVisible(el);
      });
    });
  }
  function clearInside(el){
    el.querySelectorAll('input').forEach(function(i){ if(i.type==='radio'||i.type==='checkbox') i.checked=false; else i.value=''; });
    el.querySelectorAll('textarea').forEach(function(t){ t.value=''; });
  }
  /* 三种条件一起算：data-hide-when / data-show-when 控制 hidden，.followup[data-when] 控制 show。
     触发题可能本身在另一个追问里（读回草稿时尤其如此），所以反复计算到不再变化；
     算稳之后，凡是被收起的部分一律清空作答，过时答案既不导出、也不会在条件再次成立时“复活”，也不会被存进本地草稿。 */
  function conditionalHidden(el){
    if(el.hasAttribute('data-hide-when')&&condOn(el.getAttribute('data-hide-when'))) return true;
    return el.hasAttribute('data-show-when')&&!condOn(el.getAttribute('data-show-when'));
  }
  function isFollowup(el){ return el.classList.contains('followup')&&el.hasAttribute('data-when'); }
  function refreshConditions(){
    var els=document.querySelectorAll('[data-hide-when],[data-show-when],.followup[data-when]');
    for(var pass=0;pass<10;pass++){
      var changed=false;
      Array.prototype.forEach.call(els,function(el){
        if(el.hasAttribute('data-hide-when')||el.hasAttribute('data-show-when')){
          var h=conditionalHidden(el);
          if(el.hidden!==h){ el.hidden=h; changed=true; }
        }
        if(isFollowup(el)){
          var on=condOn(el.getAttribute('data-when'));
          if(el.classList.contains('show')!==on){ if(on) el.classList.add('show'); else el.classList.remove('show'); changed=true; }
        }
      });
      if(!changed) break;
    }
    Array.prototype.forEach.call(els,function(el){
      if(el.hidden||(isFollowup(el)&&!el.classList.contains('show'))) clearInside(el);
    });
  }
  function applyStageVisibility(){ refreshConditions(); }

  /* ===== 复制我的画像：一个包含题目原文的 JSON =====
     只输出 JSON，供人和工具读取、存档与按题比较。
     form 是题目结构的指纹：题目或选项一改，指纹就变，旧答卷能对上旧题。编号由顾问登记时给，网页不生成。 */
  function zhiquFormHash(){
    var keys=[];
    document.querySelectorAll('.section').forEach(function(sec){keys.push('section='+secTitle(sec));});
    document.querySelectorAll('.q').forEach(function(q){
      keys.push('q='+q.getAttribute('data-profile-id')+'='+zhiquQuestionText(q)+(q.classList.contains('req')?':required':':optional'));
    });
    document.querySelectorAll('input,textarea,select').forEach(function(el){
      if(el.id==='summary') return;
      keys.push((el.name||el.id)+':'+el.type+(el.type==='radio'||el.type==='checkbox'?'='+el.value+'='+((el.closest('label')||el).textContent||'').trim():'')+'='+zhiquPartLabel(el));
    });
    document.querySelectorAll('[data-when],[data-hide-when],[data-show-when]').forEach(function(el){keys.push('when='+[el.getAttribute('data-when'),el.getAttribute('data-hide-when'),el.getAttribute('data-show-when')].join(';'));});
    document.querySelectorAll('.rank-item').forEach(function(it){keys.push('rank='+it.getAttribute('data-id')+'='+it.lastElementChild.textContent.trim());});
    var s=keys.join('\n'),h=5381;
    for(var i=0;i<s.length;i++){h=((h<<5)+h+s.charCodeAt(i))>>>0;}
    return ('00000000'+h.toString(16)).slice(-8);
  }
  function localStamp(){
    var d=new Date(),p=function(n){return (n<10?'0':'')+n;},o=-d.getTimezoneOffset(),sign=o>=0?'+':'-';o=Math.abs(o);
    return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds())+sign+p(Math.floor(o/60))+':'+p(o%60);
  }
  // A question's id is declared in HTML. Visible wording is kept verbatim in q.
  function zhiquControls(q){
    return Array.prototype.filter.call(q.querySelectorAll('input,textarea,select'),function(el){
      return el.closest('.q')===q&&isVisible(el)&&el.id!=='summary';
    });
  }
  function zhiquQuestionText(q){
    var label=q.querySelector('.q-label');
    return label?label.textContent.trim().replace(/\s+/g,' '):q.getAttribute('data-label')||'';
  }
  function zhiquPartLabel(el){
    if(el.getAttribute('data-profile-label')) return el.getAttribute('data-profile-label');
    var label=el.id&&document.querySelector('label[for="'+el.id+'"]');
    if(label) return label.textContent.trim();
    if(el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    var prev=el.previousElementSibling;
    if(prev&&(prev.classList.contains('minilabel')||prev.classList.contains('q-label')||prev.tagName==='LABEL')) return prev.textContent.trim();
    if(el.getAttribute('placeholder')) return el.getAttribute('placeholder');
    return el.type==='radio'?'选择':el.type==='checkbox'?'多选':'填写';
  }
  function zhiquQuestionAnswer(q){
    if(q.querySelector('.rank')) return typeof rankOrder!=='undefined'&&rankOrder.length?rankOrder.slice():null;
    var controls=zhiquControls(q),groups=[],seen={};
    controls.forEach(function(el){
      var key=(el.type==='radio'||el.type==='checkbox')?el.name:el.id;
      if(!key||seen[key]) return;
      seen[key]=true;
      var items=controls.filter(function(x){return (x.name||x.id)===key;});
      var answer;
      if(el.type==='radio'){
        var chosen=items.filter(function(x){return x.checked;}); answer=chosen.length?chosen[0].value:null;
      } else if(el.type==='checkbox'){
        answer=items.filter(function(x){return x.checked;}).map(function(x){return x.value;});
        if(!answer.length) answer=null;
      } else answer=el.value.trim()||null;
      groups.push({key:key,label:zhiquPartLabel(el),a:answer});
    });
    var answered=groups.filter(function(x){return x.a!==null;});
    if(!answered.length) return null;
    if(groups.length===1) return answered[0].a;
    var result={},counts={};
    answered.forEach(function(x){
      var key=x.label; counts[key]=(counts[key]||0)+1;
      if(counts[key]>1) key+='（'+counts[key]+'）';
      result[key]=x.a;
    });
    return result;
  }
  function zhiquParentQuestion(q){
    var wrapper=q.parentElement.closest('[data-when],[data-show-when]');
    if(!wrapper) return null;
    var cond=wrapper.getAttribute('data-when')||wrapper.getAttribute('data-show-when');
    var result=null;
    cond.split(';').some(function(group){
      var eq=group.indexOf('='),name=group.slice(0,eq).trim(),values=group.slice(eq+1).split('|');
      if(['grade','stage','stage_now'].indexOf(name)>=0) return false;
      return Array.prototype.some.call(document.querySelectorAll('input'),function(el){
        if(el.name===name&&el.checked&&isVisible(el)&&values.indexOf(el.value)>=0){
          var parent=el.closest('.q');
          if(parent&&parent!==q){ result=parent.getAttribute('data-profile-id');return true; }
        }
        return false;
      });
    });
    return result;
  }
  function zhiquProfile(kind){
    var labels={gaokao:'高考志愿',grad:'读研',career:'求职'};
    var profile={zhiqu:kind,schema:1,'问卷':'知衢 · '+labels[kind]+' · 自我盘点',form:zhiquFormHash(),filled_at:localStamp(),sections:[],rank:typeof rankOrder!=='undefined'?rankOrder.slice():[],derived:{},collapsed:[],counts:{visible:0,answered:0}};
    document.querySelectorAll('.section').forEach(function(sec){
      var section={title:secTitle(sec),items:[]};
      sec.querySelectorAll('.q').forEach(function(q){
        if(!q.getAttribute('data-profile-id')) return;
        if(!isVisible(q)){profile.collapsed.push(q.getAttribute('data-profile-id'));return;}
        var text=zhiquQuestionText(q),answer=zhiquQuestionAnswer(q);
        var item={id:q.getAttribute('data-profile-id'),q:text,status:answer!==null?'已答':'未填'},parent=zhiquParentQuestion(q);
        if(answer!==null){item.a=answer;profile.counts.answered++;}
        if(q.classList.contains('req'))item.required=true;
        if(parent)item.followup_of=parent;
        section.items.push(item);profile.counts.visible++;
      });
      if(section.items.length) profile.sections.push(section);
    });
    // Attach follow-ups to their answered parent even when the page places the
    // triggering choice later. Grade/stage visibility is not a follow-up.
    var all={},children={};
    profile.sections.forEach(function(sec){sec.items.forEach(function(item){all[item.id]=item;});});
    profile.sections.forEach(function(sec){sec.items.forEach(function(item){
      if(item.followup_of&&all[item.followup_of]) (children[item.followup_of]=children[item.followup_of]||[]).push(item);
      else delete item.followup_of;
    });});
    var emitted={};
    function emit(item,list){if(emitted[item.id])return;emitted[item.id]=true;list.push(item);(children[item.id]||[]).forEach(function(child){emit(child,list);});}
    profile.sections.forEach(function(sec){var ordered=[];sec.items.forEach(function(item){if(!item.followup_of)emit(item,ordered);});sec.items=ordered;});
    profile.sections=profile.sections.filter(function(sec){return sec.items.length;});
    var birth=val('birthdate');
    if(birth){
      profile.derived.bazi=computeBaziBlock(birth,val('birthtime'),val('birthplace'),radio('bz_sex')||radio('sex')).lines.join('\n');
    }
    return profile;
  }
  // Canonical UTF-8 JSON: recursively sort object keys, preserve array order.
  function zhiquCanonical(value){
    if(Array.isArray(value))return '['+value.map(zhiquCanonical).join(',')+']';
    if(value!==null&&typeof value==='object')return '{'+Object.keys(value).sort().map(function(k){return JSON.stringify(k)+':'+zhiquCanonical(value[k]);}).join(',')+'}';
    return JSON.stringify(value);
  }
  async function zhiquSeal(profile){
    delete profile.checksum;
    var digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(zhiquCanonical(profile)));
    profile.checksum=Array.from(new Uint8Array(digest)).map(function(n){return n.toString(16).padStart(2,'0');}).join('');
    return profile;
  }
  function zhiquRecipient(){
    var c=typeof window!=='undefined'&&window.ZHIQU_RECIPIENT;
    return c&&c.name&&c.spki&&c.hostname&&location.hostname.toLowerCase()===c.hostname.toLowerCase()?c:null;
  }
  function zhiquBase64(bytes){
    var str='';for(var i=0;i<bytes.length;i++)str+=String.fromCharCode(bytes[i]);
    return btoa(str).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  }
  async function zhiquEncrypt(text,recipient){
    var zipped=new Uint8Array(await new Response(new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer());
    var publicKey=await crypto.subtle.importKey('spki',Uint8Array.from(atob(recipient.spki),function(c){return c.charCodeAt(0);}),{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);
    var aes=await crypto.subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
    var iv=crypto.getRandomValues(new Uint8Array(12));
    var wrapped=new Uint8Array(await crypto.subtle.encrypt({name:'RSA-OAEP'},publicKey,await crypto.subtle.exportKey('raw',aes)));
    var ciphertext=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv:iv,additionalData:new TextEncoder().encode('ZQ1'),tagLength:128},aes,zipped));
    var bytes=new Uint8Array(2+wrapped.length+iv.length+ciphertext.length);
    bytes[0]=wrapped.length>>8;bytes[1]=wrapped.length&255;bytes.set(wrapped,2);bytes.set(iv,2+wrapped.length);bytes.set(ciphertext,14+wrapped.length);
    return 'ZQ1:'+zhiquBase64(bytes);
  }
  function zhiquCopyNotice(){
    var note=document.getElementById('copyPrivacy');if(!note)return;
    if(zhiquRecipient()){
      note.textContent='加密后只有'+zhiquRecipient().name+'能打开。想自己交给 AI 分析？';
      var button=document.createElement('button');button.type='button';button.className='plain-copy';button.textContent='复制未加密版本';
      button.addEventListener('click',function(){zhiquCopy(zhiquProfile(document.body.getAttribute('data-profile-kind')),true);});note.appendChild(button);
    }else note.textContent='尚未配置接收人公钥，复制的是未加密画像';
  }
  async function zhiquCopy(profile,plain){
    var msg=document.getElementById('copyDone'),out=document.getElementById('output'),ta=document.getElementById('summary');
    try{
      await zhiquSeal(profile);
      var full=JSON.stringify(profile,null,2),recipient=zhiquRecipient();
      if(recipient&&!plain)full=await zhiquEncrypt(full,recipient);
      out.classList.remove('show');ta.value=full;
      var done=function(){msg.textContent='已复制 ✓ 直接粘贴发回去就行';msg.classList.add('show');};
      var fail=function(){msg.textContent='没能自动复制，请长按全选复制';msg.classList.add('show');out.classList.add('show');out.scrollIntoView({block:'start'});};
      if(navigator.clipboard&&navigator.clipboard.writeText){
        try{await navigator.clipboard.writeText(full);done();}
        catch(e){fail();}
      }else fail();
      return full;
    }catch(e){
      // Never silently send cleartext when encryption was selected.
      ta.value='';out.classList.remove('show');msg.textContent='未能生成画像，请使用支持安全加密的最新版浏览器并重试。';msg.classList.add('show');
      return null;
    }
  }

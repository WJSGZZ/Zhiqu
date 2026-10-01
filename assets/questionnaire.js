
  function val(id){var el=document.getElementById(id);return el&&el.value?el.value.trim():'';}
  function radio(name){var el=document.querySelector('input[name="'+name+'"]:checked');return el?el.value:'';}
  function checks(name){var n=document.querySelectorAll('input[name="'+name+'"]:checked'),o=[];for(var i=0;i<n.length;i++)o.push(n[i].value);return o.join('、');}
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
  function baziEightChar(y,m,d,hh,mi){ return Solar.fromYmdHms(y,m,d,hh,mi,0).getLunar().getEightChar(); }
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
    var dt=new Date(y,m-1,d,hh,mi);
    dt=new Date(dt.getTime()+delta*60000);
    return {y:dt.getFullYear(),m:dt.getMonth()+1,d:dt.getDate(),hh:dt.getHours(),mi:dt.getMinutes()};
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
        lines.push('  · 口径：北京时间，未做真太阳时校正；子时按排盘库默认规则。');
        lines.push('  · 十神：年干 '+ec.getYearShiShenGan()+'　月干 '+ec.getMonthShiShenGan()+'　时干 '+ec.getTimeShiShenGan()+'（日干为日主，不计十神）');
        if(baziBoundaryNear(hh,mi)){
          var s1=baziShiftMinutes(y,m,d,hh,mi,-15), s2=baziShiftMinutes(y,m,d,hh,mi,15);
          var ec1=baziEightChar(s1.y,s1.m,s1.d,s1.hh,s1.mi), ec2=baziEightChar(s2.y,s2.m,s2.d,s2.hh,s2.mi);
          var changed = ec1.getYear()!==ec.getYear()||ec1.getMonth()!==ec.getMonth()||ec1.getDay()!==ec.getDay()||ec1.getTime()!==ec.getTime()
                     || ec2.getYear()!==ec.getYear()||ec2.getMonth()!==ec.getMonth()||ec2.getDay()!==ec.getDay()||ec2.getTime()!==ec.getTime();
          var noteTail=changed?('　－15分：'+ec1.getYear()+' '+ec1.getMonth()+' '+ec1.getDay()+' '+ec1.getTime()+'　＋15分：'+ec2.getYear()+' '+ec2.getMonth()+' '+ec2.getDay()+' '+ec2.getTime()):'';
          lines.push('  · （时辰临界：出生时间误差可能改变时柱）'+noteTail);
          preview+='（时辰临界）';
        }
        if(sexVal==='男'||sexVal==='女'){
          var genderFlag=(sexVal==='男')?1:0;
          var yun=ec.getYun(genderFlag);
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
        lines.push('  · 口径：北京时间，未做真太阳时校正；子时按排盘库默认规则。只填了日期，只能排年/月/日三柱；填出生时间可排完整四柱与大运。');
      }
      if(bpl) lines.push('  · 出生地：'+bpl+'（未用于校正，AI 可复核真太阳时）');
      return {lines:lines,preview:preview};
    }catch(e){
      var errTxt='（排盘计算出错，请 AI 按出生信息排盘）';
      return {lines:['八字（传统视角，选填）：'+errTxt],preview:errTxt};
    }
  }

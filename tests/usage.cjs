const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../assets/usage.js'),'utf8').replace(/bootUsagePage\(\);\s*$/,'');
const htmlEscape=value=>String(value??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function core(overrides={}){
  const elements=new Map(),events={};
  const element=id=>{
    if(!elements.has(id)) elements.set(id,{innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',title:'',classList:{add(){},remove(){},toggle(){}},setAttribute(name,value){this[name]=value;},addEventListener(){}});
    return elements.get(id);
  };
  const document={hidden:false,querySelector:element,querySelectorAll:()=>[],addEventListener(name,callback){events[name]=callback;}};
  const context=vm.createContext({Date,URLSearchParams,AbortController,console,setInterval:()=>1,clearInterval(){},
    document,window:{addEventListener(name,callback){events[name]=callback;}},location:{pathname:'/usage.html',search:''},history:{replaceState(){}},
    state:{local:true,editing:false,data:[]},$:element,$$:()=>[],esc:htmlEscape,setupLogos(){},bindDetailLinks(){},
    usageDetailParams:app=>app.catalogueId ? {id:app.catalogueId,...(/^exe-[0-9a-f]{16}$/.test(app.id)?{usageId:app.id}:{})} : /^exe-[0-9a-f]{16}$/.test(app.id)?{usageId:app.id}:null,
    pageURL:(page,params)=>page+'?'+new URLSearchParams(params),logoHTML:()=>'<svg aria-hidden="true"></svg>',...overrides});
  vm.runInContext(source+'\nthis.usage={usageState,usageDateKey,usageParseDate,usageLaunchQuote,usageRange,usageShiftDate,usageRangeLabel,usageDuration,usageDurationHTML,usageNormalize,usageChartSVG,usageChartExactDuration,usageBindChart,usageRenderChart,usageRankingHTML,usageProgressValues,usageToneScale,usageTrackingInfo,usageRenderControls,usageRenderPayload,usageRenderRanking,usageLoad,usageChoose,usageChooseChart,usageUpdateURL,usageRenderUnavailable,usageLoadBackground,usageSetBackground,renderUsage};',context);
  return {...context.usage,elements,element,context,document,events};
}
const data=(overrides={})=>({period:'day',date:'2026-10-15',start:'2026-10-15',end:'2026-10-16',buckets:[{label:'09:00',start:'2026-10-15T09:00:00',seconds:120}],apps:[{id:'editor',name:'Editor',path:'D:\\Editor\\app.exe',seconds:120}],totalSeconds:120,status:{tracking:true,since:'2026-10-15T08:00:00+08:00'},...overrides});
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
const plain=value=>JSON.parse(JSON.stringify(value));
function rankingDOM(c){
  const list=c.element('#usage-app-list');let rows=[],html='',writes=0;
  Object.defineProperty(list,'innerHTML',{get:()=>html,set:value=>{
    html=value;writes++;
    rows=[...value.matchAll(/<a class="usage-app-row detail-link"([^>]*)>([\s\S]*?)<\/a>/g)].map(match=>{
      const style=()=>({setProperty(name,value){this[name]=value;}});
      const dataset={},duration={textContent:match[2].match(/class="usage-app-duration"[^>]*>([^<]*)/)?.[1]||'',style:style()},progress={style:{...style(),width:match[2].match(/style="width:([^;"]+)/)?.[1]||''}};
      duration.style['--usage-time-color']=match[2].match(/--usage-time-color:(rgb\([^)]+\))/)?.[1];
      progress.style['--usage-bar-color']=match[2].match(/--usage-bar-color:(rgb\([^)]+\))/)?.[1];
      for(const [attribute,key] of [['usage-id','usageId'],['detail-id','detailId']]){const value=match[1].match(new RegExp('data-'+attribute+'="([^"]+)"'))?.[1];if(value) dataset[key]=value;}
      return {dataset,duration,progress,querySelector:selector=>selector==='.usage-app-duration'?duration:progress,focus(options){c.document.activeElement=this;this.focusOptions=options;}};
    });
  }});
  list.contains=element=>rows.includes(element);list.querySelectorAll=()=>rows;
  return {list,get rows(){return rows;},get writes(){return writes;}};
}

test('calendar navigation uses real dates, Monday weeks and half-open month ranges',()=>{
  const c=core();
  assert.deepEqual(plain(c.usageRange('week','2026-01-01')),{start:'2025-12-29',end:'2026-01-05'});
  assert.deepEqual(plain(c.usageRange('month','2024-02-29')),{start:'2024-02-01',end:'2024-03-01'});
  assert.equal(c.usageShiftDate('2026-03-31','month',-1),'2026-02-01');
  assert.equal(c.usageShiftDate('2026-12-31','day',1),'2027-01-01');
  assert.equal(c.usageParseDate('2026-02-29'),null);
  assert.equal(c.usageDateKey(new Date(2026,9,15,0,2)),'2026-10-15');
});

test('the launch reflection survives period changes, refreshes and calendar dates',()=>{
  const c=core();
  const quote='时间无法收藏，经历可以。';
  c.context.state.quote=quote;
  assert.equal(c.usageLaunchQuote(),quote);
  c.usageState.date='2024-02-29';c.usageState.period='month';c.usageRenderControls();
  assert.equal(c.element('#usage-quote').textContent,quote);
  c.usageState.date='2026-10-16';c.usageState.period='day';c.usageRenderControls();
  assert.equal(c.element('#usage-quote').textContent,quote);
});

test('the compact summary preserves actual time, app count and top application',()=>{
  const c=core();
  c.usageRenderPayload(c.usageNormalize(data({totalSeconds:3660,apps:[{id:'a',name:'Editor',seconds:3000},{id:'b',name:'Browser',seconds:660}]})));
  assert.equal(c.element('#usage-total').innerHTML,'1<small>小时</small>1<small>分钟</small>');
  assert.equal(c.element('#usage-app-count').textContent,'2');
  assert.equal(c.element('#usage-top-name').textContent,'Editor');
  assert.equal(c.element('#usage-top-time').textContent,'50 分钟');
});

test('time labels retain remaining seconds across minute and hour boundaries without rounding up',()=>{
  const c=core();
  for(const [seconds,label] of [[0,'0 秒'],[0.8,'不足 1 秒'],[28.9,'28 秒'],[59.9,'59 秒'],[60,'1 分钟'],[119.9,'1 分钟 59 秒'],[3599,'59 分钟 59 秒'],[3600,'1 小时'],[3661,'1 小时 1 分钟 1 秒']]) assert.equal(c.usageDuration(seconds),label);
  assert.equal(c.usageDurationHTML(3600),'1<small>小时</small>');
  assert.equal(c.usageDurationHTML(3661),'1<small>小时</small>1<small>分钟</small>1<small>秒</small>');
  assert.equal(c.usageDurationHTML(0.8),'不足1<small>秒</small>');
  const payload=c.usageNormalize(data({totalSeconds:119.9,apps:[{id:'editor',name:'Editor',seconds:119.9}]}));
  c.usageRenderPayload(payload);
  assert.equal(c.element('#usage-total').innerHTML,'1<small>分钟</small>59<small>秒</small>');
  assert.equal(c.element('#usage-top-time').textContent,'1 分钟 59 秒');
  assert.match(c.element('#usage-app-list').innerHTML,/1 分钟 59 秒/);
});

test('usage payloads retain exact totals, sort actual apps and reject impossible readings',()=>{
  const c=core();
  const result=c.usageNormalize(data({apps:[{name:'Short',seconds:5},{name:'Long',seconds:40},{name:'Zero',seconds:0}],totalSeconds:45}));
  assert.equal(result.totalSeconds,45); assert.deepEqual(plain(result.apps).map(a=>a.name),['Long','Short']);
  assert.throws(()=>c.usageNormalize(data({totalSeconds:-1})),/格式/);
  assert.throws(()=>c.usageNormalize(data({buckets:[{label:'bad',seconds:Infinity}]})),/格式/);
});

test('SVG accessibility includes exact readings and untrusted labels are escaped',()=>{
  const c=core();
  const chart=c.usageChartSVG([{label:'<img onerror="x">',seconds:125},{label:'10:00',seconds:0}]);
  assert.match(chart,/aria-labelledby="usage-chart-title usage-chart-description"/);
  assert.match(chart,/2 分钟 5 秒/); assert.match(chart,/10:00：0 秒/);
  assert.doesNotMatch(chart,/<img/); assert.match(chart,/&lt;img onerror=&quot;x&quot;&gt;/);
  assert.doesNotMatch(chart,/NaN|Infinity/);
});

test('narrow charts preserve all 24 hours with wide bars and a scrollable readable axis',()=>{
  const c=core();
  const buckets=Array.from({length:24},(_,hour)=>({label:String(hour).padStart(2,'0')+':00',seconds:hour*12}));
  const svg=c.usageChartSVG(buckets,320,{chart:'bar'});
  const dimensions=svg.match(/viewBox="0 0 (\d+) (\d+)"/);
  assert.ok(Number(dimensions[1])>=24*32);
  assert.equal((svg.match(/data-bucket="/g)||[]).length,24);
  assert.equal((svg.match(/class="usage-axis-label usage-time-label"/g)||[]).length,24);
  assert.equal((svg.match(/class="usage-bar-value"/g)||[]).length,23);
  const widths=[...svg.matchAll(/class="usage-bar"[^>]* width="([\d.]+)"/g)].map(match=>Number(match[1]));
  assert.ok(widths.every(width=>width>=24));
  assert.match(svg,/23:00：4 分钟 36 秒/);
  c.usageRenderChart(data({buckets}));
  assert.match(c.element('#usage-chart').innerHTML,/usage-chart-viewport/);
  assert.match(c.element('#usage-chart').innerHTML,/完整时间轴，小屏可横向滚动/);
});

test('axis units stay consistent and every nonzero bar displays its duration',()=>{
  const c=core();
  const svg=c.usageChartSVG([{label:'00:00',seconds:1},{label:'01:00',seconds:3599},{label:'02:00',seconds:0}],500,{chart:'bar'});
  assert.match(svg,/class="usage-axis-unit"[^>]*>分钟</);
  assert.match(svg,/>0.02分</);assert.match(svg,/>60分</);
  assert.equal((svg.match(/class="usage-bar-value"/g)||[]).length,2);
  assert.match(svg,/59 分钟 59 秒/);
  assert.doesNotMatch(svg,/NaN|Infinity/);
  assert.equal(c.usageChartExactDuration(0.125),'0.125 秒');
  assert.equal(c.usageChartExactDuration(3661.25),'1 小时 1 分钟 1.25 秒');
});

test('current and future hours are distinguished without dropping any bucket',()=>{
  const c=core();
  const buckets=Array.from({length:24},(_,hour)=>({label:String(hour).padStart(2,'0')+':00',
    start:`2026-10-16T${String(hour).padStart(2,'0')}:00:00+08:00`,
    end:hour===23?'2026-10-17T00:00:00+08:00':`2026-10-16T${String(hour+1).padStart(2,'0')}:00:00+08:00`,seconds:hour===1?120:0}));
  const svg=c.usageChartSVG(buckets,960,{period:'day',now:Date.parse('2026-10-16T02:30:00+08:00')});
  assert.equal((svg.match(/class="usage-axis-label usage-time-label"/g)||[]).length,24);
  assert.equal((svg.match(/data-bucket="/g)||[]).length,3);
  assert.equal((svg.match(/class="usage-bar-group is-future"/g)||[]).length,21);
  assert.match(svg,/class="usage-bar-group is-current" data-bucket="2"/);
  assert.match(svg,/尚未发生/);assert.match(svg,/23:00/);
  const past=c.usageChartSVG(buckets,960,{period:'day',now:Date.parse('2026-10-17T02:30:00+08:00')});
  assert.doesNotMatch(past,/usage-future-zone|usage-bar-group is-current/);
});

test('week and month charts retain every calendar bucket with a true peak summary',()=>{
  const c=core();
  for(const count of [7,28,29,30,31]){
    const buckets=Array.from({length:count},(_,index)=>({label:String(index+1),seconds:index===3?125:0}));
    const svg=c.usageChartSVG(buckets,320,{period:count===7?'week':'month',chart:'bar'});
    assert.equal((svg.match(/data-bucket="/g)||[]).length,count);
    assert.equal((svg.match(/class="usage-bar-value"/g)||[]).length,1);
    c.usageRenderChart(data({buckets,period:count===7?'week':'month'}));
    assert.match(c.element('#usage-chart').innerHTML,/高峰/);
    assert.match(c.element('#usage-chart').innerHTML,/2 分钟 5 秒/);
  }
});

test('the default straight line uses exact bucket coordinates and keeps real zero points',()=>{
  const c=core();
  for(const period of ['day','week','month']){
    const buckets=[{label:'01:00',seconds:60},{label:'02:00',seconds:0},{label:'03:00',seconds:120}];
    const svg=c.usageChartSVG(buckets,400,{period});
    assert.match(svg,/data-chart="line"/);
    assert.match(svg,/class="usage-line" d="M105.00,107.50 L217.00,185.00 L329.00,30.00"/);
    assert.equal((svg.match(/class="usage-line-point"/g)||[]).length,3);
    assert.match(svg,/class="usage-line-point" cx="217.00" cy="185.00"/);
    assert.doesNotMatch(svg,/class="usage-bar"/);
    const path=svg.match(/class="usage-line" d="([^"]+)"/)[1];
    assert.doesNotMatch(path,/[CQSA]/);
    assert.match(svg,/02:00：0 秒/);
  }
});

test('a line stops at observed time and leaves future buckets as coordinates without invented zeros',()=>{
  const c=core();
  const buckets=[0,1,2,3].map(hour=>({label:`0${hour}:00`,start:`2026-10-16T0${hour}:00:00+08:00`,end:`2026-10-16T0${hour+1}:00:00+08:00`,seconds:hour===0?120:0}));
  const svg=c.usageChartSVG(buckets,400,{now:Date.parse('2026-10-16T01:30:00+08:00')});
  assert.equal((svg.match(/class="usage-line-point"/g)||[]).length,2);
  assert.equal((svg.match(/class="usage-axis-label usage-time-label"/g)||[]).length,4);
  assert.match(svg,/01:00：0 秒/);assert.match(svg,/02:00：尚未发生/);
  assert.doesNotMatch(svg,/02:00：0 秒|03:00：0 秒/);
  assert.equal((svg.match(/class="usage-line" d="[^"L]+ L/g)||[]).length,1);
  const bar=c.usageChartSVG(buckets,400,{chart:'bar',now:Date.parse('2026-10-16T01:30:00+08:00')});
  assert.equal((bar.match(/data-bucket="/g)||[]).length,2);
});

test('a single observed point has no fictional segment and empty readings retain the honest empty state',()=>{
  const c=core();
  const single=c.usageChartSVG([{label:'09:00',seconds:5}],400);
  assert.equal((single.match(/class="usage-line-point"/g)||[]).length,1);
  assert.doesNotMatch(single,/class="usage-line"|class="usage-line-area"/);
  c.usageRenderChart(data({buckets:[],apps:[],totalSeconds:0}));
  assert.match(c.element('#usage-chart').innerHTML,/这个周期还没有记录/);
  assert.doesNotMatch(c.element('#usage-chart').innerHTML,/usage-line-point/);
  c.usageRenderChart(data({buckets:[{label:'09:00',seconds:0}],apps:[],totalSeconds:0}));
  assert.match(c.element('#usage-chart').innerHTML,/这个周期还没有记录/);
});

test('chart controls switch the existing payload immediately without fetching or changing time records',()=>{
  let calls=0;
  const location={pathname:'/usage.html',search:'?period=week&date=2026-10-05&chart=line'},saved=[];
  const buttons=['line','bar'].map(chart=>({dataset:{chart},events:{},classList:{toggle(name,on){this.active=on;}},setAttribute(name,value){this[name]=value;},addEventListener(name,callback){this.events[name]=callback;}}));
  const c=core({location,state:{local:false,editing:false,data:[]},fetch:async()=>{calls++;throw new Error('should not fetch');},
    $$:selector=>selector==='button[data-chart]'?buttons:[],history:{state:{keep:true},replaceState(state,title,url){saved.push({state,url});location.search=url.slice(url.indexOf('?'));}}});
  c.renderUsage();
  const payload=c.usageNormalize(data({period:'week',date:'2026-10-05'})),before=JSON.stringify(payload);
  Object.assign(c.usageState,{payload,payloadKey:'week:2026-10-05'});
  buttons[1].events.click();
  assert.equal(c.usageState.chart,'bar');assert.match(c.element('#usage-chart').innerHTML,/data-chart="bar"/);
  assert.equal(buttons[1]['aria-pressed'],'true');assert.equal(buttons[0]['aria-pressed'],'false');
  assert.equal(calls,0);assert.equal(JSON.stringify(payload),before);
  assert.match(saved.at(-1).url,/period=week/);assert.match(saved.at(-1).url,/date=2026-10-05/);assert.match(saved.at(-1).url,/chart=bar/);
  assert.deepEqual(saved.at(-1).state,{keep:true});
  buttons[0].events.click();assert.equal(c.usageState.chart,'line');assert.match(c.element('#usage-chart').innerHTML,/data-chart="line"/);
  c.usageChooseChart('invalid');assert.equal(c.usageState.chart,'line');assert.equal(calls,0);
});

test('query chart choice restores independently from period and date and invalid values fall back to line',()=>{
  for(const [query,expected] of [['bar','bar'],['line','line'],['pie','line'],['','line']]){
    const c=core({state:{local:false,editing:false,data:[]},location:{pathname:'/usage.html',search:`?period=month&date=2026-09-01&chart=${query}`}});
    c.renderUsage();assert.equal(c.usageState.chart,expected);assert.equal(c.usageState.period,'month');assert.equal(c.usageState.date,'2026-09-01');
  }
});

test('chart tooltip exposes exact periods on hover and keyboard focus and supports navigation',()=>{
  const c=core(),tooltip={hidden:true,innerHTML:'',style:{},offsetWidth:170,offsetHeight:48},selected=new Set();
  const groups=[0,1].map(index=>({dataset:{bucket:String(index)},events:{},classList:{remove(){selected.delete(index);},toggle(name,on){if(on) selected.add(index);else selected.delete(index);}},
    getBoundingClientRect:()=>({left:70+index*40,top:40,width:35}),addEventListener(name,callback){this.events[name]=callback;},focus(){c.document.activeElement=this;this.events.focus();},scrollIntoView(){this.scrolled=true;}}));
  let onScroll;
  const chart={clientWidth:360,getBoundingClientRect:()=>({left:0,top:0}),querySelector:selector=>selector==='.usage-chart-tooltip'?tooltip:{addEventListener(name,callback){onScroll=callback;}},querySelectorAll:()=>groups};
  c.usageBindChart(chart,data({buckets:[{label:'01:00',start:'2026-10-16T01:00:00+08:00',end:'2026-10-16T02:00:00+08:00',seconds:125.5},{label:'02:00',seconds:0}]}));
  groups[0].events.pointerenter();
  assert.equal(tooltip.hidden,false);assert.match(tooltip.innerHTML,/01:00–02:00/);assert.match(tooltip.innerHTML,/2 分钟 5.5 秒/);
  assert.deepEqual([...selected],[0]);
  groups[0].events.pointerleave();assert.equal(tooltip.hidden,true);
  groups[0].focus();assert.equal(tooltip.hidden,false);
  let prevented=false;groups[0].events.keydown({key:'ArrowRight',preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(c.document.activeElement,groups[1]);assert.equal(groups[1].scrolled,true);assert.match(tooltip.innerHTML,/0 秒/);
  groups[1].events.keydown({key:'Escape'});assert.equal(tooltip.hidden,true);
  groups[1].focus();onScroll();assert.equal(tooltip.hidden,false);assert.match(tooltip.innerHTML,/0 秒/);
  c.document.activeElement=null;groups[0].events.pointerenter();onScroll();assert.equal(tooltip.hidden,true);
});

test('ranking escapes executable names and paths and clamps progress to its visual range',()=>{
  const c=core();
  const html=c.usageRankingHTML([{id:'1',name:'<script>x</script>',path:'D:\\<app>\\x.exe',seconds:120}],60);
  assert.doesNotMatch(html,/<script>/); assert.match(html,/&lt;script&gt;/);
  assert.match(html,/width:100.000%/); assert.match(html,/D:\\&lt;app&gt;/);
});

test('ranking time labels and bars both get visibly different readable duration-based shades',()=>{
  const c=core();
  const values=[0,10,40,100].map(value=>c.usageProgressValues(value,200,100));
  assert.deepEqual(values.map(value=>value.width),['0.000%','15.400%','43.600%','100.000%']);
  const channels=color=>color.match(/\d+/g).map(Number);
  const lightness=color=>channels(color).reduce((total,channel)=>total+channel,0);
  for(const field of ['barColor','textColor']){
    assert.ok(values.every((value,index)=>!index || lightness(value[field])<lightness(values[index-1][field])));
    assert.equal(c.usageProgressValues(40,200,100)[field],c.usageProgressValues(40,500,100)[field]);
  }
  const shades=Array.from({length:100},(_,index)=>c.usageProgressValues(index+1,100,100).barColor);
  assert.equal(new Set(shades).size,100);
  const equalTime=c.usageRankingHTML([{name:'Short',seconds:10},{name:'Long',seconds:100},{name:'Same short time',seconds:10}],120);
  const barColors=[...equalTime.matchAll(/--usage-bar-color:(rgb\([^)]+\))/g)].map(match=>match[1]);
  const textColors=[...equalTime.matchAll(/--usage-time-color:(rgb\([^)]+\))/g)].map(match=>match[1]);
  assert.equal(barColors[0],barColors[2]);assert.notEqual(barColors[0],barColors[1]);
  assert.equal(textColors[0],textColors[2]);assert.notEqual(textColors[0],textColors[1]);
  const luminance=rgb=>channels(rgb).map(channel=>channel/255).map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4).reduce((total,value,index)=>total+value*[.2126,.7152,.0722][index],0);
  for(let value=0;value<=100;value++){
    const text=luminance(c.usageProgressValues(value,200,100).textColor);
    for(const paper of ['rgb(251,248,241)','rgb(245,240,228)']) assert.ok((luminance(paper)+.05)/(text+.05)>=4.5);
  }
  assert.equal(c.usageProgressValues(500,100,100).width,'100.000%');assert.equal(c.usageProgressValues(-10,100,100).width,'0.000%');
  const css=fs.readFileSync(path.join(__dirname,'../assets/usage.css'),'utf8');
  assert.match(css,/\.usage-progress span\{[^}]*background:var\(--usage-bar-color/);
  assert.match(css,/\.usage-app-duration\{[^}]*color:var\(--usage-time-color/);
  assert.doesNotMatch(css,/\.usage-progress span\{[^}]*linear-gradient/);
  assert.doesNotMatch(css,/first-child \.usage-progress/);
  assert.match(css,/@media\(prefers-reduced-motion:reduce\)[^}]*\.usage-progress span\{transition:none/);
});

test('the real skewed ranking keeps eight distinct ordered lengths and tones on a 124px track',()=>{
  const c=core(),seconds=[2469,2397,29,14,6,4,3,2],total=4924;
  const apps=seconds.map((value,index)=>({id:String(index),name:'App '+index,seconds:value}));
  const html=c.usageRankingHTML(apps,total);
  const widths=[...html.matchAll(/style="width:([\d.]+)%/g)].map(match=>Number(match[1]));
  const barColors=[...html.matchAll(/--usage-bar-color:(rgb\([^)]+\))/g)].map(match=>match[1]);
  const textColors=[...html.matchAll(/--usage-time-color:(rgb\([^)]+\))/g)].map(match=>match[1]);
  assert.equal(widths.length,8);assert.equal(widths[0],100);
  assert.ok(widths.every((width,index)=>!index || widths[index-1]>width));
  assert.ok(widths.at(-1)/100*124>7,'The two-second app still needs a visible mark on the desktop track');
  const brightness=color=>color.match(/\d+/g).map(Number).reduce((sum,value)=>sum+value,0);
  for(const colors of [barColors,textColors]){
    assert.equal(colors.length,8);assert.equal(new Set(colors).size,8);
    assert.ok(colors.every((color,index)=>!index || brightness(color)>brightness(colors[index-1])));
  }
  assert.equal(barColors[0],'rgb(111,22,14)');assert.equal(barColors.at(-1),'rgb(236,201,139)');
  assert.equal(textColors[0],'rgb(96,16,17)');assert.equal(textColors.at(-1),'rgb(130,100,50)');
  const unrelatedTotal=c.usageRankingHTML(apps,total*100);
  assert.deepEqual([...unrelatedTotal.matchAll(/style="width:([\d.]+)%/g)].map(match=>Number(match[1])),widths);
});

test('rank tone scales share colors for ties, ignore invalid times and stay independent of row order',()=>{
  const c=core(),seconds=[10,40,10,0,-5,'40',Infinity,NaN,undefined];
  const tones=c.usageToneScale(seconds.map(value=>({seconds:value})));
  assert.equal(tones.size,2);assert.equal(tones.get(10),0);assert.equal(tones.get(40),1);
  const distinct=[2469,2397,29,14,6,4,3,2];
  const first=c.usageToneScale(distinct.map(seconds=>({seconds})));
  const reordered=c.usageToneScale([3,2469,2,29,2397,4,14,6].map(seconds=>({seconds})));
  for(const seconds of distinct) assert.equal(first.get(seconds),reordered.get(seconds));
  assert.equal(c.usageToneScale([{seconds:14}]).get(14),1);
  assert.equal(c.usageToneScale([{seconds:14},{seconds:14}]).get(14),1);
  assert.equal(c.usageToneScale([{seconds:0},{seconds:-1},{seconds:NaN}]).size,0);
  const tied=c.usageRankingHTML([{name:'First',seconds:14},{name:'Second',seconds:14}],28);
  const colors=[...tied.matchAll(/--usage-bar-color:(rgb\([^)]+\))/g)].map(match=>match[1]);
  assert.deepEqual(colors,['rgb(111,22,14)','rgb(111,22,14)']);
  assert.equal((tied.match(/width:100.000%/g)||[]).length,2);
});

test('the gold-orange-terracotta scale stays continuous, spans distinct lightness and keeps readable text',()=>{
  const c=core(),at=tone=>c.usageProgressValues(1,100,100,tone);
  const expected=[
    [0,'rgb(236,201,139)','rgb(130,100,50)'],
    [.18,'rgb(222,166,96)','rgb(127,83,40)'],
    [.36,'rgb(207,131,53)','rgb(123,66,29)'],
    [.488,'rgb(188,109,45)','rgb(118,56,27)'],
    [1,'rgb(111,22,14)','rgb(96,16,17)']
  ];
  for(const [tone,bar,text] of expected){
    assert.equal(at(tone).barColor,bar);assert.equal(at(tone).textColor,text);
  }
  for(const field of ['barColor','textColor']){
    assert.equal(at(.36-.00001)[field],at(.36)[field]);
    assert.equal(at(.36+.00001)[field],at(.36)[field]);
  }
  const channels=rgb=>rgb.match(/\d+/g).map(Number);
  const luminance=rgb=>channels(rgb).map(channel=>channel/255)
    .map(value=>value<=.04045?value/12.92:((value+.055)/1.055)**2.4)
    .reduce((total,value,index)=>total+value*[.2126,.7152,.0722][index],0);
  assert.ok(luminance(at(0).barColor)-luminance(at(.36).barColor)>.2);
  assert.ok(luminance(at(.36).barColor)-luminance(at(1).barColor)>.2);
  for(const field of ['barColor','textColor']){
    let previous=Infinity;
    for(let index=0;index<=500;index++){
      const light=luminance(at(index/500)[field]);
      assert.ok(light<=previous+1e-12,`${field} must darken monotonically`);
      previous=light;
    }
  }
  for(let index=0;index<=500;index++){
    const text=luminance(at(index/500).textColor);
    for(const paper of ['rgb(251,248,241)','rgb(245,240,228)']){
      assert.ok((luminance(paper)+.05)/(text+.05)>=4.5,'Normal and hover time labels need AA contrast');
    }
  }
});

test('progress lengths ignore the total and reject zero, negative and nonnumeric values or maxima',()=>{
  const c=core();
  for(const value of [0,-1,NaN,Infinity,-Infinity,undefined,null,'2']){
    assert.equal(c.usageProgressValues(value,200,100).width,'0.000%');
  }
  for(const maximum of [0,-1,NaN,Infinity,-Infinity,undefined,null,'100']){
    assert.equal(c.usageProgressValues(2,200,maximum).width,'0.000%');
  }
  for(const total of [0,-1,NaN,Infinity,undefined,200,20000]){
    assert.equal(c.usageProgressValues(40,total,100).width,'43.600%');
  }
  assert.equal(c.usageProgressValues(0.001,1,100).width,'6.001%');
  assert.equal(c.usageProgressValues(100,1000,100).width,'100.000%');
  assert.equal(c.usageProgressValues(1000,1000,100).width,'100.000%');
});

test('the ranking explains visible minimum marks and retains its compact track on mobile',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../usage.html'),'utf8');
  const css=fs.readFileSync(path.join(__dirname,'../assets/usage.css'),'utf8');
  assert.match(html,/class="usage-ranking-note"[^>]*>短时长保留可见刻度，准确时长见右侧。/);
  assert.match(css,/\.usage-progress\{[^}]*height:8px/);
  assert.match(css,/@media\(max-width:760px\)[\s\S]*\.usage-progress\{[^}]*grid-column:3\s*\/\s*5[^}]*width:124px[^}]*max-width:100%/);
  assert.doesNotMatch(css,/\.usage-progress\{[^}]*display:none/);
});

test('collector status distinguishes idle, lock, another instance and an actual active sample',()=>{
  const c=core();
  assert.equal(c.usageTrackingInfo({tracking:true,state:'idle'}).tracking,false);
  assert.equal(c.usageTrackingInfo({tracking:true,state:'idle'}).label,'闲置已暂停');
  assert.equal(c.usageTrackingInfo({tracking:true,state:'locked'}).label,'锁屏已暂停');
  assert.equal(c.usageTrackingInfo({tracking:true,state:'screen-off'}).label,'熄屏已暂停');
  assert.equal(c.usageTrackingInfo({tracking:true,state:'screen-off'}).tracking,false);
  assert.equal(c.usageTrackingInfo({tracking:true,state:'screen-off'}).paused,true);
  assert.equal(c.usageTrackingInfo({tracking:false,state:'another-instance'}).label,'另一个 AppShelf 正在记录');
  assert.equal(c.usageTrackingInfo({tracking:true,state:'active'}).tracking,true);
  assert.equal(c.usageTrackingInfo({tracking:true,state:'active',error:'failed'}).label,'记录暂不可用');
  assert.match(c.usageTrackingInfo({tracking:true,state:'active',idleThreshold:null}).title,/阅读或观看时继续计时/);
  assert.match(c.usageTrackingInfo({tracking:true,state:'active',idleThreshold:60}).title,/连续 1 分钟 无操作后暂停/);
  c.usageRenderPayload(c.usageNormalize(data()));
  assert.match(c.element('#usage-since').textContent,/开始记录：\d{4} 年 \d+ 月 \d+ 日 \d{2}:\d{2}:\d{2}。/);
});

test('catalogue metadata uses the supplied ID rather than ambiguous matching names',()=>{
  const state={local:true,editing:false,data:[{id:'old',name:'Editor',version:'1.0'},{id:'new',name:'Editor',version:'2.0'}]};
  const c=core({state});
  const payload=c.usageNormalize(data({apps:[{id:'exe-hash',catalogueId:'new',name:'Editor',path:'D:\\new\\app.exe',seconds:60}]}));
  const html=c.usageRankingHTML(payload.apps,payload.totalSeconds);
  assert.match(html,/2.0 · D:/);assert.doesNotMatch(html,/1.0 ·/);
  const unmatched=c.usageRankingHTML([{id:'exe-other',name:'Editor',path:'E:\\other.exe',seconds:60}],60);
  assert.doesNotMatch(unmatched,/title="(?:1\.0|2\.0)/);
});

test('a late response from the previous period cannot replace the newly selected period',async()=>{
  const pending=[];
  const c=core({fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))});
  Object.assign(c.usageState,{period:'day',date:'2026-10-14'});
  const old=c.usageLoad();
  c.usageState.date='2026-10-15'; const current=c.usageLoad();
  assert.equal(pending[0].options.signal.aborted,true);
  pending[1].resolve(response(data({totalSeconds:120})));await current;
  pending[0].resolve(response(data({date:'2026-10-14',totalSeconds:900})));await old;
  assert.equal(c.usageState.payload.totalSeconds,120);
  assert.equal(c.usageState.payloadKey,'day:2026-10-15');
});

test('auto refresh skips hidden pages, editing sessions and an already pending request',async()=>{
  let calls=0;
  const state={local:true,editing:false,data:[]};
  const c=core({state,fetch:async()=>{calls++;return response(data());}});
  Object.assign(c.usageState,{period:'day',date:'2026-10-15'});
  c.document.hidden=true;await c.usageLoad({quiet:true});
  c.document.hidden=false;state.editing=true;await c.usageLoad({quiet:true});
  state.editing=false;c.usageState.loading=true;await c.usageLoad({quiet:true});
  assert.equal(calls,0);
});

test('quiet refresh keeps date editing, focus and loading presentation untouched and exposes a second-level update',async()=>{
  let finish;const c=core({fetch:()=>new Promise(resolve=>{finish=resolve;})});
  const previous=c.usageNormalize(data());
  Object.assign(c.usageState,{period:'day',date:'2026-10-15',payload:previous,payloadKey:'day:2026-10-15'});
  c.element('#usage-view').setAttribute('aria-busy','false');c.element('#usage-date').value='2026-10';
  c.element('#usage-updated').textContent='更新于 09:00:00';c.element('#usage-message-text').textContent='Previous error';
  c.document.activeElement=c.element('#usage-refresh');
  const pending=c.usageLoad({quiet:true});
  assert.equal(c.element('#usage-view')['aria-busy'],'false');assert.equal(c.element('#usage-refresh').disabled,false);
  assert.equal(c.element('#usage-date').value,'2026-10');assert.equal(c.element('#usage-updated').textContent,'更新于 09:00:00');
  assert.equal(c.element('#usage-message-text').textContent,'Previous error');
  finish(response(data({totalSeconds:121})));await pending;
  assert.equal(c.document.activeElement,c.element('#usage-refresh'));assert.equal(c.element('#usage-refresh').disabled,false);
  assert.equal(c.element('#usage-date').value,'2026-10');assert.equal(c.element('#usage-message').hidden,true);
  assert.equal(c.element('#usage-date').max,c.usageDateKey());
  assert.match(c.element('#usage-updated').textContent,/更新于 \d{2}:\d{2}:\d{2}$/);
});

test('quiet ranking updates preserve nodes and focus, and reorder by executable identity without scrolling',()=>{
  const c=core(),dom=rankingDOM(c),apps=[{id:'exe-0123456789abcdef',name:'First',seconds:119},{id:'exe-fedcba9876543210',name:'Second',seconds:90}];
  c.usageRenderRanking(data({apps,totalSeconds:209}));
  const first=dom.rows[0];first.focus();
  c.usageRenderRanking(data({apps:apps.map(app=>({...app,seconds:app.seconds+1})),totalSeconds:211}));
  assert.equal(dom.writes,1);assert.equal(dom.rows[0],first);assert.equal(c.document.activeElement,first);
  assert.equal(first.duration.textContent,'2 分钟');assert.equal(first.progress.style.width,'100.000%');
  assert.equal(first.progress.style['--usage-bar-color'],c.usageProgressValues(120,211,120).barColor);
  assert.equal(first.duration.style['--usage-time-color'],c.usageProgressValues(120,211,120).textColor);
  assert.notEqual(dom.rows[1].duration.style['--usage-time-color'],first.duration.style['--usage-time-color']);
  c.usageRenderRanking(data({apps:[{...apps[1],seconds:130},apps[0]],totalSeconds:249}));
  assert.equal(dom.writes,2);assert.equal(c.document.activeElement,dom.rows[1]);assert.equal(c.document.activeElement.dataset.usageId,apps[0].id);
  assert.equal(c.document.activeElement.focusOptions.preventScroll,true);
  const background=c.element('#usage-background-toggle');c.document.activeElement=background;
  c.usageRenderRanking(data({apps,totalSeconds:209}));assert.equal(c.document.activeElement,background);
});

test('quiet updates recompute the tone scale when a tie separates without replacing rows or losing focus',async()=>{
  const apps=[{id:'exe-0123456789abcdef',name:'First',seconds:30},
    {id:'exe-fedcba9876543210',name:'Second',seconds:30},
    {id:'exe-1234567890abcdef',name:'Third',seconds:10}];
  const changed=apps.map((app,index)=>({...app,seconds:index===1?20:app.seconds}));
  const c=core({fetch:async()=>response(data({apps:changed,totalSeconds:60}))}),dom=rankingDOM(c);
  const previous=c.usageNormalize(data({apps,totalSeconds:70}));
  Object.assign(c.usageState,{period:'day',date:'2026-10-15',payload:previous,payloadKey:'day:2026-10-15'});
  c.usageRenderPayload(previous);
  const focused=dom.rows[1],initialColor=focused.progress.style['--usage-bar-color'];
  assert.equal(initialColor,'rgb(111,22,14)');
  assert.equal(initialColor,dom.rows[0].progress.style['--usage-bar-color']);
  focused.focus();
  await c.usageLoad({quiet:true});
  assert.equal(dom.writes,1);assert.equal(dom.rows[1],focused);assert.equal(c.document.activeElement,focused);
  assert.equal(focused.duration.textContent,'20 秒');assert.equal(focused.progress.style.width,'68.667%');
  const tone=c.usageToneScale(changed).get(20),expected=c.usageProgressValues(20,60,30,tone);
  assert.equal(tone,.5);assert.equal(focused.progress.style['--usage-bar-color'],expected.barColor);
  assert.equal(focused.duration.style['--usage-time-color'],expected.textColor);
  assert.notEqual(focused.progress.style['--usage-bar-color'],initialColor);
  assert.notEqual(focused.progress.style['--usage-bar-color'],dom.rows[0].progress.style['--usage-bar-color']);
  assert.notEqual(focused.progress.style['--usage-bar-color'],dom.rows[2].progress.style['--usage-bar-color']);
});

test('an old quiet summary cannot undo a completed background setting change',async()=>{
  let finish;
  const enabled={enabled:true,running:true,startup:true,error:null},disabled={enabled:false,running:false,startup:false,error:null};
  const c=core({fetch:()=>new Promise(resolve=>{finish=resolve;}),apiPost:async()=>({ok:true,...disabled})});
  Object.assign(c.usageState,{period:'day',date:'2026-10-15',payload:c.usageNormalize(data()),payloadKey:'day:2026-10-15',background:enabled});
  const pending=c.usageLoad({quiet:true});await c.usageSetBackground(false);
  finish(response(data({status:{tracking:true,state:'active',background:enabled}})));await pending;
  assert.equal(c.usageState.background.enabled,false);assert.equal(c.element('#usage-background-toggle').checked,false);
});

test('chart refresh retains hover tooltip, keyboard focus and horizontal position without reviving an escaped tooltip',()=>{
  const c=core(),chart=c.element('#usage-chart');let groups=[],viewport,tooltip,html='';
  Object.assign(chart,{clientWidth:380,getBoundingClientRect:()=>({left:0,top:0}),contains:element=>groups.includes(element),querySelectorAll:()=>groups,
    querySelector:selector=>selector==='.usage-chart-viewport'?viewport:selector==='.usage-chart-tooltip'?tooltip:selector==='.usage-bar-group.is-selected'?groups.find(group=>group.selected):groups.find(group=>selector===`[data-bucket="${group.dataset.bucket}"]`)});
  Object.defineProperty(chart,'innerHTML',{get:()=>html,set:value=>{
    html=value;viewport={scrollLeft:0,addEventListener(){}};tooltip={hidden:true,innerHTML:'',style:{},offsetWidth:170,offsetHeight:48};
    groups=[...value.matchAll(/data-bucket="(\d+)"/g)].map(match=>{
      const group={dataset:{bucket:match[1]},events:{},selected:false,getBoundingClientRect:()=>({left:70,top:40,width:35}),
        addEventListener(name,callback){this.events[name]=callback;},focus(options){this.focusOptions=options;c.document.activeElement=this;this.events.focus();},scrollIntoView(){}};
      group.classList={remove(){group.selected=false;},toggle(name,on){group.selected=on;}};return group;
    });
  }});
  const payload=data({buckets:[{label:'09:00',seconds:119},{label:'10:00',seconds:1}]});
  c.usageRenderChart(payload);viewport.scrollLeft=170;groups[0].events.pointerenter();
  c.usageRenderChart({...payload,buckets:[{label:'09:00',seconds:120},{label:'10:00',seconds:1}]});
  assert.equal(viewport.scrollLeft,170);assert.equal(tooltip.hidden,false);assert.match(tooltip.innerHTML,/2 分钟/);
  groups[1].focus();c.usageRenderChart(payload);
  assert.equal(c.document.activeElement,groups[1]);assert.equal(c.document.activeElement.focusOptions.preventScroll,true);assert.equal(tooltip.hidden,false);
  groups[1].events.keydown({key:'Escape'});assert.equal(tooltip.hidden,true);
  c.usageRenderChart(payload);assert.equal(c.document.activeElement,groups[1]);assert.equal(tooltip.hidden,true);
});

test('an unsuccessful refresh preserves the last good reading and presents a retry',async()=>{
  const c=core({fetch:async()=>response({error:'暂时不可用'},503)});
  const previous=c.usageNormalize(data());
  Object.assign(c.usageState,{period:'day',date:'2026-10-15',payload:previous,payloadKey:'day:2026-10-15'});
  await c.usageLoad();
  assert.equal(c.usageState.payload.totalSeconds,120);
  assert.match(c.element('#usage-message-text').textContent,/保留上次读取/);
  assert.equal(c.element('#usage-retry').hidden,false);
  assert.equal(c.usageState.loading,false);
});

test('static mode shows an explanation without requesting or simulating usage',async()=>{
  let calls=0;
  const c=core({state:{local:false,editing:false,data:[]},fetch:async()=>{calls++;return response(data());}});
  c.usageRenderUnavailable(true);await c.usageLoad();
  assert.equal(calls,0);assert.equal(c.element('#usage-total').textContent,'—');
  assert.match(c.element('#usage-chart').innerHTML,/静态预览不会记录电脑活动/);
  assert.equal(c.usageState.payload,null);
});

test('bfcache return restarts one refresh timer and reactivates chart observation without rebinding',async()=>{
  let calls=0,nextTimer=0,observed=0,disconnected=0;
  const timers=new Map();
  const c=core({
    fetch:async url=>{if(url==='/api/usage/background') return response({enabled:true,running:true,startup:true,error:null});calls++;const params=new URLSearchParams(url.split('?')[1]);return response(data({period:params.get('period'),date:params.get('date')}));},
    setInterval:(callback,delay)=>{assert.equal(delay,5000);timers.set(++nextTimer,callback);return nextTimer;},
    clearInterval:id=>timers.delete(id),
    ResizeObserver:class{observe(){observed++;}disconnect(){disconnected++;}}
  });
  c.renderUsage();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(c.element('#usage-updated')['aria-live'],'off');
  const initialCalls=calls,initialTimer=c.usageState.timer;
  await c.events.pageshow({persisted:false});
  assert.equal(calls,initialCalls);assert.equal(c.usageState.timer,initialTimer);
  c.events.pagehide();
  assert.equal(timers.size,0);assert.equal(disconnected,1);
  c.element('#usage-quote').textContent='stale';
  await c.events.pageshow({persisted:true});
  assert.equal(calls,initialCalls+1);assert.equal(timers.size,1);assert.notEqual(c.usageState.timer,initialTimer);
  assert.equal(observed,2);assert.equal(c.element('#usage-quote').textContent,c.usageLaunchQuote());
  await c.events.pageshow({persisted:true});
  assert.equal(timers.size,1);
  const beforeTick=calls;await [...timers.values()][0]();assert.equal(calls,beforeTick+1);
});

test('each ranked application and the most-used summary receive the recorded executable ID',()=>{
  const calls=[];
  const c=core({logoHTML:app=>{calls.push(app);return '<img class="logo-img">';}});
  c.context.state.data=[{id:'catalogue',name:'Actual Product',site:'example.com'}];
  const apps=[{id:'exe-0123456789abcdef',catalogueId:'catalogue',name:'Runtime',seconds:90},{id:'exe-fedcba9876543210',name:'Other',seconds:30}];
  c.usageRenderPayload(c.usageNormalize(data({apps})));
  assert.equal(calls.length,3);
  assert.equal(calls[0].usageId,apps[0].id);assert.equal(calls[0].name,'Actual Product');
  assert.equal(calls[2].usageId,apps[1].id);
  assert.equal(c.element('#usage-top-logo').hidden,false);
  assert.equal((c.element('#usage-app-list').innerHTML.match(/class="logo"/g)||[]).length,2);
  c.usageRenderPayload(c.usageNormalize(data({apps:[],totalSeconds:0})));
  assert.equal(c.element('#usage-top-logo').hidden,true);
});

test('both known and unlisted usage rows have keyboard-accessible detail links',()=>{
  const c=core();
  const html=c.usageRankingHTML([
    {id:'exe-0123456789abcdef',catalogueId:'known',name:'Known',seconds:60},
    {id:'exe-fedcba9876543210',catalogueId:null,name:'Unlisted',seconds:30}
  ],90);
  assert.equal((html.match(/<a class="usage-app-row detail-link"/g)||[]).length,2);
  assert.match(html,/data-detail-id="known" data-usage-id="exe-0123456789abcdef"/);
  assert.match(html,/href="detail.html\?usageId=exe-fedcba9876543210"/);
});

test('background settings reflect actual partial failures and rejected changes restore the last state',async()=>{
  const initial={enabled:true,running:false,startup:false,error:'登录自启设置失败'};
  let submitted;
  const c=core({fetch:async()=>response(initial),apiPost:async(url,body)=>{submitted={url,body};throw new Error('服务不可用');}});
  await c.usageLoadBackground();
  assert.equal(c.element('#usage-background-toggle').checked,true);
  assert.match(c.element('#usage-background-status').textContent,/未完全生效.*登录自启设置失败/);
  await c.usageSetBackground(false);
  assert.equal(submitted.url,'/api/usage/background');assert.deepEqual(plain(submitted.body),{enabled:false});
  assert.equal(c.element('#usage-background-toggle').checked,true);assert.equal(c.usageState.background.enabled,true);
  assert.match(c.element('#usage-background-status').textContent,/更改失败/);
  assert.equal(c.element('#usage-background-toggle').disabled,false);
  c.context.apiPost=async()=>({ok:true,enabled:false,running:false,startup:false,error:null});
  await c.usageSetBackground(false);
  assert.equal(c.element('#usage-background-toggle').checked,false);
  assert.match(c.element('#usage-background-status').textContent,/后台记录和登录自启已关闭/);
});

test('unavailable background settings leave an unknown switch disabled with a retry',async()=>{
  const c=core({fetch:async()=>response({error:'无法读取'},503)});
  await c.usageLoadBackground();
  assert.equal(c.element('#usage-background-toggle').disabled,true);
  assert.equal(c.element('#usage-background-retry').hidden,false);
  assert.match(c.element('#usage-background-status').textContent,/无法读取后台设置/);
});

test('returning to a historical period restores scroll after rows render and only once',async()=>{
  const restored=[];
  const c=core({location:{pathname:'/usage.html',search:'?period=week&date=2026-10-05&chart=bar&restore=1'},
    fetch:async url=>url==='/api/usage/background' ? response({enabled:true,running:true,startup:true,error:null}) : response(data({period:'week',date:'2026-10-05'})),
    restoreViewPosition:saved=>restored.push({saved,rows:c.element('#usage-app-list').innerHTML})});
  c.renderUsage();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(c.usageState.period,'week');assert.equal(c.usageState.date,'2026-10-05');
  assert.equal(c.usageState.chart,'bar');assert.match(c.element('#usage-chart').innerHTML,/data-chart="bar"/);
  assert.equal(restored.length,1);assert.match(restored[0].rows,/Editor/);
  await c.usageLoad({quiet:true});assert.equal(restored.length,1);assert.equal(c.usageState.chart,'bar');
});

test('an initial return failure keeps scroll pending until a successful retry',async()=>{
  let restored=0;
  const c=core({fetch:async()=>response({error:'offline'},503),restoreViewPosition:()=>{restored++;}});
  Object.assign(c.usageState,{period:'day',date:'2026-10-15',restorePending:true});
  await c.usageLoad();assert.equal(restored,0);assert.equal(c.usageState.restorePending,true);
  c.context.fetch=async()=>response(data());await c.usageLoad();assert.equal(restored,1);
});

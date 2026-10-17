const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../assets/home.js'),'utf8').replace(/homeBoot\(\);\s*$/,'');
const escape=value=>String(value??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const response=(payload,status=200)=>({ok:status<400,status,json:async()=>payload});
const poem={id:'poem-test',text:'明月松间照，清泉石上流。',author:'王维',title:'山居秋暝',dynasty:'唐'};
function core(overrides={}){
  const elements=new Map(),events={};
  const element=selector=>{
    if(!elements.has(selector)) elements.set(selector,{textContent:'',innerHTML:'',hidden:false,disabled:false,title:'',
      classList:{add(){},remove(){},toggle(){}},setAttribute(){},addEventListener(name,callback){this[name]=callback;}});
    return elements.get(selector);
  };
  const context=vm.createContext({Date,URLSearchParams,AbortController,Promise,console,
    document:{hidden:false,addEventListener(name,callback){events[name]=callback;}},
    window:{addEventListener(name,callback){events[name]=callback;}},
    setInterval:()=>1,clearInterval(){},$:element,esc:escape,state:{data:[],local:true,editing:false},
    logoHTML:app=>`<span class="logo-test">${escape(app.name)}</span>`,setupLogos(){},setupGlobalSearch(){},bindSearch(){},
    usageDetailParams:app=>app.catalogueId ? {id:app.catalogueId,...(/^exe-[0-9a-f]{16}$/.test(app.id)?{usageId:app.id}:{})} : /^exe-[0-9a-f]{16}$/.test(app.id)?{usageId:app.id}:null,
    pageURL:(page,params)=>page+'?'+new URLSearchParams(params),
    loadApps:async()=>{},fetch:async()=>response({},404),...overrides});
  context.fetch=(url,options)=>url==='/api/session' || url==='data/poems.json' ? (overrides.poemFetch || (async()=>response({ok:true,poem})))(url,options) : (overrides.fetch || (async()=>response({},404)))(url,options);
  vm.runInContext(source+'\nthis.home={homeState,homeDateKey,homeGreeting,homeDuration,homeCatalogueSummary,homeNormalizePoem,homeRenderPoem,homeLoadPoem,homeNormalizeUsage,homeActivityHTML,homeUsageNote,homeRenderActivity,homeRenderUsage,homeLoadCatalogue,homeLoadUsage,homeRefresh,homeBoot};',context);
  return {...context.home,context,element,elements,events};
}
const data=(overrides={})=>({period:'day',date:new Date().toLocaleDateString('sv-SE'),totalSeconds:120,
  apps:[{id:'exe-editor',catalogueId:'editor',name:'Editor',path:'D:\\Editor\\editor.exe',seconds:120}],
  status:{tracking:true,state:'active'},...overrides});
const plain=value=>JSON.parse(JSON.stringify(value));
function activityDOM(c){
  const list=c.element('#home-activity-list');let rows=[],html='',writes=0;
  Object.defineProperty(list,'innerHTML',{get:()=>html,set:value=>{
    html=value;writes++;
    rows=[...value.matchAll(/<a class="home-activity-app detail-link"([^>]*)>([\s\S]*?)<\/a>/g)].map(match=>{
      const dataset={},duration={textContent:match[2].match(/class="home-app-duration">([^<]*)/)?.[1]||''};
      for(const [attribute,key] of [['usage-id','usageId'],['detail-id','detailId']]){const value=match[1].match(new RegExp('data-'+attribute+'="([^"]+)"'))?.[1];if(value) dataset[key]=value;}
      return {dataset,duration,querySelector:()=>duration,focus(options){c.context.document.activeElement=this;this.focusOptions=options;}};
    });
  }});
  list.contains=element=>rows.includes(element);list.querySelectorAll=()=>rows;
  return {list,get rows(){return rows;},get writes(){return writes;}};
}

test('home provides compact independent entries and shared search scripts',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../home.html'),'utf8');
  assert.match(html,/<body data-page="home">/);
  assert.match(html,/class="home-entry" href="index.html"/);
  assert.match(html,/class="home-entry" href="usage.html"/);
  assert.match(html,/assets\/style.css/);assert.match(html,/assets\/home.css/);
  assert.ok(html.indexOf('assets/app.js')<html.indexOf('assets/home.js'));
  assert.doesNotMatch(source,/apiPost|\/api\/scan|method:\s*["']POST|localStorage\.setItem/);
});

test('greeting and durations reflect local clock and actual seconds',()=>{
  const c=core();
  assert.equal(c.homeGreeting(new Date(2026,9,15,9)),'早上好。');
  assert.equal(c.homeGreeting(new Date(2026,9,15,16)),'下午好。');
  assert.equal(c.homeGreeting(new Date(2026,9,15,22)),'晚上好。');
  assert.equal(c.homeDateKey(new Date(2026,0,2,0,1)),'2026-01-02');
  for(const [seconds,label] of [[0,'0 秒'],[0.8,'不足 1 秒'],[29.9,'29 秒'],[59.9,'59 秒'],[60,'1 分钟'],[119.9,'1 分钟 59 秒'],[3599,'59 分钟 59 秒'],[3600,'1 小时'],[3661,'1 小时 1 分钟 1 秒']]) assert.equal(c.homeDuration(seconds),label);
  c.homeRenderUsage(c.homeNormalizeUsage(data({totalSeconds:119.9,apps:[{id:'exe-editor',name:'Editor',seconds:119.9}]})));
  assert.equal(c.element('#home-usage-total').textContent,'1 分钟 59 秒');
  assert.match(c.element('#home-activity-list').innerHTML,/1 分钟 59 秒/);
});

test('poetry has a quiet attributed place between the greeting and navigation cards',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../home.html'),'utf8'),css=fs.readFileSync(path.join(__dirname,'../assets/home.css'),'utf8');
  assert.ok(html.indexOf('class="home-intro"')<html.indexOf('class="home-poem"'));
  assert.ok(html.indexOf('class="home-poem"')<html.indexOf('class="home-entries"'));
  assert.match(html,/<blockquote><p id="home-poem-text">/);assert.match(html,/<figcaption>/);assert.match(html,/<cite id="home-poem-title">/);
  assert.match(css,/\.home-poem\{[^}]*grid-template-columns:minmax\(0,1fr\) auto/);
  assert.match(css,/@media\(max-width:540px\)[\s\S]*\.home-poem\{grid-template-columns:minmax\(0,1fr\)/);
});

test('the selected launch poem stays stable during overview and usage refreshes',async()=>{
  let reads=0;
  const c=core({poemFetch:async()=>{reads++;return response({ok:true,poem});},fetch:async()=>response(data())});
  await c.homeLoadPoem();await c.homeRefresh();await c.homeLoadUsage({quiet:true});await c.homeLoadPoem();
  assert.equal(reads,1);assert.equal(c.element('#home-poem-text').textContent,poem.text);
  assert.equal(c.element('#home-poem-author').textContent,'唐 · 王维');assert.equal(c.element('#home-poem-title').textContent,'《山居秋暝》');
  assert.deepEqual(plain(c.homeState.poem),poem);
});

test('poetry loads independently while catalogue and usage requests are still pending',async()=>{
  const c=core({loadApps:()=>new Promise(()=>{}),fetch:()=>new Promise(()=>{})});
  c.homeLoadCatalogue();c.homeLoadUsage();await c.homeLoadPoem();
  assert.equal(c.element('#home-poem-text').textContent,poem.text);
  assert.equal(c.homeState.catalogueLoading,true);assert.equal(c.homeState.usageLoading,true);
});

test('static preview selects from the real thousand-line anthology and keeps a session selection',async()=>{
  const pool=JSON.parse(fs.readFileSync(path.join(__dirname,'../data/poems.json'),'utf8')),saved=new Map([['appshelf-home-poem',pool[12].id]]),requests=[];
  const c=core({poemFetch:async url=>{requests.push(url);return url==='/api/session'?response({},404):response(pool);},sessionStorage:{getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)}});
  await c.homeLoadPoem();assert.equal(c.homeState.poem.id,pool[12].id);assert.deepEqual(requests,['/api/session','data/poems.json']);
  assert.equal(c.element('#home-poem-author').textContent,pool[12].dynasty+' · '+pool[12].author);
});

test('malformed poetry and failed requests preserve the existing verse without fabricating attribution',async()=>{
  const c=core({poemFetch:async()=>{throw new Error('offline');}});
  c.element('#home-poem-text').textContent='已有默认诗句';
  await c.homeLoadPoem();assert.equal(c.element('#home-poem-text').textContent,'已有默认诗句');
  assert.equal(c.homeRenderPoem({...poem,author:''}),false);
  assert.equal(c.homeRenderPoem({...poem,text:'x'.repeat(81)}),false);
  const hostile={...poem,text:'<script>hello</script>',title:'<img src=x>'};
  assert.equal(c.homeRenderPoem(hostile),true);
  assert.equal(c.element('#home-poem-text').textContent,hostile.text);assert.equal(c.element('#home-poem-text').innerHTML,'');
});

test('aborted late poetry cannot overwrite a newer selection',async()=>{
  let finish;
  const c=core({poemFetch:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=c.homeLoadPoem();
  c.homeState.poemController.abort();c.homeRenderPoem({...poem,id:'new',text:'长风破浪会有时，直挂云帆济沧海。'});
  finish(response({ok:true,poem}));await pending;
  assert.equal(c.homeState.poem.id,'new');
});

test('overview counts actual listed records and occupied categories only',()=>{
  const c=core();
  const result=c.homeCatalogueSummary([{id:'a',category:'dev-tool'},{id:'b',category:'dev-tool'},
    {id:'a',category:'duplicate'},{id:'c',category:'tool-sys',status:'new'},
    {id:'missing',category:'net-web',status:'missing'},{id:'old',category:'old',status:'removed'},
    {id:'duplicate',category:'game-plat',duplicateOf:'a'},
    {id:'absent',category:'off-doc',availability:'absent'}]);
  assert.deepEqual(plain(result),{apps:3,categories:2});
  assert.deepEqual(plain(c.homeCatalogueSummary([])),{apps:0,categories:0});
});

test('static explanatory footers are removed while editor footer controls remain in the shared editor',()=>{
  for(const name of ['home.html','index.html','category.html']){
    const html=fs.readFileSync(path.join(__dirname,'..',name),'utf8');
    assert.doesNotMatch(html,/<footer\b/);
  }
  const shared=fs.readFileSync(path.join(__dirname,'../assets/app.js'),'utf8');
  assert.match(shared,/<footer class="modal-foot">/);
  assert.match(shared,/id="ed-save"/);
});

test('home activity keeps the executable path available as a title without making it row content',()=>{
  const c=core();
  const exePath='D:\\Very long installation folder\\Application\\app.exe';
  const html=c.homeActivityHTML([{id:'exe-0123456789abcdef',name:'Actual App',path:exePath,seconds:120}]);
  assert.ok(html.includes('title="'+exePath+'"'));
  assert.equal(html.includes('>'+exePath+'<'),false);
  assert.match(html,/Actual App/);assert.match(html,/2 分钟/);
});

test('activity uses real ordering, shows at most four and safely links known records',()=>{
  const c=core();c.context.state.data=[{id:'known&<>',name:'known'}];
  const payload=c.homeNormalizeUsage(data({apps:Array.from({length:6},(_,i)=>({
    id:'exe-'+i,catalogueId:i===5 ? 'known&<>' : null,name:i===5 ? '<script>alert(1)</script>' : 'App '+i,
    path:'D:\\<folder>\\app.exe',seconds:i+1}))}));
  const html=c.homeActivityHTML(payload.apps);
  assert.equal((html.match(/<li>/g)||[]).length,4);
  assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
  assert.match(html,/detail.html\?id=known%26%3C%3E/);assert.match(html,/D:\\&lt;folder&gt;/);
  assert.ok(html.indexOf('App 4')<html.indexOf('App 3'));
  assert.doesNotMatch(html,/App 0|App 1/);
  assert.equal((html.match(/<a class="[^"]*\bhome-activity-app\b[^"]*"/g)||[]).length,1);
});

test('malformed or negative usage readings never become displayed totals',()=>{
  const c=core();
  assert.throws(()=>c.homeNormalizeUsage(data({totalSeconds:-1})),/格式/);
  assert.throws(()=>c.homeNormalizeUsage(data({period:'week'})),/格式/);
  assert.throws(()=>c.homeNormalizeUsage(data({apps:[{name:'X',seconds:Infinity}]})),/格式/);
  assert.equal(c.homeNormalizeUsage(data({apps:[{name:'Zero',seconds:0}]})).apps.length,0);
});

test('empty successful records are zero with an honest empty state',async()=>{
  const c=core({fetch:async()=>response(data({totalSeconds:0,apps:[]}))});
  await c.homeLoadUsage();
  assert.equal(c.element('#home-usage-total').textContent,'0 秒');
  assert.match(c.element('#home-activity-list').innerHTML,/今天还没有使用记录/);
});

test('static or failed usage stays unknown rather than fabricating a zero',async()=>{
  const c=core({fetch:async()=>response({},404)});
  await c.homeLoadUsage();
  assert.equal(c.element('#home-usage-total').textContent,'—');
  assert.match(c.element('#home-activity-list').innerHTML,/在本机运行后查看/);
  c.context.fetch=async()=>{throw new Error('offline');};
  await c.homeLoadUsage();
  assert.equal(c.element('#home-usage-total').textContent,'—');
  assert.match(c.element('#home-activity-list').innerHTML,/暂时无法读取/);
});

test('usage completes while catalogue is unavailable or still pending',async()=>{
  let release;
  const c=core({loadApps:()=>new Promise(resolve=>{release=resolve;}),fetch:async()=>response(data())});
  const catalogue=c.homeLoadCatalogue();
  await c.homeLoadUsage();
  assert.equal(c.element('#home-usage-total').textContent,'2 分钟');
  assert.equal(c.homeState.catalogueLoading,true);
  c.context.state.data=[{id:'editor',category:'dev-ide'}];release();await catalogue;
  assert.equal(c.element('#home-app-count').textContent,'1');
  assert.match(c.element('#home-activity-list').innerHTML,/detail.html\?id=editor/);
});

test('catalogue failure preserves independent usage and labels retained metrics',async()=>{
  const c=core({fetch:async()=>response(data())});
  c.context.state.data=[{id:'one',category:'tool-sys'}];
  await c.homeRefresh();
  c.context.loadApps=async()=>{throw new Error('catalogue unavailable');};
  await c.homeRefresh();
  assert.equal(c.element('#home-app-count').textContent,'1');
  assert.match(c.element('#home-catalogue-status').textContent,/上次读取/);
  assert.equal(c.element('#home-usage-total').textContent,'2 分钟');
});

test('usage refresh error remains visible after catalogue subsequently refreshes',async()=>{
  const c=core({fetch:async()=>response(data())});
  await c.homeLoadUsage();
  c.context.fetch=async()=>response({},503);await c.homeLoadUsage();
  await c.homeLoadCatalogue();
  assert.match(c.element('#home-usage-status').textContent,/保留上次读取/);
  assert.equal(c.element('#home-usage-total').textContent,'2 分钟');
});

test('out-of-order refreshes cannot replace a newer usage response',async()=>{
  const pending=[];
  const c=core({fetch:()=>new Promise(resolve=>pending.push(resolve))});
  const first=c.homeLoadUsage(),second=c.homeLoadUsage();
  pending[1](response(data({totalSeconds:240})));await second;
  pending[0](response(data({totalSeconds:120})));await first;
  assert.equal(c.element('#home-usage-total').textContent,'4 分钟');
});

test('quiet refresh skips hidden pages and boot binds shared search once',async()=>{
  let calls=0,searches=0,bound=0;
  const c=core({fetch:async()=>{calls++;return response(data());},setupGlobalSearch:()=>{searches++;},bindSearch:()=>{bound++;}});
  c.context.document.hidden=true;await c.homeLoadUsage({quiet:true});assert.equal(calls,0);
  c.context.document.hidden=false;await c.homeBoot();c.homeBoot();
  assert.equal(searches,1);assert.equal(bound,1);assert.equal(calls,1);
  c.events.pagehide();
});

test('home reports actual recorder states and the configured foreground timing policy',()=>{
  const c=core();
  assert.match(c.homeUsageNote({tracking:true,state:'active',idleThreshold:null}),/阅读或观看时也会计时/);
  assert.match(c.homeUsageNote({tracking:true,state:'active',idleThreshold:60}),/连续 1 分钟 无操作后暂停/);
  assert.match(c.homeUsageNote({tracking:true,state:'screen-off'}),/熄屏期间暂停/);
  assert.match(c.homeUsageNote({tracking:true,state:'unavailable'}),/等待识别前台应用/);
  assert.match(c.homeUsageNote({tracking:true,state:'sampling-gap'}),/正在恢复记录/);
  assert.doesNotMatch(c.homeUsageNote({tracking:true,state:'stopped'}),/正在记录/);
  assert.match(c.homeUsageNote({tracking:true,state:'active',error:'failed'}),/采集暂不可用/);
});

test('home updates seconds in place and keeps the focused executable when ranking changes',()=>{
  const c=core(),dom=activityDOM(c),apps=[{id:'exe-0123456789abcdef',name:'First',seconds:119},{id:'exe-fedcba9876543210',name:'Second',seconds:90}];
  c.homeRenderActivity(data({apps}));const first=dom.rows[0];first.focus();
  c.homeRenderActivity(data({apps:apps.map(app=>({...app,seconds:app.seconds+1}))}));
  assert.equal(dom.writes,1);assert.equal(dom.rows[0],first);assert.equal(c.context.document.activeElement,first);
  assert.equal(first.duration.textContent,'2 分钟');
  c.homeRenderActivity(data({apps:[{...apps[1],seconds:130},apps[0]]}));
  assert.equal(dom.writes,2);assert.equal(c.context.document.activeElement,dom.rows[1]);
  assert.equal(c.context.document.activeElement.dataset.usageId,apps[0].id);assert.equal(c.context.document.activeElement.focusOptions.preventScroll,true);
  const refresh=c.element('#home-refresh');c.context.document.activeElement=refresh;
  c.homeRenderActivity(data({apps}));assert.equal(c.context.document.activeElement,refresh);
});

test('a quiet response received after hiding the page leaves the previous reading intact',async()=>{
  let finish;const c=core({fetch:()=>new Promise(resolve=>{finish=resolve;})});
  c.homeState.usage=c.homeNormalizeUsage(data({totalSeconds:119}));c.homeRenderUsage(c.homeState.usage);
  c.homeState.catalogueLoading=true;c.context.document.activeElement=c.element('#home-refresh');
  const pending=c.homeLoadUsage({quiet:true});assert.equal(c.element('#home-refresh').disabled,false);c.context.document.hidden=true;
  finish(response(data({totalSeconds:200})));await pending;
  assert.equal(c.homeState.usage.totalSeconds,119);assert.equal(c.element('#home-usage-total').textContent,'1 分钟 59 秒');
  assert.equal(c.homeState.usageLoading,false);
});

test('bfcache return refreshes both sources once, restarts its timer and restores saved scroll afterward',async()=>{
  let requests=0,loads=0,searches=0,bindings=0,nextTimer=0;
  const timers=new Map(),restores=[];
  const c=core({
    loadApps:async()=>{loads++;c.context.state.data=Array.from({length:loads},(_,i)=>({id:'app-'+i,category:'tool-sys'}));},
    fetch:async()=>{requests++;return response(data());},
    setupGlobalSearch:()=>{searches++;},bindSearch:()=>{bindings++;},
    setInterval:(callback,delay)=>{assert.equal(delay,5000);timers.set(++nextTimer,callback);return nextTimer;},
    clearInterval:id=>timers.delete(id),
    history:{state:{appshelfView:{view:'home.html',top:900,navigation:'original-return'}}},
    restoreViewPosition:saved=>{restores.push({saved,apps:c.element('#home-app-count').textContent});}
  });
  await c.homeBoot();
  const initialTimer=c.homeState.timer;
  await c.events.pageshow({persisted:false});assert.equal(loads,1);assert.equal(requests,1);
  c.context.window.scrollY=310;c.events.pagehide();assert.equal(timers.size,0);
  c.context.window.scrollY=0;
  await c.events.pageshow({persisted:true});
  assert.equal(loads,2);assert.equal(requests,2);assert.equal(searches,1);assert.equal(bindings,1);
  assert.equal(timers.size,1);assert.notEqual(c.homeState.timer,initialTimer);
  const latest=restores.at(-1);
  assert.equal(latest.apps,'2');assert.equal(latest.saved.top,310);assert.equal(latest.saved.view,'home.html');
  assert.equal(latest.saved.navigation,'original-return');
  await c.events.pageshow({persisted:true});assert.equal(timers.size,1);
});

test('home activity links unlisted executables as well as catalogue records',()=>{
  const c=core();c.context.state.data=[{id:'known',name:'Known'}];
  const html=c.homeActivityHTML([
    {id:'exe-0123456789abcdef',catalogueId:'known',name:'Known',seconds:60},
    {id:'exe-fedcba9876543210',catalogueId:null,name:'Unknown',seconds:30}
  ]);
  assert.equal((html.match(/<a class="home-activity-app detail-link"/g)||[]).length,2);
  assert.match(html,/id=known&amp;usageId=exe-0123456789abcdef/);
  assert.match(html,/href="detail.html\?usageId=exe-fedcba9876543210"/);
});

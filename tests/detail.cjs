const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../assets/detail.js'),'utf8').replace(/bootDetail\(\);\s*$/,'');
const exe='exe-0123456789abcdef';
const esc=value=>String(value??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const recorded={id:exe,usageId:exe,catalogueId:null,recordedOnly:true,name:'Unknown App',path:'D:\\App\\real.exe',paths:[{path:'D:\\App\\real.exe',kind:'file',note:''}],category:null,size:null};
const response=(app,status=200)=>({ok:status<400,json:async()=>status<400?{app}:{error:'读取失败'}});
function core(options={}){
  const elements=new Map(),logos=[];
  const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',addEventListener(){}});return elements.get(id);};
  const state={local:true,data:[],...options.state};
  const context=vm.createContext({URLSearchParams,console,document:{title:''},location:{search:'?usageId='+exe},state,
    pageRender(){},$:element,$$:()=>[],esc,byId:id=>state.data.find(app=>app.id===id),isListed:a=>a.status!=='removed',
    renderBackLink(){},backTarget:()=>({href:'usage.html?period=week&date=2026-10-12',label:'返回使用时间'}),
    catOf:key=>key==='tool-sys'?{k:key,label:'实用工具'}:null,groupOf:()=>({k:'tool',label:'工具'}),pageURL:(page,params)=>page+'?'+new URLSearchParams(params),
    pathsOf:app=>app.paths||[],pathLabel:p=>p.path||p.note,isDiskPath:p=>/^\w:[\\/]/.test(p),fmtSize:()=>'',
    srcHTML:()=>'<span>INSTALL_BADGE</span>',statusHTML:()=>'',statusActionsHTML:()=>'<span>STATUS_ACTIONS</span>',relatedHTML:()=>'<span>RELATED_ITEMS</span>',
    logoHTML:app=>{logos.push(app);return '<svg></svg>';},setupLogos(){},bindDetailLinks(){},bindStatusActions(){},openEditor(){},
    setupGlobalSearch(){},prepareDetailReturn(){},normalizeDrive:value=>value,loadApps:async()=>{},bindSearch(){},setupSyncControls(){},checkStatus:async()=>{},setInterval:()=>1,
    fetch:async()=>response(recorded),...options});
  vm.runInContext(source+'\nthis.detail={detailState,loadRecordedDetail,render,bootDetail};',context);
  return {...context.detail,context,state,element,logos};
}
test('an unknown executable has real paths and a read-only detail without invented installation fields',async()=>{
  const c=core();await c.loadRecordedDetail();
  const html=c.element('#catalog').innerHTML;
  assert.match(html,/Unknown App/);assert.match(html,/D:\\App\\real.exe/);assert.match(html,/仅查看记录/);
  assert.doesNotMatch(html,/id="d-edit"|INSTALL_BADGE|STATUS_ACTIONS|RELATED_ITEMS|工具 · 实用工具/);
  assert.equal(c.state.data.length,0);
});
test('known catalogue details retain edit support and receive the actual executable icon identifier',async()=>{
  const c=core({location:{search:'?id=known&usageId='+exe},state:{local:true,data:[{id:'known',name:'Curated App',category:'tool-sys',description:'My description',paths:[]}]}});
  await c.loadRecordedDetail();
  assert.match(c.element('#catalog').innerHTML,/Curated App/);assert.match(c.element('#catalog').innerHTML,/id="d-edit"/);
  assert.match(c.element('#catalog').innerHTML,/My description/);assert.equal(c.logos.at(-1).usageId,exe);
});
test('a recorded detail remains readable if the catalogue fails to load',async()=>{
  const c=core({loadApps:async()=>{throw new Error('catalogue unavailable');}});
  await c.bootDetail();assert.match(c.element('#catalog').innerHTML,/Unknown App/);
  assert.equal(c.state.data.length,0);
});

test('an older duplicate link opens the preserved primary details',()=>{
  const c=core({location:{search:'?id=old-copy'},state:{local:true,data:[
    {id:'old-copy',name:'Scanned Copy',duplicateOf:'primary',paths:[]},
    {id:'primary',name:'WeGame',description:'My original notes',paths:[]}
  ]}});
  c.render();
  assert.match(c.element('#catalog').innerHTML,/WeGame|My original notes/);
  assert.doesNotMatch(c.element('#catalog').innerHTML,/Scanned Copy/);
  assert.equal(c.state.data.length,2);
});
test('invalid usage IDs make no request and a failed recorded detail can be retried',async()=>{
  let calls=0;
  const invalid=core({location:{search:'?usageId=../../secret'},fetch:async()=>{calls++;return response(recorded);}});
  await invalid.loadRecordedDetail();assert.equal(calls,0);assert.match(invalid.element('#catalog').innerHTML,/标识无效/);
  const c=core({fetch:async()=>response(null,503)});await c.loadRecordedDetail();
  assert.match(c.element('#catalog').innerHTML,/detail-retry/);
  c.context.fetch=async()=>response(recorded);await c.loadRecordedDetail();
  assert.match(c.element('#catalog').innerHTML,/Unknown App/);
});

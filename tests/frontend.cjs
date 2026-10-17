const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
function core(overrides = {}) {
  const context = vm.createContext({
    URLSearchParams, console, setTimeout, clearTimeout,
    document: {querySelector: () => null, querySelectorAll: () => []},
    ...overrides
  });
  vm.runInContext(source + '\nthis.core = {state, pathsFromText, pathsOf, pathText, drivesOf, visible, listedApps, availableDrives, normalizeDrive, serializeEdit, srcHTML, hl, loadApps, apiPost, pageURL, backTarget, renderBackLink, renderCatChips, renderDriveChips, bindSearch, applyGlobalSearch, renderSearchSuggestions, saveEdit, navigateCategory, updateCategorySelection, logoHTML, setupLogos, setupGlobalSearch};', context);
  context.core.run = code => vm.runInContext(code,context);
  return context.core;
}
const plain = value => JSON.parse(JSON.stringify(value));
const response = (body, status = 200) => ({ok: status < 400, status, json: async () => body});
const values = overrides => ({name:'App',category:'tool-sys',source:'downloaded',date:'',site:'',group:'',description:'Description',size:'',paths:'',...overrides});

test('legacy paths split once and preserve directory parentheses; annotations stay separate', () => {
  const c = core();
  const paths = c.pathsOf({path:'C:\\Program Files (x86)\\App · D:/Library\n\\\\server\\share'});
  assert.deepEqual(plain(paths).map(p => p.path), ['C:\\Program Files (x86)\\App','D:/Library','\\\\server\\share']);
  assert.deepEqual(plain(c.pathsOf({path:'D:\\steam2（游戏库 D:\\SteamLibrary）'})), [{path:'D:\\steam2',kind:'unknown',note:'游戏库 D:\\SteamLibrary'}]);
  assert.equal(c.pathsOf({path:'D:\\App (1)'})[0].path,'D:\\App (1)');
});

test('editor saves paths and group without submitting immutable size and source', () => {
  const c = core();
  const original = {paths:[{path:'C:\\软件（正式）',kind:'directory',note:'用户选择'}]};
  const patch = c.serializeEdit(values({paths:'C:\\软件（正式）\nD:/App',size:String(1234567 / 1024**2)}), original);
  assert.equal(patch.group,null);
  assert.equal(JSON.parse(JSON.stringify(patch)).group,null);
  assert.equal('size' in patch,false);
  assert.equal('source' in patch,false);
  assert.deepEqual(plain(patch.paths),[{path:'C:\\软件（正式）',kind:'directory',note:'用户选择'},{path:'D:/App',kind:'unknown',note:''}]);
  assert.equal('size' in c.serializeEdit(values({size:'-2'}),{}),false);
  assert.equal('size' in c.serializeEdit(values({size:'NaN'}),{}),false);
});

test('system component dates remain visible and never submit an editable date', () => {
  const c = core();
  const original = {source:'bundled',installDate:'2025-03-09',size:1234567};
  const patch = c.serializeEdit(values({source:'downloaded',date:'2026-10-15',size:'999'}),original);
  assert.equal('installDate' in patch,false);
  assert.equal('source' in patch,false);
  assert.equal('size' in patch,false);
  assert.match(c.srcHTML(original),/2025 年 3 月 9 日/);
  assert.match(c.srcHTML({source:'bundled'}),/安装日期未知/);
  assert.equal(original.installDate,'2025-03-09');
});

test('note-only locations and unknown installation source survive editing', () => {
  const c = core();
  const app = {paths:[{path:'',kind:'unknown',note:'安装位置未知'}]};
  assert.equal(c.pathText(app),'安装位置未知');
  const patch = c.serializeEdit(values({paths:'安装位置未知',source:'unknown',date:'2026-10-15'}),app);
  assert.deepEqual(plain(patch.paths),plain(app.paths));
  assert.equal(patch.installDate,'2026-10-15');
  assert.match(c.srcHTML({source:'unknown'}),/来源待确认/);
  const draft = c.serializeEdit(values({paths:'系统组件说明'}),{});
  assert.deepEqual(plain(draft.paths),[{path:'',kind:'unknown',note:'系统组件说明'}]);
});

test('drive filtering includes every path and supports UNC, slash paths and extra drives', () => {
  const c = core();
  const app = {name:'Test',description:'',paths:[{path:'C:/App'},{path:'Z:\\Library'},{path:'\\\\server\\share'}]};
  c.state.data = [app]; c.state.drive = 'Z';
  assert.equal(c.visible(app),true);
  c.state.drive = 'network';
  assert.equal(c.visible(app),true);
  assert.ok(c.availableDrives().some(d => d.k === 'Z'));
  c.state.q = 'library';
  assert.equal(c.visible(app),true);
  assert.deepEqual(plain(c.drivesOf({path:'安装位置未知'})),['sys']);
});

test('date badges and highlighting never interpolate unescaped input as HTML', () => {
  const c = core();
  assert.equal(c.srcHTML({installDate:'<img src=x onerror=alert(1)>',source:'downloaded'}).includes('<img'),false);
  assert.equal(c.hl('<img>&','img'), '&lt;<mark>img</mark>&gt;&amp;');
  assert.equal(c.hl('A+B','+'),'A<mark>+</mark>B');
  assert.equal(c.hl('&','&'),'<mark>&amp;</mark>');
});

test('local mode obtains session and revision, and never overlays browser drafts', async () => {
  const calls = [];
  const c = core({
    fetch: async url => { calls.push(url); return response(url === '/api/session' ? {ok:true,token:'session-token'} : {apps:[{id:'1',name:'server'}],revision:'rev-1'}); },
    localStorage: {getItem: () => {throw new Error('Local drafts must not be read');}}
  });
  await c.loadApps();
  assert.deepEqual(calls,['/api/session','/api/apps']);
  assert.equal(c.state.local,true); assert.equal(c.state.data[0].name,'server'); assert.equal(c.state.revision,'rev-1');
});

test('static mode overlays browser drafts and permits a disk-path draft without local validation', async () => {
  const calls = [];
  const c = core({
    fetch: async url => { calls.push(url); return url === '/api/session' ? response({},404) : response([{id:'1',name:'base'}]); },
    localStorage: {getItem: () => '{"1":{"name":"draft"}}'}
  });
  await c.loadApps();
  assert.equal(c.state.local,false); assert.equal(c.state.data[0].name,'draft');
  assert.equal(c.serializeEdit(values({paths:'D:\\OfflineApp'}),{}).paths[0].path,'D:\\OfflineApp');
  assert.deepEqual(calls,['/api/session','data/apps.json']);
});

test('mutations carry the session token and revision conflict retains current data', async () => {
  let request;
  const c = core({fetch: async (url, options) => {request = options; return response({error:'stale'},409);}});
  Object.assign(c.state,{local:true,token:'secret',revision:'old',data:[{id:'1',name:'unsaved'}]});
  await assert.rejects(c.apiPost('/api/save',{id:'1',revision:'old',patch:{name:'change'}}),/刷新清单/);
  assert.equal(request.headers['X-AppShelf-Token'],'secret');
  assert.equal(JSON.parse(request.body).revision,'old');
  assert.equal(c.state.revision,'old'); assert.equal(c.state.data[0].name,'unsaved'); assert.equal(c.state.pending,true);
});

test('navigation preserves search, drive and encoded IDs', () => {
  const c = core();
  Object.assign(c.state,{q:'C++ & 工具',drive:'Z'});
  const url = c.pageURL('detail.html',{id:'a&b'});
  const params = new URLSearchParams(url.split('?')[1]);
  assert.equal(params.get('id'),'a&b'); assert.equal(params.get('q'),'C++ & 工具'); assert.equal(params.get('drive'),'Z');
});

test('category and drive counters apply search consistently without duplicate drive counts', () => {
  const elements = {'#chips':{innerHTML:'',querySelectorAll:()=>[]},'#drive-chips':{innerHTML:'',querySelectorAll:()=>[],querySelector:()=>({addEventListener(){}})}};
  const c = core({document:{querySelector:s => elements[s],querySelectorAll:()=>[]}});
  c.state.data = [
    {name:'Git',category:'dev-tool',paths:[{path:'C:/Git'},{path:'D:/Git'},{path:'D:/Git/extra'}]},
    {name:'Other',category:'dev-tool',path:'C:/Other'}
  ];
  c.state.q = 'git'; c.state.drive = 'D';
  c.renderCatChips(null); c.renderDriveChips(null);
  assert.match(elements['#chips'].innerHTML,/构建工具链<\/span><span class="category-count">1<\/span>/);
  assert.match(elements['#drive-chips'].innerHTML,/<option value="D" selected>D 盘 · 1<\/option>/);
  assert.match(elements['#drive-chips'].innerHTML,/<option value="all">所有位置 · 1<\/option>/);
});

test('category selection and location selection represent independent filters', () => {
  let onLocationChange;
  const categoryBox = {innerHTML:'',querySelectorAll:()=>[]};
  const locationBox = {innerHTML:'',querySelector:()=>({addEventListener:(event,handler)=>{onLocationChange=handler;}})};
  const c = core({document:{querySelector:s=>({'#chips':categoryBox,'#drive-chips':locationBox}[s])}});
  c.state.data = [{name:'Git',category:'dev-tool',path:'D:/Git'}];
  c.renderCatChips('dev-tool'); c.renderDriveChips('dev-tool');
  assert.equal((categoryBox.innerHTML.match(/aria-current="page"/g)||[]).length,1);
  assert.match(categoryBox.innerHTML,/data-cat="dev-tool"[^>]+aria-current="page"/);
  assert.doesNotMatch(categoryBox.innerHTML,/category-all[^>]+aria-current/);
  onLocationChange({target:{value:'all'}});
  assert.equal(c.state.category,'dev-tool');
  assert.equal(c.state.drive,'all');
  c.renderCatChips(null);
  assert.match(categoryBox.innerHTML,/category-all[^>]+aria-current="page"/);
  assert.equal((categoryBox.innerHTML.match(/aria-current="page"/g)||[]).length,1);
  assert.equal((categoryBox.innerHTML.match(/<details/g)||[]).length,8);
});

test('a selected drive remains visible with zero entries and invalid URL filters normalize', () => {
  const box = {innerHTML:'',querySelector:()=>({addEventListener(){}})};
  const c = core({document:{querySelector:()=>box}});
  c.state.drive = 'Z'; c.state.data = [];
  c.renderDriveChips(null);
  assert.match(box.innerHTML,/<option value="Z" selected>Z 盘 · 0<\/option>/);
  assert.equal(c.normalizeDrive('z'),'Z'); assert.equal(c.normalizeDrive('network'),'network');
  assert.equal(c.normalizeDrive('bogus'),'all');
});

test('location selection retains keyboard focus after the options are rerendered', () => {
  let currentSelect;
  const doc = {activeElement:null,querySelector:()=>box};
  const box = {querySelector:()=>currentSelect,set innerHTML(value){this.html=value;currentSelect={id:'drive-select',addEventListener(name,handler){this.change=handler;},focus(){doc.activeElement=this;}};}};
  const c = core({document:doc});
  c.state.data = []; c.renderDriveChips(null);
  const original = currentSelect;
  doc.activeElement = original;
  c.run('pageRender = () => renderDriveChips(null)');
  original.change({target:{value:'D'}});
  assert.notEqual(currentSelect,original);
  assert.equal(doc.activeElement,currentSelect); assert.equal(c.state.drive,'D');
});

test('detail return uses a validated origin category and all-app entries return to all apps', () => {
  const c = core();
  Object.assign(c.state,{q:'Git 工具',drive:'D'});
  const categoryReturn = c.backTarget('category','?cat=dev-tool');
  assert.equal(categoryReturn.label,'返回全部应用');
  assert.match(categoryReturn.href,/^index.html\?/);
  c.state.category = 'dev-tool';
  const detailURL = c.pageURL('detail.html',{id:'git'});
  assert.equal(new URLSearchParams(detailURL.split('?')[1]).get('fromCat'),'dev-tool');
  const returned = c.backTarget('detail',detailURL.split('?')[1]);
  const params = new URLSearchParams(returned.href.split('?')[1]);
  assert.match(returned.href,/^category.html\?/); assert.equal(params.get('cat'),'dev-tool');
  assert.equal(params.get('q'),'Git 工具'); assert.equal(params.get('drive'),'D');
  c.state.category = null;
  const allDetail = c.pageURL('detail.html',{id:'git'});
  assert.equal(new URLSearchParams(allDetail.split('?')[1]).has('fromCat'),false);
  assert.match(c.backTarget('detail',allDetail.split('?')[1]).href,/^index.html\?/);
  assert.match(c.backTarget('detail','?fromCat=https://evil.example').href,/^index.html\?/);
});

test('global search leaves category and location filters and ignores stale delayed typing', () => {
  const handlers = {}, clearHandlers = {};
  const timers = [];
  const input = {value:'',addEventListener:(name,handler)=>{handlers[name]=handler;},focus(){this.focused=true;}};
  const clear = {hidden:true,addEventListener:(name,handler)=>{clearHandlers[name]=handler;}};
  const c = core({document:{querySelector:s=>({'#q':input,'#clear-search':clear}[s]),addEventListener(){}},setTimeout:f=>{timers.push(f);return 0;}});
  c.state.library = true;
  c.state.drive = 'D'; c.state.category = 'dev-tool'; c.bindSearch();
  input.value = 'new query'; handlers.input({target:input});
  const beforeDebounce = c.pageURL('category.html',{cat:'dev-tool'});
  assert.equal(new URLSearchParams(beforeDebounce.split('?')[1]).get('q'),'new query');
  assert.equal(clear.hidden,false);
  timers[0]();
  assert.equal(c.state.category,null); assert.equal(c.state.drive,'all');
  clearHandlers.click();
  timers[0]();
  assert.equal(c.state.q,''); assert.equal(input.value,''); assert.equal(c.state.drive,'all');
  assert.equal(c.state.category,null); assert.equal(input.focused,true); assert.equal(clear.hidden,true);
});

test('missing, absent and duplicate entries are hidden while real portable copies remain searchable', () => {
  const c = core();
  c.state.data = [
    {id:'old',name:'Geek',status:'removed'},
    {id:'uncertain',name:'Geek',status:'missing'},
    {id:'duplicate',name:'Geek',duplicateOf:'one'},
    {id:'absent',name:'Geek',availability:'absent'},
    {id:'one',name:'Geek',path:'D:/geek/geek.exe'},
    {id:'two',name:'Geek',path:'C:/Temp/geek64.exe'}
  ];
  c.state.q = 'geek';
  assert.deepEqual(plain(c.listedApps()).map(a=>a.id),['one','two']);
  assert.equal(c.visible(c.state.data[0]),false);
  assert.equal(c.visible(c.state.data[1]),false);
  assert.equal(c.state.data.length,6);
});

test('search in detail uses all categories and locations and escapes result data', () => {
  const box = {hidden:true,innerHTML:''}, input = {setAttribute(){}};
  const c = core({document:{querySelector:s=>({'#global-results':box,'#q':input}[s])}});
  c.state.data = [{id:'one',name:'Geek <x>',category:'tool-sys',path:'D:/geek.exe'},{id:'two',name:'Geek 64',category:'dev-tool',path:'C:/geek64.exe'},{id:'gone',name:'Geek gone',status:'removed'}];
  Object.assign(c.state,{drive:'E',category:'ai-code'});
  c.applyGlobalSearch('Geek');
  assert.equal(box.hidden,false);
  assert.match(box.innerHTML,/全部应用 · 2 个结果/);
  assert.match(box.innerHTML,/Geek &lt;x&gt;/);
  assert.match(box.innerHTML,/Geek 64/);
  assert.doesNotMatch(box.innerHTML,/Geek gone/);
});

test('malformed static data reports an error and retains the previous usable snapshot', async () => {
  const c = core({fetch:async url => url === '/api/session' ? response({},404) : response([{id:'1',name:'App',paths:[null]}]),localStorage:{getItem:()=>null}});
  c.state.data = [{id:'previous',name:'Previous'}];
  await assert.rejects(c.loadApps(),/路径格式/);
  assert.equal(c.state.data[0].id,'previous');
});

test('refresh obtains a fresh server token after a server restart', async () => {
  const c = core({fetch:async url => response(url === '/api/session' ? {ok:true,token:'new-token'} : {apps:[],revision:'new-revision'})});
  Object.assign(c.state,{local:true,token:'expired-token'});
  await c.loadApps();
  assert.equal(c.state.token,'new-token');
});

function editorFixture() {
  const fields = {};
  for(const [key,value] of Object.entries({'#ed-name':'App','#ed-cat':'tool-sys','#ed-src':'unknown','#ed-date':'','#ed-site':'','#ed-group':'','#ed-desc':'Description','#ed-size':'','#ed-paths':'安装位置未知'})) fields[key] = {value,disabled:false};
  fields['#ed-save'] = {disabled:false}; fields['#ed-err'] = {hidden:true,textContent:''};
  const controls = Object.values(fields).filter(el => 'disabled' in el);
  const ov = {dataset:{revision:'old-revision'},querySelector:s=>fields[s],querySelectorAll:()=>controls,isConnected:true,closed:false,closeEditor(){this.closed = true;}};
  return {ov,fields,controls};
}

test('an expired session keeps editor content and restores controls after a failed save', async () => {
  let finish;
  const waiting = new Promise(resolve => {finish = resolve;});
  const c = core({fetch:async()=>waiting});
  const {ov,fields,controls} = editorFixture();
  Object.assign(c.state,{local:true,token:'expired',editing:true,data:[{id:'1',name:'App',paths:[{path:'',kind:'unknown',note:'安装位置未知'}]}]});
  const saving = c.saveEdit(ov,'1');
  assert.equal(ov.saving,true); assert.ok(controls.every(el => el.disabled));
  finish(response({error:'本地会话已失效，请刷新页面后重试'},403));
  await saving;
  assert.equal(ov.closed,false); assert.equal(c.state.editing,true); assert.equal(ov.saving,false);
  assert.equal(fields['#ed-desc'].value,'Description'); assert.equal(fields['#ed-save'].disabled,false);
  assert.match(fields['#ed-err'].textContent,/本地会话已失效/);
});

test('a successful save replaces stale keys and does not duplicate a pending submission', async () => {
  let finish, requests = 0;
  const waiting = new Promise(resolve => {finish = resolve;});
  const toast = {textContent:'',classList:{add(){},remove(){}}};
  const c = core({fetch:async()=>{requests++;return waiting;},document:{querySelector:s=>s === '#toast' ? toast : null,querySelectorAll:()=>[]},setTimeout:()=>0});
  const {ov} = editorFixture();
  Object.assign(c.state,{local:true,token:'valid',editing:true,data:[{id:'1',name:'Old',group:'old-group',status:'new'}]});
  const saving = c.saveEdit(ov,'1');
  await c.saveEdit(ov,'1');
  assert.equal(requests,1);
  finish(response({ok:true,app:{id:'1',name:'Updated'},revision:'new-revision'}));
  await saving;
  assert.equal(c.state.data[0].name,'Updated');
  assert.equal('group' in c.state.data[0],false); assert.equal('status' in c.state.data[0],false);
  assert.equal(c.state.revision,'new-revision'); assert.equal(ov.closed,true);
});

test('detail rendering copies note-only locations as their displayed text', () => {
  const catalog = {innerHTML:'',querySelectorAll:()=>[]}, crumb = {innerHTML:''};
  const c = core({document:{querySelector:s=>({'#catalog':catalog,'#crumb':crumb,'#d-edit':{addEventListener(){}}}[s]),querySelectorAll:()=>[]},location:{search:'?id=1'}});
  c.state.data = [{id:'1',name:'App',category:'tool-sys',paths:[{path:'',kind:'unknown',note:'系统组件'}]}];
  c.run(fs.readFileSync(path.join(__dirname,'../assets/detail.js'),'utf8').replace(/bootDetail\(\);/,'render();'));
  assert.match(catalog.innerHTML,/class="btn mini copy-path" data-p="系统组件"/);
});

test('back controls show only an arrow while retaining a descriptive accessible label', () => {
  const attributes = {}, handlers = {};
  const link = {dataset:{},textContent:'old label',setAttribute:(k,v)=>{attributes[k]=v;},addEventListener:(k,v)=>{handlers[k]=v;}};
  const c = core({document:{querySelector:s=>s === '#back-link' ? link : null,querySelectorAll:()=>[]},location:{search:'?fromCat=ai-code'}});
  c.renderBackLink('detail');
  assert.equal(link.textContent,'');
  assert.equal(attributes['aria-label'],'返回AI 编程');
  assert.equal(link.title,'返回AI 编程');
  assert.match(link.href,/^category.html\?cat=ai-code/);
});

test('category navigation updates only results and selection without replacing sidebar nodes or fetching', () => {
  const pushed = [], attrs = {};
  let sidebarReplacements = 0, fetches = 0;
  const group = {dataset:{group:'dev'},open:false};
  const links = [null,'dev-tool','ai-code'].map(cat => ({dataset:{cat:cat || ''},classList:{toggle(k,v){this[k]=v;}},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}}));
  const sidebar = {scrollTop:123,querySelectorAll:s=>s.includes('details') ? [group] : links,set innerHTML(_){sidebarReplacements++;}};
  const select = {addEventListener(){}};
  const node = () => ({hidden:false,textContent:'',innerHTML:'',dataset:{},classList:{toggle(){}},setAttribute(k,v){this[k]=v;},addEventListener(){},querySelectorAll:()=>[]});
  const ids = Object.fromEntries(['library-overview','library-category','library-header','back-link','crumb','crumb-all','cat-title','cat-desc','q','result','stat-count','stat-cat','stat-dl','stat-size','catalog'].map(id=>['#'+id,node()]));
  ids['#chips'] = sidebar;
  ids['#drive-chips'] = {...node(),querySelector:()=>select};
  const c = core({document:{body:{dataset:{}},querySelector:s=>ids[s] || null,querySelectorAll:()=>[]},location:{search:'',pathname:'/index.html'},history:{pushState:(_,__,url)=>pushed.push(url)},fetch:()=>{fetches++;throw new Error('No data reload expected');}});
  c.state.library = true;
  c.state.data = [{id:'git',name:'Git',category:'dev-tool',description:'Tool',path:'D:/Git'},{id:'ai',name:'Assistant',category:'ai-code',description:'AI',path:'C:/Assistant'}];
  c.run(fs.readFileSync(path.join(__dirname,'../assets/library.js'),'utf8') + '\npageRender = renderLibrary;');
  c.navigateCategory('dev-tool');
  assert.equal(c.state.category,'dev-tool');
  assert.match(ids['#catalog'].innerHTML,/Git/);
  assert.doesNotMatch(ids['#catalog'].innerHTML,/Assistant/);
  assert.equal(sidebar.scrollTop,123); assert.equal(group.open,false);
  assert.equal(sidebarReplacements,0); assert.equal(fetches,0);
  assert.equal(links[1]['aria-current'],'page');
  assert.match(pushed[0],/^category.html\?cat=dev-tool/);
  c.navigateCategory('ai-code');
  assert.equal(links[1]['aria-current'],undefined);
  assert.equal(links[2]['aria-current'],'page');
  assert.match(ids['#catalog'].innerHTML,/Assistant/);
  assert.equal(sidebarReplacements,0);
  c.navigateCategory(null);
  assert.match(ids['#catalog'].innerHTML,/Assistant/);
  assert.match(ids['#catalog'].innerHTML,/Git/);
  assert.equal(links[0]['aria-current'],'page');
  assert.equal(ids['#library-category'].hidden,true);
});

test('leaving a search refreshes sidebar totals without replacing nodes or losing group state', () => {
  const groupCount = {textContent:'2'}, allCount = {textContent:'2'}, languageCount = {textContent:'2'};
  const group = {dataset:{group:'dev'},open:false,querySelector:()=>groupCount};
  const link = (cat,count)=>({dataset:{cat},classList:{toggle(){}},setAttribute(){},removeAttribute(){},querySelector:()=>count});
  const links = [link('',allCount),link('dev-lang',languageCount)];
  let replacements = 0;
  const box = {scrollTop:200,querySelectorAll:s=>s.includes('details')?[group]:links,set innerHTML(_){replacements++;}};
  const input = {value:'Node'},clear = {hidden:false};
  const c = core({document:{querySelector:s=>({'#chips':box,'#q':input,'#clear-search':clear}[s])},location:{search:'',pathname:'/index.html'},history:{pushState(){}}});
  Object.assign(c.state,{library:true,q:'Node',category:null,data:Array.from({length:6},(_,i)=>({id:String(i),name:i<2?'Node '+i:'Java '+i,category:'dev-lang'}))});
  c.run('pageRender=()=>updateCategorySelection();');
  c.navigateCategory('dev-lang');
  assert.equal(languageCount.textContent,6);
  assert.equal(groupCount.textContent,6);
  assert.equal(allCount.textContent,6);
  assert.equal(c.state.data.filter(c.visible).length,6);
  assert.equal(input.value,'');assert.equal(clear.hidden,true);
  assert.equal(group.open,false);assert.equal(box.scrollTop,200);assert.equal(replacements,0);
});

test('local program logos are preferred, including applications with no website', () => {
  const image = 'data:image/png;base64,AAAA';
  const c = core({APP_LOGOS:{byName:{'trae solo cn':image},bySite:{'trae.cn':image}}});
  assert.match(c.logoHTML({name:'TRAE SOLO CN'}),/src="data:image\/png;base64,AAAA"/);
  assert.match(c.logoHTML({name:'Related',site:'trae.cn'}),/data-local="true"/);
  const unknown = c.logoHTML({name:'Unknown'});
  assert.match(unknown,/logo-placeholder/);
  assert.doesNotMatch(unknown,/logo-letter/);
});

test('recorded executables use native logos with cached product logos as fallback', () => {
  const c=core({APP_LOGOS:{byName:{product:'data:image/png;base64,AAAA'}}});
  c.state.local=true;
  const html=c.logoHTML({name:'Product',usageId:'exe-0123456789abcdef'});
  assert.match(html,/src="\/api\/usage\/icon\?id=exe-0123456789abcdef"/);
  assert.match(html,/data-fallback="data:image\/png;base64,AAAA"/);
  assert.doesNotMatch(c.logoHTML({name:'Product',usageId:'../../secret'}),/\/api\/usage\/icon/);
  c.state.local=false;
  assert.doesNotMatch(c.logoHTML({name:'Product',usageId:'exe-0123456789abcdef'}),/\/api\/usage\/icon/);
});

test('failed native icons fall back to an offline catalogue icon before a neutral placeholder', () => {
  const errors=[];
  const img={dataset:{fallback:'data:image/png;base64,AAAA',site:'',local:'true'},complete:false,
    addEventListener:(name,callback)=>errors.push(callback),replaceWith:element=>{img.replacement=element;}};
  const c=core({document:{querySelectorAll:()=>[img],createElement:()=>({})}});
  c.setupLogos();errors[0]();
  assert.equal(img.src,'data:image/png;base64,AAAA');
  errors[0]();assert.match(img.replacement.innerHTML,/logo-placeholder/);
});

test('every bundled cached logo is a PNG and screenshot TRAE entry has an offline logo', () => {
  const cached = fs.readFileSync(path.join(__dirname,'../assets/logos.js'),'utf8');
  const logos = JSON.parse(cached.split('const APP_LOGOS = ')[1].replace(/;\s*$/,''));
  assert.ok(logos.byName['traework cn 0.2.2']);
  assert.equal(logos.byName['trae solo cn'],logos.byName['traework cn 0.2.2']);
  assert.ok(logos.bySite['trae.cn']);
  for(const value of [...Object.values(logos.byName),...Object.values(logos.bySite)]){
    assert.match(value,/^data:image\/png;base64,/);
    assert.equal(Buffer.from(value.split(',')[1],'base64').subarray(1,4).toString(),'PNG');
  }
});

test('the shared brand uses a local decorative logo with an accessible home link and intact navigation',()=>{
  for(const page of ['home','index','category','detail','usage','"><script>alert(1)</script>']){
    let inserted=null,insertions=0;
    const document={body:{dataset:{page},prepend:element=>{inserted=element;insertions++;}},querySelector:selector=>selector==='#global-search'?inserted:null,createElement:()=>({innerHTML:''})};
    const c=core({document});c.setupGlobalSearch();c.setupGlobalSearch();
    assert.equal(insertions,1);
    assert.match(inserted.innerHTML,/<a class="app-brand" href="home.html" aria-label="AppShelf 首页">/);
    assert.match(inserted.innerHTML,/<img class="app-brand-icon" src="assets\/appshelf.png" width="24" height="24" alt="" aria-hidden="true">AppShelf<\/a>/);
    for(const destination of ['home.html','index.html','usage.html']) assert.ok(inserted.innerHTML.includes('href="'+destination+'"'));
    assert.equal((inserted.innerHTML.match(/aria-current="page"/g)||[]).length,1);
    assert.doesNotMatch(inserted.innerHTML,/<script>|javascript:/);
  }
});

test('every page declares the new bundled favicon inside its head',()=>{
  for(const name of ['home','index','category','detail','usage']){
    const head=fs.readFileSync(path.join(__dirname,'../'+name+'.html'),'utf8').split('</head>')[0];
    assert.match(head,/<link rel="icon" type="image\/x-icon" href="assets\/appshelf.ico">/);
    assert.match(head,/<link rel="icon" type="image\/png" sizes="512x512" href="assets\/appshelf.png">/);
  }
});

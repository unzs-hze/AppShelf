/* Home is read-only.  Catalogue and usage are independent sources. */
const homeState={catalogueReady:false,catalogueLoading:false,usageLoading:false,usage:null,usageRequest:0,controller:null,timer:null,initialized:false,poem:null,poemRequest:0,poemController:null};

function homeNormalizePoem(poem){
  if(!poem || typeof poem!=="object" || ["id","text","author","title","dynasty"].some(key=>typeof poem[key]!=="string" || !poem[key].trim() || poem[key].length>(key==="text" ? 80 : 120))) return null;
  return {id:poem.id,text:poem.text,author:poem.author,title:poem.title,dynasty:poem.dynasty};
}
function homeRenderPoem(poem){
  const value=homeNormalizePoem(poem);
  if(!value) return false;
  homeState.poem=value;
  $("#home-poem-text").textContent=value.text;
  $("#home-poem-author").textContent=value.dynasty+" · "+value.author;
  $("#home-poem-title").textContent="《"+value.title+"》";
  return true;
}
async function homeLoadPoem(){
  if(homeState.poem) return;
  if(homeRenderPoem(state.poem)) return;
  homeState.poemController?.abort();
  const controller=new AbortController(),request=++homeState.poemRequest;
  homeState.poemController=controller;
  try{
    const session=await fetch("/api/session",{cache:"no-store",signal:controller.signal});
    if(session.ok){
      const value=await session.json();
      if(request!==homeState.poemRequest || controller.signal.aborted) return;
      if(value.ok && homeRenderPoem(value.poem)){state.poem=homeState.poem;return;}
    }
    const response=await fetch("data/poems.json",{cache:"force-cache",signal:controller.signal});
    if(!response.ok) return;
    const data=await response.json();
    if(request!==homeState.poemRequest || controller.signal.aborted || !Array.isArray(data) || data.length!==1000) return;
    const poems=data.map(homeNormalizePoem).filter(Boolean);
    if(poems.length!==1000 || new Set(poems.map(poem=>poem.id)).size!==1000 || new Set(poems.map(poem=>poem.text)).size!==1000) return;
    let saved;
    try{saved=sessionStorage.getItem("appshelf-home-poem");}catch(_){}
    const selected=poems.find(poem=>poem.id===saved) || poems[Math.floor(Math.random()*poems.length)];
    homeRenderPoem(selected);
    try{sessionStorage.setItem("appshelf-home-poem",selected.id);}catch(_){}
  }catch(_){/* The built-in verse stays visible when a local request fails. */}
}

function homeDateKey(date=new Date()){
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
}
function homeGreeting(date=new Date()){
  const hour=date.getHours();
  return hour<6 ? "夜深了。" : hour<12 ? "早上好。" : hour<18 ? "下午好。" : "晚上好。";
}
function homeRenderDate(date=new Date()){
  $("#home-greeting").textContent=homeGreeting(date);
  $("#home-date").textContent=date.toLocaleDateString("zh-CN",{year:"numeric",month:"long",day:"numeric",weekday:"long"});
}
function homeDuration(seconds){
  const numeric=Number(seconds),total=Number.isFinite(numeric) ? Math.max(0,numeric) : 0;
  if(total>0 && total<1) return "不足 1 秒";
  const value=Math.floor(total),hours=Math.floor(value/3600),minutes=Math.floor(value%3600/60),rest=value%60;
  return [hours ? hours+" 小时" : "",minutes ? minutes+" 分钟" : "",rest || !value ? rest+" 秒" : ""].filter(Boolean).join(" ");
}
function homeCatalogueSummary(apps){
  const seen=new Set(),categories=new Set();
  for(const app of apps){
    if(!app || ["missing","removed"].includes(app.status) || app.duplicateOf || app.availability==="absent" || typeof app.id!=="string" || !app.id || seen.has(app.id)) continue;
    seen.add(app.id);
    if(typeof app.category==="string" && app.category.trim()) categories.add(app.category);
  }
  return {apps:seen.size,categories:categories.size};
}
function homeNormalizeUsage(payload){
  if(!payload || payload.period!=="day" || !/^\d{4}-\d{2}-\d{2}$/.test(payload.date) || !Array.isArray(payload.apps) || typeof payload.totalSeconds!=="number" || !Number.isFinite(payload.totalSeconds) || payload.totalSeconds<0) throw new Error("今日记录格式不正确");
  const apps=payload.apps.map(app=>{
    if(!app || typeof app.name!=="string" || !app.name.trim() || typeof app.seconds!=="number" || !Number.isFinite(app.seconds) || app.seconds<0) throw new Error("应用使用记录格式不正确");
    return {...app,id:typeof app.id==="string" ? app.id : "",name:app.name,path:typeof app.path==="string" ? app.path : "",catalogueId:typeof app.catalogueId==="string" ? app.catalogueId : null};
  }).filter(app=>app.seconds>0).sort((a,b)=>b.seconds-a.seconds || a.name.localeCompare(b.name,"zh-CN"));
  return {...payload,apps,status:payload.status && typeof payload.status==="object" ? payload.status : {}};
}
function homeActivityHTML(apps){
  return apps.slice(0,4).map(app=>{
    const known=state.data.find(item=>item.id===(app.catalogueId||app.id));
    const meta=known?.version ? "版本 "+known.version : "前台记录";
    const content=`<span class="logo">${logoHTML({...known,name:known?.name || app.name,usageId:app.id})}</span><span class="home-app-info"><span class="home-app-name" title="${esc(app.path || app.name)}">${esc(app.name)}</span><span class="home-app-meta">${esc(meta)}</span></span><span class="home-app-duration">${esc(homeDuration(app.seconds))}</span><span class="home-app-arrow" aria-hidden="true">↗</span>`;
    const params=usageDetailParams(app);
    const href=params ? pageURL("detail.html",params) : "";
    return params ? `<li><a class="home-activity-app detail-link"${params.id ? ` data-detail-id="${esc(params.id)}"` : ""}${params.usageId ? ` data-usage-id="${esc(params.usageId)}"` : ""} href="${esc(href)}">${content}</a></li>` : `<li><div class="home-activity-app">${content}</div></li>`;
  }).join("");
}
function homeUsageNote(status){
  if(status.error) return "采集暂不可用，已保存的记录仍可查看。";
  if(status.state==="idle") return "电脑闲置，计时已暂停。";
  if(status.state==="locked") return "锁屏期间暂停计时。";
  if(status.state==="screen-off") return "熄屏期间暂停计时。";
  if(status.state==="another-instance") return "另一个 AppShelf 正在记录。";
  if(status.state==="unavailable") return "等待识别前台应用，已有记录已保留。";
  if(status.state==="sampling-gap") return "正在恢复记录，暂停期间不补算。";
  if(status.tracking && (!status.state || status.state==="active")) return typeof status.idleThreshold==="number" && status.idleThreshold>0 ? `正在记录前台活动；连续 ${homeDuration(status.idleThreshold)} 无操作后暂停。` : "正在记录前台停留时间，阅读或观看时也会计时。";
  return "已保存的本机前台记录。";
}
function homeRenderActivity(payload){
  const list=$("#home-activity-list"),apps=payload.apps.slice(0,4),active=list.contains?.(document.activeElement) ? document.activeElement : null;
  const rows=Array.from(list.querySelectorAll?.(".home-activity-app")||[]);
  const signature=JSON.stringify(apps.map(app=>({...app,seconds:0,known:state.data.find(item=>item.id===(app.catalogueId||app.id))})));
  if(signature===homeState.activitySignature && rows.length===apps.length && rows.length){
    rows.forEach((row,index)=>{const duration=row.querySelector(".home-app-duration");if(duration) duration.textContent=homeDuration(apps[index].seconds);});
    return;
  }
  const identity=active?.dataset;
  list.innerHTML=apps.length ? homeActivityHTML(apps) : '<li class="home-empty"><strong>今天还没有使用记录</strong>开始使用应用后，常用应用会出现在这里。</li>';
  homeState.activitySignature=signature;
  setupLogos(list);
  if(typeof bindDetailLinks === "function") bindDetailLinks(list);
  if(identity && (identity.usageId || identity.detailId)){
    Array.from(list.querySelectorAll?.("a.detail-link")||[]).find(link=>link.dataset.usageId===identity.usageId && link.dataset.detailId===identity.detailId)?.focus({preventScroll:true});
  }
}
function homeRenderUsage(payload){
  $("#home-usage-total").textContent=homeDuration(payload.totalSeconds);
  homeRenderActivity(payload);
  const note=$("#home-usage-status");
  const label=homeUsageNote(payload.status);
  if(note.textContent!==label) note.textContent=label;
  note.classList.toggle("is-error",!!payload.status.error);
}
function homeRenderRefresh(){
  $("#home-refresh").disabled=homeState.catalogueLoading && homeState.usageLoading;
}
async function homeLoadCatalogue(){
  if(homeState.catalogueLoading) return;
  homeState.catalogueLoading=true;homeRenderRefresh();
  try{
    await loadApps();
    const summary=homeCatalogueSummary(state.data);
    $("#home-app-count").textContent=String(summary.apps);
    $("#home-category-count").textContent=String(summary.categories);
    const note=$("#home-catalogue-status");
    note.textContent=state.local ? "本机应用清单" : "静态预览清单";
    note.classList.remove("is-error");
    homeState.catalogueReady=true;
    if(homeState.usage) homeRenderActivity(homeState.usage);
    if(typeof renderSearchSuggestions==="function") renderSearchSuggestions();
  }catch(_){
    const note=$("#home-catalogue-status");
    note.textContent=homeState.catalogueReady ? "应用目录刷新失败，保留上次读取的概览。" : "应用目录暂时无法读取，可以稍后重试。";
    note.classList.add("is-error");
    if(!homeState.catalogueReady){$("#home-app-count").textContent="—";$("#home-category-count").textContent="—";}
  }finally{homeState.catalogueLoading=false;homeRenderRefresh();}
}
async function homeLoadUsage(options={}){
  if(options.quiet && (document.hidden || state.editing || homeState.usageLoading)) return;
  homeState.controller?.abort();
  const controller=new AbortController(),request=++homeState.usageRequest;
  homeState.controller=controller;homeState.usageLoading=true;
  if(!options.quiet) homeRenderRefresh();
  try{
    const response=await fetch("/api/usage?period=day",{cache:"no-store",signal:controller.signal});
    if(!response.ok){const error=new Error("今日记录暂时无法读取");error.staticMode=response.status===404;throw error;}
    const payload=homeNormalizeUsage(await response.json());
    if(request!==homeState.usageRequest || controller.signal.aborted || (options.quiet && (document.hidden || state.editing))) return;
    homeState.usage=payload;homeRenderUsage(payload);
  }catch(error){
    if(request!==homeState.usageRequest || controller.signal.aborted || error.name==="AbortError") return;
    const previous=homeState.usage && homeState.usage.date===homeDateKey();
    const note=$("#home-usage-status");
    if(previous) note.textContent="今日记录刷新失败，保留上次读取的数据。";
    else{
      homeState.usage=null;
      $("#home-usage-total").textContent="—";
      $("#home-activity-list").innerHTML=error.staticMode ? '<li class="home-empty"><strong>在本机运行后查看使用时间</strong>这里会显示真实前台记录，静态预览不提供使用时间。</li>' : '<li class="home-empty"><strong>今日记录暂时无法读取</strong>已有记录仍保存在本机，请稍后重试。</li>';
      note.textContent=error.staticMode ? "使用时间需要本地记录。" : "使用时间读取失败，可以稍后重试。";
    }
    note.classList.toggle("is-error",!error.staticMode);
  }finally{
    if(request===homeState.usageRequest){homeState.usageLoading=false;homeRenderRefresh();}
  }
}
function homeRefresh(){
  homeRenderDate();
  return Promise.allSettled([homeLoadCatalogue(),homeLoadUsage()]);
}
function homeStartRefreshTimer(){
  clearInterval(homeState.timer);
  homeState.timer=setInterval(()=>homeLoadUsage({quiet:true}),5000);
}
function homeBoot(){
  if(homeState.initialized) return;
  homeState.initialized=true;
  setupGlobalSearch();bindSearch();homeRenderDate();
  homeLoadPoem();
  $("#home-refresh").addEventListener("click",()=>homeRefresh());
  document.addEventListener("visibilitychange",()=>{if(!document.hidden){homeRenderDate();homeLoadUsage({quiet:true});}});
  window.addEventListener("pagehide",()=>{
    homeState.returnTop=Math.max(0,Number(window.scrollY)||0);
    homeState.controller?.abort();homeState.usageRequest++;homeState.usageLoading=false;
    homeState.poemController?.abort();homeState.poemRequest++;
    clearInterval(homeState.timer);homeState.timer=null;
  });
  window.addEventListener("pageshow",event=>{
    if(!event.persisted) return;
    homeLoadPoem();
    homeStartRefreshTimer();
    const previous=typeof history!=="undefined" ? history.state?.appshelfView : null;
    const saved={...(previous||{}),view:"home.html",top:homeState.returnTop??previous?.top??Math.max(0,Number(window.scrollY)||0)};
    return homeRefresh().then(()=>{if(typeof restoreViewPosition==="function") restoreViewPosition(saved);});
  });
  homeStartRefreshTimer();
  return homeRefresh().then(() => { if(typeof restoreViewPosition === "function") restoreViewPosition(); });
}
homeBoot();

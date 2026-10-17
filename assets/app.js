/* ============ AppShelf 共享核心 ============ */

const GROUPS = [
  { k:"sys",  label:"系统" },
  { k:"dev",  label:"开发" },
  { k:"ai",   label:"AI" },
  { k:"off",  label:"办公" },
  { k:"net",  label:"网络" },
  { k:"game", label:"游戏" },
  { k:"lib",  label:"组件" },
  { k:"tool", label:"工具" }
];

const CATS = [
  { k:"sys-asus",  g:"sys",  label:"华硕 · 天选生态" },
  { k:"sys-hw",    g:"sys",  label:"硬件驱动" },
  { k:"sys-os",    g:"sys",  label:"系统与安全" },
  { k:"dev-ide",   g:"dev",  label:"编辑器 · IDE" },
  { k:"dev-lang",  g:"dev",  label:"语言运行时" },
  { k:"dev-db",    g:"dev",  label:"数据库" },
  { k:"dev-tool",  g:"dev",  label:"构建工具链" },
  { k:"dev-net",   g:"dev",  label:"网络 · 虚拟化" },
  { k:"ai-code",   g:"ai",   label:"AI 编程" },
  { k:"ai-tool",   g:"ai",   label:"AI 助手 · 生成" },
  { k:"off-doc",   g:"off",  label:"办公文档" },
  { k:"off-media", g:"off",  label:"影音创意" },
  { k:"net-web",   g:"net",  label:"浏览器" },
  { k:"net-im",    g:"net",  label:"通讯社交" },
  { k:"net-tool",  g:"net",  label:"网络 · 网盘" },
  { k:"game-plat", g:"game", label:"游戏平台" },
  { k:"game-app",  g:"game", label:"游戏本体" },
  { k:"game-tool", g:"game", label:"模拟器 · 工具" },
  { k:"lib-rt",    g:"lib",  label:"运行库" },
  { k:"lib-ac",    g:"lib",  label:"反作弊" },
  { k:"tool-sys",  g:"tool", label:"实用工具" }
];

const DRIVES = [
  { k:"all", label:"所有位置" },
  { k:"C",   label:"C 盘" },
  { k:"D",   label:"D 盘" },
  { k:"E",   label:"E 盘" },
  { k:"F",   label:"F 盘" },
  { k:"network", label:"网络位置" },
  { k:"sys", label:"未记录路径" }
];

const $  = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s ?? "").replace(/[&<>"]/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[m]));

const state = { q:"", drive:"all", category:null, data:[], order:new Map(), local:false, token:"", quote:"", poem:null, revision:"", editing:false, pending:false };

function catOf(k){ return CATS.find(c => c.k === k); }
function groupOf(k){ const c = catOf(k); return GROUPS.find(g => g.k === (c ? c.g : k)); }

function hl(text, term){
  const s = String(text ?? "");
  if(!term) return esc(s);
  const pat = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let end = 0, html = "";
  for(const m of s.matchAll(new RegExp(pat, "gi"))){
    html += esc(s.slice(end, m.index)) + `<mark>${esc(m[0])}</mark>`;
    end = m.index + m[0].length;
  }
  return html + esc(s.slice(end));
}
function pad(n){ return String(n).padStart(3, "0"); }

/* ---- 盘符与筛选 ---- */
function driveOf(p){
  if(/^(?:\\\\|\/\/)/.test(p || "")) return "network";
  const m = /^([A-Za-z]):[\\/]/.exec(p || "");
  return m ? m[1].toUpperCase() : "sys";
}
function isDiskPath(p){ return /^(?:[A-Za-z]:[\\/]|\\\\|\/\/)/.test(p || ""); }
function parsePathLine(value){
  let path = String(value || "").trim(), note = "";
  const m = /^(.*?)[（(]([^（）()]*)[）)]$/.exec(path);
  // Old catalog entries append explanatory text to a real installation path.
  if(m && path.includes("（") && isDiskPath(m[1].trim())){ path = m[1].trim(); note = m[2].trim(); }
  return { path, kind:"unknown", note };
}
function pathsFromText(t){
  return String(t || "").split(/\r?\n|\s+·\s+/).map(path => ({path:path.trim(),kind:"unknown",note:""})).filter(p => p.path);
}
function pathsOf(a){
  if(a && Array.isArray(a.paths)) return a.paths.filter(p => p && (typeof p === "string" || typeof p === "object")).map(p => typeof p === "string" ? parsePathLine(p) : {
    path:String(p.path || ""), kind:p.kind || "unknown", note:String(p.note || "")
  }).filter(p => p.path || p.note);
  return pathsFromText(typeof a === "string" ? a : a?.path).map(p => parsePathLine(p.path));
}
function pathLabel(p){ return p.path ? p.path + (p.note ? `（${p.note}）` : "") : p.note; }
function pathText(a, delimiter=" · "){ return pathsOf(a).map(pathLabel).join(delimiter); }
function drivesOf(a){ const drives = [...new Set(pathsOf(a).filter(p => isDiskPath(p.path)).map(p => driveOf(p.path)))]; return drives.length ? drives : ["sys"]; }
function availableDrives(){
  const known = new Set(state.data.flatMap(drivesOf));
  if(/^[A-Z]$/.test(state.drive)) known.add(state.drive);
  const extra = [...known].filter(k => /^[A-Z]$/.test(k) && !DRIVES.some(d => d.k === k)).sort().map(k => ({k,label:k+" 盘"}));
  return [...DRIVES.slice(0, -2), ...extra, ...DRIVES.slice(-2)];
}
function normalizeDrive(value){
  if(["all","network","sys"].includes(value)) return value;
  return /^[A-Za-z]$/.test(value || "") ? value.toUpperCase() : "all";
}
function pageURL(page, params={}){
  const p = new URLSearchParams(params);
  if(page === "detail.html" && catOf(state.category)) p.set("fromCat", state.category);
  if(page === "detail.html"){
    const origin = currentViewURL();
    if(origin) p.set("returnTo",origin);
  }
  if(state.q) p.set("q", state.q);
  if(state.drive !== "all") p.set("drive", state.drive);
  return page + (p.size ? "?" + p.toString() : "");
}
function backTarget(page, search=location.search){
  const params = new URLSearchParams(search);
  const returnTo = page === "detail" ? safeViewURL(params.get("returnTo")) : null;
  if(returnTo){
    const p = new URLSearchParams(returnTo.split("?")[1] || "");
    p.set("restore","1");
    const file = returnTo.split("?")[0];
    const label = file === "home.html" ? "返回首页" : file === "usage.html" ? "返回使用时间" : "返回应用目录";
    return {href:file+"?"+p.toString(),label};
  }
  const origin = page === "detail" ? catOf(params.get("fromCat")) : null;
  return origin
    ? {href:pageURL("category.html",{cat:origin.k}),label:"返回" + origin.label}
    : {href:pageURL("index.html"),label:"返回全部应用"};
}
function renderBackLink(page){
  const link = $("#back-link");
  if(!link) return;
  const target = backTarget(page);
  link.href = target.href;
  link.textContent = "";
  link.setAttribute("aria-label", target.label);
  link.title = target.label;
  if(!link.dataset.bound){
    link.addEventListener("click", e => {
      link.href = backTarget(page).href;
      if(page === "detail" && plainNavigation(e) && typeof history !== "undefined"){
        const saved = history.state?.appshelfReturn;
        const query = new URLSearchParams(location.search);
        if(saved && typeof saved.navigation === "string" && !!saved.navigation && saved.view === safeViewURL(query.get("returnTo")) && saved.navigation === query.get("returnVia") && history.length === saved.sourceLength+1 && history.length > 1){
          e.preventDefault(); history.back(); return;
        }
      }
      if(page === "category" && state.library && plainNavigation(e)){
        e.preventDefault(); navigateCategory(null);
      }
    });
    link.dataset.bound = "true";
  }
  $$('footer a[href="index.html"], footer a[data-return-all]',document).forEach(anchor => {
    anchor.href = pageURL("index.html");
    if(!anchor.dataset.returnAll){
      anchor.dataset.returnAll = "true";
      anchor.addEventListener("click", e => {
        anchor.href = pageURL("index.html");
        if(state.library && plainNavigation(e)){ e.preventDefault(); navigateCategory(null); }
      });
    }
  });
}
function updateViewURL(){
  if(typeof history === "undefined") return;
  const p = new URLSearchParams(location.search);
  state.q ? p.set("q", state.q) : p.delete("q");
  state.drive !== "all" ? p.set("drive", state.drive) : p.delete("drive");
  history.replaceState(null, "", location.pathname + (p.size ? "?" + p : ""));
}
function plainNavigation(e){
  return !e || ((!e.button || e.button === 0) && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey && !e.defaultPrevented);
}
function safeViewURL(value){
  if(typeof value !== "string" || value.length > 4096 || !/^(?:home|index|category|usage)\.html(?:\?[^#]*)?$/.test(value)) return null;
  const separator = value.indexOf("?"), file = separator < 0 ? value : value.slice(0,separator);
  const params = new URLSearchParams(separator < 0 ? "" : value.slice(separator+1));
  params.delete("restore");
  params.sort();
  return file + (params.size ? "?"+params : "");
}
function currentViewURL(){
  if(state.library){
    const params = new URLSearchParams();
    if(catOf(state.category)) params.set("cat",state.category);
    if(state.q) params.set("q",state.q);
    if(state.drive !== "all") params.set("drive",state.drive);
    return safeViewURL((state.category ? "category.html" : "index.html")+(params.size ? "?"+params : ""));
  }
  const page = document.body?.dataset?.page;
  if(page === "home") return "home.html";
  if(page === "usage") return safeViewURL("usage.html"+(typeof location !== "undefined" ? location.search : ""));
  if(page === "detail" && typeof location !== "undefined") return safeViewURL(new URLSearchParams(location.search).get("returnTo"));
  return null;
}
function saveViewPosition(anchorId=null){
  if(document.body?.dataset?.page === "detail") return;
  saveSidebarState();
  if(typeof window === "undefined") return;
  const view = currentViewURL();
  if(!view) return;
  const anchor = anchorId ? $$(".entry").find(el => el.dataset.id === anchorId) : null;
  const value = {view,top:Math.max(0,Number(window.scrollY) || 0),anchorId,
    anchorOffset:anchor?.getBoundingClientRect().top,
    navigation:Date.now().toString(36)+"-"+Math.random().toString(36).slice(2),pending:true,
    historyLength:typeof history !== "undefined" ? history.length : 0,
    openRelated:$$("details.related-entries").filter(el => el.open).map(el => el.dataset.relatedFor)};
  try{ sessionStorage.setItem("appshelf-view:"+view,JSON.stringify(value)); }catch(_){}
  if(typeof history !== "undefined"){
    history.scrollRestoration = "manual";
    history.replaceState({...history.state,appshelfView:value},"");
  }
  return value;
}
function usageDetailParams(app){
  const usageId=/^exe-[0-9a-f]{16}$/.test(app?.id || "") ? app.id : null;
  const candidate=byId(app?.catalogueId || app?.id);
  const known=candidate?.duplicateOf ? byId(candidate.duplicateOf) || candidate : candidate;
  const id=known?.id || app?.catalogueId;
  return id ? {id,...(usageId ? {usageId} : {})} : usageId ? {usageId} : null;
}
function detailNavigationURL(id,anchorId=null,usageId=null){
  const params={};
  if(id) params.id=id;
  if(/^exe-[0-9a-f]{16}$/.test(usageId || "")) params.usageId=usageId;
  const saved = saveViewPosition(anchorId), url = pageURL("detail.html",params);
  if(!saved) return url;
  const query = new URLSearchParams(url.split("?")[1]);
  query.set("returnVia",saved.navigation);
  return "detail.html?"+query;
}
function prepareDetailReturn(){
  if(document.body?.dataset?.page !== "detail" || typeof history === "undefined") return;
  const query = new URLSearchParams(location.search), view = safeViewURL(query.get("returnTo")), navigation = query.get("returnVia");
  if(!view || !navigation || history.state?.appshelfReturn) return;
  try{
    const saved = JSON.parse(sessionStorage.getItem("appshelf-view:"+view) || "null");
    if(saved?.pending && saved.view === view && Number.isInteger(saved.historyLength) && saved.historyLength >= 1 && saved.navigation === navigation && history.length === saved.historyLength+1){
      history.replaceState({...history.state,appshelfReturn:{view,navigation,sourceLength:saved.historyLength}},"");
      saved.pending = false;
      sessionStorage.setItem("appshelf-view:"+view,JSON.stringify(saved));
    }
  }catch(_){}
}
function restoreViewPosition(saved){
  if(typeof window === "undefined") return false;
  const view = currentViewURL(), params = new URLSearchParams(location.search);
  let value = saved || (typeof history !== "undefined" ? history.state?.appshelfView : null);
  if(!value && params.get("restore") === "1"){
    try{ value = JSON.parse(sessionStorage.getItem("appshelf-view:"+view) || "null"); }catch(_){}
  }
  if(!value || value.view !== view || !Number.isFinite(value.top) || value.top < 0) return false;
  if(params.has("restore") && typeof history !== "undefined"){
    params.delete("restore");
    history.replaceState({...history.state,appshelfView:value},"",location.pathname+(params.size ? "?"+params : ""));
  }
  const openRelated = Array.isArray(value.openRelated) ? value.openRelated.filter(id => typeof id === "string") : [];
  $$("details.related-entries").forEach(el => { el.open = openRelated.includes(el.dataset.relatedFor); });
  const apply = () => {
    const anchor = value.anchorId ? $$(".entry").find(el => el.dataset.id === value.anchorId) : null;
    const top = anchor && Number.isFinite(value.anchorOffset) ? window.scrollY + anchor.getBoundingClientRect().top - value.anchorOffset : value.top;
    window.scrollTo({top:Math.max(0,top),left:0,behavior:"instant"});
  };
  if(typeof requestAnimationFrame === "function") requestAnimationFrame(apply); else apply();
  return true;
}
function bindDetailLinks(root){
  $$("a.detail-link",root).forEach(link => {
    if(link.dataset.returnBound) return;
    link.dataset.returnBound = "true";
    link.addEventListener("click", () => {
      if(link.dataset.detailId || /^exe-[0-9a-f]{16}$/.test(link.dataset.usageId || "")) link.href = detailNavigationURL(link.dataset.detailId || null,link.closest(".entry")?.dataset.id || null,link.dataset.usageId);
    });
  });
}
function saveSidebarState(){
  const box = $("#chips");
  if(!box) return;
  const value = {scroll:Number(box.scrollTop) || 0,open:Object.fromEntries($$("details.category-group",box).map(el => [el.dataset.group,el.open]))};
  state.sidebar = value;
  try{ sessionStorage.setItem("appshelf-library-nav",JSON.stringify(value)); }catch(_){}
}
function sidebarState(){
  if(state.sidebar) return state.sidebar;
  try{
    const value = JSON.parse(sessionStorage.getItem("appshelf-library-nav") || "null");
    if(value && typeof value.open === "object" && Number.isFinite(value.scroll)) return value;
  }catch(_){}
  return {scroll:0,open:{}};
}
function updateCategorySelection(){
  const box = $("#chips");
  if(!box) return;
  $$("a.category-link",box).forEach(link => {
    const category = catOf(link.dataset.cat);
    const active = (category?.k || null) === state.category;
    link.classList.toggle("is-active",active);
    if(active) link.setAttribute("aria-current","page"); else link.removeAttribute("aria-current");
    link.href = category ? pageURL("category.html",{cat:category.k}) : pageURL("index.html");
    const count = link.querySelector?.(".category-count");
    if(count) count.textContent = state.data.filter(a => (!category || a.category === category.k) && visible(a)).length;
  });
  $$("details.category-group",box).forEach(group => {
    const count = group.querySelector?.("summary .category-count");
    if(count) count.textContent = state.data.filter(a => groupOf(a.category)?.k === group.dataset.group && visible(a)).length;
  });
}
function navigateCategory(category, options={}){
  if(state.editing || state.busy) return;
  const selected = catOf(category)?.k || null;
  if(selected === state.category && !state.q) return;
  saveViewPosition();
  state.q = "";
  if($("#q")) $("#q").value = "";
  if($("#clear-search")) $("#clear-search").hidden = true;
  state.category = selected;
  if(typeof history !== "undefined" && options.push !== false){
    history.pushState(null,"",selected ? pageURL("category.html",{cat:selected}) : pageURL("index.html"));
  }
  pageRender({keepSidebar:true});
}
function matchesQuery(a){
  const q = state.q.trim().toLowerCase();
  return !q || [a.name, a.description, a.publisher, a.version, a.site, pathText(a)].join(" ").toLowerCase().includes(q);
}
function isListed(a){
  return !!a && a.status !== "removed" && a.status !== "missing" && !a.duplicateOf && a.availability !== "absent";
}
function listedApps(){ return state.data.filter(isListed); }
function visible(a){
  return isListed(a) && (state.drive === "all" || drivesOf(a).includes(state.drive)) && matchesQuery(a);
}

function fmtSize(b){
  if(b == null || b === "") return "";
  if(b < 1024*1024) return (b/1024).toFixed(0) + " KB";
  if(b < 1024**3)   return (b/1024**2).toFixed(1) + " MB";
  return (b/1024**3).toFixed(2) + " GB";
}
function fmtDate(d){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(String(d || ""))) return "";
  const [y,m,day] = String(d).split("-");
  if(+m < 1 || +m > 12 || +day < 1 || +day > 31) return "";
  return `${y} 年 ${String(+m)} 月 ${String(+day)} 日`;
}

/* ---- 来源徽标 ---- */
function srcHTML(a){
  const date = fmtDate(a.installDate)
    ? `<span class="src date" title="${a.dateSource === "registry" ? "注册表安装记录" : a.dateSource === "manual" ? "手动填写" : "清单记录的安装日期"}">${esc(fmtDate(a.installDate))} 安装</span>` : a.source === "bundled" ? `<span class="src date" title="系统没有提供可用安装日期">安装日期未知</span>` : "";
  if(a.source === "bundled")
    return `<span class="src bundled" title="系统或设备厂商预装">系统自带</span>` + date;
  return (a.source === "downloaded" ? `<span class="src dl" title="清单记录为下载安装">下载安装</span>` : `<span class="src" title="扫描记录暂未提供可靠的安装来源">来源待确认</span>`) + date;
}

/* ---- Logo ---- */
function firstChar(name){
  const m = String(name || "").match(/[A-Za-z0-9\u4e00-\u9fff]/);
  return m ? m[0].toUpperCase() : "?";
}
function logoHTML(a){
  const logos = typeof APP_LOGOS === "undefined" ? {} : APP_LOGOS;
  const local = logos.byName?.[String(a.name || "").trim().toLowerCase()] || logos.bySite?.[String(a.site || "").toLowerCase()];
  const remote = a.site ? `https://favicon.im/${encodeURIComponent(a.site)}?larger=true` : "";
  const native = state.local && /^exe-[0-9a-f]{16}$/.test(a.usageId || "") ? "/api/usage/icon?id="+a.usageId : "";
  if(!native && !local && !remote) return defaultLogoHTML();
  return `<img class="logo-img" alt="" referrerpolicy="no-referrer"
    data-site="${esc(a.site || "")}" data-local="${local ? "true" : "false"}"
    data-fallback="${esc(native ? local || remote : "")}"
    src="${esc(native || local || remote)}">`;
}
function defaultLogoHTML(){
  return `<svg class="logo-placeholder" viewBox="0 0 32 32" fill="none" aria-label="暂无可用应用图标" role="img"><rect x="5" y="5" width="22" height="22" rx="5" stroke="currentColor" stroke-width="1.5"/><path d="M5 12h22M10 8.5h.01M14 8.5h.01M11 17h10M11 21h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
}
function setupLogos(root){
  $$("img.logo-img", root).forEach(img => {
    const site = img.dataset.site;
    const alts = [...new Set([img.dataset.fallback || "", ...(site ? [
      ...(img.dataset.local === "true" ? [`https://favicon.im/${encodeURIComponent(site)}?larger=true`] : []),
      `https://api.iowen.cn/favicon/${encodeURIComponent(site)}.png`,
      `https://www.google.com/s2/favicons?sz=64&domain=${encodeURIComponent(site)}`
    ] : [])].filter(Boolean))];
    const fallback = () => {
      if(alts.length){ img.src = alts.shift(); return; }
      const s = document.createElement("span");
      s.className = "logo-fallback";
      s.innerHTML = defaultLogoHTML();
      img.replaceWith(s);
    };
    img.addEventListener("error", fallback);
    if(img.complete && !img.naturalWidth) fallback();
  });
}

/* ---- 状态徽标（新增 / 已卸载） ---- */
function statusHTML(a){
  if(a.status === "new")     return `<span class="st new" title="扫描发现的新软件，点击编辑补全介绍">新发现</span>`;
  if(a.status === "missing") return `<span class="st removed" title="扫描暂未检测到，请确认后处理">未检测到</span>`;
  if(a.status === "removed") return `<span class="st removed" title="已标记为卸载，可恢复记录">已卸载</span>`;
  if(a.status === "unavailable") return `<span class="st removed" title="所在磁盘或路径暂不可用">路径不可用</span>`;
  return "";
}

function statusActionsHTML(a){
  if(!state.local) return "";
  if(a.status === "new") return `<div class="status-actions"><button class="btn mini" data-action="accept" data-id="${esc(a.id)}">确认收录</button></div>`;
  if(a.status === "missing" || a.status === "removed") return `<div class="status-actions"><button class="btn mini" data-action="restore" data-id="${esc(a.id)}">保留并恢复</button><button class="btn mini" data-action="delete" data-id="${esc(a.id)}">确认移除</button></div>`;
  return "";
}

/* ---- 条目卡片 ---- */
function pathSegsOf(p){
  return pathsOf(p).map(pathLabel);
}
function relatedApps(a){
  const eligible = app => app && typeof app.group === "string" && !!app.group && !(app.group === "git" && /^Logitech\b/i.test(app.name));
  if(!eligible(a)) return [];
  return state.data.filter(app => eligible(app) && app.id !== a.id && app.group === a.group && isListed(app));
}
function relatedHTML(a,{expanded=false}={}){
  const peers = relatedApps(a);
  if(!peers.length) return "";
  return `<details class="related-entries" data-related-for="${esc(a.id)}"${expanded ? " open" : ""}><summary><span>相关条目与位置</span><span class="related-names">${peers.map(app => esc(app.name)+(app.architecture ? " · "+esc(app.architecture) : "")).join("、")}</span></summary><ul class="related-list">${peers.map(app => `<li><div class="related-title"><a class="detail-link" data-detail-id="${esc(app.id)}" href="${esc(pageURL("detail.html",{id:app.id}))}">${esc(app.name)}</a><span>${esc(catOf(app.category)?.label || "未分类")}</span>${app.version ? `<span>v${esc(app.version)}</span>` : ""}${app.architecture ? `<span>${esc(app.architecture)}</span>` : ""}${statusHTML(app)}</div><code>${esc(pathText(app) || "未记录位置")}</code></li>`).join("")}</ul></details>`;
}

function entryHTML(a){
  const cat = catOf(a.category) || { label:"未分类", k:"tool-sys" };
  const g   = groupOf(a.category) || { k:"tool" };
  const q   = state.q.trim();
  const size = a.size != null ? fmtSize(a.size) : "—";
  const removed = a.status === "removed";
  // 路径：磁盘路径可点击跳转文件夹；系统说明文字不可点
  const segs = pathsOf(a).map(p => {
    const seg = pathLabel(p);
    if(isDiskPath(p.path) && state.local) return `<code class="p-seg link" data-p="${esc(p.path)}" title="点击在资源管理器中定位">${hl(seg, q)}</code>`;
    return `<code class="p-seg">${hl(seg, q)}</code>`;
  }).join(`<span class="p-dot">·</span>`);
  return `
    <article class="entry${removed ? " is-removed" : ""}" data-id="${esc(a.id)}">
      <div class="num">${pad(state.order.get(a)+1)}</div>
      <div class="logo" style="--c:var(--c-${cat.k},var(--c-${g.k},#6b6356))">${logoHTML(a)}</div>
      <div class="body">
        <div class="name">
          <a class="name-link detail-link" data-detail-id="${esc(a.id)}" href="${esc(pageURL("detail.html", {id:a.id}))}">${hl(a.name, q)}</a>
          <span class="tag" style="--c:var(--c-${cat.k},#6b6356)"><i></i>${esc(cat.label)}</span>
        </div>
        <div class="desc">${hl(a.description, q)}</div>
        <div class="meta">
          ${statusHTML(a)}
          ${srcHTML(a)}
          ${a.version ? `<span class="src version">v${esc(a.version)}</span>` : ""}
          ${a.architecture ? `<span class="src">${esc(a.architecture)}</span>` : ""}
          ${a.publisher ? `<span class="src publisher">${esc(a.publisher)}</span>` : ""}
          <span class="size" title="${a.sizeSource === "registry" ? "注册表报告的估计占用" : "记录的磁盘占用"}">${size}</span>
        </div>
        <div class="path">
          <span class="p-segs" title="${esc(pathText(a))}">${segs}</span>
          <button class="copy" data-p="${esc(pathText(a, "\n"))}" type="button">复制</button>
        </div>
        ${statusActionsHTML(a)}
        ${relatedHTML(a)}
      </div>
      <button class="edit" data-id="${esc(a.id)}" type="button" title="编辑此条目">编辑</button>
    </article>`;
}

/* 点击卡片跳详情；复制/编辑/路径段除外 */
function bindEntries(root){
  setupLogos(root);
  $$(".entry", root).forEach(en => {
    en.addEventListener("click", e => {
      if(e.target.closest("a, .copy, .edit, .p-seg.link, .status-actions, details, summary")) return;
      location.href = detailNavigationURL(en.dataset.id,en.dataset.id);
    });
  });
  bindDetailLinks(root);
  // 点击路径段 → 资源管理器定位（阻止跳详情）
  $$(".p-seg.link", root).forEach(seg => {
    seg.addEventListener("click", async e => {
      e.stopPropagation();
      const p = seg.dataset.p;
      try{
        const j = await apiPost("/api/reveal", { path:p });
        showToast(j.ok ? "已定位：" + p : (j.error || "打开失败"));
      }catch(e){ showToast(e.message); }
    });
  });
  $$(".copy", root).forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const path = e.currentTarget.dataset.p;
      navigator.clipboard.writeText(path).then(() => {
        btn.classList.add("done");
        const old = btn.textContent;
        btn.textContent = "已复制";
        setTimeout(() => { btn.classList.remove("done"); btn.textContent = old; }, 1100);
        showToast("已复制：" + path);
      }).catch(() => showToast("复制失败，请手动选择路径"));
    });
  });
  $$(".edit", root).forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      openEditor(btn.dataset.id);
    });
  });
  bindStatusActions(root);
}

/* ---- 分区渲染（index 全部子类 / category 单个子类） ---- */
function renderSections(cats){
  const catalog = $("#catalog");
  const shownCats = cats.filter(c => state.data.some(a => a.category === c.k && visible(a)));
  if(!shownCats.length){
    catalog.innerHTML = `<div class="empty">${!state.data.length && state.local ? "清单还是空的。点击「扫描本机」建立自己的应用清单。" : `没有匹配「${esc(state.q.trim())}」的应用，换个关键词或盘符试试。`}</div>`;
    return;
  }
  catalog.innerHTML = shownCats.map(c => {
    const items = state.data.filter(a => a.category === c.k && visible(a));
    return `
      <section class="cat-sec" id="sec-${c.k}">
        <header class="sec-head">
          <h2><i style="--c:var(--c-${c.k},#6b6356)"></i>${c.label}</h2>
          <span class="sec-count">${items.length} 款</span>
        </header>
        ${items.map(entryHTML).join("")}
      </section>`;
  }).join("");
  bindEntries(catalog);
}

/* ---- 分类导航与独立的位置筛选 ---- */
function renderCatChips(current){
  state.category = catOf(current) ? current : null;
  const counts = {};
  CATS.forEach(c => counts[c.k] = 0);
  state.data.forEach(a => {
    if(visible(a)) counts[a.category]++;
  });
  const box = $("#chips");
  if(!box) return;
  const saved = sidebarState();
  const groups = $$("details.category-group",box);
  const scroll = groups.length ? box.scrollTop : saved.scroll;
  const openGroups = groups.length ? new Map(groups.map(el => [el.dataset.group,el.open])) : new Map(Object.entries(saved.open));
  const total = state.data.filter(visible).length;
  box.innerHTML = `<a class="category-link category-all${!state.category ? " is-active" : ""}" data-cat="" href="${esc(pageURL("index.html"))}"${!state.category ? ' aria-current="page"' : ""}><span>全部应用</span><span class="category-count">${total}</span></a>` +
    GROUPS.map(group => {
      const categories = CATS.filter(c => c.g === group.k);
      const count = categories.reduce((sum,c) => sum + (counts[c.k] || 0),0);
      const open = openGroups.has(group.k) ? openGroups.get(group.k) : true;
      return `<details class="category-group" data-group="${group.k}"${open ? " open" : ""}>
        <summary><span class="category-group-title"><i style="--c:var(--c-${group.k},#6b6356)"></i>${esc(group.label)}</span><span class="category-count">${count}</span></summary>
        <div class="category-links">${categories.map(c => `<a class="category-link${state.category === c.k ? " is-active" : ""}" data-cat="${c.k}" href="${esc(pageURL("category.html",{cat:c.k}))}"${state.category === c.k ? ' aria-current="page"' : ""}><span>${esc(c.label)}</span><span class="category-count">${counts[c.k] || 0}</span></a>`).join("")}</div>
      </details>`;
    }).join("");
  box.scrollTop = scroll;
  $$("details.category-group",box).forEach(group => group.addEventListener("toggle",saveSidebarState));
  $$("a.category-link",box).forEach(link => link.addEventListener("click", e => {
    const category = catOf(link.dataset.cat);
    link.href = category ? pageURL("category.html",{cat:category.k}) : pageURL("index.html");
    if(state.library && plainNavigation(e)){
      e.preventDefault(); navigateCategory(category?.k || null);
    }
  }));
}

function renderDriveChips(scope){
  const pool = listedApps().filter(a => !scope || a.category === scope);
  const dcounts = {};
  DRIVES.forEach(d => dcounts[d.k] = 0);
  pool.forEach(a => {
    if(matchesQuery(a)){
      drivesOf(a).forEach(d => { dcounts[d] = (dcounts[d] || 0) + 1; });
      dcounts.all++;
    }
  });
  const box = $("#drive-chips");
  if(!box) return;
  const previousSelect = $("#drive-select",box);
  const restoreFocus = previousSelect && document.activeElement === previousSelect;
  box.innerHTML = `<label class="location-select-label" for="drive-select">安装位置</label><select id="drive-select">${availableDrives().map(d => `<option value="${esc(d.k)}"${state.drive === d.k ? " selected" : ""}>${esc(d.label)} · ${dcounts[d.k] || 0}</option>`).join("")}</select>`;
  const select = $("#drive-select",box);
  select.addEventListener("change", e => {
    state.drive = e.target.value;
    updateViewURL();
    pageRender();
  });
  if(restoreFocus) select.focus({preventScroll:true});
}

function setupGlobalSearch(){
  if($("#global-search")) return;
  const bar = document.createElement("div");
  bar.id = "global-search";
  bar.className = "global-search";
  const page = document.body.dataset.page;
  const active = page === "home" ? "home" : page === "usage" ? "usage" : "library";
  const nav = [["home","home.html","首页"],["library","index.html","应用目录"],["usage","usage.html","使用时间"]].map(([key,href,label]) => `<a href="${href}" class="app-nav-link${active === key ? " is-active" : ""}"${active === key ? ' aria-current="page"' : ""}>${label}</a>`).join("");
  bar.innerHTML = `<div class="container global-search-inner"><a class="app-brand" href="home.html" aria-label="AppShelf 首页"><img class="app-brand-icon" src="assets/appshelf.png" width="24" height="24" alt="" aria-hidden="true">AppShelf</a><nav class="app-nav" aria-label="主要功能">${nav}</nav><div class="global-search-box"><form class="search" id="search-form" role="search"><label class="sr-only" for="q">搜索全部应用</label><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="q" type="search" placeholder="搜索全部应用 · 名称、用途、路径" autocomplete="off" aria-controls="global-results" aria-expanded="false"><button id="clear-search" class="clear-search" type="button" aria-label="清空搜索" hidden>×</button><kbd>Ctrl K</kbd></form><div id="global-results" class="global-results" hidden></div></div></div>`;
  document.body.prepend(bar);
}
function globalSearchURL(){
  const params = new URLSearchParams();
  if(state.q.trim()) params.set("q",state.q.trim());
  return "index.html" + (params.size ? "?" + params : "");
}
function renderSearchSuggestions(){
  const box = $("#global-results"), input = $("#q");
  if(!box) return;
  const show = !state.library && !!state.q.trim();
  box.hidden = !show;
  input?.setAttribute("aria-expanded",String(show));
  if(!show) return;
  const items = listedApps().filter(matchesQuery);
  box.innerHTML = `<div class="global-results-head">全部应用 · ${items.length} 个结果</div>` + items.slice(0,8).map(a => `<a class="global-result" href="${esc("detail.html?" + new URLSearchParams({id:a.id,q:state.q}))}"><span>${esc(a.name)}</span><small>${esc(pathText(a))}</small></a>`).join("") + (items.length ? `<a class="global-results-all" href="${esc(globalSearchURL())}">查看全部 ${items.length} 个结果 →</a>` : `<p class="global-no-results">没有找到匹配的软件</p>`);
}
function applyGlobalSearch(value){
  state.q = value;
  if(state.library){
    state.category = null; state.drive = "all";
    if(typeof history !== "undefined") history.replaceState(null,"",globalSearchURL());
    pageRender();
  }else renderSearchSuggestions();
}
function bindSearch(){
  const input = $("#q");
  if(!input) return;
  const clear = $("#clear-search");
  const syncClear = () => { if(clear) clear.hidden = !input.value; };
  let timer;
  input.addEventListener("input", e => {
    clearTimeout(timer);
    const value = e.target.value;
    state.q = value;
    syncClear();
    timer = setTimeout(() => { if(input.value === value) applyGlobalSearch(value); },120);
  });
  if(clear) clear.addEventListener("click", () => {
    clearTimeout(timer);
    input.value = "";
    syncClear(); applyGlobalSearch(""); input.focus();
  });
  $("#search-form")?.addEventListener("submit", e => {
    e.preventDefault(); clearTimeout(timer); applyGlobalSearch(input.value);
    if(!state.library) location.href = globalSearchURL();
  });
  input.addEventListener("focus",renderSearchSuggestions);
  input.addEventListener("keydown", e => {
    if(e.key === "Escape"){ $("#global-results").hidden = true; input.setAttribute("aria-expanded","false"); input.blur(); }
  });
  document.addEventListener("keydown", e => {
    if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k"){ e.preventDefault(); input.focus(); input.select(); }
  });
  document.addEventListener("click", e => {
    if(!e.target.closest("#global-search")){ $("#global-results").hidden = true; input.setAttribute("aria-expanded","false"); }
  });
  syncClear();
}

/* ---- 本地接口与静态草稿 ---- */
const LS_KEY = "appshelf-edits";
async function apiPost(path, body={}){
  if(!state.local || !state.token) throw new Error("此操作需要本地服务");
  const r = await fetch(path, { method:"POST", headers:{"Content-Type":"application/json", "X-AppShelf-Token":state.token}, body:JSON.stringify(body) });
  const j = await r.json();
  if(!r.ok || !j.ok){
    const conflict = r.status === 409 && (path === "/api/save" || path === "/api/dismiss");
    const error = new Error(conflict ? "清单已被扫描或其他窗口更新。请关闭编辑窗口，刷新清单后重新编辑；本次修改尚未保存。" : (j.error || "操作失败"));
    error.status = r.status;
    if(conflict){ state.pending = true; renderSyncStatus(); }
    throw error;
  }
  return j;
}
function normalizeLoadedApps(data){
  if(!Array.isArray(data)) throw new Error("清单格式不正确");
  const ids = new Set();
  return data.map(a => {
    if(!a || typeof a !== "object" || Array.isArray(a) || typeof a.id !== "string" || !a.id || typeof a.name !== "string" || !a.name.trim() || ids.has(a.id)) throw new Error("清单包含无效或重复条目");
    ids.add(a.id);
    if(a.paths !== undefined && (!Array.isArray(a.paths) || a.paths.some(p => !p || typeof p !== "object" || Array.isArray(p) || typeof p.path !== "string" || (p.note !== undefined && typeof p.note !== "string")))) throw new Error("条目路径格式不正确：" + a.name);
    return {...a,category:catOf(a.category) ? a.category : "tool-sys",description:typeof a.description === "string" ? a.description : "",path:typeof a.path === "string" ? a.path : "",site:typeof a.site === "string" ? a.site : "",group:typeof a.group === "string" ? a.group : null,size:typeof a.size === "number" && Number.isFinite(a.size) && a.size >= 0 ? a.size : null};
  });
}
async function loadApps(){
  if(!state.token || state.local){
    try{
      const r = await fetch("/api/session", {cache:"no-store"});
      const session = r.ok ? await r.json() : null;
      if(session?.ok && typeof session.token === "string"){
        state.token = session.token; state.local = true;
        if(typeof session.quote === "string" && session.quote.trim()) state.quote = session.quote;
        if(session.poem && typeof session.poem === "object") state.poem = session.poem;
      }
    }catch(_){}
  }
  const res = await fetch(state.local ? "/api/apps" : "data/apps.json", {cache:"no-store"});
  if(!res.ok) throw new Error("读取清单失败（" + res.status + "）");
  const payload = await res.json();
  const data = state.local ? payload?.apps : payload;
  if(!Array.isArray(data)) throw new Error("清单格式不正确");
  if(!state.local){
    try{
      const edits = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
      data.forEach(a => { if(a && edits[a.id] && typeof edits[a.id] === "object" && !Array.isArray(edits[a.id])) Object.assign(a, edits[a.id]); });
    }catch(_){}
  }
  const normalized = normalizeLoadedApps(data);
  state.data = normalized;
  state.revision = state.local ? payload.revision : "";
  state.pending = false;
  state.order = new Map(normalized.map((a,i) => [a,i]));
}

function byId(id){ return state.data.find(a => a.id === id); }

function setupSyncControls(){
  if($("#sync-bar")) return;
  const bar = document.createElement("div");
  bar.id = "sync-bar";
  bar.className = "sync-bar";
  bar.innerHTML = `<p id="sync-status" role="status" aria-live="polite"></p><div class="sync-buttons"><button class="btn mini" id="refresh-data" type="button">刷新清单</button><button class="btn mini" id="scan-data" type="button">扫描本机</button></div>`;
  $("main").prepend(bar);
  $("#refresh-data").addEventListener("click", refreshApps);
  $("#scan-data").addEventListener("click", scanApps);
  renderSyncStatus();
}
function renderSyncStatus(status){
  const box = $("#sync-status");
  if(!box) return;
  if(status) state.scanStatus = status;
  const s = state.scanStatus || {};
  let message = "静态预览 · 修改仅保存在当前浏览器，可自由编辑路径草稿";
  if(state.local){
    message = s.running ? "正在扫描本机…完成后点击刷新清单查看结果" : "本地清单 · 修改保存在本机用户数据目录";
    if(s.lastScan && !s.running){
      const date = new Date(s.lastScan);
      if(!isNaN(date.getTime())) message += " · 最近扫描 " + date.toLocaleTimeString("zh-CN", {hour:"2-digit",minute:"2-digit"});
    }
    if(state.pending) message = "清单有新变化，点击刷新查看。当前页面和编辑内容已保留。";
    if(s.error) message += " · 扫描失败：" + s.error;
  }
  box.textContent = message;
  $("#scan-data").hidden = !state.local;
  $("#scan-data").disabled = state.editing || !!s.running || !!state.busy;
  $("#refresh-data").disabled = state.editing || !!state.busy;
}
async function checkStatus(){
  if(!state.local) return;
  try{
    const r = await fetch("/api/status", {cache:"no-store"});
    if(!r.ok) throw new Error("无法获取扫描状态");
    const s = await r.json();
    if(s.revision && s.revision !== state.revision) state.pending = true;
    renderSyncStatus(s);
  }catch(e){ renderSyncStatus({error:e.message}); }
}
async function refreshApps(){
  if(state.editing) return showToast("请先保存或关闭编辑窗口，再刷新清单");
  state.busy = true; renderSyncStatus();
  try{ await loadApps(); pageRender(); showToast("清单已刷新"); }
  catch(e){ showToast(e.message); }
  finally{ state.busy = false; renderSyncStatus(); checkStatus(); }
}
async function scanApps(){
  if(state.editing) return showToast("请先保存或关闭编辑窗口，再扫描本机");
  state.busy = true; renderSyncStatus({running:true});
  try{
    const j = await apiPost("/api/scan");
    await loadApps(); pageRender();
    const d = j.diff || {};
    const count = x => Array.isArray(x) ? x.length : (Number(x) || 0);
    showToast(`扫描完成：新增 ${count(d.new)}，未检测到 ${count(d.removed)}，恢复 ${count(d.restored)}`);
  }catch(e){ showToast(e.message); }
  finally{ state.busy = false; await checkStatus(); renderSyncStatus(); }
}
function bindStatusActions(root){
  $$("[data-action]", root).forEach(btn => btn.addEventListener("click", async e => {
    e.stopPropagation();
    const {id,action} = btn.dataset;
    if(state.busy || state.editing) return;
    if(action === "delete" && !window.confirm("确认标记为已卸载并从列表隐藏？记录会保留，不会删除磁盘文件。")) return;
    btn.disabled = true; state.busy = true; renderSyncStatus();
    try{
      await apiPost("/api/dismiss", {id,action,revision:state.revision});
      await loadApps(); pageRender(); renderSyncStatus();
      showToast(action === "delete" ? "已隐藏已卸载记录" : "已确认并保留记录");
    }catch(e){ showToast(e.message); btn.disabled = false; }
    finally{ state.busy = false; renderSyncStatus(); }
  }));
}

/* ---- 编辑弹窗 ---- */
function openEditor(id){
  const a = byId(id);
  if(!a || state.editing || state.busy) return;
  const previousFocus = document.activeElement;
  state.editing = true;
  renderSyncStatus();
  const catOpts = CATS.map(c =>
    `<option value="${c.k}"${a.category===c.k?" selected":""}>${groupOf(c.k).label} · ${c.label}</option>`).join("");
  const ov = document.createElement("div");
  ov.className = "modal-ov";
  ov.id = "editor";
  ov.dataset.revision = state.revision;
  ov.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="editor-title">
      <header class="modal-head">
        <h3 id="editor-title">编辑条目</h3>
        <button type="button" class="modal-x" title="关闭">✕</button>
      </header>
      <div class="modal-body editor-grid">
        <label class="fld"><span>名称 *</span><input id="ed-name" value="${esc(a.name)}"></label>
        <label class="fld"><span>分类</span><select id="ed-cat">${catOpts}</select></label>
        <label class="fld"><span>官网域名</span><input id="ed-site" value="${esc(a.site || "")}" placeholder="例：jetbrains.com"></label>
        <label class="fld"><span>相关分组 · 可留空</span>
          <input id="ed-group" value="${esc(a.group || "")}" placeholder="例：geek、mysql" list="grp-list">
          <datalist id="grp-list">${[...new Set(state.data.map(x=>x.group).filter(Boolean))].map(g=>`<option value="${esc(g)}">`).join("")}</datalist>
        </label>
        <div class="editor-facts">
          <label class="fld"><span>来源 · 只读</span><input id="ed-src" readonly aria-readonly="true" value="${a.source === "bundled" ? "系统自带" : a.source === "downloaded" ? "下载安装" : "来源待确认"}"></label>
          <label class="fld" id="ed-date-wrap"><span>安装日期${a.source === "bundled" ? " · 只读" : ""}</span><input id="ed-date" type="${a.source === "bundled" ? "text" : "date"}" value="${esc(a.installDate || "")}"${a.source === "bundled" ? ' readonly aria-readonly="true" placeholder="系统未提供日期"' : ""}></label>
          <label class="fld"><span>占用 · 只读</span><input id="ed-size" readonly aria-readonly="true" value="${a.size == null ? "未知" : esc(fmtSize(a.size))}" title="${a.sizeSource === "registry" ? "注册表报告的估计占用" : "清单记录的占用"}"></label>
        </div>
        <label class="fld editor-text"><span>介绍 *</span><textarea id="ed-desc" rows="4">${esc(a.description)}</textarea></label>
        <label class="fld editor-text"><span>安装路径 · 一行一个</span>
          <textarea id="ed-paths" rows="4">${esc(pathsOf(a).map(p => p.path || p.note).join("\n"))}</textarea></label>
        <p class="ed-err" id="ed-err" hidden></p>
      </div>
      <footer class="modal-foot">
        <span class="ed-hint">来源和占用由扫描维护${a.source === "bundled" ? "，系统组件日期只读" : ""}</span>
        <button type="button" class="btn ghost" id="ed-cancel">取消</button>
        <button type="button" class="btn" id="ed-save">保存</button>
      </footer>
    </div>`;
  document.body.appendChild(ov);
  document.body.classList.add("editor-open");
  const close = () => {
    if(ov.saving) return;
    ov.remove(); document.body.classList.remove("editor-open"); state.editing = false; renderSyncStatus();
    if(previousFocus?.isConnected) previousFocus.focus();
  };
  ov.closeEditor = close;

  $(".modal-x", ov).addEventListener("click", close);
  $("#ed-cancel", ov).addEventListener("click", close);
  ov.addEventListener("click", e => { if(e.target === ov) close(); });
  ov.addEventListener("keydown", e => {
    if(e.key === "Escape"){ e.preventDefault(); close(); }
    if(e.key === "Tab"){
      const focusable = $$("button:not(:disabled), input, select, textarea", ov).filter(el => !el.closest("[hidden]"));
      const first = focusable[0], last = focusable[focusable.length - 1];
      if(e.shiftKey && document.activeElement === first){ e.preventDefault(); last.focus(); }
      else if(!e.shiftKey && document.activeElement === last){ e.preventDefault(); first.focus(); }
    }
  });
  $("#ed-name", ov).focus();

  $("#ed-save", ov).addEventListener("click", () => saveEdit(ov, id));
}

function edErr(msg,root=document){
  const box = $("#ed-err",root);
  if(!box) return;
  box.hidden = !msg;
  box.textContent = msg || "";
}

function serializeEdit(values, original){
  const paths = pathsFromText(values.paths).map(p => {
    const previous = pathsOf(original).find(x => x.path === p.path || (!x.path && x.note === p.path));
    if(previous) return {...previous};
    return isDiskPath(p.path) ? p : {path:"",kind:"unknown",note:p.path};
  });
  const patch = {
    name:values.name.trim(), category:values.category,
    site:values.site.trim(), group:values.group.trim() || null,
    description:values.description.trim(), paths,
    path:paths.map(pathLabel).join(" · ")
  };
  if(original.source !== "bundled") patch.installDate = values.date || null;
  if(!patch.name) throw new Error("名称不能为空");
  if(!patch.description) throw new Error("介绍不能为空");
  return patch;
}

async function saveEdit(ov, id){
  if(ov.saving) return;
  if(ov.measuring) return edErr("测量正在进行，请稍候再保存",ov);
  const a = byId(id);
  if(!a) return edErr("条目已不在当前清单中，请关闭编辑窗口后刷新",ov);
  let patch;
  try{
    patch = serializeEdit({name:$("#ed-name",ov).value,category:$("#ed-cat",ov).value,source:$("#ed-src",ov).value,date:$("#ed-date",ov).value,site:$("#ed-site",ov).value,group:$("#ed-group",ov).value,description:$("#ed-desc",ov).value,size:$("#ed-size",ov).value,paths:$("#ed-paths",ov).value}, a);
  }catch(e){ return edErr(e.message,ov); }
  const controls = $$("button, input, select, textarea",ov).map(el => ({el,disabled:el.disabled}));
  ov.saving = true;
  controls.forEach(({el}) => { el.disabled = true; });
  try{
    if(state.local){
      const j = await apiPost("/api/save", {id,patch,revision:ov.dataset.revision});
      state.data[state.data.indexOf(a)] = j.app;
      state.order = new Map(state.data.map((app,i) => [app,i]));
      state.revision = j.revision; state.pending = false;
    }else{
      const edits = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
      edits[id] = Object.assign(edits[id] || {},patch);
      localStorage.setItem(LS_KEY,JSON.stringify(edits));
      Object.assign(a,patch);
    }
    ov.saving = false;
    ov.closeEditor();
    showToast(state.local ? "已保存到本机清单" : "已保存浏览器草稿");
    pageRender(); renderSyncStatus();
  }catch(e){ edErr("保存失败：" + e.message,ov); }
  finally{ ov.saving = false; controls.forEach(({el,disabled}) => { el.disabled = disabled; }); }
}

/* ---- Toast ---- */
let toastTimer;
function showToast(msg){
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
}

/* ---- 启动 ---- */
let pageRender = () => {};
async function boot(render){
  pageRender = render;
  setupGlobalSearch();
  prepareDetailReturn();
  const params = new URLSearchParams(location.search);
  state.q = params.get("q") || "";
  state.drive = normalizeDrive(params.get("drive") || "all");
  if(params.has("drive") && params.get("drive") !== state.drive) updateViewURL();
  try{
    await loadApps();
  }catch(err){
    const c = $("#catalog");
    if(c){
      c.innerHTML = `<div class="empty">未能加载数据（${esc(err.message)}）。<button class="btn ghost" id="retry-load">重试</button></div>`;
      $("#retry-load").addEventListener("click", () => location.reload());
    }
    return;
  }
  if($("#q")) $("#q").value = state.q;
  bindSearch();
  setupSyncControls();
  render();
  if(state.library) restoreViewPosition();
  await checkStatus();
  if(state.local) setInterval(checkStatus,15000);
}

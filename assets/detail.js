/* ============ AppShelf 详情页 ============ */
const detailState={usageApp:null,loading:false,error:"",request:0,catalogueError:""};

function recordedUsageId(){return new URLSearchParams(location.search).get("usageId") || "";}
async function loadRecordedDetail(){
  const usageId=recordedUsageId();
  if(!/^exe-[0-9a-f]{16}$/.test(usageId)){detailState.error="使用记录标识无效";render();return;}
  if(!state.local){detailState.error="请在本机运行 AppShelf 后查看使用记录详情";render();return;}
  const request=++detailState.request;
  detailState.loading=true;detailState.error="";render();
  try{
    const response=await fetch("/api/usage/app?"+new URLSearchParams({id:usageId}),{cache:"no-store"});
    const value=await response.json();
    if(!response.ok) throw new Error(value.error||"使用记录详情暂时无法读取");
    if(!value.app || typeof value.app.name!=="string" || !value.app.name.trim()) throw new Error("使用记录详情格式不正确");
    if(request!==detailState.request) return;
    detailState.usageApp={...value.app,usageId};
  }catch(error){if(request===detailState.request) detailState.error=error.message;}
  finally{if(request===detailState.request){detailState.loading=false;render();}}
}

function render(){
  renderBackLink("detail");
  const id = new URLSearchParams(location.search).get("id"),usageId=recordedUsageId();
  const candidate=byId(id)||byId(detailState.usageApp?.catalogueId);
  const base=candidate?.duplicateOf ? byId(candidate.duplicateOf) || candidate : candidate;
  const a=base ? {...base,...(/^exe-[0-9a-f]{16}$/.test(usageId) ? {usageId} : {})} : detailState.usageApp;
  const recordedOnly=!base;
  const unlisted=recordedOnly && (!a?.catalogueId || a.recordedOnly!==false);
  const catalog = $("#catalog");

  if(!a || (!isListed(a) && !usageId)){
    const back = backTarget("detail");
    const message=detailState.loading ? "正在读取使用记录详情…" : detailState.error || detailState.catalogueError || "没有找到该条目。";
    catalog.innerHTML = `<div class="empty">${esc(message)} ${usageId && !detailState.loading ? '<button class="btn ghost" id="detail-retry">重试</button>' : ""} <a href="${esc(back.href)}">${esc(back.label)}</a></div>`;
    $("#detail-retry")?.addEventListener("click",loadRecordedDetail);
    return;
  }
  const c = catOf(a.category) || { label:"未分类", k:"tool-sys" };
  const g = groupOf(a.category) || { label:"工具", k:"tool" };
  document.title = `${a.name} · AppShelf`;
  $("#crumb").innerHTML = recordedOnly ? `<a href="home.html">首页</a><span> / </span>使用记录<span> / </span>${esc(a.name)}` :
    `<a href="${esc(pageURL("index.html"))}">全部应用</a><span> / </span>` +
    `<a href="${esc(pageURL("category.html",{cat:c.k}))}">${esc(g.label)} · ${esc(c.label)}</a><span> / </span>${esc(a.name)}`;

  const site = a.site
    ? `<a class="site-link" href="https://${esc(a.site)}" target="_blank" rel="noopener">${esc(a.site)} ↗</a>` : "";

  const segs = pathsOf(a).map(p => {
    const seg = pathLabel(p), disk = isDiskPath(p.path);
    return `
      <div class="prow${disk ? "" : " text"}">
        <code>${esc(seg)}</code>
        ${disk ? `<button class="btn mini open-dir" data-p="${esc(p.path)}" ${state.local ? "" : "disabled title='需本地服务'"}>定位</button>` : ""}
        <button class="btn mini copy-path" data-p="${esc(p.path || p.note)}">复制</button>
      </div>`;
  }).join("");

  catalog.innerHTML = `
    <article class="detail">
      <header class="d-head">
        <div class="logo big" style="--c:var(--c-${c.k},#6b6356)">${logoHTML(a)}</div>
        <div class="d-title">
          <h1>${esc(a.name)}</h1>
          <div class="d-tags">
            ${recordedOnly ? `<span class="tag">${unlisted ? "使用记录 · 未收录目录" : "目录资料 · 只读"}</span>` : `<span class="tag" style="--c:var(--c-${c.k},#6b6356)"><i></i>${esc(g.label)} · ${esc(c.label)}</span>`}
            ${recordedOnly ? "" : srcHTML(a)}
            ${recordedOnly ? "" : statusHTML(a)}
            ${a.version ? `<span class="src">版本 ${esc(a.version)}</span>` : ""}
            ${a.architecture ? `<span class="src">${esc(a.architecture)}</span>` : ""}
            ${a.publisher ? `<span class="src">${esc(a.publisher)}</span>` : ""}
            <span class="size" title="磁盘占用">${a.size != null ? fmtSize(a.size) : "占用未知"}</span>
            ${site}
          </div>
        </div>
        ${recordedOnly ? '<span class="src">仅查看记录</span>' : '<button class="btn" id="d-edit" type="button">编辑此条目</button>'}
      </header>
      ${recordedOnly ? "" : statusActionsHTML(a)}
      ${base && detailState.error ? `<p class="d-note">使用记录详情暂不可读取，以下为已收录的目录资料。${esc(detailState.error)}</p>` : ""}

      <section class="d-sec">
        <h2>介绍</h2>
        <p class="d-desc">${esc(a.description || (unlisted ? "这是前台使用记录中的可执行文件，尚未收录应用目录。这里只展示实际读取到的信息。" : "暂无介绍"))}</p>
      </section>

      <section class="d-sec">
        <h2>位置 · 共 ${pathsOf(a).length} 处</h2>
        <p class="d-note">${state.local ? "「定位」会在资源管理器中显示该位置。" : "当前为静态预览，启动本地服务后可定位文件和目录。"}</p>
        <div class="paths">${segs}</div>
      </section>
      ${recordedOnly ? "" : relatedHTML(a,{expanded:true})}
    </article>`;

  setupLogos(catalog);
  bindDetailLinks(catalog);
  bindStatusActions(catalog);
  $("#d-edit")?.addEventListener("click", () => openEditor(a.id));
  $$(".open-dir", catalog).forEach(btn => {
    btn.addEventListener("click", async () => {
      try{
        const j = await apiPost("/api/reveal", {path:btn.dataset.p});
        showToast(j.ok ? "已在资源管理器打开" : (j.error || "打开失败"));
      }catch(e){ showToast(e.message); }
    });
  });
  $$(".copy-path", catalog).forEach(btn => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.p).then(() => {
        showToast("已复制：" + btn.dataset.p);
      }).catch(() => showToast("复制失败，请手动选择路径"));
    });
  });
}

async function bootDetail(){
  pageRender=render;
  setupGlobalSearch();prepareDetailReturn();renderBackLink("detail");
  const params=new URLSearchParams(location.search);
  state.q=params.get("q")||"";state.drive=normalizeDrive(params.get("drive")||"all");
  $("#catalog").innerHTML='<div class="empty">正在读取详情…</div>';
  try{await loadApps();}catch(error){state.data=[];detailState.catalogueError=error.message;}
  if($("#q")) $("#q").value=state.q;
  bindSearch();render();
  if(recordedUsageId()) await loadRecordedDetail();
  if(byId(params.get("id")) || byId(detailState.usageApp?.catalogueId)){
    setupSyncControls();
    if(state.local){await checkStatus();detailState.statusTimer=setInterval(checkStatus,15000);}
  }
}
bootDetail();

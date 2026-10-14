/* ============ AppShelf 详情页 ============ */

function pathSegs(p){
  return String(p || "").split("·").map(s => s.trim()).filter(Boolean);
}

function render(){
  const id = new URLSearchParams(location.search).get("id");
  const a = byId(id);
  const catalog = $("#catalog");

  if(!a){
    catalog.innerHTML = `<div class="empty">没有找到该条目。<a href="index.html">返回总目录</a></div>`;
    return;
  }
  const c = catOf(a.category) || { label:"未分类", k:"tool-sys" };
  const g = groupOf(a.category) || { label:"工具", k:"tool" };
  document.title = `${a.name} · AppShelf`;
  $("#crumb").innerHTML =
    `<a href="index.html">全部应用</a><span> / </span>` +
    `<a href="category.html?cat=${c.k}">${esc(g.label)} · ${esc(c.label)}</a><span> / </span>${esc(a.name)}`;

  const site = a.site
    ? `<a class="site-link" href="https://${esc(a.site)}" target="_blank" rel="noopener">${esc(a.site)} ↗</a>` : "";

  const segs = pathSegs(a.path).map(seg => {
    const disk = /^[A-Za-z]:\\/.test(seg);
    return `
      <div class="prow${disk ? "" : " text"}">
        <code>${esc(seg)}</code>
        ${disk ? `<button class="btn mini open-dir" data-p="${esc(seg)}" ${state.local ? "" : "disabled title='需本地服务（python server.py）'"}>打开目录</button>` : ""}
        <button class="btn mini copy-path" data-p="${esc(seg)}">复制</button>
      </div>`;
  }).join("");

  catalog.innerHTML = `
    <article class="detail">
      <header class="d-head">
        <div class="logo big" style="--c:var(--c-${c.k},#6b6356)">${logoHTML(a)}</div>
        <div class="d-title">
          <h1>${esc(a.name)}</h1>
          <div class="d-tags">
            <span class="tag" style="--c:var(--c-${c.k},#6b6356)"><i></i>${esc(g.label)} · ${esc(c.label)}</span>
            ${srcHTML(a)}
            <span class="size" title="磁盘占用">${a.size != null ? fmtSize(a.size) : "占用未知"}</span>
            ${site}
          </div>
        </div>
        <button class="btn" id="d-edit" type="button">编辑此条目</button>
      </header>

      <section class="d-sec">
        <h2>介绍</h2>
        <p class="d-desc">${esc(a.description)}</p>
      </section>

      <section class="d-sec">
        <h2>位置 · 共 ${pathSegs(a.path).length} 处</h2>
        <p class="d-note">${state.local ? "「打开目录」会在资源管理器中定位该文件夹。" : "当前为静态模式，「打开目录」需用 python server.py 启动本地服务。"}</p>
        <div class="paths">${segs}</div>
      </section>
    </article>`;

  setupLogos(catalog);
  $("#d-edit").addEventListener("click", () => openEditor(a.id));
  $$(".open-dir", catalog).forEach(btn => {
    btn.addEventListener("click", async () => {
      try{
        const r = await fetch("/api/open", {
          method:"POST", headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ path: btn.dataset.p })
        });
        const j = await r.json();
        showToast(j.ok ? "已在资源管理器打开" : (j.error || "打开失败"));
      }catch(_){ showToast("打开失败：需要本地服务"); }
    });
  });
  $$(".copy-path", catalog).forEach(btn => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(btn.dataset.p).then(() => {
        showToast("已复制：" + btn.dataset.p);
      });
    });
  });
}

boot(render);

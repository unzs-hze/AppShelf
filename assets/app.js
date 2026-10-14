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
  { k:"all", label:"全部" },
  { k:"C",   label:"C 盘" },
  { k:"D",   label:"D 盘" },
  { k:"E",   label:"E 盘" },
  { k:"F",   label:"F 盘" },
  { k:"sys", label:"系统内置" }
];

const $  = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s ?? "").replace(/[&<>"]/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[m]));

const state = { q:"", drive:"all", data:[], order:new Map(), local:false };

function catOf(k){ return CATS.find(c => c.k === k); }
function groupOf(k){ const c = catOf(k); return GROUPS.find(g => g.k === (c ? c.g : k)); }

function hl(text, term){
  const s = esc(text);
  if(!term) return s;
  const pat = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return s.replace(new RegExp(pat, "gi"), m => `<mark>${m}</mark>`);
}
function pad(n){ return String(n).padStart(3, "0"); }

/* ---- 盘符与筛选 ---- */
function driveOf(p){
  const m = /[A-Za-z]:\\/.exec(p || "");
  return m ? m[0][0].toUpperCase() : "sys";
}
function visible(a){
  const q = state.q.trim().toLowerCase();
  if(state.drive !== "all" && driveOf(a.path) !== state.drive) return false;
  if(!q) return true;
  return (a.name + a.description + a.path).toLowerCase().includes(q);
}

function fmtSize(b){
  if(b == null || b === "") return "";
  if(b < 1024*1024) return (b/1024).toFixed(0) + " KB";
  if(b < 1024**3)   return (b/1024**2).toFixed(1) + " MB";
  return (b/1024**3).toFixed(2) + " GB";
}
function fmtDate(d){
  if(!d) return "";
  const [y,m,day] = d.split("-");
  return `${y} 年 ${String(+m)} 月 ${String(+day)} 日`;
}

/* ---- 来源徽标 ---- */
function srcHTML(a){
  const q = state.q.trim();
  if(a.source === "bundled")
    return `<span class="src bundled" title="系统或设备厂商预装">系统自带</span>`;
  const date = a.installDate
    ? `<span class="src date" title="按注册表安装记录 / 目录创建时间">${fmtDate(a.installDate)} 安装</span>` : "";
  return `<span class="src dl" title="本机下载安装">下载安装</span>${date}`;
}

/* ---- Logo ---- */
function firstChar(name){
  const m = String(name || "").match(/[A-Za-z0-9\u4e00-\u9fff]/);
  return m ? m[0].toUpperCase() : "?";
}
function logoHTML(a){
  if(!a.site) return `<span class="logo-letter">${esc(firstChar(a.name))}</span>`;
  return `<img class="logo-img" alt="" referrerpolicy="no-referrer"
    data-site="${esc(a.site)}" data-ch="${esc(firstChar(a.name))}"
    src="https://favicon.im/${esc(a.site)}?larger=true">`;
}
function setupLogos(root){
  $$("img.logo-img", root).forEach(img => {
    const alts = [
      `https://api.iowen.cn/favicon/${img.dataset.site}.png`,
      `https://www.google.com/s2/favicons?sz=64&domain=${img.dataset.site}`
    ];
    img.addEventListener("error", () => {
      if(alts.length){ img.src = alts.shift(); return; }
      const s = document.createElement("span");
      s.className = "logo-letter";
      s.textContent = img.dataset.ch || "?";
      img.replaceWith(s);
    });
  });
}

/* ---- 状态徽标（新增 / 已卸载） ---- */
function statusHTML(a){
  if(a.status === "new")     return `<span class="st new" title="扫描发现的新软件，点击编辑补全介绍">新发现</span>`;
  if(a.status === "removed") return `<span class="st removed" title="本机已检测不到该软件">已卸载</span>`;
  return "";
}

/* ---- 条目卡片 ---- */
function pathSegsOf(p){
  return String(p || "").split("·").map(s => s.trim()).filter(Boolean);
}

function entryHTML(a){
  const cat = catOf(a.category) || { label:"未分类", k:"tool-sys" };
  const g   = groupOf(a.category) || { k:"tool" };
  const q   = state.q.trim();
  const size = a.size != null ? fmtSize(a.size) : "—";
  const grp = a.group ? state.data.filter(x => x.group === a.group) : [];
  const grpBadge = grp.length > 1 ? `<span class="grp" title="同族共 ${grp.length} 个版本/副本">×${grp.length}</span>` : "";
  const removed = a.status === "removed";
  // 路径：磁盘路径可点击跳转文件夹；系统说明文字不可点
  const segs = pathSegsOf(a.path).map(seg => {
    const disk = /^[A-Za-z]:\\/.test(seg);
    if(disk) return `<code class="p-seg link" data-p="${esc(seg)}" title="点击在资源管理器中定位">${hl(seg, q)}</code>`;
    return `<code class="p-seg">${hl(seg, q)}</code>`;
  }).join(`<span class="p-dot">·</span>`);
  return `
    <article class="entry${removed ? " is-removed" : ""}" data-id="${esc(a.id)}">
      <div class="num">${pad(state.order.get(a)+1)}</div>
      <div class="logo" style="--c:var(--c-${cat.k},var(--c-${g.k},#6b6356))">${logoHTML(a)}</div>
      <div class="body">
        <div class="name">
          <a class="name-link" href="detail.html?id=${esc(a.id)}">${hl(a.name, q)}</a>${grpBadge}
          <span class="tag" style="--c:var(--c-${cat.k},#6b6356)"><i></i>${esc(cat.label)}</span>
        </div>
        <div class="desc">${hl(a.description, q)}</div>
        <div class="meta">
          ${statusHTML(a)}
          ${srcHTML(a)}
          <span class="size" title="磁盘占用">${size}</span>
        </div>
        <div class="path">
          <span class="p-segs" title="${esc(a.path)}">${segs}</span>
          <button class="copy" data-p="${esc(a.path)}" type="button">复制</button>
        </div>
      </div>
      <button class="edit" data-id="${esc(a.id)}" type="button" title="编辑此条目">编辑</button>
    </article>`;
}

/* 点击卡片跳详情；复制/编辑/路径段除外 */
function bindEntries(root){
  setupLogos(root);
  $$(".entry", root).forEach(en => {
    en.addEventListener("click", e => {
      if(e.target.closest(".copy, .edit, .p-seg.link")) return;
      location.href = "detail.html?id=" + en.dataset.id;
    });
  });
  // 点击路径段 → 资源管理器定位（阻止跳详情）
  $$(".p-seg.link", root).forEach(seg => {
    seg.addEventListener("click", async e => {
      e.stopPropagation();
      const p = seg.dataset.p;
      try{
        const r = await fetch("/api/reveal", { method:"POST",
          headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ path: p }) });
        const j = await r.json();
        showToast(j.ok ? "已定位：" + p : (j.error || "打开失败"));
      }catch(_){ showToast("需本地服务（python server.py）才能定位文件夹"); }
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
}

/* ---- 分区渲染（index 全部子类 / category 单个子类） ---- */
function renderSections(cats){
  const catalog = $("#catalog");
  const shownCats = cats.filter(c => state.data.some(a => a.category === c.k && visible(a)));
  if(!shownCats.length){
    catalog.innerHTML = `<div class="empty">没有匹配「${esc(state.q.trim())}」的应用，换个关键词或盘符试试。</div>`;
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

/* ---- 工具栏：分类 chips（跳转独立页面）+ 盘符筛选 ---- */
function renderCatChips(current){
  const counts = {};
  CATS.forEach(c => counts[c.k] = 0);
  state.data.forEach(a => {
    if(state.drive === "all" || driveOf(a.path) === state.drive) counts[a.category]++;
  });
  const box = $("#chips");
  box.innerHTML = CATS.map(c =>
    `<a class="chip${current===c.k?" on":""}" href="category.html?cat=${c.k}">
       <i style="--c:var(--c-${c.k},#6b6356)"></i>${c.label}<span class="num">${counts[c.k]||0}</span></a>`
  ).join("");
}

function renderDriveChips(scope){
  const q = state.q.trim().toLowerCase();
  const pool = scope ? state.data.filter(a => a.category === scope) : state.data;
  const dcounts = {};
  DRIVES.forEach(d => dcounts[d.k] = 0);
  pool.forEach(a => {
    if(!q || (a.name + a.description + a.path).toLowerCase().includes(q)){
      dcounts[driveOf(a.path)]++;
      dcounts.all++;
    }
  });
  const box = $("#drive-chips");
  box.innerHTML = DRIVES.map(d =>
    `<button class="chip${state.drive===d.k?" on":""}" data-drive="${d.k}">
       <i></i>${d.label}<span class="num">${dcounts[d.k]||0}</span></button>`
  ).join("");
  $$(".chip", box).forEach(btn => {
    btn.addEventListener("click", () => {
      state.drive = btn.dataset.drive;
      pageRender();
    });
  });
}

function bindSearch(){
  const input = $("#q");
  if(!input) return;
  let timer;
  input.addEventListener("input", e => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = e.target.value; pageRender(); }, 120);
  });
}

/* ---- 数据加载：fetch + 静态模式 localStorage 合并 ---- */
const LS_KEY = "appshelf-edits";
async function loadApps(){
  const res = await fetch("data/apps.json");
  if(!res.ok) throw new Error("HTTP " + res.status);
  state.data = await res.json();
  try{
    const edits = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    state.data.forEach((a, i) => {
      const p = edits[a.id];
      if(p) Object.assign(a, p);
      state.order.set(a, i);
    });
  }catch(_){}
  state.data.forEach((a, i) => { if(!state.order.has(a)) state.order.set(a, i); });
  try{
    const ping = await fetch("/api/ping", { method:"POST" });
    state.local = ping.ok;
  }catch(_){ state.local = false; }
}

function byId(id){ return state.data.find(a => a.id === id); }

/* ---- 编辑弹窗 ---- */
function openEditor(id){
  const a = byId(id);
  if(!a) return;
  const catOpts = CATS.map(c =>
    `<option value="${c.k}"${a.category===c.k?" selected":""}>${groupOf(c.k).label} · ${c.label}</option>`).join("");
  const sizeMB = a.size != null ? (a.size/1024**2).toFixed(1) : "";
  const ov = document.createElement("div");
  ov.className = "modal-ov";
  ov.id = "editor";
  ov.innerHTML = `
    <div class="modal">
      <header class="modal-head">
        <h3>编辑条目</h3>
        <button type="button" class="modal-x" title="关闭">✕</button>
      </header>
      <div class="modal-body">
        <label class="fld"><span>名称 *</span><input id="ed-name" value="${esc(a.name)}"></label>
        <div class="fld-row">
          <label class="fld"><span>分类</span><select id="ed-cat">${catOpts}</select></label>
          <label class="fld"><span>来源</span>
            <select id="ed-src">
              <option value="downloaded"${a.source!=="bundled"?" selected":""}>下载安装</option>
              <option value="bundled"${a.source==="bundled"?" selected":""}>系统自带</option>
            </select></label>
        </div>
        <div class="fld-row">
          <label class="fld" id="ed-date-wrap"><span>安装日期</span>
            <input id="ed-date" type="date" value="${esc(a.installDate || "")}"></label>
          <label class="fld"><span>占用 (MB)</span>
            <div class="size-in">
              <input id="ed-size" type="number" min="0" step="0.1" value="${sizeMB}" placeholder="未知">
              <button type="button" id="ed-measure" ${state.local?"":"disabled title='需本地服务'"}>实测</button>
            </div></label>
        </div>
        <label class="fld"><span>官网域名</span><input id="ed-site" value="${esc(a.site || "")}" placeholder="例：jetbrains.com"></label>
        <label class="fld"><span>同族分组（相同分组的多个版本会合并展示，可留空）</span>
          <input id="ed-group" value="${esc(a.group || "")}" placeholder="例：geek、mysql" list="grp-list">
          <datalist id="grp-list">${[...new Set(state.data.map(x=>x.group).filter(Boolean))].map(g=>`<option value="${esc(g)}">`).join("")}</datalist>
        </label>
        <label class="fld"><span>安装路径（一行一个；系统组件可填说明文字）</span>
          <textarea id="ed-paths" rows="3">${esc(a.path)}</textarea></label>
        <label class="fld"><span>介绍 *</span><textarea id="ed-desc" rows="4">${esc(a.description)}</textarea></label>
        <p class="ed-err" id="ed-err" hidden></p>
      </div>
      <footer class="modal-foot">
        <span class="ed-hint">${state.local ? "本地模式 · 保存写入 apps.json" : "静态模式 · 保存到浏览器本地"}</span>
        <button type="button" class="btn ghost" id="ed-cancel">取消</button>
        <button type="button" class="btn" id="ed-save">保存</button>
      </footer>
    </div>`;
  document.body.appendChild(ov);

  const srcSel = $("#ed-src", ov), dateWrap = $("#ed-date-wrap", ov);
  const syncDate = () => { dateWrap.hidden = srcSel.value === "bundled"; };
  srcSel.addEventListener("change", syncDate); syncDate();

  $(".modal-x", ov).addEventListener("click", () => ov.remove());
  $("#ed-cancel", ov).addEventListener("click", () => ov.remove());
  ov.addEventListener("click", e => { if(e.target === ov) ov.remove(); });

  $("#ed-measure", ov).addEventListener("click", async () => {
    const paths = pathsFromText($("#ed-paths", ov).value);
    const first = paths.find(p => /^[A-Za-z]:\\/.test(p));
    if(!first) return edErr("路径里没有可测量的磁盘目录");
    try{
      const r = await fetch("/api/measure", {
        method:"POST", headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ path: first })
      });
      const j = await r.json();
      if(j.error) return edErr(j.error);
      $("#ed-size", ov).value = (j.size/1024**2).toFixed(1);
      edErr("");
    }catch(_){ edErr("测量失败：需要通过 python server.py 打开"); }
  });

  $("#ed-save", ov).addEventListener("click", () => saveEdit(ov, id));
}

function pathsFromText(t){
  return String(t || "").split("\n").map(s => s.trim()).filter(Boolean);
}
function edErr(msg){
  const box = $("#ed-err");
  if(!box) return;
  box.hidden = !msg;
  box.textContent = msg || "";
}

async function saveEdit(ov, id){
  const a = byId(id);
  const patch = {
    name: $("#ed-name", ov).value.trim(),
    category: $("#ed-cat", ov).value,
    source: $("#ed-src", ov).value,
    installDate: $("#ed-src", ov).value === "downloaded" ? ($("#ed-date", ov).value || null) : null,
    site: $("#ed-site", ov).value.trim(),
    group: $("#ed-group", ov).value.trim() || undefined,
    description: $("#ed-desc", ov).value.trim()
  };
  const sizeRaw = $("#ed-size", ov).value.trim();
  patch.size = sizeRaw === "" ? null : Math.max(0, Math.round(parseFloat(sizeRaw) * 1024**2));
  if(isNaN(patch.size)) patch.size = null;

  /* 校验 1：必填 */
  if(!patch.name) return edErr("名称不能为空");
  if(!patch.description) return edErr("介绍不能为空");

  /* 校验 2：路径真实性 —— X:\ 开头的行必须真实存在 */
  const lines = pathsFromText($("#ed-paths", ov).value);
  const disk = lines.filter(l => /^[A-Za-z]:\\/.test(l));
  if(disk.length){
    if(state.local){
      try{
        const r = await fetch("/api/check-path", {
          method:"POST", headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ paths: disk })
        });
        const j = await r.json();
        const bad = (j.results || []).filter(x => !x.exists).map(x => x.path);
        if(bad.length) return edErr("以下路径在本机不存在，请修改：\n" + bad.join("\n"));
      }catch(_){ return edErr("校验服务不可用，请用 python server.py 打开"); }
    }else{
      return edErr("静态模式下无法校验磁盘路径，请用 python server.py 打开后再编辑路径");
    }
  }
  patch.path = lines.join(" · ");

  if(state.local){
    try{
      const r = await fetch("/api/save", {
        method:"POST", headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ id, patch })
      });
      const j = await r.json();
      if(!j.ok) return edErr(j.error || "保存失败");
      Object.assign(a, j.app);
    }catch(e){ return edErr("保存失败：" + e.message); }
  }else{
    const edits = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    edits[id] = Object.assign(edits[id] || {}, patch);
    localStorage.setItem(LS_KEY, JSON.stringify(edits));
    Object.assign(a, patch);
  }
  ov.remove();
  showToast(state.local ? "已保存到 apps.json" : "已保存到浏览器本地");
  pageRender();
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
  try{
    await loadApps();
  }catch(err){
    const c = $("#catalog");
    if(c) c.innerHTML = `<div class="empty">未能加载数据（${err.message}）。请通过本地服务器打开。</div>`;
    return;
  }
  bindSearch();
  render();
}

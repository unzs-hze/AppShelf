/* ============ AppShelf 分类页 ============ */

const cat = catOf(new URLSearchParams(location.search).get("cat"));
if(!cat) location.replace("index.html");

function render(){
  if(!cat) return;
  document.title = `${cat.label} · AppShelf`;
  const pool = state.data.filter(a => a.category === cat.k);
  const shown = pool.filter(visible);
  const g = groupOf(cat.k);

  $("#crumb").innerHTML =
    `<a href="index.html">全部应用</a><span> / </span><b>${esc(g.label)}</b><span> / </span>${esc(cat.label)}`;
  $("#cat-title").innerHTML = `<i style="--c:var(--c-${cat.k},#6b6356)"></i>${esc(cat.label)}`;
  $("#cat-desc").textContent = `${g.label}大类 · ${pool.length} 款应用，合计占用 ${fmtSize(pool.reduce((s, a) => s + (a.size || 0), 0)) || "—"}`;

  renderCatChips(cat.k);
  renderDriveChips(cat.k);
  renderSections([cat]);

  const q = state.q.trim();
  $("#result").innerHTML = (q || state.drive !== "all")
    ? `找到 <b>${shown.length}</b> 款应用`
      + (state.drive !== "all" ? `（${esc(DRIVES.find(d => d.k === state.drive).label)}）` : "")
      + (q ? `（关键词：${esc(q)}）` : "")
    : `本分类共 <b>${pool.length}</b> 款应用 · 点击条目查看详情`;
}

if(cat) boot(render);

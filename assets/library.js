/* Shared library shell: category changes never replace the sidebar or reload data. */
function renderLibrary(options={}){
  const cat = catOf(state.category);
  const group = cat ? groupOf(cat.k) : null;
  $("#library-overview").hidden = !!cat;
  $("#library-category").hidden = !cat;
  $("#library-header").classList.toggle("slim",!!cat);
  document.body.dataset.page = cat ? "category" : "index";
  document.title = cat ? `${cat.label} · AppShelf` : "本机应用清单 · AppShelf";
  $("#q").placeholder = "搜索全部应用 · 名称、用途、路径";
  if(cat){
    renderBackLink("category");
    $("#crumb").innerHTML = `<a href="${esc(pageURL("index.html"))}" id="crumb-all">全部应用</a><span> / </span><b>${esc(group.label)}</b><span> / </span>${esc(cat.label)}`;
    $("#crumb-all").addEventListener("click", e => { if(plainNavigation(e)){ e.preventDefault(); navigateCategory(null); } });
    $("#cat-title").textContent = cat.label;
    const pool = listedApps().filter(a => a.category === cat.k);
    $("#cat-desc").textContent = `${group.label} · ${pool.length} 款应用`;
  }
  if(options.keepSidebar) updateCategorySelection(); else renderCatChips(state.category);
  renderDriveChips(state.category);
  renderSections(cat ? [cat] : CATS);
  const shown = state.data.filter(a => (!cat || a.category === cat.k) && visible(a));
  const parts = [cat ? cat.label : "全部应用",`<b>${shown.length}</b> 款应用`];
  if(state.drive !== "all") parts.push(esc((availableDrives().find(d => d.k === state.drive) || {label:state.drive}).label));
  if(state.q.trim()) parts.push(`搜索「${esc(state.q.trim())}」`);
  $("#result").innerHTML = parts.join(" · ");
  $("#stat-count").textContent = listedApps().length;
  $("#stat-cat").textContent = CATS.length;
  $("#stat-dl").textContent = listedApps().filter(a => a.source === "downloaded").length;
  $("#stat-size").textContent = fmtSize(listedApps().reduce((sum,a) => sum + (a.size || 0),0));
}

function bootLibrary(){
  state.library = true;
  const initial = new URLSearchParams(location.search);
  state.category = initial.get("q") ? null : catOf(initial.get("cat"))?.k || null;
  $("#library-overview").hidden = !!state.category;
  $("#library-category").hidden = !state.category;
  $("#library-header").classList.toggle("slim",!!state.category);
  window.addEventListener("popstate", event => {
    const params = new URLSearchParams(location.search);
    const q = params.get("q") || "", drive = normalizeDrive(params.get("drive") || "all");
    const keepSidebar = state.q === q && state.drive === drive;
    state.q = q; state.drive = drive;
    state.category = catOf(params.get("cat"))?.k || null;
    $("#q").value = q;
    $("#clear-search").hidden = !q;
    renderLibrary({keepSidebar});
    restoreViewPosition(event.state?.appshelfView);
  });
  window.addEventListener("pageshow", event => { if(event.persisted) restoreViewPosition(); });
  window.addEventListener("beforeunload",saveSidebarState);
  return boot(renderLibrary);
}

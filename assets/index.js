/* ============ AppShelf 首页 ============ */

function render(){
  renderCatChips(null);
  renderDriveChips(null);
  renderSections(CATS);

  const q = state.q.trim();
  const shown = state.data.filter(visible);
  if(q || state.drive !== "all"){
    const d = DRIVES.find(d => d.k === state.drive);
    $("#result").innerHTML = `找到 <b>${shown.length}</b> 款应用` +
      (state.drive !== "all" ? `（${esc(d.label)}）` : "") +
      (q ? `（关键词：${esc(q)}）` : "");
  }else{
    $("#result").innerHTML = `共 <b>${shown.length}</b> 款应用，按 ${CATS.length} 个子类分区 · 点分类进入独立页面，点条目看详情`;
  }

  $("#stat-count").textContent = state.data.length;
  $("#stat-cat").textContent = CATS.length;
  $("#stat-dl").textContent = state.data.filter(a => a.source === "downloaded").length;
  $("#stat-size").textContent = fmtSize(state.data.reduce((s, a) => s + (a.size || 0), 0));
}

boot(render);

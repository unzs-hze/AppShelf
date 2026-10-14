/* ============ AppShelf 渲染与交互 ============ */

const CATS = [
  { k:"sys", label:"系统 · 硬件驱动" },
  { k:"dev", label:"开发 · 编程" },
  { k:"ai",  label:"AI 工具" },
  { k:"off", label:"办公 · 文档 · 影音" },
  { k:"net", label:"网络 · 下载 · 通讯" },
  { k:"game",label:"游戏 · 游戏平台" },
  { k:"lib", label:"运行库 · 反作弊 · 组件" }
];

const $ = (s, el=document) => el.querySelector(s);
const esc = s => String(s).replace(/[&<>]/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;" }[m]));

const state = { q:"", cat:"all", data:[] };

function catOf(k){ return CATS.find(c => c.k === k); }

function hl(text, term){
  const s = esc(text);
  if(!term) return s;
  const pat = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return s.replace(new RegExp(pat, "gi"), m => `<mark>${m}</mark>`);
}

function pad(n){ return String(n).padStart(3, "0"); }

function filtered(){
  const q = state.q.trim().toLowerCase();
  return state.data.filter(a => {
    if(state.cat !== "all" && a.category !== state.cat) return false;
    if(!q) return true;
    return (a.name + a.description + a.path).toLowerCase().includes(q);
  });
}

function renderChips(){
  const counts = {};
  state.data.forEach(a => { counts[a.category] = (counts[a.category]||0)+1; });
  const chips = $("#chips");
  let html = `<button class="chip on" data-cat="all"><i style="--c:var(--ink)"></i>全部<span class="num">${state.data.length}</span></button>`;
  CATS.forEach(c => {
    html += `<button class="chip" data-cat="${c.k}"><i style="--c:var(--c-${c.k})"></i>${c.label}<span class="num">${counts[c.k]||0}</span></button>`;
  });
  chips.innerHTML = html;
  chips.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => {
      chips.querySelectorAll(".chip").forEach(x => x.classList.remove("on"));
      btn.classList.add("on");
      state.cat = btn.dataset.cat;
      render();
    });
  });
}

function render(){
  const list = filtered();
  const q = state.q.trim();
  $("#stat-count").textContent = state.data.length;
  $("#stat-cat").textContent = CATS.length;

  const res = $("#result");
  if(q || state.cat !== "all"){
    res.innerHTML = `找到 <b>${list.length}</b> 款应用${q ? `（关键词：${esc(q)}）`:""}`;
  } else {
    res.innerHTML = `共 <b>${list.length}</b> 款应用，按安装顺序排列`;
  }

  const catalog = $("#catalog");
  if(!list.length){
    catalog.innerHTML = `<div class="empty">没有匹配「${esc(q)}」的应用，换个关键词试试。</div>`;
    return;
  }

  catalog.innerHTML = list.map((a, i) => {
    const cat = catOf(a.category) || { label:"其他", k:"lib" };
    return `
      <article class="entry">
        <div class="num">${pad(i+1)}</div>
        <div class="body">
          <div class="name">
            <span>${hl(a.name, q)}</span>
            <span class="tag" style="--c:var(--c-${cat.k})"><i></i>${esc(cat.label)}</span>
          </div>
          <div class="desc">${hl(a.description, q)}</div>
          <div class="path">
            <code title="${esc(a.path)}">${hl(a.path, q)}</code>
            <button class="copy" data-p="${esc(a.path)}" type="button">复制</button>
          </div>
        </div>
      </article>`;
  }).join("");

  catalog.querySelectorAll(".copy").forEach(btn => {
    btn.addEventListener("click", e => {
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
}

let toastTimer;
function showToast(msg){
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
}

function bindSearch(){
  const input = $("#q");
  let timer;
  input.addEventListener("input", e => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.q = e.target.value; render(); }, 120);
  });
}

/* 启动 */
async function init(){
  try{
    const res = await fetch("data/apps.json");
    if(!res.ok) throw new Error("HTTP " + res.status);
    state.data = await res.json();
  }catch(err){
    $("#catalog").innerHTML = `<div class="empty">未能加载数据（${err.message}）。请通过本地服务器打开，或将 apps.json 路径指向正确位置。</div>`;
    return;
  }
  renderChips();
  bindSearch();
  render();
}

init();

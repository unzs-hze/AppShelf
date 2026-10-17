/* AppShelf · 真实前台使用记录。只展示接口返回的数据。 */
const usageState = {period:"day",date:"",chart:"line",payload:null,payloadKey:"",loading:false,request:0,controller:null,initialized:false,timer:null};
const USAGE_PERIODS = ["day","week","month"];
const USAGE_CHARTS = ["line","bar"];

function usageDateKey(date=new Date()){
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
}
function usageParseDate(key){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(String(key || ""))) return null;
  const [year,month,day] = key.split("-").map(Number);
  const date = new Date(year,month-1,day,12);
  return usageDateKey(date) === key ? date : null;
}
function usageLaunchQuote(){
  return state.quote || "时间花在哪里，生活就慢慢长成哪里的样子。";
}
function usageRange(period,key){
  const start = usageParseDate(key);
  if(!start) throw new Error("统计日期无效");
  if(period === "week") start.setDate(start.getDate()-((start.getDay()+6)%7));
  if(period === "month") start.setDate(1);
  const end = new Date(start);
  if(period === "month") end.setMonth(end.getMonth()+1);
  else end.setDate(end.getDate()+(period === "week" ? 7 : 1));
  return {start:usageDateKey(start),end:usageDateKey(end)};
}
function usageShiftDate(key,period,amount){
  const date = usageParseDate(key);
  if(!date) throw new Error("统计日期无效");
  if(period === "month"){date.setDate(1);date.setMonth(date.getMonth()+amount);}
  else date.setDate(date.getDate()+amount*(period === "week" ? 7 : 1));
  return usageDateKey(date);
}
function usageRangeLabel(period,key){
  const range = usageRange(period,key);
  const first = usageParseDate(range.start), last = usageParseDate(range.end);
  last.setDate(last.getDate()-1);
  if(period === "month") return `${first.getFullYear()} 年 ${first.getMonth()+1} 月`;
  if(period === "day") return `${first.getFullYear()} 年 ${first.getMonth()+1} 月 ${first.getDate()} 日`;
  const firstLabel = `${first.getFullYear()} 年 ${first.getMonth()+1} 月 ${first.getDate()} 日`;
  const lastLabel = `${last.getFullYear() !== first.getFullYear() ? last.getFullYear()+" 年 " : ""}${last.getMonth()+1} 月 ${last.getDate()} 日`;
  return firstLabel + " — " + lastLabel;
}
function usageSeconds(value){
  if(typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error("使用时间记录格式不正确");
  return value;
}
function usageDuration(seconds){
  const numeric=Number(seconds),total=Number.isFinite(numeric) ? Math.max(0,numeric) : 0;
  if(total>0 && total<1) return "不足 1 秒";
  const value=Math.floor(total),hours=Math.floor(value/3600),minutes=Math.floor(value%3600/60),rest=value%60;
  return [hours ? hours+" 小时" : "",minutes ? minutes+" 分钟" : "",rest || !value ? rest+" 秒" : ""].filter(Boolean).join(" ");
}
function usageDurationHTML(seconds){
  return usageDuration(seconds).replace(/(\d+) (小时|分钟|秒)/g,"$1<small>$2</small>").replace(/ /g,"");
}
function usageNormalize(payload){
  if(!payload || !USAGE_PERIODS.includes(payload.period) || !usageParseDate(payload.date) || !Array.isArray(payload.buckets) || !Array.isArray(payload.apps) || payload.buckets.length > 96) throw new Error("使用时间记录格式不正确");
  return {...payload,totalSeconds:usageSeconds(payload.totalSeconds),
    buckets:payload.buckets.map(bucket => {
      if(!bucket || typeof bucket.label !== "string") throw new Error("时间分布格式不正确");
      return {...bucket,seconds:usageSeconds(bucket.seconds)};
    }),
    apps:payload.apps.map(app => {
      if(!app || typeof app.name !== "string" || !app.name.trim()) throw new Error("应用记录格式不正确");
      return {id:typeof app.id === "string" ? app.id : "",catalogueId:typeof app.catalogueId === "string" ? app.catalogueId : null,name:app.name,path:typeof app.path === "string" ? app.path : "",seconds:usageSeconds(app.seconds)};
    }).filter(app => app.seconds > 0).sort((a,b) => b.seconds-a.seconds || a.name.localeCompare(b.name,"zh-CN")),
    status:payload.status && typeof payload.status === "object" ? payload.status : {}
  };
}
function usageAxisDuration(seconds){
  if(seconds >= 3600) return Number((seconds/3600).toFixed(1)) + " 时";
  if(seconds >= 60) return Number((seconds/60).toFixed(1)) + " 分";
  return Math.round(seconds) + " 秒";
}
function usageChartExactDuration(seconds){
  const value=Math.max(0,Number(seconds)||0),hours=Math.floor(value/3600),minutes=Math.floor(value%3600/60),rest=Number((value%60).toFixed(3));
  return ((hours ? hours+" 小时 " : "")+(minutes ? minutes+" 分钟 " : "")+(rest || (!hours && !minutes) ? rest+" 秒" : "")).trim();
}
function usageChartInterval(bucket,period="day"){
  const start=String(bucket.start||"").match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/);
  const end=String(bucket.end||"").match(/^\d{4}-\d{2}-\d{2}T(\d{2}:\d{2})/);
  if(!start) return bucket.label;
  const date=Number(start[2])+" 月 "+Number(start[3])+" 日";
  return period==="day" && end ? date+" · "+start[4]+"–"+end[1] : date;
}
function usageChartNumber(value){
  if(value>0 && value<.01) return "<0.01";
  return String(Number(value.toFixed(value<1 ? 2 : 1)));
}
function usageChartSVG(buckets,renderWidth=920,options={}){
  const period=options.period||"day",kind=USAGE_CHARTS.includes(options.chart) ? options.chart : "line",left=49,right=15,top=30,bottom=33,height=218;
  const requestedWidth=Number(renderWidth);
  const width=Math.max(300,Number.isFinite(requestedWidth) && requestedWidth>0 ? Math.min(2000,requestedWidth) : 920,left+right+buckets.length*36);
  const chartWidth=width-left-right,chartHeight=height-top-bottom,cell=chartWidth/Math.max(1,buckets.length);
  const now=options.now??Date.now(),starts=buckets.map(bucket=>Date.parse(bucket.start)),ends=buckets.map(bucket=>Date.parse(bucket.end));
  const isFuture=index=>Number.isFinite(starts[index]) && starts[index]>now;
  const maximum=Math.max(0,...buckets.filter((_,index)=>!isFuture(index)).map(bucket=>bucket.seconds));
  const unit=maximum>=7200 ? {seconds:3600,label:"小时",short:"时"} : maximum>=120 ? {seconds:60,label:"分钟",short:"分"} : {seconds:1,label:"秒",short:"秒"};
  const target=Math.max(maximum/unit.seconds/3,.1),magnitude=10**Math.floor(Math.log10(target));
  const step=([1,2,5,10].find(value=>value*magnitude>=target)||10)*magnitude;
  const ticks=Math.max(1,Math.ceil(maximum/unit.seconds/step)),ceiling=step*ticks*unit.seconds;
  const firstFuture=starts.findIndex(start=>Number.isFinite(start) && start>now);
  const futureWidth=firstFuture<0 ? 0 : cell*(buckets.length-firstFuture);
  const future=firstFuture<0 ? "" : `<rect class="usage-future-zone" x="${(left+firstFuture*cell).toFixed(2)}" y="${top-12}" width="${futureWidth.toFixed(2)}" height="${chartHeight+12}"/>${futureWidth>=90 ? `<text class="usage-future-label" x="${(left+firstFuture*cell+futureWidth/2).toFixed(2)}" y="${top+13}" text-anchor="middle">尚未发生</text>` : ""}`;
  const grid=Array.from({length:ticks+1},(_,index)=>{
    const y=top+chartHeight-index/ticks*chartHeight;
    return `<line class="usage-grid${index===0 ? " is-baseline" : ""}" x1="${left}" y1="${y.toFixed(2)}" x2="${width-right}" y2="${y.toFixed(2)}"/><text class="usage-axis-label" x="${left-10}" y="${(y+3).toFixed(2)}" text-anchor="end">${usageChartNumber(index*step)}</text>`;
  }).join("");
  const points=buckets.map((bucket,index)=>({x:left+cell*(index+.5),y:top+chartHeight-bucket.seconds/ceiling*chartHeight,future:isFuture(index)}));
  const segments=[];
  points.forEach(point=>{
    if(point.future){if(segments.at(-1)?.length) segments.push([]);return;}
    if(!segments.length) segments.push([]);
    segments.at(-1).push(point);
  });
  const line=kind!=="line" ? "" : segments.filter(segment=>segment.length>1).map(segment=>{
    const path=segment.map((point,index)=>(index ? "L" : "M")+point.x.toFixed(2)+","+point.y.toFixed(2)).join(" ");
    const area=`M${segment[0].x.toFixed(2)},${top+chartHeight} L${path.slice(1)} L${segment.at(-1).x.toFixed(2)},${top+chartHeight} Z`;
    return `<path class="usage-line-area" d="${area}"/><path class="usage-line" d="${path}"/>`;
  }).join("");
  const barWidth=Math.min(68,cell*.7);
  const bars=buckets.map((bucket,index)=>{
    const x=left+cell*(index+.5),barHeight=bucket.seconds>0 ? Math.max(2,bucket.seconds/ceiling*chartHeight) : 0,y=top+chartHeight-barHeight;
    const future=isFuture(index),isCurrent=Number.isFinite(starts[index]) && Number.isFinite(ends[index]) && starts[index]<=now && ends[index]>now;
    const description=esc(usageChartInterval(bucket,period)+"，"+(future ? "尚未发生" : usageChartExactDuration(bucket.seconds)+(isCurrent ? "，当前时段" : "")));
    const label=period==="day" && /^\d{2}:00$/.test(bucket.label) ? bucket.label.slice(0,2) : bucket.label;
    const mark=future ? "" : kind==="line" ? `<circle class="usage-line-point" cx="${x.toFixed(2)}" cy="${points[index].y.toFixed(2)}" r="3"/>` : bucket.seconds>0 ? `<rect class="usage-bar" x="${(x-barWidth/2).toFixed(2)}" y="${y.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${barHeight.toFixed(2)}" rx="3"/><text class="usage-bar-value" x="${x.toFixed(2)}" y="${Math.max(12,y-7).toFixed(2)}" text-anchor="middle">${esc(usageChartNumber(bucket.seconds/unit.seconds)+unit.short)}</text>` : `<circle class="usage-zero" cx="${x.toFixed(2)}" cy="${top+chartHeight}" r="1.5"/>`;
    return `<g class="usage-bar-group${future ? " is-future" : ""}${isCurrent ? " is-current" : ""}"${future ? "" : ` data-bucket="${index}" tabindex="0" aria-describedby="usage-chart-tooltip"`} role="img" aria-label="${description}"><title>${description}</title>${future ? "" : `<rect class="usage-bar-hit" x="${(left+cell*index+2).toFixed(2)}" y="${top-15}" width="${Math.max(1,cell-4).toFixed(2)}" height="${chartHeight+34}" rx="4"/>`}${mark}<text class="usage-axis-label usage-time-label" x="${x.toFixed(2)}" y="${height-12}" text-anchor="middle">${esc(label)}</text></g>`;
  }).join("");
  return `<svg viewBox="0 0 ${width} ${height}" style="width:${width}px;min-width:100%" data-chart="${kind}" role="group" aria-labelledby="usage-chart-title usage-chart-description"><title id="usage-chart-title">前台应用使用时间${kind==="line" ? "折线图" : "柱状图"}</title><desc id="usage-chart-description">${esc(buckets.map((bucket,index)=>bucket.label+"："+(isFuture(index) ? "尚未发生" : usageChartExactDuration(bucket.seconds))).join("；"))}</desc><text class="usage-axis-unit" x="${left-10}" y="13" text-anchor="end">${unit.label}</text>${future}${grid}${line}${bars}</svg>`;
}
function usageBindChart(chart,payload,selectedIndex=null){
  const tooltip=chart.querySelector?.(".usage-chart-tooltip"),groups=Array.from(chart.querySelectorAll?.("[data-bucket]")||[]);
  if(!tooltip) return;
  const hide=()=>{tooltip.hidden=true;groups.forEach(group=>group.classList.remove("is-selected"));};
  const show=group=>{
    const bucket=payload.buckets[Number(group.dataset.bucket)];
    if(!bucket) return;
    groups.forEach(item=>item.classList.toggle("is-selected",item===group));
    tooltip.innerHTML=`<strong>${esc(usageChartInterval(bucket,payload.period))}</strong><span>${esc(usageChartExactDuration(bucket.seconds))}</span>`;
    tooltip.hidden=false;
    const box=chart.getBoundingClientRect(),bar=group.getBoundingClientRect();
    tooltip.style.left=Math.max(6,Math.min(chart.clientWidth-tooltip.offsetWidth-6,bar.left-box.left+bar.width/2-tooltip.offsetWidth/2))+"px";
    tooltip.style.top=Math.max(1,bar.top-box.top-tooltip.offsetHeight-5)+"px";
  };
  groups.forEach((group,index)=>{
    group.addEventListener("pointerenter",()=>show(group));
    group.addEventListener("pointerleave",()=>{if(document.activeElement!==group) hide();});
    group.addEventListener("focus",()=>show(group));group.addEventListener("blur",hide);
    group.addEventListener("keydown",event=>{
      if(event.key==="Escape"){hide();return;}
      const next=event.key==="ArrowRight" ? Math.min(groups.length-1,index+1) : event.key==="ArrowLeft" ? Math.max(0,index-1) : event.key==="Home" ? 0 : event.key==="End" ? groups.length-1 : -1;
      if(next>=0){event.preventDefault();groups[next].focus();groups[next].scrollIntoView({block:"nearest",inline:"nearest"});}
    });
  });
  chart.querySelector(".usage-chart-viewport")?.addEventListener("scroll",()=>{
    if(groups.includes(document.activeElement)) show(document.activeElement);else hide();
  },{passive:true});
  if(selectedIndex!==null){const selected=groups.find(group=>group.dataset.bucket===selectedIndex);if(selected) show(selected);}
  return {hide};
}
function usageEmptyHTML(title,message){
  return `<div class="usage-empty"><svg viewBox="0 0 40 40" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><circle cx="20" cy="20" r="15"/><path d="M20 10v10l6 4" stroke-linecap="round"/></svg><h3>${esc(title)}</h3><p>${esc(message)}</p></div>`;
}
function usageToneScale(apps){
  // Spread distinct durations across the palette so seconds remain distinguishable beside hours.
  const times=[...new Set(apps.map(app=>app.seconds).filter(seconds=>Number.isFinite(seconds) && seconds>0))].sort((a,b)=>a-b);
  return new Map(times.map((seconds,index)=>[seconds,times.length>1 ? index/(times.length-1) : 1]));
}
function usageProgressValues(seconds,total,maximum,tone){
  const value=Number.isFinite(seconds) ? Math.max(0,seconds) : 0;
  const lengthRatio=Number.isFinite(maximum) && maximum>0 ? Math.min(1,value/maximum) : 0;
  const ratio=Number.isFinite(tone) ? Math.max(0,Math.min(1,tone)) : maximum>0 ? Math.min(1,value/maximum) : 0;
  const mix=(light,middle,dark)=>{
    const pivot=.36;
    const from=ratio<=pivot ? light : middle,to=ratio<=pivot ? middle : dark;
    const amount=ratio<=pivot ? ratio/pivot : (ratio-pivot)/(1-pivot);
    return "rgb("+from.map((channel,index)=>Math.round(channel+(to[index]-channel)*amount)).join(",")+")";
  };
  // A visible starting mark prevents short sessions disappearing below one pixel.
  return {width:(value>0 && lengthRatio>0 ? 6+94*lengthRatio : 0).toFixed(3)+"%",
    barColor:mix([236,201,139],[207,131,53],[111,22,14]),textColor:mix([130,100,50],[123,66,29],[96,16,17])};
}
function usageRankingHTML(apps,totalSeconds){
  const maximum=apps.reduce((max,app)=>Math.max(max,app.seconds),0);
  const tones=usageToneScale(apps);
  return apps.map((app,index)=>{
    const known=state.data.find(item=>item.id===(app.catalogueId||app.id));
    const subtitle=known?.version ? known.version+(app.path ? " · "+app.path : "") : app.path;
    const progress=usageProgressValues(app.seconds,totalSeconds,maximum,tones.get(app.seconds));
    const content=`<span class="usage-rank" aria-label="第 ${index+1} 位">${String(index+1).padStart(2,"0")}</span><span class="logo">${logoHTML({...known,name:known?.name || app.name,usageId:app.id})}</span><span class="usage-app-info"><span class="usage-app-name" title="${esc(app.name)}">${esc(app.name)}</span><span class="usage-app-path" title="${esc(subtitle)}">${esc(subtitle || "前台应用")}</span></span><span class="usage-progress" aria-hidden="true"><span style="width:${progress.width};--usage-bar-color:${progress.barColor}"></span></span><span class="usage-app-duration" style="--usage-time-color:${progress.textColor}">${usageDuration(app.seconds)}</span>`;
    const params=usageDetailParams(app);
    return params ? `<li><a class="usage-app-row detail-link"${params.id ? ` data-detail-id="${esc(params.id)}"` : ""}${params.usageId ? ` data-usage-id="${esc(params.usageId)}"` : ""} href="${esc(pageURL("detail.html",params))}">${content}</a></li>` : `<li class="usage-app-row">${content}</li>`;
  }).join("");
}
function usageRenderControls(options={}){
  $("#usage-quote").textContent=usageLaunchQuote();
  $$("[data-period]").forEach(button=>{
    const selected=button.dataset.period===usageState.period;
    button.classList.toggle("is-active",selected);button.setAttribute("aria-pressed",String(selected));
  });
  $$("button[data-chart]").forEach(button=>{
    const selected=button.dataset.chart===usageState.chart;
    button.classList.toggle("is-active",selected);button.setAttribute("aria-pressed",String(selected));
  });
  if(!options.quiet) $("#usage-date").value=usageState.date;
  $("#usage-date").max=usageDateKey();
  $("#usage-range").textContent=usageRangeLabel(usageState.period,usageState.date);
  const current=usageRange(usageState.period,usageDateKey()).start;
  const selected=usageRange(usageState.period,usageState.date).start;
  $("#usage-next").disabled=selected>=current;
  $("#usage-today").disabled=selected===current;
  $("#usage-today").textContent={day:"回到今天",week:"回到本周",month:"回到本月"}[usageState.period];
  $("#usage-chart-subtitle").textContent=usageState.period==="day" ? "按小时" : "按天";
  if(!options.quiet) $("#usage-refresh").disabled=usageState.loading || !state.local;
}
function usageShowMessage(message,retry=true){
  $("#usage-message").hidden=!message;
  $("#usage-message-text").textContent=message||"";
  $("#usage-retry").hidden=!retry;
}
function usageNormalizeBackground(value){
  if(!value || ["enabled","running","startup"].some(key=>typeof value[key]!=="boolean")) throw new Error("后台设置格式不正确");
  return {enabled:value.enabled,running:value.running,startup:value.startup,error:value.error ? String(value.error) : null};
}
function usageRenderBackground(value){
  usageState.background=value;
  $("#usage-background-toggle").checked=value.enabled;
  $("#usage-background-toggle").disabled=!!usageState.backgroundBusy || !state.local;
  const label=value.error ? "设置未完全生效："+value.error : value.enabled ? (value.running ? (value.startup ? "后台记录中 · 已开启登录自启" : "后台记录中 · 登录自启未开启") : "后台已开启，记录服务尚未运行") : "后台记录和登录自启已关闭";
  if($("#usage-background-status").textContent!==label) $("#usage-background-status").textContent=label;
  $("#usage-background-retry").hidden=!value.error;
}
async function usageLoadBackground(){
  if(!state.local || usageState.backgroundBusy) return;
  const request=(usageState.backgroundRequest||0)+1;usageState.backgroundRequest=request;usageState.backgroundBusy=true;
  $("#usage-background-toggle").disabled=true;
  try{
    const response=await fetch("/api/usage/background",{cache:"no-store"});
    const value=await response.json();
    if(!response.ok) throw new Error(value.error||"无法读取后台设置");
    if(request!==usageState.backgroundRequest) return;
    usageRenderBackground(usageNormalizeBackground(value));
  }catch(error){
    if(request!==usageState.backgroundRequest) return;
    $("#usage-background-status").textContent="无法读取后台设置："+error.message;
    $("#usage-background-retry").hidden=false;
  }finally{
    if(request===usageState.backgroundRequest){usageState.backgroundBusy=false;$("#usage-background-toggle").disabled=!usageState.background;}
  }
}
async function usageSetBackground(enabled){
  if(!state.local || usageState.backgroundBusy || !usageState.background) return;
  const previous=usageState.background;
  const request=(usageState.backgroundRequest||0)+1;usageState.backgroundRequest=request;usageState.backgroundBusy=true;
  $("#usage-background-toggle").disabled=true;
  $("#usage-background-status").textContent="正在保存…";
  try{
    const value=await apiPost("/api/usage/background",{enabled:!!enabled});
    if(request!==usageState.backgroundRequest) return;
    usageRenderBackground(usageNormalizeBackground(value));
  }catch(error){
    if(request!==usageState.backgroundRequest) return;
    $("#usage-background-toggle").checked=previous.enabled;
    $("#usage-background-status").textContent="更改失败："+error.message;
    $("#usage-background-retry").hidden=false;
  }finally{
    if(request===usageState.backgroundRequest){usageState.backgroundBusy=false;$("#usage-background-toggle").disabled=false;}
  }
}
function usageRestorePosition(){
  if(!usageState.restorePending) return;
  usageState.restorePending=false;
  if(typeof restoreViewPosition==="function") restoreViewPosition(usageState.returnPosition);
  usageState.returnPosition=null;
}
function usageTrackingInfo(status={}){
  if(status.error) return {label:"记录暂不可用",tracking:false,paused:false,title:String(status.error)};
  const labels={idle:"闲置已暂停",locked:"锁屏已暂停","screen-off":"熄屏已暂停","another-instance":"另一个 AppShelf 正在记录",unsupported:"当前系统不支持记录",stopped:"记录已暂停",unavailable:"等待前台应用","sampling-gap":"正在恢复记录"};
  const paused=!!status.idle || !!status.paused || ["idle","locked","screen-off","unavailable","sampling-gap"].includes(status.state);
  const tracking=!!status.tracking && !paused && (!status.state || status.state==="active");
  const label=labels[status.state] || (status.idle || status.paused ? "闲置已暂停" : tracking ? "正在记录" : "记录已暂停");
  const idle=typeof status.idleThreshold==="number" && status.idleThreshold>0 ? `；连续 ${usageDuration(status.idleThreshold)} 无操作后暂停` : "；阅读或观看时继续计时";
  return {label,tracking,paused,title:"前台停留时间由后台记录服务统计；锁屏、熄屏或睡眠时暂停"+idle};
}
function usageRenderTracking(status={}){
  const info=usageTrackingInfo(status);
  $("#usage-tracker").classList.toggle("is-tracking",info.tracking);
  $("#usage-tracker").classList.toggle("is-paused",info.paused);
  const label=state.local ? info.label : "本地记录";
  if($("#tracking-label").textContent!==label) $("#tracking-label").textContent=label;
  $("#usage-tracker").title=info.title;
  const since=status.since ? new Date(status.since) : null;
  $("#usage-since").textContent=since && !isNaN(since.getTime()) ? ` 开始记录：${since.getFullYear()} 年 ${since.getMonth()+1} 月 ${since.getDate()} 日 ${since.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})}。` : "";
}
function usageRenderPayload(payload){
  $("#usage-total").innerHTML=usageDurationHTML(payload.totalSeconds);
  $("#usage-app-count").textContent=String(payload.apps.length);
  $("#usage-top-name").textContent=payload.apps[0]?.name||"—";
  $("#usage-top-name").title=payload.apps[0]?.name||"";
  const top=payload.apps[0],known=top && state.data.find(item=>item.id===(top.catalogueId||top.id));
  $("#usage-top-logo").hidden=!top;
  $("#usage-top-logo").innerHTML=top ? logoHTML({...known,name:known?.name || top.name,usageId:top.id}) : "";
  setupLogos($("#usage-top-logo"));
  $("#usage-top-time").textContent=payload.apps.length ? usageDuration(payload.apps[0].seconds) : "本周期还没有记录";
  $("#usage-ranking-count").textContent=payload.apps.length ? `${payload.apps.length} 款应用` : "";
  usageRenderChart(payload);
  usageRenderRanking(payload);
  usageRenderTracking(payload.status);
}
function usageRenderRanking(payload){
  const list=$("#usage-app-list"),active=list.contains?.(document.activeElement) ? document.activeElement : null;
  const rows=Array.from(list.querySelectorAll?.(".usage-app-row")||[]);
  const signature=JSON.stringify(payload.apps.map(app=>({...app,seconds:0,known:state.data.find(item=>item.id===(app.catalogueId||app.id))})));
  if(signature===usageState.rankingSignature && rows.length===payload.apps.length && rows.length){
    const maximum=payload.apps.reduce((max,app)=>Math.max(max,app.seconds),0);
    const tones=usageToneScale(payload.apps);
    rows.forEach((row,index)=>{
      const app=payload.apps[index],duration=row.querySelector(".usage-app-duration"),progress=row.querySelector(".usage-progress > span");
      const value=usageProgressValues(app.seconds,payload.totalSeconds,maximum,tones.get(app.seconds));
      if(duration){duration.textContent=usageDuration(app.seconds);duration.style.setProperty("--usage-time-color",value.textColor);}
      if(progress){progress.style.width=value.width;progress.style.setProperty("--usage-bar-color",value.barColor);}
    });
    return;
  }
  const identity=active?.dataset;
  list.innerHTML=payload.apps.length ? usageRankingHTML(payload.apps,payload.totalSeconds) : `<li>${usageEmptyHTML("等待下一次打开应用","有前台活动的应用会按使用时间出现在这里。")}</li>`;
  usageState.rankingSignature=signature;
  setupLogos(list);bindDetailLinks(list);
  if(identity && (identity.usageId || identity.detailId)){
    Array.from(list.querySelectorAll?.("a.detail-link")||[]).find(link=>link.dataset.usageId===identity.usageId && link.dataset.detailId===identity.detailId)?.focus({preventScroll:true});
  }
}
function usageRenderChart(payload){
  const chart=$("#usage-chart"),hasActivity=payload.buckets.some(bucket=>bucket.seconds>0);
  const width=chart.clientWidth ? Math.max(300,chart.clientWidth-36) : 920;
  const scrollLeft=chart.querySelector?.(".usage-chart-viewport")?.scrollLeft||0;
  const focusedIndex=chart.contains?.(document.activeElement) ? document.activeElement?.dataset?.bucket : null;
  const selectedIndex=chart.querySelector?.(".usage-bar-group.is-selected")?.dataset?.bucket ?? null;
  usageState.chartWidth=Math.round(width);
  if(!hasActivity){chart.innerHTML=usageEmptyHTML("这个周期还没有记录","开始使用电脑后，这里会逐步显示记录。历史时间不会补算。");return;}
  const peak=payload.buckets.reduce((best,bucket)=>bucket.seconds>best.seconds ? bucket : best,payload.buckets[0]);
  chart.innerHTML=`<div class="usage-chart-viewport" role="region" aria-label="完整时间轴，小屏可横向滚动">${usageChartSVG(payload.buckets,width,{period:payload.period,chart:usageState.chart})}</div><div class="usage-chart-tooltip" id="usage-chart-tooltip" role="tooltip" hidden></div><div class="usage-chart-caption"><p><span>高峰</span> ${esc(usageChartInterval(peak,payload.period))} <strong>${esc(usageChartExactDuration(peak.seconds))}</strong></p><span>悬停或聚焦${usageState.chart==="bar" ? "柱形" : "数据点"}查看明细</span></div>`;
  const viewport=chart.querySelector?.(".usage-chart-viewport");
  if(viewport) viewport.scrollLeft=scrollLeft;
  const interaction=usageBindChart(chart,payload,selectedIndex);
  if(/^\d+$/.test(focusedIndex||"")) chart.querySelector?.(`[data-bucket="${focusedIndex}"]`)?.focus({preventScroll:true});
  if(selectedIndex===null && focusedIndex!==null) interaction?.hide();
}
function usageRenderUnavailable(staticMode=false){
  $("#usage-total").textContent="—";$("#usage-app-count").textContent="—";
  $("#usage-top-name").textContent="—";$("#usage-top-name").title="";
  $("#usage-top-logo").hidden=true;$("#usage-top-logo").innerHTML="";
  $("#usage-top-time").textContent=staticMode ? "需要本地使用记录" : "等待真实记录";
  $("#usage-ranking-count").textContent="";
  const empty=usageEmptyHTML(staticMode ? "在桌面版中查看使用时间" : "暂时无法读取记录",staticMode ? "在本机运行 AppShelf 后，这里会逐步显示真实记录。静态预览不会记录电脑活动。" : "已有记录会保留在本机，请稍后重试。");
  $("#usage-chart").innerHTML=empty;$("#usage-app-list").innerHTML="";
  usageRenderTracking(staticMode ? {} : {error:"暂时无法读取记录状态"});
  if(staticMode) $("#usage-updated").textContent="静态预览 · 没有模拟数据";
}
function usageUpdateURL(){
  const params=new URLSearchParams(location.search);
  params.set("period",usageState.period);params.set("date",usageState.date);params.set("chart",usageState.chart);
  history.replaceState(history.state,"",location.pathname+"?"+params);
}
function usageChooseChart(kind){
  if(!USAGE_CHARTS.includes(kind)) return;
  usageState.chart=kind;
  usageRenderControls();usageUpdateURL();
  if(usageState.payload && usageState.payloadKey===usageState.period+":"+usageState.date) usageRenderChart(usageState.payload);
}
async function usageLoad(options={}){
  if(!state.local || (options.quiet && (document.hidden || state.editing || usageState.loading))) return;
  usageState.controller?.abort();
  const controller=new AbortController(),request=++usageState.request;
  const period=usageState.period,date=usageState.date,key=period+":"+date,backgroundRequest=usageState.backgroundRequest||0;
  const quiet=!!options.quiet && usageState.payloadKey===key;
  usageState.controller=controller;usageState.loading=true;
  if(!quiet){
    $("#usage-view").setAttribute("aria-busy","true");
    $("#usage-view").classList.add("is-loading");
    $("#usage-updated").textContent=usageState.payloadKey===key ? "更新中…" : "正在读取记录…";
    usageRenderControls();usageShowMessage("");
  }
  if(usageState.payloadKey!==key){
    $("#usage-top-logo").hidden=true;$("#usage-top-logo").innerHTML="";
    $("#usage-total").textContent="—";$("#usage-app-count").textContent="—";$("#usage-top-name").textContent="—";$("#usage-top-name").title="";$("#usage-top-time").textContent="等待真实记录";
    $("#usage-chart").innerHTML='<p class="usage-pending">正在读取记录…</p>';
    $("#usage-app-list").innerHTML='<li class="usage-pending">正在读取记录…</li>';
  }
  try{
    const response=await fetch("/api/usage?"+new URLSearchParams({period,date}),{cache:"no-store",signal:controller.signal});
    const raw=await response.json();
    if(!response.ok) throw new Error(raw.error||"使用记录暂时无法读取");
    const payload=usageNormalize(raw);
    if(payload.period!==period || payload.date!==date) throw new Error("统计周期与请求不一致，请重试");
    if(request!==usageState.request || controller.signal.aborted || document.hidden || state.editing) return;
    usageState.payload=payload;usageState.payloadKey=key;
    usageRenderPayload(payload);
    if(payload.status.background && !usageState.backgroundBusy && (usageState.backgroundRequest||0)===backgroundRequest){
      try{usageRenderBackground(usageNormalizeBackground(payload.status.background));}catch(_){}
    }
    $("#usage-updated").textContent="更新于 "+new Date().toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
    usageShowMessage(payload.status.error ? "记录暂不可用："+String(payload.status.error) : "");
    if(usageState.payloadKey===key) usageRestorePosition();
  }catch(error){
    if(request!==usageState.request || controller.signal.aborted || error.name==="AbortError") return;
    if(usageState.payloadKey!==key) usageRenderUnavailable();
    usageShowMessage((usageState.payloadKey===key ? "刷新失败，保留上次读取的记录。" : "")+error.message);
    $("#usage-updated").textContent=usageState.payloadKey===key ? "当前为上次读取的记录" : "读取失败";
    if(usageState.payloadKey===key) usageRestorePosition();
  }finally{
    if(request===usageState.request){
      usageState.loading=false;
      if(!quiet){
        $("#usage-view").setAttribute("aria-busy","false");$("#usage-view").classList.remove("is-loading");
        usageRenderControls();
      }else usageRenderControls({quiet:true});
    }
  }
}
function usageChoose(period,date){
  if(!USAGE_PERIODS.includes(period) || !usageParseDate(date) || date>usageDateKey()) return;
  usageState.restorePending=false;usageState.returnPosition=null;
  usageState.period=period;usageState.date=date;
  usageRenderControls();usageUpdateURL();
  if(state.local) usageLoad();
}
function usageStartRefreshTimer(){
  clearInterval(usageState.timer);
  usageState.timer=state.local ? setInterval(()=>usageLoad({quiet:true}),5000) : null;
}
function renderUsage(){
  if(usageState.initialized) return;
  usageState.initialized=true;
  $("#usage-updated").setAttribute("aria-live","off");
  const params=new URLSearchParams(location.search);
  usageState.period=USAGE_PERIODS.includes(params.get("period")) ? params.get("period") : "day";
  usageState.chart=USAGE_CHARTS.includes(params.get("chart")) ? params.get("chart") : "line";
  const selected=params.get("date");
  usageState.date=usageParseDate(selected) && selected<=usageDateKey() ? selected : usageDateKey();
  usageState.restorePending=params.get("restore")==="1" || (typeof history!=="undefined" && !!history.state?.appshelfView);
  $$("[data-period]").forEach(button=>button.addEventListener("click",()=>usageChoose(button.dataset.period,usageState.date)));
  $$("button[data-chart]").forEach(button=>button.addEventListener("click",()=>usageChooseChart(button.dataset.chart)));
  $("#usage-date").addEventListener("change",event=>{
    const date=event.target.value;
    if(!usageParseDate(date) || date>usageDateKey()){usageRenderControls();return;}
    usageChoose(usageState.period,date);
  });
  $("#usage-previous").addEventListener("click",()=>usageChoose(usageState.period,usageShiftDate(usageState.date,usageState.period,-1)));
  $("#usage-next").addEventListener("click",()=>{
    const next=usageShiftDate(usageState.date,usageState.period,1);
    usageChoose(usageState.period,next>usageDateKey() ? usageDateKey() : next);
  });
  $("#usage-today").addEventListener("click",()=>usageChoose(usageState.period,usageDateKey()));
  $("#usage-refresh").addEventListener("click",()=>{usageLoad();usageLoadBackground();});$("#usage-retry").addEventListener("click",()=>usageLoad());
  $("#usage-background-toggle").addEventListener("change",event=>usageSetBackground(event.target.checked));
  $("#usage-background-retry").addEventListener("click",()=>usageState.background?.error ? usageSetBackground(usageState.background.enabled) : usageLoadBackground());
  document.addEventListener("visibilitychange",()=>{if(!document.hidden && !state.editing) usageLoad({quiet:true});});
  if(typeof ResizeObserver!=="undefined"){
    usageState.resizeObserver=new ResizeObserver(()=>{
      const width=Math.round(Math.max(300,($("#usage-chart").clientWidth||956)-36));
      if(width!==usageState.chartWidth && usageState.payload && !usageState.loading && usageState.payloadKey===usageState.period+":"+usageState.date && !document.hidden && !state.editing) usageRenderChart(usageState.payload);
    });
    usageState.resizeObserver.observe($("#usage-chart"));
  }
  window.addEventListener("pagehide",()=>{
    usageState.returnTop=Math.max(0,Number(window.scrollY)||0);
    usageState.controller?.abort();usageState.request++;usageState.loading=false;
    usageState.backgroundRequest=(usageState.backgroundRequest||0)+1;usageState.backgroundBusy=false;
    clearInterval(usageState.timer);usageState.timer=null;usageState.resizeObserver?.disconnect();
  });
  window.addEventListener("pageshow",event=>{
    if(!event.persisted) return;
    const previous=typeof history!=="undefined" ? history.state?.appshelfView : null;
    if(typeof currentViewURL==="function") usageState.returnPosition={...(previous||{}),view:currentViewURL(),top:usageState.returnTop??previous?.top??0};
    usageState.restorePending=true;
    usageStartRefreshTimer();usageRenderControls();
    usageState.resizeObserver?.observe($("#usage-chart"));
    usageLoadBackground();
    return usageLoad({quiet:true});
  });
  usageRenderControls();
  if(state.local){usageLoad();usageLoadBackground();usageStartRefreshTimer();}
  else{$("#usage-view").setAttribute("aria-busy","false");usageRenderUnavailable(true);$("#usage-background-status").textContent="后台设置需在本机运行后调整";usageRestorePosition();}
}
async function bootUsagePage(){
  setupGlobalSearch();
  try{await loadApps();}
  catch(_){$("#usage-search-note").hidden=false;state.data=[];}
  bindSearch();renderUsage();
}
bootUsagePage();

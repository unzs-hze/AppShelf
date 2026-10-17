/* Pure document/history simulations; no browser, network or real tracker. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
const exportsSource = '\nthis.nav = {state, saveViewPosition, currentViewURL, usageDetailParams, detailNavigationURL, bindDetailLinks, prepareDetailReturn, restoreViewPosition, renderBackLink};';

function linkElement() {
  return {dataset: {}, attributes: {}, handlers: {}, href: '', textContent: '', title: '',
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(event, callback) { this.handlers[event] = callback; },
  };
}

function browser({page = 'index', url = 'index.html', length = 3, storage = new Map(),
                  initialState = null, entries = [], related = [], top = 0} = {}) {
  const frames = [], scrolls = [], events = [], replacements = [];
  const location = {};
  function setURL(value) {
    const parsed = new URL(value, 'http://127.0.0.1:8931/');
    Object.assign(location, {pathname: parsed.pathname, search: parsed.search, href: parsed.href});
  }
  setURL(url);
  const history = {state: initialState, length, backCalls: 0, scrollRestoration: 'auto',
    replaceState(value, unused, nextURL) {
      this.state = value;
      replacements.push({value, url: nextURL});
      if (nextURL !== undefined) setURL(nextURL);
    },
    pushState(value, unused, nextURL) {
      this.state = value;
      this.length++;
      if (nextURL !== undefined) setURL(nextURL);
    },
    back() { this.backCalls++; events.push('history-back'); },
  };
  const backLink = linkElement();
  const document = {body: {dataset: {page}},
    querySelector(selector) { return selector === '#back-link' ? backLink : null; },
    querySelectorAll(selector) {
      if (selector === '.entry') return entries;
      if (selector === 'details.related-entries') return related;
      return [];
    },
  };
  const window = {scrollY: top, scrollX: 0,
    scrollTo(value) { scrolls.push(value); events.push('scroll'); this.scrollY = value.top; },
  };
  const sessionStorage = {getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  };
  const context = vm.createContext({URL, URLSearchParams, console, setTimeout, clearTimeout,
    document, window, location, history, sessionStorage,
    requestAnimationFrame: callback => { frames.push(callback); return frames.length; },
  });
  vm.runInContext(source + exportsSource, context);
  const api = context.nav;
  const params = new URLSearchParams(location.search);
  Object.assign(api.state, {library: page === 'index' || page === 'category',
    category: params.get('cat'), q: params.get('q') || '', drive: params.get('drive') || 'all'});
  return {api, window, document, history, location, backLink, storage, frames, scrolls,
    replacements, events, entries, related, setURL,
    flush() { while (frames.length) frames.shift()(); },
    click(overrides = {}) {
      const event = {button: 0, defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; }, ...overrides};
      backLink.handlers.click(event);
      return event;
    },
  };
}

function snapshot(b, patch = {}) {
  return {view: b.api.currentViewURL(), top: 800, anchorId: null, anchorOffset: null,
    openRelated: [], ...patch};
}

function departure() {
  const b = browser({page: 'category',
    url: 'category.html?cat=net-im&q=QQ+%26+tools&drive=D', length: 4, top: 1350,
    initialState: {preserveMe: 'existing history state'}});
  b.entries.push({dataset: {id: 'qq'}, getBoundingClientRect: () => ({top: 117})});
  b.related.push({dataset: {relatedFor: 'qq'}, open: true},
                 {dataset: {relatedFor: 'geek'}, open: false});
  const detailURL = b.api.detailNavigationURL('qq-detail', 'qq');
  const saved = b.history.state.appshelfView;
  return {b, detailURL, saved};
}

test('saving a directory view retains scroll, entry offset, expanded relations and history metadata', () => {
  const {b, saved} = departure();
  assert.equal(saved.top, 1350);
  assert.equal(saved.anchorId, 'qq');
  assert.equal(saved.anchorOffset, 117);
  assert.deepEqual(Array.from(saved.openRelated), ['qq']);
  assert.equal(saved.historyLength, 4);
  assert.equal(saved.pending, true);
  assert.equal(typeof saved.navigation, 'string');
  assert.ok(saved.navigation.length > 5);
  assert.equal(b.history.state.preserveMe, 'existing history state');
  assert.equal(b.history.scrollRestoration, 'manual');
  const persisted = JSON.parse(b.storage.get('appshelf-view:' + saved.view));
  assert.equal(persisted.anchorOffset, 117);
  assert.deepEqual(persisted.openRelated, ['qq']);
});

test('detail navigation carries a canonical directory origin including category, query and location', () => {
  const {detailURL, saved} = departure();
  const query = new URLSearchParams(detailURL.split('?')[1]);
  assert.equal(query.get('id'), 'qq-detail');
  assert.equal(query.get('returnTo'), saved.view);
  assert.equal(query.get('returnVia'), saved.navigation);
  const origin = new URL(query.get('returnTo'), 'http://127.0.0.1/');
  assert.equal(origin.pathname, '/category.html');
  assert.equal(origin.searchParams.get('cat'), 'net-im');
  assert.equal(origin.searchParams.get('q'), 'QQ & tools');
  assert.equal(origin.searchParams.get('drive'), 'D');
});

test('current origins cover home, usage and inherited detail contexts safely', () => {
  assert.equal(browser({page: 'home', url: 'home.html'}).api.currentViewURL(), 'home.html');
  assert.equal(browser({page: 'usage', url: 'usage.html?period=week&date=2026-10-15'}).api.currentViewURL(),
               'usage.html?date=2026-10-15&period=week');
  const query = new URLSearchParams({id: 'a', returnTo: 'category.html?q=Git&cat=dev-tool&drive=Z'});
  assert.equal(browser({page: 'detail', url: 'detail.html?' + query}).api.currentViewURL(),
               'category.html?cat=dev-tool&drive=Z&q=Git');
  const unsafe = new URLSearchParams({returnTo: 'https://outside.example/'});
  assert.equal(browser({page: 'detail', url: 'detail.html?' + unsafe}).api.currentViewURL(), null);
});

test('a matching one-use departure token and adjacent history return with history.back', () => {
  const {b: sourceView, detailURL, saved} = departure();
  const detail = browser({page: 'detail', url: detailURL,
    length: sourceView.history.length + 1, storage: sourceView.storage});
  detail.api.prepareDetailReturn();
  const marked = detail.history.state.appshelfReturn;
  assert.equal(marked.view, saved.view);
  assert.equal(marked.navigation, saved.navigation);
  assert.equal(marked.sourceLength, 4);
  assert.equal(JSON.parse(detail.storage.get('appshelf-view:' + saved.view)).pending, false);
  detail.api.renderBackLink('detail');
  const event = detail.click();
  assert.equal(event.defaultPrevented, true);
  assert.equal(detail.history.backCalls, 1);
  assert.equal(detail.backLink.attributes['aria-label'], '返回应用目录');
});

test('deep links and new tabs use the safe return href without backing into unrelated history', () => {
  const {b: sourceView, detailURL, saved} = departure();
  const deepLink = new URL(detailURL, 'http://127.0.0.1/');
  deepLink.searchParams.delete('returnVia');
  for (const options of [
    {url: deepLink.pathname + deepLink.search, length: 12},
    {url: detailURL, length: 1},
    {url: detailURL, length: sourceView.history.length + 3},
  ]) {
    const detail = browser({page: 'detail', storage: new Map(sourceView.storage), ...options});
    detail.api.prepareDetailReturn();
    detail.api.renderBackLink('detail');
    const event = detail.click();
    assert.equal(event.defaultPrevented, false);
    assert.equal(detail.history.backCalls, 0);
    const returned = new URL(detail.backLink.href, 'http://127.0.0.1/');
    assert.equal(returned.pathname, '/category.html');
    assert.equal(returned.searchParams.get('q'), 'QQ & tools');
    assert.equal(returned.searchParams.get('drive'), 'D');
    assert.equal(returned.searchParams.get('cat'), 'net-im');
    assert.equal(returned.searchParams.get('restore'), '1');
    assert.equal(JSON.parse(detail.storage.get('appshelf-view:' + saved.view)).pending, true);
  }
});

test('foreign and executable return URLs fall back to an internal directory link', () => {
  for (const returnTo of ['https://outside.example/', '//outside.example/',
    'javascript:alert(1)', 'file:///C:/private.txt', '../index.html', 'detail.html?id=other']) {
    const query = new URLSearchParams({id: 'qq', returnTo, returnVia: 'forged'});
    const detail = browser({page: 'detail', url: 'detail.html?' + query, length: 8});
    detail.api.prepareDetailReturn();
    detail.api.renderBackLink('detail');
    const event = detail.click();
    assert.equal(event.defaultPrevented, false);
    assert.equal(detail.history.backCalls, 0);
    assert.equal(detail.backLink.href, 'index.html');
  }
});

test('wrong or already consumed tokens cannot establish an automatic history return', () => {
  for (const consumed of [false, true]) {
    const {b: sourceView, detailURL, saved} = departure();
    const next = new URL(detailURL, 'http://127.0.0.1/');
    if (consumed) {
      const persisted = JSON.parse(sourceView.storage.get('appshelf-view:' + saved.view));
      persisted.pending = false;
      sourceView.storage.set('appshelf-view:' + saved.view, JSON.stringify(persisted));
    } else next.searchParams.set('returnVia', 'different-navigation-token');
    const detail = browser({page: 'detail', url: next.pathname + next.search,
      length: 5, storage: sourceView.storage});
    detail.api.prepareDetailReturn();
    detail.api.renderBackLink('detail');
    assert.equal(detail.click().defaultPrevented, false);
    assert.equal(detail.history.backCalls, 0);
  }
});

test('return guards recheck adjacency and leave modified clicks to the browser', () => {
  const {b: sourceView, detailURL} = departure();
  const detail = browser({page: 'detail', url: detailURL, length: 5, storage: sourceView.storage});
  detail.api.prepareDetailReturn();
  detail.api.renderBackLink('detail');
  const modified = detail.click({ctrlKey: true});
  assert.equal(modified.defaultPrevented, false);
  assert.equal(detail.history.backCalls, 0);
  detail.history.length = 6;
  assert.equal(detail.click().defaultPrevented, false);
  assert.equal(detail.history.backCalls, 0);
  assert.match(detail.backLink.href, /^category\.html\?/);
});

test('related detail links preserve the original directory snapshot without generating a new departure', () => {
  const {b: sourceView, detailURL, saved} = departure();
  const detail = browser({page: 'detail', url: detailURL, length: 5,
    storage: sourceView.storage, top: 75});
  detail.api.prepareDetailReturn();
  const before = new Map(detail.storage), beforeState = JSON.stringify(detail.history.state);
  const next = detail.api.detailNavigationURL('other-related-app');
  const query = new URLSearchParams(next.split('?')[1]);
  assert.equal(query.get('id'), 'other-related-app');
  assert.equal(query.get('returnTo'), saved.view);
  assert.equal(query.has('returnVia'), false);
  assert.equal(detail.api.saveViewPosition('unrelated-anchor'), undefined);
  assert.deepEqual([...detail.storage], [...before]);
  assert.equal(JSON.stringify(detail.history.state), beforeState);
});

test('restore expands related records before computing the entry anchor offset', () => {
  const b = browser({top: 20});
  let open = false;
  const relation = {dataset: {relatedFor: 'qq'},
    get open() { return open; },
    set open(value) { open = value; b.events.push('related-open:' + value); },
  };
  b.related.push(relation);
  b.entries.push({dataset: {id: 'qq'}, getBoundingClientRect() {
    b.events.push('anchor-layout');
    return {top: (open ? 2200 : 1000) - b.window.scrollY};
  }});
  const restored = b.api.restoreViewPosition(snapshot(b, {
    top: 800, anchorId: 'qq', anchorOffset: 150, openRelated: ['qq'],
  }));
  assert.equal(restored, true);
  assert.equal(relation.open, true);
  assert.equal(b.scrolls.length, 0, 'The layout measurement must wait for the next frame');
  b.flush();
  assert.equal(b.scrolls[0].top, 2050);
  assert.equal(b.scrolls[0].left, 0);
  assert.ok(b.events.indexOf('related-open:true') < b.events.indexOf('anchor-layout'));
  assert.ok(b.events.indexOf('anchor-layout') < b.events.indexOf('scroll'));
});

test('missing anchors and invalid offsets fall back to the saved document scroll position', () => {
  for (const anchorOffset of [150, null, NaN, Infinity, 'invalid']) {
    const b = browser({top: 25});
    const value = snapshot(b, {top: 900, anchorId: 'missing-entry', anchorOffset});
    assert.equal(b.api.restoreViewPosition(value), true);
    b.flush();
    assert.equal(b.scrolls[0].top, 900);
  }
  const b = browser();
  b.entries.push({dataset: {id: 'exists'}, getBoundingClientRect: () => ({top: 100})});
  assert.equal(b.api.restoreViewPosition(snapshot(b, {top: 450, anchorId: 'exists', anchorOffset: NaN})), true);
  b.flush();
  assert.equal(b.scrolls[0].top, 450);
});

test('restoring a fallback href reads the matching snapshot and removes only the restore flag', () => {
  const b = browser({page: 'category', url: 'category.html?cat=net-im&drive=D&q=QQ&restore=1',
    initialState: {keep: 'existing detail'}});
  const value = snapshot(b, {top: 710});
  b.storage.set('appshelf-view:' + value.view, JSON.stringify(value));
  assert.equal(b.api.restoreViewPosition(), true);
  b.flush();
  assert.equal(b.scrolls[0].top, 710);
  const params = new URLSearchParams(b.location.search);
  assert.equal(params.has('restore'), false);
  assert.equal(params.get('cat'), 'net-im');
  assert.equal(params.get('q'), 'QQ');
  assert.equal(params.get('drive'), 'D');
  assert.equal(b.history.state.keep, 'existing detail');
  assert.equal(b.history.state.appshelfView.view, value.view);
});

test('history.back restoration also works from its history snapshot without a URL restore flag', () => {
  const b = browser();
  b.history.state = {appshelfView: snapshot(b, {top: 1120})};
  assert.equal(b.api.restoreViewPosition(), true);
  b.flush();
  assert.equal(b.scrolls[0].top, 1120);
});

test('invalid positions and snapshots for a different view cause no scroll or expansion', () => {
  for (const patch of [{top: -1}, {top: Infinity}, {top: NaN}, {top: '100'},
    {view: 'category.html?cat=game-app'}, {view: 'https://outside.example/'}]) {
    const b = browser();
    const relation = {dataset: {relatedFor: 'qq'}, open: false};
    b.related.push(relation);
    assert.equal(b.api.restoreViewPosition(snapshot(b, {...patch, openRelated: ['qq']})), false);
    b.flush();
    assert.equal(b.scrolls.length, 0);
    assert.equal(relation.open, false);
  }
  const b = browser({url: 'index.html?restore=1'});
  b.storage.set('appshelf-view:index.html', '{invalid json');
  assert.equal(b.api.restoreViewPosition(), false);
});

test('malformed expanded-state metadata never crashes restoration', () => {
  for (const openRelated of [{}, 7, true]) {
    const b = browser();
    b.related.push({dataset: {relatedFor: 'qq'}, open: false});
    assert.doesNotThrow(() => b.api.restoreViewPosition(snapshot(b, {openRelated})));
    b.flush();
  }
});

test('usage-only and known detail links retain the executable ID, historical period and departure scroll',()=>{
  const b=browser({page:'usage',url:'usage.html?period=week&date=2026-10-05',top:642});
  const usageId='exe-0123456789abcdef';
  assert.equal(b.api.usageDetailParams({id:usageId}).usageId,usageId);
  b.api.state.data=[{id:'catalogue',name:'Known'}];
  const known=b.api.usageDetailParams({id:usageId,catalogueId:'catalogue'});
  assert.equal(known.id,'catalogue');assert.equal(known.usageId,usageId);
  b.api.state.data.push({id:'scan-copy',name:'Known',duplicateOf:'catalogue'});
  assert.equal(b.api.usageDetailParams({id:usageId,catalogueId:'scan-copy'}).id,'catalogue');
  const link=linkElement();link.dataset.usageId=usageId;link.closest=()=>null;
  b.api.bindDetailLinks({querySelectorAll:()=>[link]});link.handlers.click();
  const query=new URLSearchParams(link.href.split('?')[1]);
  assert.equal(query.has('id'),false);assert.equal(query.get('usageId'),usageId);
  assert.equal(query.get('returnTo'),'usage.html?date=2026-10-05&period=week');
  assert.ok(query.get('returnVia'));assert.equal(b.history.state.appshelfView.top,642);
  link.dataset.detailId='catalogue';link.handlers.click();
  const linked=new URLSearchParams(link.href.split('?')[1]);
  assert.equal(linked.get('id'),'catalogue');assert.equal(linked.get('usageId'),usageId);
});

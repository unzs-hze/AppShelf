/* Pure VM regressions for related records; no browser or local tracker starts. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../assets/app.js'), 'utf8');
function core(apps = []) {
  const context = vm.createContext({
    URLSearchParams, console, setTimeout, clearTimeout,
    document: {querySelector: () => null, querySelectorAll: () => []},
  });
  vm.runInContext(source + '\nthis.related = {state, relatedApps, relatedHTML, entryHTML};', context);
  const c = context.related;
  c.state.data = apps;
  c.state.order = new Map(apps.map((app, index) => [app, index]));
  return c;
}

function app(id, patch = {}) {
  return {id, name: id, category: 'tool-sys', description: 'Application notes',
    path: '', paths: [], site: '', source: 'unknown', size: null, ...patch};
}

const qq = () => app('3a839cbd', {
  name: 'QQ 9.9.19', category: 'net-im', group: 'qq', path: 'D:\\Chat\\QqChat',
  paths: [{path: 'D:\\Chat\\QqChat', kind: 'directory', note: ''}],
});
const qqMail = () => app('1b397f66', {
  name: 'Tencent QQMail Plugin', category: 'net-im', group: 'qq',
  path: 'C:\\Program Files (x86)\\QQMailPlugin',
  paths: [{path: 'C:\\Program Files (x86)\\QQMailPlugin', kind: 'directory', note: ''}],
});

test('QQ names its mail plugin as a related record and never calls the group two copies', () => {
  const first = qq(), plugin = qqMail();
  const ungroupedQQ = app('119b7ffd69961bb0', {name: 'QQ', status: 'new'});
  const c = core([first, plugin, ungroupedQQ]);
  const result = c.relatedApps(first);
  assert.equal(result.length, 1);
  assert.equal(result[0], plugin);
  const html = c.relatedHTML(first);
  const summary = /<summary\b[^>]*>([\s\S]*?)<\/summary>/.exec(html);
  assert.ok(summary, 'Related records need an accessible native expand control');
  assert.match(summary[1], /Tencent QQMail Plugin/);
  assert.match(html, /C:\\Program Files \(x86\)\\QQMailPlugin/);
  assert.doesNotMatch(html, /\d+\s*(?:份|个副本)/);
  assert.doesNotMatch(c.entryHTML(first), /\d+\s*份/);
});

test('Geek lists the other executable location explicitly in both directions', () => {
  const installed = app('b53d50eb', {name: 'Geek Uninstaller', group: 'geek',
    path: 'D:\\geek\\geek.exe', paths: [{path: 'D:\\geek\\geek.exe'}]});
  const portable = app('c59a9f6aec12bace', {name: 'Geek Uninstaller', group: 'geek', status: 'new',
    path: 'C:\\Users\\Example\\AppData\\Local\\Temp\\geek64.exe',
    paths: [{path: 'C:\\Users\\Example\\AppData\\Local\\Temp\\geek64.exe'}]});
  const c = core([installed, portable]);
  assert.equal(c.relatedApps(installed)[0], portable);
  assert.equal(c.relatedApps(portable)[0], installed);
  assert.match(c.relatedHTML(installed), /Temp\\geek64\.exe/);
  assert.match(c.relatedHTML(portable), /D:\\geek\\geek\.exe/);
  assert.match(c.relatedHTML(installed), /新发现/);
  for (const record of [installed, portable]) {
    assert.doesNotMatch(c.entryHTML(record), /\d+\s*份/);
  }
});

test('related records include current discoveries while hiding missing, removed and duplicate records', () => {
  const current = app('jdk17', {group: 'jdk', name: 'JDK 17', category: 'dev-lang'});
  const missing = app('jdk8', {group: 'jdk', name: 'JDK 8', category: 'dev-lang', status: 'missing'});
  const found = app('jdk21', {group: 'jdk', name: 'JDK 21', category: 'dev-lang', status: 'new'});
  const removed = app('jdk6', {group: 'jdk', name: 'JDK 6', category: 'dev-lang', status: 'removed'});
  const duplicate=app('jdk21-copy',{group:'jdk',name:'JDK 21',duplicateOf:'jdk21'});
  const c = core([current, missing, found, removed,duplicate]);
  const result = c.relatedApps(current);
  assert.equal(result.length, 1);
  assert.ok(!result.includes(missing));
  assert.ok(result.includes(found));
  const html = c.relatedHTML(current);
  assert.doesNotMatch(html, /JDK 8|未检测到|jdk21-copy/);
  assert.match(html, /JDK 21/);
  assert.match(html, /新发现/);
  assert.doesNotMatch(html, /JDK 6/);
});

test('cross-category and cross-drive related entries remain visible under unrelated filters', () => {
  const first = app('trae-editor', {name: 'TraeCode', group: 'trae', category: 'dev-ide',
    paths: [{path: 'D:\\Editors\\Trae'}]});
  const assistant = app('trae-assistant', {name: 'TRAE SOLO', group: 'trae', category: 'ai-code',
    paths: [{path: 'C:\\Users\\Example\\TRAE SOLO'}]});
  const c = core([first, assistant]);
  Object.assign(c.state, {q: 'No matching app name', drive: 'Z', category: 'net-im'});
  assert.equal(c.relatedApps(first)[0], assistant);
  const html = c.relatedHTML(first);
  assert.match(html, /TRAE SOLO/);
  assert.match(html, /AI 编程/);
  assert.match(html, /C:\\Users\\Example\\TRAE SOLO/);
});

test('no group or a group without peers produces no related widget', () => {
  for (const group of [undefined, null, '', 'only-one']) {
    const current = app('single', {group});
    const other = app('other', {group: 'another-group'});
    const c = core([current, other]);
    assert.equal(c.relatedApps(current).length, 0);
    assert.equal(c.relatedHTML(current), '');
  }
});

test('same IDs are excluded even for detached objects and group keys must match exactly', () => {
  const original = qq(), sameId = {...original}, plugin = qqMail();
  const differentGroup = app('uppercase-group', {group: 'QQ', name: 'Another QQ'});
  const c = core([original, sameId, plugin, differentGroup]);
  const result = c.relatedApps({...original});
  assert.equal(result.length, 1);
  assert.equal(result[0], plugin);
});

test('historical Logitech substring mistakes never associate Logitech with Git', () => {
  const git = app('git', {group: 'git', name: 'Git 2.55', category: 'dev-tool'});
  const otherGit = app('git-portable', {group: 'git', name: 'Git Portable', category: 'dev-tool'});
  const logitech = app('mouse', {group: 'git', name: 'Logitech G HUB', category: 'sys-hw'});
  const upper = app('keyboard', {group: 'git', name: 'LOGITECH Gaming Software', category: 'sys-hw'});
  const c = core([git, otherGit, logitech, upper]);
  assert.equal(c.relatedApps(git).length, 1);
  assert.equal(c.relatedApps(git)[0], otherGit);
  assert.equal(c.relatedApps(logitech).length, 0);
  assert.equal(c.relatedApps(upper).length, 0);
  assert.doesNotMatch(c.relatedHTML(git), /Logitech|LOGITECH/);
  assert.equal(c.relatedHTML(logitech), '');
  const unrelatedBrandGroup = app('hub', {group: 'logitech', name: 'Logitech G HUB'});
  const brandPeer = app('devices', {group: 'logitech', name: 'Logitech Options'});
  c.state.data = [unrelatedBrandGroup, brandPeer];
  assert.equal(c.relatedApps(unrelatedBrandGroup)[0], brandPeer);
});

test('details are collapsed by default and can be expanded for a detail page', () => {
  const first = qq(), plugin = qqMail(), c = core([first, plugin]);
  assert.match(c.relatedHTML(first), /<details\b/);
  assert.doesNotMatch(c.relatedHTML(first), /<details\b[^>]*\sopen(?:\s|>|=)/);
  assert.match(c.relatedHTML(first, {expanded: true}), /<details\b[^>]*\sopen(?:\s|>|=)/);
});

test('untrusted related names, IDs and path notes are escaped in both summary and rows', () => {
  const current = app('safe', {group: 'unsafe'});
  const malicious = app('peer" onmouseover="alert(1)', {group: 'unsafe',
    name: '"><img src=x onerror=alert(2)> & Plugin', category: '"><svg onload=alert(3)>',
    paths: [{path: 'D:\\"><script>alert(4)</script>\\app.exe', note: '<iframe src=x>'}]});
  const c = core([current, malicious]);
  const html = c.relatedHTML(current);
  assert.match(html, /&lt;img/);
  assert.match(html, /&lt;script/);
  assert.match(html, /&lt;iframe/);
  assert.match(html, /&amp; Plugin/);
  assert.doesNotMatch(html, /<img\b|<script\b|<iframe\b|<svg\s+onload/);
  assert.doesNotMatch(html, /\sonmouseover="alert\(1\)"/);
});

test('rendering related records does not rewrite or annotate the catalogue', () => {
  const first = qq(), plugin = qqMail(), apps = [first, plugin], c = core(apps);
  const before = JSON.stringify(apps);
  c.relatedApps(first);
  c.relatedHTML(first);
  c.entryHTML(first);
  assert.equal(c.state.data, apps);
  assert.equal(c.relatedApps(first)[0], plugin);
  assert.equal(JSON.stringify(apps), before);
});

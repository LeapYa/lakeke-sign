// 严格抓「辣可可」上下文的身份字段（只用 appId/mpId 双重校验的上下文），合并进 lakeke.env
// 保留 env 里已有的新鲜 token（若 capture 到的 storage token 更新则采用）
// 用法：docker exec woc-hook sh -c 'cd /work/lakeke-sign && NODE_PATH=/opt/wmpf/node_modules node cdp_lakeke_ident.js [waitSec]'
const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');

const ENVFILE = process.env.ENVFILE || '/work/lakeke-sign/lakeke.env';
const PORT = Number(process.env.CDP_PORT || 62000);
const WAIT = Number(process.argv[2] || 60);
const APPID = 'wxf8a17a14c0521576';
const MPID = 'gh_6420f1a617e8';
const NEED = ['token', 'mpId', 'openId', 'unionId', 'gameId', 'memberId', 'cardId', 'cardNo', 'thirdShopId', 'gcId'];

const JS = `(function () {
  var need = ${JSON.stringify(NEED)};
  var out = {};
  try { var ai = wx.getAccountInfoSync(); out.__appId = (ai.miniProgram && ai.miniProgram.appId) || ''; } catch (e) { out.__appId = ''; }
  function put(k, v) { if (v === undefined || v === null || v === '') return; if (out[k] === undefined) out[k] = String(v); }
  function coerce(v) {
    if (typeof v === 'string') { var t = v.trim();
      if ((t.charAt(0) === '{' && t.charAt(t.length - 1) === '}') || (t.charAt(0) === '[' && t.charAt(t.length - 1) === ']')) {
        try { return JSON.parse(t); } catch (e) { return v; } } }
    return v; }
  function scan(o, d) {
    if (!o || typeof o !== 'object' || d > 4) return;
    if (Object.prototype.toString.call(o) === '[object Array]') { for (var i = 0; i < o.length && i < 50; i++) scan(o[i], d + 1); return; }
    for (var k in o) { var v = o[k], lk = String(k).toLowerCase();
      if (typeof v === 'string' || typeof v === 'number') { for (var n = 0; n < need.length; n++) if (lk === need[n].toLowerCase()) put(need[n], v); }
      else scan(v, d + 1); } }
  try { wx.getStorageInfoSync().keys.forEach(function (k) {
    try { var raw = wx.getStorageSync(k), lk = String(k).toLowerCase();
      for (var n = 0; n < need.length; n++) if (lk === need[n].toLowerCase() && (typeof raw === 'string' || typeof raw === 'number')) put(need[n], raw);
      scan(coerce(raw), 0); } catch (e) {} }); } catch (e) {}
  try { var app = getApp(); if (app) scan(app.globalData, 0); } catch (e) {}
  try { var pages = (getCurrentPages() || []).map(function (p) { return p.route || ''; }); out.__pages = pages.join(',');
    (getCurrentPages() || []).forEach(function (p) { var d = p.data || {};
      if (d.gameId !== undefined) put('gameId', d.gameId);
      scan(d, 0);
      var mi = d.memberInfo || d.member || {};
      if (mi.id !== undefined) put('memberId', mi.id);
      if (mi.cardId !== undefined) put('cardId', mi.cardId);
      if (mi.cardNo !== undefined) put('cardNo', mi.cardNo);
      if (mi.mcId !== undefined) put('thirdShopId', mi.mcId);
      var bi = d.baseInfo || {};
      if (bi.mcId !== undefined) put('thirdShopId', bi.mcId);
      if (bi.gameId !== undefined) put('gameId', bi.gameId);
      if (bi.mpId !== undefined) put('mpId', bi.mpId);
      scan(mi, 0); scan(bi, 0); }); } catch (e) {}
  return JSON.stringify(out);
})()`;

function mask(v) { const s = String(v || ''); return s.length > 8 ? `${s.slice(0, 4)}${'*'.repeat(s.length - 8)}${s.slice(-4)} (${s.length})` : '*'.repeat(s.length); }
function jwtExp(t) { try { return JSON.parse(Buffer.from(t.split('.')[1], 'base64url').toString()).exp; } catch (e) { return null; } }
function loadEnv() {
  const env = {};
  try { for (const l of fs.readFileSync(ENVFILE, 'utf8').split('\n')) { const i = l.indexOf('='); if (i > 0) env[l.slice(0, i).trim()] = l.slice(i + 1).trim(); } } catch (e) {}
  return env;
}

function attempt() {
  return new Promise((resolve) => {
    let pick = null, pages = '';
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}`);
    let done = false;
    const finish = () => { if (done) return; done = true; try { ws.close(); } catch (e) {} resolve({ pick, pages }); };
    ws.on('open', () => {
      ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable', params: {} }));
      for (let cid = 1; cid <= 60; cid++) setTimeout(() => ws.send(JSON.stringify({ id: 1000 + cid, method: 'Runtime.evaluate',
        params: { expression: '(typeof wx)', returnByValue: true, contextId: cid } })), cid * 35);
      setTimeout(finish, 9000);
    });
    ws.on('message', (data) => {
      let m; try { m = JSON.parse(data.toString()); } catch (e) { return; }
      const id = m.id; if (typeof id !== 'number' || id < 1000) return;
      const tag = Math.floor(id / 1000) - 1, cid = id % 1000;
      const val = m.result && m.result.result && m.result.result.value;
      if (!val) return;
      if (tag === 0 && val === 'object') {
        ws.send(JSON.stringify({ id: 2000 + cid, method: 'Runtime.evaluate', params: { expression: JS, returnByValue: true, contextId: cid } }));
      } else if (tag === 1) {
        let d; try { d = JSON.parse(val); } catch (e) { return; }
        if (d.__pages) pages = d.__pages;
        const byApp = d.__appId === APPID;
        const byMp = d.mpId === MPID;
        console.log(`[scan] ctx ${cid} appId=${d.__appId || '-'} mpId=${mask(d.mpId) || '-'} pages=${d.__pages || '-'} 命中=${Object.keys(d).filter((k) => !k.startsWith('__')).length}${byApp || byMp ? '  <== 辣可可' : ''}`);
        if (!(byApp || byMp)) return;
        const fields = {}; for (const k of Object.keys(d)) if (!k.startsWith('__')) fields[k] = d[k];
        if (!pick || Object.keys(fields).length > Object.keys(pick.fields).length) pick = { cid, fields, appId: d.__appId };
      }
    });
    ws.on('error', () => finish());
  });
}

(async () => {
  const env0 = loadEnv();
  let found = null;
  const end = Date.now() + WAIT * 1000;
  while (Date.now() < end) {
    const r = await attempt();
    if (r.pick && (!found || Object.keys(r.pick.fields).length > Object.keys(found).length)) found = r.pick.fields;
    if (found && found.openId && found.unionId && found.memberId) break;
    await new Promise((x) => setTimeout(x, 1500));
  }
  if (!found || !Object.keys(found).length) { console.log('[END] 没抓到辣可可上下文（确认小程序开着）'); process.exit(1); }

  const env = Object.assign({}, env0);
  // 身份字段一律以小程序 storage 为准
  for (const k of ['openId', 'unionId', 'gcId', 'mpId', 'gameId', 'memberId', 'cardId', 'cardNo', 'thirdShopId']) {
    if (found[k]) env['LAKEKE_' + k.toUpperCase()] = found[k];
  }
  // token：取 exp 更晚的那个
  if (found.token) {
    const cur = env.LAKEKE_TOKEN || '';
    const eNew = jwtExp(found.token), eCur = cur ? jwtExp(cur) : 0;
    if (!eCur || (eNew && eNew > eCur)) { env.LAKEKE_TOKEN = found.token; console.log(`[token] 采用小程序 storage 里的 token`); }
    else console.log(`[token] 保留 env 里的新 token（比 storage 里新 ${((eCur - (eNew || 0)) / 60).toFixed(0)} 分钟）`);
  }
  fs.writeFileSync(ENVFILE, Object.entries(env).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join('\n') + '\n');
  console.log(`\n[save] 已写入 ${ENVFILE}`);
  for (const [k, v] of Object.entries(env).filter(([k]) => k.startsWith('LAKEKE_')).sort()) {
    const sensitive = /TOKEN|OPENID|UNIONID/.test(k);
    console.log(`  ${k} = ${sensitive ? mask(v) : v}`);
  }
  process.exit(0);
})();

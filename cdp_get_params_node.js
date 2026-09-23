// 在 woc-hook 容器内运行（共享实例网络命名空间，才能连 ws://127.0.0.1:62000）
// 用法：docker exec woc-hook sh -c 'cd /work/lakeke-sign && NODE_PATH=/opt/wmpf/node_modules node cdp_get_params_node.js 120'
// 作用：从辣可可小程序 AppService 上下文取参 → 写 /work/lakeke-sign/lakeke.env（只打脱敏摘要）
const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');

const OUT = process.env.OUT || '/work/lakeke-sign/lakeke.env';
const PORT = Number(process.env.CDP_PORT || 62000);
const WAIT = Number(process.argv[2] || 90);
const APPID = 'wxf8a17a14c0521576';       // 辣可可
const APPID_ZX = 'wxb98e6393065cf180';    // 辣可可甄选
const NEED = ['token', 'mpId', 'openId', 'unionId', 'gameId',
  'memberId', 'cardId', 'cardNo', 'thirdShopId', 'gcId'];

const FULL_JS = `(function () {
  var need = ${JSON.stringify(NEED)};
  var out = {};
  function put(k, v) {
    if (v === undefined || v === null || v === '') return;
    if (out[k] === undefined) out[k] = String(v);
  }
  function coerce(v) {
    if (typeof v === 'string') {
      var t = v.trim();
      if ((t.charAt(0) === '{' && t.charAt(t.length - 1) === '}') ||
          (t.charAt(0) === '[' && t.charAt(t.length - 1) === ']')) {
        try { return JSON.parse(t); } catch (e) { return v; }
      }
    }
    return v;
  }
  function scan(o, depth) {
    if (!o || typeof o !== 'object' || depth > 4) return;
    if (Object.prototype.toString.call(o) === '[object Array]') {
      for (var i = 0; i < o.length && i < 50; i++) scan(o[i], depth + 1);
      return;
    }
    for (var k in o) {
      var v = o[k], lk = String(k).toLowerCase();
      if (typeof v === 'string' || typeof v === 'number') {
        for (var n = 0; n < need.length; n++) {
          if (lk === need[n].toLowerCase()) put(need[n], v);
        }
      } else scan(v, depth + 1);
    }
  }
  try {
    var ai = wx.getAccountInfoSync();
    out.__appId = (ai.miniProgram && ai.miniProgram.appId) || '';
  } catch (e) {}
  try {
    var info = wx.getStorageInfoSync();
    info.keys.forEach(function (k) {
      try {
        var raw = wx.getStorageSync(k), lk = String(k).toLowerCase();
        for (var n = 0; n < need.length; n++) {
          if (lk === need[n].toLowerCase() && (typeof raw === 'string' || typeof raw === 'number')) put(need[n], raw);
        }
        scan(coerce(raw), 0);
      } catch (e) {}
    });
  } catch (e) { out.__err = e.message; }
  try { var app = getApp(); if (app) scan(app.globalData, 0); } catch (e) {}
  try {
    var pages = (getCurrentPages() || []).map(function (p) { return p.route || ''; });
    out.__pages = pages.join(',');
    (getCurrentPages() || []).forEach(function (p) {
      var d = p.data || {};
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
      scan(mi, 0); scan(bi, 0);
    });
  } catch (e) {}
  return JSON.stringify(out);
})()`;

function mask(v) {
  const s = String(v);
  return s.length > 8 ? `${s.slice(0, 4)}${'*'.repeat(s.length - 8)}${s.slice(-4)} (${s.length})` : '*'.repeat(s.length);
}

let ws;
let best = {};
let bestAppId = '';
const wxCtx = new Set();
const ctxAppId = new Map();

function send(cid, expr, tag) {
  const id = 1000 * (tag + 1) + cid;
  try {
    ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true, contextId: cid } }));
  } catch (e) {}
}

function attempt() {
  return new Promise((resolve) => {
    best = {}; bestAppId = ''; wxCtx.clear();
    const found = {};
    ws = new WebSocket(`ws://127.0.0.1:${PORT}`);
    let closed = false;
    const finish = () => {
      if (closed) return;
      closed = true;
      try { ws.close(); } catch (e) {}
      resolve({ fields: best, appId: bestAppId, wxCtx: [...wxCtx], pages: lastPages });
    };
    let lastPages = '';

    ws.on('open', () => {
      ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable', params: {} }));
      for (let cid = 1; cid <= 80; cid++) setTimeout(() => send(cid, '(typeof wx)', 0), cid * 30);
      setTimeout(() => {
        for (const cid of wxCtx) send(cid, FULL_JS, 1);
      }, 3200);
      setTimeout(finish, 9000);
    });
    ws.on('message', (data) => {
      let m; try { m = JSON.parse(data.toString()); } catch (e) { return; }
      const id = m.id;
      if (typeof id !== 'number' || id < 1000) return;
      const tag = Math.floor(id / 1000) - 1, cid = id % 1000;
      const val = m.result && m.result.result && m.result.result.value;
      if (!val) return;
      if (tag === 0 && val === 'object') wxCtx.add(cid);
      else if (tag === 1) {
        let d; try { d = JSON.parse(val); } catch (e) { return; }
        ctxAppId.set(cid, d.__appId || '');
        if (d.__pages) lastPages = d.__pages;
        const fields = {};
        for (const k of Object.keys(d)) if (!k.startsWith('__')) fields[k] = d[k];
        const isTarget = (d.__appId === APPID);
        const better = isTarget && bestAppId !== APPID
          ? true
          : (isTarget === (bestAppId === APPID) && Object.keys(fields).length > Object.keys(best).length);
        if (better) { best = fields; bestAppId = d.__appId || ''; }
        console.log(`[try] ctx ${cid} appId=${d.__appId} pages=${d.__pages} 命中=${Object.keys(fields).length}`);
      }
    });
    ws.on('error', () => finish());
    ws.on('close', () => {});
  });
}

(async () => {
  console.log(`[get] 等待 ${WAIT}s；目标 appId=${APPID}（辣可可）`);
  const end = Date.now() + WAIT * 1000;
  let got = null;
  while (Date.now() < end) {
    const r = await attempt();
    console.log(`[enum] 有 wx 的上下文=${JSON.stringify(r.wxCtx)} 当前最好 appId=${r.appId} 字段=${Object.keys(r.fields).length}`);
    if (r.fields && Object.keys(r.fields).length > Object.keys(got || {}).length) got = r.fields;
    if (got && (Object.keys(got).length >= 9)) break;
    await new Promise((r2) => setTimeout(r2, 2000));
  }
  if (!got || !Object.keys(got).length) {
    console.log('[END] 未取到参数：hook 启动后需要重新打开小程序');
    process.exit(1);
  }
  const lines = Object.entries(got).map(([k, v]) => `LAKEKE_${k.toUpperCase()}=${v}`);
  fs.writeFileSync(OUT, lines.join('\n') + '\n');
  console.log(`\n[save] 已写入 ${OUT}（${lines.length} 字段）`);
  for (const [k, v] of Object.entries(got)) console.log(`  LAKEKE_${k.toUpperCase()} = ${mask(v)}`);
  process.exit(0);
})();

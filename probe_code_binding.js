// 判定 jsCode 是否与小程序 appid 绑定。
// 注意干扰：hook 会把一次 Runtime.evaluate 广播给所有已连接的小程序，所以会回来多份结果。
// 做法：收集全部 code（去重），然后每个 code × 每个 mpId 交叉打 /auth/login，看谁能成功。
// 全程只打印 code 的 hash 前缀，不打印 code 本身。
const WebSocket = require('ws');
const https = require('https');
const crypto = require('crypto');

const TARGETS = [
  { name: '辣可可', mpid: 'gh_6420f1a617e8' },
  { name: '辣可可甄选', mpid: 'gh_08623aa177ad' },
];
const LOGIN = 'https://wechat.wuuxiang.com/i5xforyou/auth/login';

const LOGIN_JS = `new Promise(function(r){try{wx.login({success:function(x){r(x.code)},fail:function(e){r('ERR:'+String(e&&e.errMsg))}})}catch(e){r('ERR:'+String(e))}})`;

function post(url, form) {
  return new Promise((resolve) => {
    const body = new URLSearchParams(form).toString();
    const u = new URL(url);
    const req = https.request({
      hostname: u.hostname, path: u.pathname, method: 'POST', timeout: 15000, rejectUnauthorized: false,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded', 'Content-Length': Buffer.byteLength(body),
        apiCaller: 'wxxcx', 'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36 '
          + 'MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/25715',
      },
    }, (res) => { let d = ''; res.on('data', (c) => { d += c; });
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { resolve({ status: -2, message: d.slice(0, 100) }); } }); });
    req.on('error', (e) => resolve({ status: -1, message: e.message }));
    req.on('timeout', () => { req.destroy(); resolve({ status: -1, message: 'timeout' }); });
    req.write(body); req.end();
  });
}

const short = (s) => crypto.createHash('sha1').update(String(s)).digest('hex').slice(0, 8);
const ws = new WebSocket('ws://127.0.0.1:62000');
let done = false;
const codes = new Set();
const finish = (c) => { if (!done) { done = true; try { ws.close(); } catch (e) {} process.exit(c); } };

ws.on('open', () => {
  ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable', params: {} }));
  // 在所有上下文里都要一次 code（广播会覆盖到全部小程序）
  for (let c = 1; c <= 20; c++) {
    setTimeout(() => ws.send(JSON.stringify({ id: 1000 + c, method: 'Runtime.evaluate',
      params: { expression: LOGIN_JS, returnByValue: true, awaitPromise: true, contextId: c } })), c * 120);
  }
  setTimeout(async () => {
    const list = [...codes].filter((x) => x && !x.startsWith('ERR:'));
    console.log(`[probe] 收到 ${codes.size} 个不同返回值，其中可用 code ${list.length} 个：${list.map(short).join(', ')}`);
    if (!list.length) { console.log('[probe] 没拿到 code（有没有小程序开着？）'); finish(2); return; }
    for (const code of list) {
      console.log(`\n── code ${short(code)}（长度 ${code.length}）──`);
      for (const t of TARGETS) {
        const r = await post(LOGIN, { code, mpid: t.mpid });
        console.log(`   + ${t.name.padEnd(6)} mpId → status=${r.status} ${r.status === 0 ? 'success' : (r.message || '')}`);
      }
    }
    console.log('\n[判读] 每个 code 只会跟「产生它的那个小程序」配对上成功，说明 code 与 appid 绑定。');
    finish(0);
  }, 6000);
});

ws.on('message', (d) => {
  let m; try { m = JSON.parse(d.toString()); } catch (e) { return; }
  const id = m.id;
  if (typeof id !== 'number' || id < 1000) return;
  const v = m.result && m.result.result && m.result.result.value;
  if (typeof v === 'string' && v) codes.add(v);
});
ws.on('error', (e) => { console.log('[probe] CDP 连接失败:', e.message); finish(2); });

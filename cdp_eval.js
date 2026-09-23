// 通用 CDP 执行器（在 woc-hook 容器内跑）：连 ws://127.0.0.1:62000，
// 找到目标小程序上下文（默认按 appId 精确匹配），在**该上下文内**执行表达式。
//
// 用法：
//   node cdp_eval.js <表达式> [appId] [--promise] [--wait 秒] [--any]
//     appId 省略时默认辣可可 wxf8a17a14c0521576；--any 表示不限小程序（取第一个有 wx 的上下文）
//   例：node cdp_eval.js "JSON.stringify(wx.getAccountInfoSync().miniProgram)" 
//       node cdp_eval.js "wx.exitMiniProgram(); 'bye'"
//       node cdp_eval.js "'ok'" --any
//
//   node cdp_eval.js --probe [期望appId]     # 只报告「当前打开的小程序是谁」，不执行表达式
//     输出一行 APPID=<id>（多个用逗号分隔），并在命中期望 appId 时退出 0、否则退出 2。
//     这是**与界面形态无关**的判据：不管小程序是独立窗口还是窗口内嵌，appId 都读得到。
//     用法示例（判断现在开的是不是辣可可）：
//       node cdp_eval.js --probe wxf8a17a14c0521576 && echo 是辣可可
//
// 退出码：0 = 找到上下文并执行成功（--probe 时为命中期望）; 2 = 没找到目标上下文; 3 = 表达式异常
const WebSocket = require('ws');

const LAKEKE = 'wxf8a17a14c0521576';
const argv = process.argv.slice(2);
if (!argv.length) { console.error('用法: node cdp_eval.js <表达式> [appId] [--promise] [--wait s] [--any]'); process.exit(1); }
const probeMode = argv[0] === '--probe';
const expr = probeMode ? null : argv[0];
const flags = probeMode ? argv.slice(1) : argv.slice(1);
const any = flags.includes('--any');
const awaitPromise = flags.includes('--promise');
const waitIdx = flags.indexOf('--wait');
const WAIT = waitIdx >= 0 ? Number(flags[waitIdx + 1] || 15) : 15;
const appId = flags.find((f) => !f.startsWith('--') && !/^\d+$/.test(f)) || LAKEKE;

const PORT = Number(process.env.CDP_PORT || 62000);
const ws = new WebSocket(`ws://127.0.0.1:${PORT}`);
let target = 0;
let done = false;
const found = new Set();          // --probe：收集所有小程序的 appId

function finish(code) {
  if (done) return;
  done = true;
  try { ws.close(); } catch (e) {}
  process.exit(code);
}

ws.on('open', () => {
  ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable', params: {} }));
  const probe = '(function(){try{return wx.getAccountInfoSync().miniProgram.appId}catch(e){return ""}})()';
  for (let c = 1; c <= 80; c++) {
    setTimeout(() => {
      try {
        ws.send(JSON.stringify({ id: 1000 + c, method: 'Runtime.evaluate',
          params: { expression: probe, returnByValue: true, contextId: c } }));
      } catch (e) {}
    }, c * 35);
  }
  setTimeout(() => {
    if (probeMode) {
      console.log(`APPID=${[...found].join(',')}`);
      process.exit(found.has(appId) ? 0 : 2);
    }
    if (!target) { console.error(`[cdp] 没找到目标上下文（appId=${any ? '任意' : appId}）`); finish(2); }
    else {
      ws.send(JSON.stringify({ id: 5001, method: 'Runtime.evaluate',
        params: { expression: expr, returnByValue: true, awaitPromise, contextId: target } }));
      setTimeout(() => finish(0), 6000);
    }
  }, WAIT * 1000);
});

ws.on('message', (d) => {
  let m; try { m = JSON.parse(d.toString()); } catch (e) { return; }
  const id = m.id;
  if (typeof id === 'number' && id > 1000 && id < 2000) {
    const v = m.result && m.result.result && m.result.result.value;
    if (typeof v === 'string' && v) found.add(v);
    if (!target && ((any && v) || v === appId)) { target = id - 1000; console.error(`[cdp] 命中上下文 ctx ${target} appId=${v}`); }
    return;
  }
  if (id === 5001) {
    const r = m.result || {};
    if (r.exceptionDetails) {
      console.error('[cdp] 执行异常:', JSON.stringify(r.exceptionDetails).slice(0, 300));
      finish(3);
    } else {
      const val = r.result && r.result.value;
      console.log(typeof val === 'string' ? val : JSON.stringify(val));
    }
  }
});

ws.on('error', (e) => { console.error('[cdp] 连接失败:', e.message); finish(2); });

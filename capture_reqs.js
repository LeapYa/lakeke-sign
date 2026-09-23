const WebSocket=require('ws');
const APPID='wxf8a17a14c0521576', GID='1000273253';
const HOOK=`(function(){ if(!globalThis.__reqs){ globalThis.__reqs=[];
  var o=wx.request; wx.request=function(a){ try{ if(globalThis.__reqs.length<60)
    globalThis.__reqs.push({url:(a&&a.url)||'',method:(a&&a.method)||'GET',data:(a&&a.data)||null}); }catch(e){}
    return o.apply(this,arguments); }; }
  return 'hooked:'+ (typeof wx.request); })()`;
const RELOAD=`(function(){ try{ wx.reLaunch({url:'/pages/sign/index?gameId=${GID}'}); return 'relaunch ok'; }catch(e){ return 'err:'+e.message; } })()`;
const READ=`JSON.stringify((globalThis.__reqs||[]))`;
function probe(ws,id,expr,ctx){ ws.send(JSON.stringify({id,method:'Runtime.evaluate',params:{expression:expr,returnByValue:true,awaitPromise:false,contextId:ctx}})); }
const ws=new WebSocket('ws://127.0.0.1:62000');
let target=null, phase='find';
ws.on('open',()=>{ ws.send(JSON.stringify({id:1,method:'Runtime.enable',params:{}}));
  for(let c=1;c<=60;c++) setTimeout(()=>ws.send(JSON.stringify({id:1000+c,method:'Runtime.evaluate',params:{expression:'(function(){try{return (wx.getAccountInfoSync().miniProgram.appId)}catch(e){return ""}})()',returnByValue:true,contextId:c}})),c*35);
  setTimeout(()=>{ if(target){ probe(ws,5000,HOOK,target); setTimeout(()=>probe(ws,5001,RELOAD,target),1200); setTimeout(()=>probe(ws,5002,READ,target),11000); setTimeout(()=>ws.close(),14000);} else { console.log('未找到辣可可上下文'); ws.close(); } },4000);
});
ws.on('message',(d)=>{ let m;try{m=JSON.parse(d.toString())}catch(e){return} const id=m.id;
  if(typeof id==='number'&&id>1000&&id<2000){ const v=m.result&&m.result.result&&m.result.result.value; if(v===APPID&&!target) target=id-1000; }
  if(id===5000||id===5001){  }
  if(id===5002){ const v=(m.result&&m.result.result&&m.result.result.value)||'[]';
    try{ const arr=JSON.parse(v); console.log('共捕获',arr.length,'条请求');
      const seen=new Set();
      for(const r of arr){ const path=(r.url||'').replace(/^https?:\/\/[^/]+/,'');
        const key=r.method+' '+path; if(seen.has(key))continue; seen.add(key);
        console.log('  '+r.method+' '+path); }
    }catch(e){ console.log('解析失败',v.slice(0,200)); } }
});

const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async()=>{
 const html=fs.readFileSync(process.argv[2],'utf8');
 const embedded=JSON.parse(html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const frames=embedded.modes.shortest.slice(0,2).map(f=>({...f,routing:{algorithm:'qos_priority',path:[23,24,25]}}));
 let state={status:'ready',frames:0,new_frames:[]},selected=null;
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.clock.install();await page.clock.pauseAt(new Date(Date.now()+1000));
  await page.route('http://127.0.0.1:8765/**', async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
   if(url.pathname==='/start'){selected=route.request().postDataJSON().algorithm;state={status:'running',run_id:'a'.repeat(32),algorithm:selected,frames:1,new_frames:[frames[0]]};return route.fulfill({status:202,json:state})}
   if(url.pathname==='/state')return route.fulfill({json:{...state,new_frames:state.new_frames.filter(f=>f.telemetry.epoch>Number(url.searchParams.get('after')))}});
   if(url.pathname==='/replay')return route.fulfill({json:{...embedded,modes:{qos_priority:frames},summary:{deadline_misses:0},batches:{},source:'live-test'}});
  });
  await page.goto('http://127.0.0.1:8765/');await page.locator('#liveMode').click();
  await page.waitForFunction(()=>!document.getElementById('startLive').disabled);
  await page.selectOption('#liveAlgorithm','qos_priority');await page.click('#startLive');
  await page.waitForFunction(()=>document.getElementById('counts').textContent.includes('102 nodes'));
  assert.equal(selected,'qos_priority');assert.equal(await page.locator('#startLive').isDisabled(),true);
  await page.screenshot({path:'/tmp/tinyleo-live-mode.png',fullPage:true});
  state={...state,status:'completed',frames:2,new_frames:frames,download:'saved',local_archive:'/test/run.zip'};
  await page.clock.runFor(1000);await page.waitForFunction(()=>!document.getElementById('replayLatest').disabled);
  await page.click('#replayLatest');await page.waitForFunction(()=>document.getElementById('algorithmLabel').textContent==='QoS Priority');
  assert.equal(await page.locator('#algorithmLabel').textContent(),'QoS Priority');
  assert.equal(await page.locator('#livePanel').isHidden(),true);assert.deepEqual(errors,[]);
  await page.screenshot({path:'/tmp/tinyleo-live-ui.png',fullPage:true});
  console.log('PASS: Live switch, real API algorithm selection, state rendering, duplicate-start disabled, saved replay loading.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});

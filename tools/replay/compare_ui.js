/* Compare view on the existing offline page; Live polling remains independent. */
const comparison={shortest:null,qos:null,time:80,timer:null,valid:false,imports:{shortest:0,qos:0}};
const CC=TinyLEOCompare;
const compareColors={shortest:'#69b7ff',qos:'#ffaf64',shared:'#99a6b5'};
const cellAnchors={12:[60.7212,-135.0568],13:[62.454,-114.3718],14:[63.7467,-68.517],
  23:[49.2827,-123.1207],24:[51.0447,-114.0719],25:[43.6532,-79.3832]};
function compareStop(){clearTimeout(comparison.timer);comparison.timer=null;$('comparePlay').textContent='▶ Play';}
function exitCompare(){compareStop();$('comparePanel').hidden=true;document.querySelector('.layout').hidden=false;$('importButton').hidden=false;}
function showCompare(){
 stop();showingLive=false;compareStop();$('comparePanel').hidden=false;
 for(const id of ['livePanel','replayControls','timeline'])$(id).hidden=true;
 document.querySelector('.layout').hidden=true;$('importButton').hidden=true;
 document.querySelector('.badge').textContent='● COMPARE · Recorded emulation results';
 document.querySelector('header p').textContent='Matched experiments · one network · per-flow results';
}
$('compareMode').onclick=showCompare;
// Use English controls even when the operating system localizes file inputs.
for(const [id,title] of [['compareShortest','Choose Shortest Path JSON'],['compareQos','Choose QoS Priority JSON']]){
 const input=$(id);input.hidden=true;
 const button=document.createElement('button');button.type='button';button.textContent=title;
 button.onclick=()=>input.click();input.parentElement.appendChild(button);
}
function number(value,places=2){return Number.isFinite(value)?value.toFixed(places):'N/A';}
function compareTable(target,heads,rows){
 const table=document.createElement('table');table.className='compare-table';
 const header=document.createElement('thead'),tr=document.createElement('tr');
 for(const title of heads){const th=document.createElement('th');th.scope='col';th.textContent=title;tr.append(th);}
 header.append(tr);table.append(header);const body=document.createElement('tbody');
 for(const row of rows){const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}
 table.append(body);$(target).replaceChildren(table);
}
async function importComparison(event,side){
 compareStop();const file=event.target.files[0];if(!file)return;
 const generation=++comparison.imports[side];
 comparison[side]=null;comparison.valid=false;$('compareResults').hidden=true;$('comparePlay').disabled=true;
 $('compareStatus').textContent='Reading recording…';
 try{
  if(file.size>100*1024*1024)throw Error('Recording exceeds the 100 MB import limit.');
  const parsed=JSON.parse(await file.text());
  if(generation!==comparison.imports[side])return;
  comparison[side]=parsed;
  if(!comparison.shortest||!comparison.qos){$('compareStatus').textContent='Recording loaded. Choose the other algorithm to compare.';return;}
  const check=CC.validatePair(comparison.shortest,comparison.qos);
  if(!check.valid)throw Error(check.errors.join(' · '));
  comparison.valid=true;$('compareResults').hidden=false;$('comparePlay').disabled=false;
  $('compareStatus').textContent=`Matched recorded inputs · Shortest Path: ${comparison.shortest.source} · QoS Priority: ${comparison.qos.source} · ${comparison.shortest.scenario.traffic_demands.length} flows · 301 states. This is not a live experiment.`;
  $('compareFlow').replaceChildren();
  for(const d of comparison.shortest.scenario.traffic_demands){const option=document.createElement('option');option.value=d.id;option.textContent=`${d.id} · ${d.service_class} · P${d.priority}`;$('compareFlow').append(option);}
  comparison.time=80;compareSummary();compareRender();
 }catch(error){if(generation===comparison.imports[side]){$('compareStatus').textContent='Cannot compare: '+error.message;comparison.valid=false;}}
}
$('compareShortest').onchange=e=>importComparison(e,'shortest');
$('compareQos').onchange=e=>importComparison(e,'qos');
function compareSummary(){
 if(!comparison.valid)return;
 const phase=$('comparePhase').value,a=CC.summarize(comparison.shortest,phase),b=CC.summarize(comparison.qos,phase),rows=[],demands=[];
 for(const d of comparison.shortest.scenario.traffic_demands){
  const x=a.flows[d.id],y=b.flows[d.id];
  const metrics=[['UDP loss','loss_percent','%',true],['p95 ping RTT','rtt_p95_ms','ms',false],
   ['Received throughput','throughput_mbps','Mbit/s',false],['Mean geographic hops','mean_hops','hops',null]];
  for(const [title,key,unit,loss] of metrics){
   const valid=Number.isFinite(x[key])&&Number.isFinite(y[key]);
   const delta=valid?(loss===null?y[key]-x[key]:loss?y[key]-x[key]:CC.relativeChange(x[key],y[key])):null;
   rows.push([`${d.id} · ${title}`,`${number(x[key])} ${unit}`,`${number(y[key])} ${unit}`,
     `${number(delta)} ${loss===null?'hops':loss?'pp':'%'}`]);
  }
  const paths=CC.pathSummary(comparison.shortest,comparison.qos,d.id,phase);
  const desc=items=>items.map(p=>`${p.path.join(' → ')} (${p.frames} frames)`).join('; ')||'No comparable active route';
  demands.push([`${d.id} · ${d.service_class} · P${d.priority}`,desc(paths.shortest),desc(paths.qos),`${paths.different} / ${paths.comparable}`]);
 }
 rows.push(['Topology deadline misses',a.deadline_misses,b.deadline_misses,b.deadline_misses-a.deadline_misses]);
 compareTable('compareSummary',['Metric','Shortest Path','QoS Priority','Change'],rows);
 compareTable('compareDemands',['Flow / priority','Shortest Path · paths and frequency','QoS Priority · paths and frequency','Different frames'],demands);
}
function compareMap(frame,segments,paths){
 const svg=$('compareMap');svg.replaceChildren();
 const project=(lat,lon)=>[(lon+155)/110*960,520-(lat-35)/50*520];
 const geometry=(comparison.shortest.map||originalReplay.map).geometry;
 const polygons=geometry.type==='MultiPolygon'?geometry.coordinates:[geometry.coordinates];
 for(const polygon of polygons){const d=polygon.map(ring=>ring.map((p,i)=>(i?'L':'M')+project(p[1],p[0]).join(',')).join(' ')+'Z').join(' ');el('path',{d,fill:'#182f3d',stroke:'#37556a','stroke-width':1,'fill-rule':'evenodd'},svg);}
 const background=el('g',{'data-physical-topology':'shared',opacity:.28},svg);
 for(const l of frame.links){const a=frame.nodes[l.a],b=frame.nodes[l.b];if(!a||!b||Math.abs(a[1]-b[1])>180)continue;
  const [x1,y1]=project(a[0],a[1]),[x2,y2]=project(b[0],b[1]);el('line',{x1,y1,x2,y2,stroke:l.kind==='gsls'?'#ffc97d':'#56dac4','stroke-width':1},background);}
 for(const [name,p] of Object.entries(frame.nodes)){const [cx,cy]=project(p[0],p[1]);const dot=el('circle',{cx,cy,r:name.startsWith('GS')?4:2,fill:name.startsWith('GS')?'#ffc97d':'#56dac4'},background);el('title',{},dot,name);}
 const defs=el('defs',{},svg);
 for(const [kind,color] of Object.entries(compareColors)){const marker=el('marker',{id:'compare-arrow-'+kind,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto-start-reverse'},defs);el('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color},marker);}
 const all=[...segments.shared,...segments.shortest,...segments.qos];
 for(const kind of ['shared','shortest','qos'])for(const [a,b] of segments[kind]){
  if(kind==='shared'&&$('compareDifferences').checked)continue;
  if(!cellAnchors[a]||!cellAnchors[b])continue;
  let [x1,y1]=project(...cellAnchors[a]),[x2,y2]=project(...cellAnchors[b]);
  const length=Math.hypot(x2-x1,y2-y1)||1;
  if(all.some(e=>e[0]===b&&e[1]===a)){const dx=-(y2-y1)/length*5,dy=(x2-x1)/length*5;x1+=dx;x2+=dx;y1+=dy;y2+=dy;}
  const line=el('line',{x1,y1,x2,y2,stroke:compareColors[kind],'stroke-width':kind==='shared'?2:4,
    'stroke-dasharray':kind==='qos'?'8 5':'none','marker-end':`url(#compare-arrow-${kind})`,'data-route':kind},svg);
  el('title',{},line,`${kind}: cell ${a} → ${b}`);
 }
 const cells=new Set(paths.filter(Array.isArray).flat());
 for(const cell of cells){if(!cellAnchors[cell])continue;const [cx,cy]=project(...cellAnchors[cell]);el('circle',{cx,cy,r:6,fill:'#0e1c29',stroke:'#d6e4ef','stroke-width':2},svg);el('text',{x:cx+10,y:cy-10,fill:'#e2f1f8','font-size':14},svg,'Cell '+cell);}
}
function series(run,demand,metric){
 const records=run.flow_measurements?.[demand?.id]||{};
 if(metric==='rtt')return (records.ping||[]).map(r=>({t:r.simulation_time_s,value:r.kind==='reply'?r.rtt_ms:null}));
 return (records.intervals||[]).map(r=>({t:r.end_s,value:metric==='loss'?(r.packets?r.lost_packets/r.packets*100:null):r.duration_s>0?r.bytes_received*8/r.duration_s/1e6:null}));
}
function comparePlot(id,demand,metric){
 const svg=$(id);svg.replaceChildren();const [lo,hi]=CC.PHASES[$('comparePhase').value];
 const sets=[series(comparison.shortest,demand,metric),series(comparison.qos,demand,metric)].map(s=>s.filter(p=>p.t>=lo&&p.t<hi));
 const values=sets.flat().map(p=>p.value).filter(Number.isFinite),max=values.length?Math.max(1,...values)*1.12:1;
 const x=t=>45+(t-lo)/(hi-lo)*380,y=v=>165-v/max*140;
 for(const [phase,bounds] of Object.entries(CC.PHASES)){if(phase==='full')continue;const a=Math.max(lo,bounds[0]),b=Math.min(hi,bounds[1]);if(a<b)el('rect',{x:x(a),y:20,width:x(b)-x(a),height:145,fill:phase==='competition'?'#392f23':'#152c36',opacity:.6},svg);}
 el('line',{x1:45,y1:165,x2:425,y2:165,stroke:'#456074'},svg);
 for(const [text,px,py] of [[number(max,1),2,28],['0',20,169],[lo+'s',45,188],[hi+'s',390,188]])el('text',{x:px,y:py,fill:'#91a7b7','font-size':11},svg,text);
 sets.forEach((points,index)=>{let previous=null;const color=index?compareColors.qos:compareColors.shortest;
  for(const p of points){if(!Number.isFinite(p.value)){previous=null;continue;}
   if(previous&&p.t-previous.t<=1.5)el('line',{x1:x(previous.t),y1:y(previous.value),x2:x(p.t),y2:y(p.value),stroke:color,'stroke-width':1.5,'stroke-dasharray':index?'5 3':'none'},svg);
   const dot=el('circle',{cx:x(p.t),cy:y(p.value),r:2,fill:color},svg);el('title',{},dot,`${index?'QoS':'Shortest'}: t=${number(p.t,3)}s, ${number(p.value,3)}`);previous=p;
  }
 });
 if(comparison.time>=lo&&comparison.time<=hi)el('line',{x1:x(comparison.time),y1:15,x2:x(comparison.time),y2:165,stroke:'#cddde6','stroke-width':1},svg);
 if(!values.length)el('text',{x:80,y:100,fill:'#a9bbc8','font-size':13},svg,'No measured samples in this window');
}
function compareRender(){
 if(!comparison.valid)return;
 const id=$('compareFlow').value,d=comparison.shortest.scenario.traffic_demands.find(d=>d.id===id),t=comparison.time;
 $('compareTime').value=t;$('compareTimeLabel').textContent=`t = ${t} s / 300 s`;
 const pair=CC.pairedFrame(comparison.shortest,comparison.qos,t);
 const p=CC.pathAt(comparison.shortest,t,id),q=CC.pathAt(comparison.qos,t,id),segments=CC.routeSegments(p,q);
 $('compareFlowTitle').textContent=`${d.id} · ${d.service_class} · Priority ${d.priority}`;
 $('compareRoutes').replaceChildren();
 for(const [label,path] of [['Shortest Path',p],['QoS Priority',q]]){const row=document.createElement('p');row.textContent=label+': '+(path?path.join(' → '):'No active recorded route');$('compareRoutes').append(row);}
 $('compareRouteStatus').textContent=!pair.valid?pair.error:!segments.available?'No comparable active routes at this time':segments.same?'Same route at this time':'Geographic routes differ at this time';
 if(pair.valid)compareMap(pair.left,segments,[p,q]);else $('compareMap').replaceChildren();
 const first=CC.firstDifference(comparison.shortest,comparison.qos,id);$('compareFirstDifference').disabled=first===null;
 $('compareFirstDifference').title=first===null?'No recorded route difference for this flow':`Jump to t=${first}s`;
 const sums=[comparison.shortest,comparison.qos].map(run=>CC.summarize(run,$('comparePhase').value).flows[id]);
 $('compareCoverage').textContent=sums.map((s,i)=>`${i?'QoS':'Shortest'}: receiver coverage ${number(s.covered_s,2)} / ${number(s.expected_s,0)} s; boundary exclusions ${number(s.excluded_boundary_s,3)} s; RTT replies ${s.ping_samples}, observed probe loss ${number(s.ping_loss_percent)}%.`).join(' ');
 const demands=comparison.shortest.scenario.traffic_demands,c2=demands.find(d=>d.service_class==='C2'),bulk=demands.find(d=>['bulk','best_effort'].includes(d.service_class));
 comparePlot('compareRtt',c2,'rtt');comparePlot('compareLoss',c2,'loss');comparePlot('compareThroughput',bulk,'throughput');
}
function compareSeek(t){compareStop();comparison.time=Math.max(0,Math.min(300,t));compareRender();}
function compareTick(){comparison.time++;compareRender();if(comparison.time>=300)compareStop();else comparison.timer=setTimeout(compareTick,1000/Number($('compareSpeed').value));}
$('comparePlay').onclick=()=>{if(comparison.timer!==null){compareStop();return;}if(comparison.time===300)comparison.time=0;$('comparePlay').textContent='Ⅱ Pause';comparison.timer=setTimeout(compareTick,1000/Number($('compareSpeed').value));};
$('compareTime').oninput=e=>compareSeek(Number(e.target.value));
$('comparePrevious').onclick=()=>compareSeek(comparison.time-1);$('compareNext').onclick=()=>compareSeek(comparison.time+1);
$('compareSpeed').onchange=()=>{if(comparison.timer!==null){clearTimeout(comparison.timer);comparison.timer=setTimeout(compareTick,1000/Number($('compareSpeed').value));}};
$('compareFlow').onchange=()=>{compareStop();compareRender();};$('compareDifferences').onchange=compareRender;
$('comparePhase').onchange=()=>{compareSummary();compareRender();};
$('compareFirstDifference').onclick=()=>{const t=CC.firstDifference(comparison.shortest,comparison.qos,$('compareFlow').value);if(t!==null)compareSeek(t);};
document.querySelectorAll('[data-compare-jump]').forEach(button=>button.onclick=()=>compareSeek(Number(button.dataset.compareJump)));
document.addEventListener('visibilitychange',()=>{if(document.hidden)compareStop();});

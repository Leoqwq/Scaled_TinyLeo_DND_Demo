/* Pure comparison math. Also embedded verbatim into the standalone HTML. */
(function(root) {
  'use strict';
  const PHASES={baseline:[20,80],competition:[80,240],recovery:[240,290],full:[0,301]};
  const finite=n=>typeof n==='number' && Number.isFinite(n);
  const stable=x=>JSON.stringify(canonical(x));
  function canonical(x) {
    if(Array.isArray(x)) return x.map(canonical);
    if(x && typeof x==='object') return Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])]));
    return x;
  }
  function frames(run) { return Object.values(run?.modes||{})[0]||[]; }
  function algorithm(run) { return Object.keys(run?.modes||{})[0]; }
  function frameAt(run,second) { return frames(run).find(f=>f.telemetry?.simulation_time_s===second)||null; }
  function physical(frame) {
    return {nodes:frame.nodes,links:frame.links.map(l=>({...l,a:l.a<l.b?l.a:l.b,b:l.a<l.b?l.b:l.a}))
      .sort((a,b)=>stable(a).localeCompare(stable(b)))};
  }
  function pairedFrame(a,b,second) {
    const left=frameAt(a,second),right=frameAt(b,second);
    if(!left||!right) return {valid:false,error:'Missing recorded state at this time',left,right};
    if(!left.nodes||!right.nodes||!Array.isArray(left.links)||!Array.isArray(right.links))
      return {valid:false,error:'Invalid physical state',left,right};
    if(stable(physical(left))!==stable(physical(right)))
      return {valid:false,error:'Physical topology differs at this time',left,right};
    return {valid:true,left,right};
  }
  function validatePair(a,b) {
    const errors=[];
    if(a?.schema_version!==2||b?.schema_version!==2) errors.push('Requires two multi-flow schema v2 recordings; legacy files remain available in Replay.');
    if(algorithm(a)!=='shortest_path'||algorithm(b)!=='qos_priority') errors.push('Select one Shortest Path and one QoS Priority recording.');
    for(const [label,run] of [['Shortest Path',a],['QoS Priority',b]]) {
      if(run?.summary?.status!=='completed'||run?.summary?.comparison_eligible!==true)
        errors.push(`${label}: incomplete or ineligible measurements`);
      const times=frames(run).map(f=>f.telemetry?.simulation_time_s);
      if(times.length!==301||times.some((t,i)=>t!==i)) errors.push(`${label}: missing, duplicate or unordered time axis`);
    }
    for(const key of ['scenario_sha256','physical_sha256','runtime_sha256','shaping_sha256','time_axis_sha256','measurement_version']) {
      const value=a?.provenance?.[key];
      if(typeof value!=='string'||!value||value==='unknown'||value!==b?.provenance?.[key]) errors.push(`Mismatched or missing ${key}`);
    }
    if(!a?.scenario?.traffic_demands?.length||stable(a?.scenario)!==stable(b?.scenario)) errors.push('Demand, schedule or shaping inputs differ');
    return {valid:errors.length===0,errors};
  }
  function routeSegments(a,b) {
    if(!Array.isArray(a)||!Array.isArray(b)||a.length<2||b.length<2)
      return {shared:[],shortest:[],qos:[],same:false,available:false};
    const edges=p=>p.slice(1).map((v,i)=>[p[i],v]);
    const left=edges(a),right=edges(b),ls=new Set(left.map(stable)),rs=new Set(right.map(stable));
    return {shared:left.filter(e=>rs.has(stable(e))),shortest:left.filter(e=>!rs.has(stable(e))),
      qos:right.filter(e=>!ls.has(stable(e))),same:stable(a)===stable(b),available:true};
  }
  function pathAt(run,time,id) { return frameAt(run,time)?.routing?.flows?.find(d=>d.id===id)?.path||null; }
  function firstDifference(a,b,id) {
    for(const f of frames(a)) {
      const t=f.telemetry.simulation_time_s;
      const routes=routeSegments(pathAt(a,t,id),pathAt(b,t,id));
      if(routes.available&&!routes.same&&pairedFrame(a,b,t).valid) return t;
    }
    return null;
  }
  function bounds(phase) {
    if(!Object.hasOwn(PHASES,phase)) throw Error('Unknown summary phase');
    return PHASES[phase];
  }
  function pathSummary(a,b,id,phase) {
    const [lo,hi]=bounds(phase),left=new Map(),right=new Map();let comparable=0,different=0;
    for(let t=lo;t<hi;t++) {
      const p=pathAt(a,t,id),q=pathAt(b,t,id);
      if(!routeSegments(p,q).available||!pairedFrame(a,b,t).valid) continue;
      comparable++;if(stable(p)!==stable(q)) different++;
      for(const [map,path] of [[left,p],[right,q]]) map.set(stable(path),(map.get(stable(path))||0)+1);
    }
    const sorted=map=>[...map].map(([path,n])=>({path:JSON.parse(path),frames:n})).sort((a,b)=>b.frames-a.frames);
    return {comparable,different,shortest:sorted(left),qos:sorted(right)};
  }
  function relativeChange(a,b) { return finite(a)&&finite(b)&&a!==0?(b-a)/a*100:null; }
  function percentile(values,q=.95) {
    if(!values.length) return null;
    const sorted=values.slice().sort((a,b)=>a-b);
    return sorted[Math.max(0,Math.ceil(q*sorted.length)-1)];
  }
  function validInterval(r) {
    return finite(r.start_s)&&finite(r.end_s)&&r.end_s>r.start_s&&finite(r.duration_s)&&r.duration_s>0
      &&['packets','lost_packets','bytes_received'].every(k=>Number.isInteger(r[k])&&r[k]>=0)
      &&r.lost_packets<=r.packets;
  }
  function summarize(run,phase='competition') {
    const [lo,hi]=bounds(phase),result={phase,start_s:lo,end_s:hi,flows:{},deadline_misses:0};
    result.deadline_misses=frames(run).filter(f=>f.telemetry.simulation_time_s>=lo&&f.telemetry.simulation_time_s<hi&&f.telemetry.deadline_missed).length;
    for(const demand of run.scenario?.traffic_demands||[]) {
      const data=run.flow_measurements?.[demand.id]||{},start=Math.max(lo,demand.start_s),end=Math.min(hi,demand.end_s);
      const expected=Math.max(0,end-start),all=data.intervals||[];
      let packets=0,lost=0,bytes=0,covered=0,duration=0,boundary=0,previous=-Infinity,invalid=0;
      for(const row of [...all].sort((a,b)=>a.start_s-b.start_s)) {
        if(!validInterval(row)) {invalid++;continue;}
        if(row.start_s<previous-1e-6) {invalid++;continue;}
        previous=row.end_s;
        const overlap=Math.max(0,Math.min(end,row.end_s)-Math.max(start,row.start_s));
        if(row.start_s<start||row.end_s>end) {boundary+=overlap;continue;}
        packets+=row.packets;lost+=row.lost_packets;bytes+=row.bytes_received;
        covered+=overlap;duration+=row.duration_s;
      }
      const probes=(data.ping||[]).filter(p=>finite(p.simulation_time_s)&&p.simulation_time_s>=start&&p.simulation_time_s<end);
      const replies=probes.filter(p=>p.kind==='reply'&&finite(p.rtt_ms)&&p.rtt_ms>=0);
      const missed=probes.filter(p=>p.kind==='unanswered');
      const paths=frames(run).filter(f=>f.telemetry.simulation_time_s>=start&&f.telemetry.simulation_time_s<end)
        .map(f=>f.routing?.flows?.find(d=>d.id===demand.id)?.path).filter(p=>Array.isArray(p)&&p.length>=2);
      result.flows[demand.id]={loss_percent:packets?lost/packets*100:null,
        throughput_mbps:duration?bytes*8/duration/1e6:null,rtt_p95_ms:percentile(replies.map(p=>p.rtt_ms)),
        packets,lost_packets:lost,bytes_received:bytes,ping_samples:replies.length,
        ping_loss_percent:replies.length+missed.length?missed.length/(replies.length+missed.length)*100:null,
        covered_s:covered,expected_s:expected,coverage_fraction:expected?covered/expected:null,
        excluded_boundary_s:boundary,invalid_intervals:invalid,
        mean_hops:paths.length?paths.reduce((n,p)=>n+p.length-1,0)/paths.length:null,
        measurement_complete:data.complete===true};
    }
    return result;
  }
  const api={PHASES,stable,frames,algorithm,frameAt,pairedFrame,validatePair,routeSegments,pathAt,
    firstDifference,pathSummary,relativeChange,percentile,summarize};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  else root.TinyLEOCompare=api;
})(globalThis);

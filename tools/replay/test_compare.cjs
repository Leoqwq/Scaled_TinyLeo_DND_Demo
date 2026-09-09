const assert = require('node:assert/strict');
const C = require('./compare.js');
function run(algorithm='shortest_path') {
  const frames=Array.from({length:301},(_,t)=>({nodes:{GS1:[60,-135,0]},links:[],
    telemetry:{epoch:t,simulation_time_s:t,deadline_missed:false},
    routing:{flows:[{id:'c2',path:[12,13,14]}]}}));
  return {schema_version:2,source:algorithm,summary:{status:'completed',comparison_eligible:true},
    modes:{[algorithm]:frames},provenance:Object.fromEntries(['scenario_sha256','physical_sha256','runtime_sha256','shaping_sha256','time_axis_sha256'].map(k=>[k,'a'.repeat(64)]).concat([['measurement_version','iperf 3.20']])),
    scenario:{traffic_demands:[{id:'c2',priority:5,service_class:'C2',start_s:20,end_s:290,source:12,destination:14}]},
    flow_measurements:{c2:{complete:true,intervals:[
      {start_s:80,end_s:81,duration_s:1,packets:10,lost_packets:1,bytes_received:9000},
      {start_s:81,end_s:82,duration_s:1,packets:90,lost_packets:9,bytes_received:81000}],
      ping:[{simulation_time_s:80.1,rtt_ms:10,kind:'reply',sequence:1},
            {simulation_time_s:81.1,rtt_ms:20,kind:'reply',sequence:2},
            {simulation_time_s:82.1,rtt_ms:80,kind:'reply',sequence:3},
            {simulation_time_s:83.1,rtt_ms:null,kind:'unanswered',sequence:4}]}}};
}

assert.deepEqual(C.routeSegments([12,13,14],[12,13,24,25]), {
  shared:[[12,13]],shortest:[[13,14]],qos:[[13,24],[24,25]],same:false,available:true});
assert.deepEqual(C.routeSegments([12,13],[13,12]).shared,[]);
assert.equal(C.routeSegments(null,null).available,false);
assert.equal(C.routeSegments([12,13],[12,13]).same,true);
assert.equal(C.frameAt({modes:{x:[{telemetry:{simulation_time_s:2}}]}},1),null);
assert.equal(C.validatePair(run(),run('qos_priority')).valid,true);
const duplicate=run(); duplicate.modes.shortest_path[1].telemetry.simulation_time_s=0;
assert.equal(C.validatePair(duplicate,run('qos_priority')).valid,false);
const mismatch=run('qos_priority');mismatch.provenance.shaping_sha256='b'.repeat(64);
assert.match(C.validatePair(run(),mismatch).errors.join(' '),/shaping/);
const invalid=run('qos_priority');invalid.modes.qos_priority[80].nodes.GS1=[61,-135,0];
assert.equal(C.pairedFrame(run(),invalid,80).valid,false);
const legacy=run();legacy.schema_version=1;
assert.equal(C.validatePair(legacy,run('qos_priority')).valid,false);
const zero=C.relativeChange(0,1);assert.equal(zero,null);
assert.equal(C.relativeChange(100,80),-20);
const sum=C.summarize(run(),'competition').flows.c2;
assert.equal(sum.loss_percent,10);
assert.equal(sum.throughput_mbps,.36);
assert.equal(sum.rtt_p95_ms,80);
assert.equal(sum.ping_samples,3);
assert.equal(sum.ping_loss_percent,25);
assert.equal(sum.covered_s,2);
assert.equal(sum.coverage_fraction,2/160);
const boundary=run();boundary.flow_measurements.c2.intervals.unshift({start_s:79.5,end_s:80.5,duration_s:1,packets:999,lost_packets:0,bytes_received:999000});
assert.equal(C.summarize(boundary,'competition').flows.c2.loss_percent,10);
assert.equal(C.summarize(boundary,'competition').flows.c2.excluded_boundary_s,.5);
const empty=run();empty.flow_measurements.c2.intervals=[];
assert.equal(C.summarize(empty,'competition').flows.c2.loss_percent,null);
const q=run('qos_priority');q.modes.qos_priority[83].routing.flows[0].path=[12,23,24,25,14];
assert.equal(C.firstDifference(run(),q,'c2'),83);
assert.equal(C.firstDifference(run(),run('qos_priority'),'c2'),null);
const paths=C.pathSummary(run(),q,'c2','competition');
assert.equal(paths.different,1);assert.equal(paths.comparable,160);
assert.deepEqual(paths.shortest[0],{path:[12,13,14],frames:160});
console.log('PASS: comparison validation, directed overlay, exact summary, missing/boundary data, timestamp alignment.');
module.exports={run};

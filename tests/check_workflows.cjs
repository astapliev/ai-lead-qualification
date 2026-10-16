const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const dir = path.join(__dirname, '../n8n');
let compiled = 0;
for (const file of fs.readdirSync(dir).filter(f => f.endsWith('.json'))) {
  const d = JSON.parse(fs.readFileSync(path.join(dir, file)));
  const names = new Set(d.nodes.map(n => n.name));
  assert.equal(d.active, false);
  assert.equal(Object.keys(d.pinData).length, 0);
  for (const [source, groups] of Object.entries(d.connections)) {
    assert(names.has(source));
    for (const targets of Object.values(groups)) for (const output of targets) {
      for (const e of output) assert(names.has(e.node), `Missing ${e.node}`);
    }
  }
  for (const n of d.nodes) if (n.parameters.jsCode) {
    new Function('$input', '$', n.parameters.jsCode);
    compiled++;
  }
}
const intake = JSON.parse(fs.readFileSync(path.join(dir,'intake.json')));
const worker = JSON.parse(fs.readFileSync(path.join(dir,'worker.json')));
const get = (d, name) => d.nodes.find(n => n.name === name);
assert.equal(get(intake,'Lead Intake').parameters.authentication, 'headerAuth');
assert.equal(get(intake,'Wake Worker').parameters.options.waitForSubWorkflow, false);
assert.equal(intake.connections['Return Duplicate'].main[0][0].node, 'Wake Worker');
assert.equal(get(worker,'AI Lead Analysis').retryOnFail, false);
assert(!worker.nodes.some(n => n.type.endsWith('scheduleTrigger')));
const code = get(intake,'Normalize & Validate Lead Data').parameters.jsCode;
const validate = bodies => new Function('$input', code)({all:()=>bodies.map(body=>({json:{body}}))});
const base = {request_id:'7ea00834-741c-4257-ba4d-a1027ab28743',name:'Ацамаз Плиев',contact:'Telegram: @example_user',service:'AI-автоматизация продаж',budget:null,message:'Перенести заявки в CRM. Сохранить историю.',timeline:'1–2 недели'};
let cases = 0;
for (const [field, values] of Object.entries({
 name:[null,[],{},1,true,'X','<>'], contact:[null,[],{},1,true,'Telegram: @x','Телефон: +7１２３４５６７８９０'],
 service:[null,[],{},1,true,'wrong'], budget:[false,true,{},[],'100',0,-1,1.5,1000000001],
 message:[null,[],{},1,true,'short',base.message+'\0'], timeline:[[],{},1,true,'wrong'],
 request_id:[null,[],{},1,true,base.request_id.toUpperCase(),base.request_id+'\n']
})) for (const value of values) {
 const result = validate([{...base,[field]:value}])[0];
 assert.equal(result.json.is_valid,false, `Accepted invalid ${field}`);
 assert(field in result.json.field_errors);
 cases++;
}
const accepted = validate([base, {...base,name:'आदित्य शर्मा'}, {...base,name:'  Ацамаз   Плиев  ',contact:'Email: USER@EXAMPLE.COM'}]);
for (let i=0;i<accepted.length;i++) {
 assert.equal(accepted[i].json.is_valid,true);
 assert.equal(accepted[i].pairedItem.item,i);
 assert.equal(Object.keys(accepted[i].json.payload).length,7);
}
assert.equal(accepted[2].json.payload.contact,'Email: user@example.com');
// Worker paths: normal AI output, retry, exhausted attempts, permanent error, parser error.
const outcomeCode=get(worker,'Prepare Worker Outcome').parameters.jsCode;
const source={...base,id:'9223372036854775000',processing_token:'12',processing_attempts:1};
function outcome(data, attempts=1) {
 return new Function('$input','$',outcomeCode)({all:()=>[{json:data}]},()=>({first:()=>({json:{...source,processing_attempts:attempts}})}))[0].json;
}
assert.equal(outcome({output:{lead_score:80,intent:'buy',urgency:'high',reason:'Подходящая задача'}}).action,'success');
assert.equal(outcome({error:{status:503}}).action,'retry');
assert.equal(outcome({error:{status:503}},3).action,'review');
assert.equal(outcome({error:{status:401}}).action,'review');
assert.equal(outcome({error:{name:'OutputParserException'}}).action,'review');
assert.equal(outcome({error:{status:429,retry_after:300}}).delay_seconds,300);
assert.equal(outcome({error:{status:429,retry_after:Infinity}}).delay_seconds,120);
console.log(`PASS: 3 workflow graphs, ${compiled} JavaScript nodes compiled, ${cases+3} intake cases, 7 AI outcome cases.`);

import test from 'node:test';
import assert from 'node:assert/strict';
import {compileRoutes} from '../qwencode_public/compile-routes.mjs';

const privateRoute=()=>({
  schema:'qwen-role-routes/v1',
  workcellClass:'private',
  routes:[{
    role:'coder',
    kind:'sovereign',
    dataClass:'private',
    modelId:'synthetic-sovereign',
    envKey:'SYNTHETIC_GUEST_KEY',
    baseUrl:'http://127.0.0.1:11434/v1',
    privateNetworkAdmitted:true
  }]
});
const cloudRoute=()=>({
  schema:'qwen-role-routes/v1',
  workcellClass:'public',
  routes:[{
    role:'planner',
    kind:'cloud',
    dataClass:'public',
    modelId:'synthetic-cloud',
    envKey:'SYNTHETIC_PUBLIC_KEY',
    baseUrl:'https://example.invalid/v1'
  }]
});
const fail=(base,delta)=>assert.throws(()=>compileRoutes({
    ...base, routes:[{...base.routes[0],...delta}]
}));

test('POSITIVE sovereign metadata emits no ambient effect grant',()=>{
  const out=compileRoutes(privateRoute());
  assert.equal(out.model.name,'synthetic-sovereign');
  assert.deepEqual(Object.keys(out.mcpServers),[]);
  assert.equal(out.memory.enableTeamMemorySync,false);
  assert.equal(out.memory.enableManagedAutoMemory,false);
  assert.equal(out.experimental.agentTeam,false);
  assert.equal(Object.hasOwn(out,'tools'),false,'no ambient YOLO or tool grant');
  assert.equal(out.modelProviders.openai[0].envKey,'SYNTHETIC_GUEST_KEY');
  assert.equal(Object.hasOwn(out.modelProviders.openai[0],'apiKey'),false);
});

test('POSITIVE public cloud route uses HTTPS and no hidden model fallback',()=>{
  const out=compileRoutes(cloudRoute());
  assert.equal(out.agents.modelGrades.planner,'openai:synthetic-cloud');
  assert.deepEqual(out.agents.allowedGrades,['planner']);
  assert.deepEqual(out.modelProviders.openai.map(x=>x.id),['synthetic-cloud']);
  assert.equal(Object.hasOwn(out,'tools'),false);
});

test('NEGATIVE private-to-cloud downgrade is forbidden',()=>{
  const p=privateRoute();
  fail(p,{kind:'cloud',baseUrl:'https://example.invalid/v1'});
  fail(p,{dataClass:'public'});
  const q=cloudRoute();
  fail(q,{dataClass:'private'});
});

test('NEGATIVE insecure cloud URLs and embedded credentials are denied',()=>{
  const base=cloudRoute();
  fail(base,{baseUrl:'http://example.invalid/v1'});
  fail(base,{baseUrl:'https://user:pass@example.invalid/v1'});
  fail(base,{baseUrl:'https://example.invalid/v1?token=accidental-secret'});
  fail(base,{baseUrl:'file:///etc/passwd'});
  fail(base,{apiKey:'not-a-real-key'});
  fail(base,{token:'not-a-real-token'});
  fail(base,{secret:'not-a-real-secret'});
});

test('NEGATIVE private route must explicitly mark separately admitted network',()=>{
  const base=privateRoute();
  fail(base,{privateNetworkAdmitted:false});
  fail(base,{envKey:'not-an-env-var-name'});
  fail(base,{baseUrl:'http://user:password@127.0.0.1:11434/v1'});
});

test('NEGATIVE unknown roles, duplicates and unsafe media assertions are denied',()=>{
  const base=privateRoute();
  fail(base,{role:'root-shell'});
  fail(base,{role:'video-critic',supportsImages:false});
  assert.throws(()=>compileRoutes({...base,routes:[base.routes[0],{...base.routes[0]}]}));
  assert.throws(()=>compileRoutes({...base,routes:[]}));
  assert.throws(()=>compileRoutes({...base,routes:[{...base.routes[0],role:'critic'}]}));
});

test('NEGATIVE model ID collision and context inflation are denied',()=>{
  const base=privateRoute();
  fail(base,{modelId:'../escape'});
  fail(base,{contextWindowSize:2_000_000});
  fail(base,{timeoutMs:9_999_999});
});

/**
 * Public-safe Qwen Code model-role compiler. Node 22+ standard library only.
 * Outputs config data, never a credential, network grant, or production admission.
 * Native CLI agent selection still requires model/provider runtime qualification.
 */
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const ROLES=new Set(['planner','coder','operator','critic','video-critic','pdf-converter','researcher']);
const ENV=/^[A-Z][A-Z0-9_]{2,63}$/;
const MODEL=/^[A-Za-z0-9][A-Za-z0-9_.:/+\-]{0,127}$/;
const classes=new Set(['public','private']);

export function compileRoutes(input) {
  assert.equal(input?.schema,'qwen-role-routes/v1','unsupported route schema');
  assert.ok(classes.has(input.workcellClass),'unknown workcell data class');
  assert.ok(Array.isArray(input.routes) && input.routes.length>=1 && input.routes.length<=12,'invalid route count');
  const seenRoles=new Set(),seenModelIds=new Set();
  const registry=[]; const roles={};
  const ordered=[...input.routes].sort((a,b)=>String(a.role).localeCompare(String(b.role)));
  for(const r of ordered){
    assert.ok(ROLES.has(r.role),'unrecognized role');
    assert.ok(!seenRoles.has(r.role),'duplicate role');
    seenRoles.add(r.role);
    assert.ok(MODEL.test(r.modelId),'model ID missing or invalid');
    assert.ok(!seenModelIds.has(r.modelId),'ambiguous model ID across providers');
    seenModelIds.add(r.modelId);
    assert.ok(ENV.test(r.envKey),'credential must be an env-var reference');
    assert.ok(!('apiKey' in r)&&!('secret' in r)&&!('token' in r),'embedded credential forbidden');
    assert.ok(r.kind==='sovereign'||r.kind==='cloud','invalid source class');
    assert.ok(r.dataClass==='public'||r.dataClass==='private','invalid data classification');
    assert.ok(input.workcellClass==='private'
      ? r.kind==='sovereign'&&r.dataClass==='private'
      : r.dataClass==='public','cross-class route forbidden');
    const u=new URL(r.baseUrl);
    assert.ok(!u.username&&!u.password&&!u.hash&&!u.search,'URL must not contain userinfo/query/fragment');
    assert.ok(u.protocol==='http:'||u.protocol==='https:','unknown URL protocol');
    if(r.kind==='cloud')assert.equal(u.protocol,'https:','cloud route requires HTTPS');
    if(r.kind==='sovereign')assert.ok(r.privateNetworkAdmitted===true,
      'unqualified private network route');
    const timeout=Number(r.timeoutMs??120000),context=Number(r.contextWindowSize??32768);
    assert.ok(Number.isInteger(timeout)&&timeout>=1000&&timeout<=600000,'invalid timeout');
    assert.ok(Number.isInteger(context)&&context>=2048&&context<=131072,'invalid context');
    if(r.role==='video-critic')assert.equal(r.supportsImages,true,
      'video critique requires visual capability');
    registry.push({id:r.modelId,name:r.role+'-'+r.modelId,envKey:r.envKey,
      baseUrl:u.toString().replace(/\/$/,''),
      generationConfig:{timeout,contextWindowSize:context,maxRetries:1,
        modalities:{image:r.supportsImages===true}}});
    roles[r.role]='openai:'+r.modelId;
  }
  assert.ok(seenRoles.has('coder')||seenRoles.has('planner'),'missing primary role');
  const primary=roles.coder||roles.planner;
  return {
    security:{auth:{selectedType:'openai'}},
    model:{name:primary.replace(/^openai:/,'')},
    modelProviders:{openai:registry},
    agents:{modelGrades:roles,allowedGrades:Object.keys(roles),
      defaultBackground:true,maxParallelAgents:3},
    // Never pre-enable YOLO in a transport/profile compiler. The qualified
    // workcell controller sets that mode only after external admission.
    mcpServers:{},
    memory:{enableManagedAutoMemory:false,enableManagedAutoDream:false,
      enableStructuredRecall:false,enableTeamMemory:false,
      enableTeamMemorySync:false,autoSkillConfirm:true},
    experimental:{agentTeam:false},
    privacy:{usageStatisticsEnabled:false}
  };
}

function selfTest(){
  const good={schema:'qwen-role-routes/v1',workcellClass:'private',routes:[{
    role:'coder',kind:'sovereign',dataClass:'private',modelId:'local-coder',
    envKey:'LOCAL_CODER_KEY',baseUrl:'http://127.0.0.1:11434/v1',
    privateNetworkAdmitted:true}]};
  const x=compileRoutes(good);
  assert.equal(x.agents.modelGrades.coder,'openai:local-coder');
  assert.equal(x.modelProviders.openai[0].envKey,'LOCAL_CODER_KEY');
  assert.equal(x.model.name,'local-coder');
  assert.equal(Object.hasOwn(x,'tools'),false,'compiler may not grant YOLO');
  assert.equal(JSON.stringify(x).includes('apiKey'),false);
  const bad=(change)=>{assert.throws(()=>compileRoutes({...good,routes:[{...good.routes[0],...change}]}));};
  bad({kind:'cloud',baseUrl:'https://example.invalid/v1'});
  bad({privateNetworkAdmitted:false});
  bad({envKey:'shh-secret'});
  bad({apiKey:'bad'});
  bad({modelId:'../escape'});
  bad({baseUrl:'http://user:password@localhost:11434/v1'});
  const pub={schema:'qwen-role-routes/v1',workcellClass:'public',routes:[{
    role:'planner',kind:'cloud',dataClass:'public',modelId:'public-model',
    envKey:'PUBLIC_PLAN_KEY',baseUrl:'https://example.invalid/v1'}]};
  assert.equal(compileRoutes(pub).agents.allowedGrades[0],'planner');
  assert.throws(()=>compileRoutes({...pub,routes:[{...pub.routes[0],
    baseUrl:'http://example.invalid/v1'}]}));
  console.log('PASS public/private model-grade, credential and route-denial tests');
}

if(process.argv[1] && fileURLToPath(import.meta.url)===process.argv[1]){
  const arg=process.argv[2];
  if(arg==='--self-test')selfTest();
  else if(arg==='--manifest'&&process.argv[3]){
    const data=JSON.parse(readFileSync(process.argv[3],'utf8'));
    process.stdout.write(JSON.stringify(compileRoutes(data),null,2)+'\n');
  }else{
    console.error('usage: node compile-routes.mjs --self-test | --manifest routes.json');
    process.exitCode=2;
  }
}

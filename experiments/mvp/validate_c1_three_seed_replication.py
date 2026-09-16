#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema

REPO_ROOT=Path(__file__).resolve().parents[2]
SCHEMA=REPO_ROOT/'schemas'/'observation-bundle.schema.json'
TRACR_REVISION='9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd'
ORACLE='sha256:737c3f9f42b6f5f0d6dfce68765b872e2b7d574b6ab9d7a60fae459e8789d07f'
SEEDS={0,1,2}; STEPS=['0','10','50','200','1000']

def finite(v): return isinstance(v,(int,float)) and math.isfinite(float(v))
def sha(value): return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('bundle',type=Path); a=ap.parse_args()
    b=json.loads(a.bundle.read_text()); jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b['probe_id']=='c1-learned-reverse-three-seed-replication-v1'
    assert b['instrument']=='longitudinal-mechanistic-seed-replication-suite'
    assert b['access_tier']=='A4' and b['evidence_level']=='CAUSAL'
    assert b['model_identity']['revision']==TRACR_REVISION
    assert b['artifact_provenance']['tracked'] is False
    o=b['observations']; d=b['derived_metrics']
    assert o['oracle']['parameter_sha256']==ORACLE and o['oracle']['parameter_count']==18755
    p=o['replication_protocol']; assert p['seeds']==[0,1,2] and p['methodological_expansion'] is False
    assert p['train_examples']==60 and p['test_examples']==21 and p['steps']==1000 and p['checkpoint_steps']==[0,10,50,200,1000]
    rows=o['seeds']; assert len(rows)==3 and {r['seed'] for r in rows}==SEEDS
    for r in rows:
        assert r['deterministic_replay_exact'] is True
        assert r['deterministic_replay_parameter_sha256']==r['final_parameter_sha256']
        assert r['final_parameter_sha256'].startswith('sha256:') and len(r['final_parameter_sha256'])==71
        assert r['checkpoint_steps']==[0,10,50,200,1000]
        for field in ('test_sequence_accuracy','best_opposite_route_probability','best_cka_to_oracle','best_rsa_to_oracle'):
            assert set(r[field])==set(STEPS)
            assert all(finite(v) for v in r[field].values())
        assert all(0<=v<=1 for v in r['test_sequence_accuracy'].values())
        assert all(0<=v<=1.000001 for v in r['best_opposite_route_probability'].values())
        assert all(0<=v<=1.000001 for v in r['best_cka_to_oracle'].values())
        assert all(-1.000001<=v<=1.000001 for v in r['best_rsa_to_oracle'].values())
        assert finite(r['route_probability_vs_test_accuracy_pearson']) and -1.000001<=r['route_probability_vs_test_accuracy_pearson']<=1.000001
        for key in ('final_train_sequence_accuracy','final_test_sequence_accuracy','final_all_sequence_accuracy'):
            assert finite(r[key]) and 0<=r[key]<=1
        assert len(r['final_attention_routing'])==2 and len(r['final_causal_ablation'])==4
        for x in r['final_causal_ablation']:
            assert x['block'] in {'attn','mlp'} and x['layer'] in {0,1}
            assert finite(x['sequence_accuracy']) and 0<=x['sequence_accuracy']<=1
    assert d['seed_count']==3 and d['all_deterministic_replays_exact'] is True
    for fld in ('mean_test_sequence_accuracy_by_step','std_test_sequence_accuracy_by_step','mean_best_route_probability_by_step','std_best_route_probability_by_step','mean_best_cka_by_step','std_best_cka_by_step','mean_best_rsa_by_step','std_best_rsa_by_step'):
        assert set(d[fld])==set(STEPS) and all(finite(v) for v in d[fld].values())
    for fld in ('per_seed_cka_change_final_minus_initial','per_seed_rsa_change_final_minus_initial','per_seed_route_change_final_minus_initial','per_seed_route_accuracy_correlation'):
        assert set(d[fld])=={'0','1','2'} and all(finite(v) for v in d[fld].values())
    assert d['portable_method_checks'] and all(d['portable_method_checks'].values())
    assert b['provenance']['raw_output_hash']==sha({'observations':o,'derived_metrics':d})
    print(json.dumps({'valid':True,'seeds':[0,1,2],'all_final_perfect':d['all_final_test_sequence_accuracy_eq_1'],'all_cka_final_below_initial':d['all_cka_final_below_initial'],'final_route_mean':d['final_route_probability_mean'],'final_cka_mean':d['final_cka_mean'],'scientific_outcome_not_acceptance_gate':True},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())

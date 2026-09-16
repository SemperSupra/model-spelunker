#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema

ROOT=Path(__file__).resolve().parents[2]
SCHEMA=ROOT/'schemas'/'observation-bundle.schema.json'
DIGEST='sha256:515724650b6cdf6d860ade66faf970b50cc64e1d089db405963162aae908adef'
REV='a0e552de83495b5c28c14c71c374f3e33280b340'
IDS={'zero','terminal_pos_0.5','terminal_pos_1','terminal_pos_2','terminal_pos_5','terminal_pos_10','terminal_neg5','lag1_pos5','lag15_pos5','lag16_pos5','lag32_pos5'}

def finite(x):return isinstance(x,(int,float)) and math.isfinite(float(x))
def h(v):return 'sha256:'+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def cmp_ok(x):
    for k in ('cosine_distance','max_abs_delta','mean_abs_delta','relative_l2_delta'):assert finite(x[k]) and x[k]>=-1e-7

def main():
    p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('candidate',type=Path);a=p.parse_args();b=json.loads(a.bundle.read_text());c=json.loads(a.candidate.read_text());jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b['probe_id']=='chronos-bolt-embedding-localization-v1' and b['instrument']=='timeseries-public-encoder-embedding-localization-suite' and b['access_tier']=='A2' and b['evidence_level']=='RELATIONAL';assert b['model_identity']['revision']==REV
    ap=b['artifact_provenance'];assert ap['tracked'] and ap['verified'] and ap['identity_digest']==DIGEST and ap['upstream_revision']==REV;assert c['logical_id']=='forecast/chronos/bolt-tiny' and c['oci']['digest']==DIGEST and c['oci']['pullback_verified'] and c['state']=='candidate'
    o=b['observations'];prot=o['protocol'];assert prot['context_length']==128 and prot['prediction_length']==32 and prot['patch_size']==16 and prot['patch_stride']==16 and prot['public_api']=='ChronosBoltPipeline.embed' and prot['full_embedding_tensors_persisted'] is False;assert prot['data_patch_count']==8;assert prot['embedding_sequence_length'] in (8,9);assert prot['embedding_dimension']>0
    rows=o['conditions'];assert len(rows)==len(IDS) and {r['id'] for r in rows}==IDS
    for r in rows:
        assert finite(r['loc']) and finite(r['scale']) and r['scale']>0
        e=r['embedding'];assert e['shape']==[prot['embedding_sequence_length'],prot['embedding_dimension']];assert e['sha256_float32'].startswith('sha256:') and len(e['sha256_float32'])==71;cmp_ok(e['full_vs_terminal_pos5']);assert len(e['data_patch_vs_terminal_pos5'])==8;[cmp_ok(x) for x in e['data_patch_vs_terminal_pos5']];cmp_ok(e['final_data_patch_vs_terminal_pos5']);
        if prot['use_reg_token']: assert e['reg_token_vs_terminal_pos5'] is not None and (cmp_ok(e['reg_token_vs_terminal_pos5']) is None)
        else: assert e['reg_token_vs_terminal_pos5'] is None
        f=r['forecast'];assert f['sha256_float32'].startswith('sha256:') and f['finite'] is True and f['quantile_crossing_cells']>=0;assert finite(f['median_abs_mean']) and finite(f['median_first']) and finite(f['median_last']);cmp_ok(r['forecast_vs_terminal_pos5'])
        rep=r['repeat'];assert rep['embedding_hash_equal'] is True and rep['embedding_max_abs_delta']<=1e-6 and rep['loc_equal'] is True and rep['scale_equal'] is True
    ref=next(r for r in rows if r['id']=='terminal_pos_5');assert abs(ref['embedding']['full_vs_terminal_pos5']['max_abs_delta'])<=1e-6 and abs(ref['forecast_vs_terminal_pos5']['max_abs_delta'])<=1e-6
    pos=[r for r in rows if r['id'].startswith('terminal_pos_')];assert len(pos)==5
    d=b['derived_metrics'];
    for k in ('positive_amplitude_embedding_max_abs_delta','positive_amplitude_embedding_max_cosine_distance','positive_amplitude_forecast_rescaled_max_abs_delta','terminal_sign_embedding_cosine_distance','lag1_embedding_cosine_distance','lag15_embedding_cosine_distance','lag16_embedding_cosine_distance','lag32_embedding_cosine_distance','lag1_final_patch_embedding_cosine_distance','lag16_final_patch_embedding_cosine_distance'):assert finite(d[k]) and d[k]>=-1e-7
    assert len(d['positive_amplitude_loc_per_unit'])==5 and len(d['positive_amplitude_scale_per_unit'])==5 and all(finite(x) for x in d['positive_amplitude_loc_per_unit']+d['positive_amplitude_scale_per_unit']);assert d['all_embedding_repeats_exact'] is True and d['all_outputs_finite'] is True
    assert b['provenance']['raw_output_hash']==h({'observations':o,'derived_metrics':d})
    print(json.dumps({'valid':True,'embedding_shape':[len(rows),prot['embedding_sequence_length'],prot['embedding_dimension']], 'positive_amp_embedding_max_delta':d['positive_amplitude_embedding_max_abs_delta'],'lag1_embedding_cosine':d['lag1_embedding_cosine_distance'],'sign_embedding_cosine':d['terminal_sign_embedding_cosine_distance'],'scientific_outcome_not_acceptance_gate':True},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

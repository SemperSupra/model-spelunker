#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema

ROOT=Path(__file__).resolve().parents[2]
SCHEMA=ROOT/'schemas'/'observation-bundle.schema.json'
DIGEST='sha256:515724650b6cdf6d860ade66faf970b50cc64e1d089db405963162aae908adef'
REV='a0e552de83495b5c28c14c71c374f3e33280b340'
LAGS=sorted(set(list(range(16))+[0,16,32,48,64,80,96,112]))
Q=[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]

def finite(x):return isinstance(x,(int,float)) and math.isfinite(float(x))
def h(v):return 'sha256:'+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('candidate',type=Path);a=p.parse_args();b=json.loads(a.bundle.read_text());c=json.loads(a.candidate.read_text());jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b['probe_id']=='chronos-bolt-patch-offset-map-v1' and b['instrument']=='timeseries-patch-offset-terminal-position-map' and b['access_tier']=='A1' and b['evidence_level']=='REPRODUCED'
    assert b['model_identity']['revision']==REV
    ap=b['artifact_provenance'];assert ap['tracked'] and ap['verified'] and ap['identity_digest']==DIGEST and ap['upstream_revision']==REV
    assert c['logical_id']=='forecast/chronos/bolt-tiny' and c['oci']['digest']==DIGEST and c['oci']['pullback_verified'] and c['state']=='candidate'
    o=b['observations'];pcl=o['protocol'];assert pcl['context_length']==128 and pcl['prediction_length']==32 and pcl['patch_size']==16 and pcl['patch_stride']==16 and pcl['quantiles']==Q and pcl['amplitude']==5.0 and pcl['lags']==LAGS and pcl['full_forecast_tensors_persisted'] is False
    rows=o['position_rows'];assert len(rows)==len(LAGS) and [r['lag_from_end'] for r in rows]==LAGS
    final=[r for r in rows if r['is_final_patch']];term=[r for r in rows if r['is_patch_terminal']]
    assert len(final)==16 and {r['offset_within_patch'] for r in final}==set(range(16));assert len(term)==8 and {r['patch_index'] for r in term}==set(range(8))
    for r in rows:
        assert r['absolute_index']==127-r['lag_from_end'];assert r['patch_index']==r['absolute_index']//16 and r['offset_within_patch']==r['absolute_index']%16
        assert r['is_final_patch']==(r['patch_index']==7);assert r['is_patch_terminal']==(r['offset_within_patch']==15)
        f=r['forecast'];assert f['sha256_float32'].startswith('sha256:') and f['finite'] is True;assert f['quantile_crossing_cells']>=0 and 0<=f['quantile_crossing_fraction']<=1
        for k in ('median_first','median_last','median_mean','median_min','median_max','median_abs_mean','median_delta_last_minus_first','q10_q90_width_mean','q10_q90_width_max'):assert finite(f[k])
        for k in ('median_mean_abs_delta_from_terminal_reference','median_max_abs_delta_from_terminal_reference','full_forecast_cosine_distance_from_terminal_reference'):assert finite(r[k]) and r[k]>=-1e-6
        q=r['repeat'];assert q['hash_equal'] is True and finite(q['max_abs_delta']) and q['max_abs_delta']<=1e-6 and finite(q['mean_abs_delta']) and q['mean_abs_delta']<=1e-6
    ref=next(r for r in rows if r['lag_from_end']==0);assert ref['is_patch_terminal'] and ref['offset_within_patch']==15 and abs(ref['median_mean_abs_delta_from_terminal_reference'])<=1e-6
    d=b['derived_metrics'];assert d['position_count']==23 and d['final_patch_offset_count']==16 and d['patch_terminal_count']==8 and d['same_batch_repeat_exact'] is True and d['same_batch_repeat_max_abs_delta']<=1e-6 and d['all_outputs_finite'] is True
    assert len(d['final_patch_offset_curve'])==16 and {x['offset'] for x in d['final_patch_offset_curve']}==set(range(16));assert len(d['patch_terminal_curve'])==8 and {x['patch_index'] for x in d['patch_terminal_curve']}==set(range(8))
    assert finite(d['terminal_reference_median_abs_mean']) and d['terminal_reference_median_abs_mean']>=0;assert finite(d['max_nonterminal_final_patch_median_abs_mean']) and d['max_nonterminal_final_patch_median_abs_mean']>=0;assert finite(d['terminal_to_max_nonterminal_magnitude_ratio']) and d['terminal_to_max_nonterminal_magnitude_ratio']>=0
    assert all(x in LAGS for x in d['quantile_crossing_positions'])
    assert b['provenance']['raw_output_hash']==h({'observations':o,'derived_metrics':d})
    print(json.dumps({'valid':True,'positions':23,'final_patch_offsets':16,'patch_terminals':8,'terminal_ratio':d['terminal_to_max_nonterminal_magnitude_ratio'],'crossing_positions':d['quantile_crossing_positions'],'scientific_outcome_not_acceptance_gate':True},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

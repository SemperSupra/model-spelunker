#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
import jsonschema

ROOT=Path(__file__).resolve().parents[2]
SCHEMA=ROOT/'schemas'/'observation-bundle.schema.json'
DIGEST='sha256:f2d664ae986b0b0598037a9f0b929fd0b0b748871474a06c84658c1f2a1a4b42'
REV='d90ca5fe260221311c53c58e660288d3deb8d356'
DATAREV='2e83e61823b4c47dcbcb1980bb88601274127609'
CONFIGS={'german':'de','french':'fr','spanish':'es'}
CONDS={'baseline','snr_20db','snr_10db'}

def finite(x):return isinstance(x,(int,float)) and math.isfinite(float(x))
def h(v):return 'sha256:'+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def check_stats(s):
    assert set(s)=={'mean','std','min','max','variance'}
    assert all(finite(v) and v>=-1e-8 for v in s.values())
    assert s['min']<=s['mean']<=s['max'] and s['std']>=0 and s['variance']>=0
def check_partition(p):
    assert len(p['speaker_means'])==3 and len(p['within_speaker_variances'])==3
    assert finite(p['between_speaker_mean_variance']) and p['between_speaker_mean_variance']>=0
    assert finite(p['mean_within_speaker_utterance_variance']) and p['mean_within_speaker_utterance_variance']>=0
    assert finite(p['descriptive_between_fraction']) and 0<=p['descriptive_between_fraction']<=1

def main():
    a=argparse.ArgumentParser();a.add_argument('bundle',type=Path);x=a.parse_args();b=json.loads(x.bundle.read_text());jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b['probe_id']=='audio-repeated-speaker-variance-faster-whisper-tiny-v1';assert b['instrument']=='audio-repeated-speaker-utterance-variance-suite';assert b['access_tier']=='A2';assert b['evidence_level']=='REPRODUCED';assert b['model_identity']['revision']==REV
    ap=b['artifact_provenance'];assert ap['tracked'] and ap['verified'] and ap['identity_digest']==DIGEST and ap['upstream_revision']==REV
    o=b['observations'];dset=o['dataset'];assert dset['repository']=='facebook/multilingual_librispeech' and dset['revision']==DATAREV and dset['license_spdx']=='CC-BY-4.0';assert dset['speaker_freeze_provenance']['source_run_id']=='35054188355'
    assert set(o['protocol']['conditions'])==CONDS and o['protocol']['utterances_per_speaker']==3 and o['protocol']['speakers_per_language']==3 and o['protocol']['full_encoder_tensor_persisted'] is False
    assert len(o['languages'])==3 and {z['config'] for z in o['languages']}==set(CONFIGS); utterances=[]
    for lang in o['languages']:
        assert lang['expected_language']==CONFIGS[lang['config']];assert lang['source_parquet_sha256'].startswith('sha256:');assert len(lang['speakers'])==3 and len({s['speaker_id'] for s in lang['speakers']})==3
        for sp in lang['speakers']:
            assert len(sp['utterances'])==3
            for u in sp['utterances']:
                utterances.append(u);assert u['sample_id'] and u['source_audio_sha256'].startswith('sha256:') and u['ground_truth_transcript'];rows=u['conditions'];assert len(rows)==3 and {r['condition'] for r in rows}==CONDS
                shapes=set()
                for r in rows:
                    rep=r['representation'];sh=tuple(rep['encoder_shape']);assert len(sh)==3 and sh[0]==1;shapes.add(sh);assert rep['encoder_hash'].startswith('sha256:');assert finite(rep['pooled_cosine_distance_from_baseline']) and rep['pooled_cosine_distance_from_baseline']>=-1e-6;assert finite(rep['frame_cosine_distance_from_baseline']) and rep['frame_cosine_distance_from_baseline']>=-1e-6
                    dec=r['decoder'];assert isinstance(dec['transcript'],str) and dec['detected_language'];assert finite(dec['language_probability']);assert isinstance(dec['language_matches_expected'],bool)
                    for k in ('ground_truth_char_error','relative_to_baseline_char_error'):
                        q=dec[k];assert q['reference_chars']>0 and q['char_edit_distance']>=0 and finite(q['normalized_char_edit_distance']) and q['normalized_char_edit_distance']>=0
                assert len(shapes)==1;base=next(r for r in rows if r['condition']=='baseline');assert base['decoder']['relative_to_baseline_char_error']['char_edit_distance']==0;assert abs(base['representation']['frame_cosine_distance_from_baseline'])<=1e-6;assert abs(base['representation']['pooled_cosine_distance_from_baseline'])<=1e-6
                rep=u['baseline_repeat'];assert rep['encoder_hash_equal'] and rep['transcript_equal'] and rep['language_equal']
    d=b['derived_metrics'];assert d['language_count']==3 and d['speaker_count']==9 and d['utterance_count']==27;assert d['all_baseline_encoder_repeats_exact'] and d['all_baseline_transcript_repeats_exact'] and d['all_baseline_language_repeats_exact'];assert set(d['per_language'])==set(CONFIGS)
    for lang,s in d['per_language'].items():
        assert len(s['speaker_ids'])==3 and len(set(s['speaker_ids']))==3 and set(s['conditions'])==CONDS
        for c,q in s['conditions'].items():
            for k in ('ground_truth_cer','relative_to_baseline_cer','frame_cosine_distance'):check_stats(q[k])
            for k in ('ground_truth_variance_partition','relative_cer_variance_partition','frame_variance_partition'):check_partition(q[k])
    assert b['provenance']['raw_output_hash']==h({'observations':o,'derived_metrics':d});assert finite(b['cost']['experiment_seconds']) and finite(b['cost']['peak_rss_mib'])
    print(json.dumps({'valid':True,'languages':3,'speakers':9,'utterances':27,'scientific_outcome_not_acceptance_gate':True},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())

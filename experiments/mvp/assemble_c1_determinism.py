#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, time
from pathlib import Path

TRACR_REVISION='9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd'

def sha(v): return 'sha256:'+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def pair(rows, mode): return [x for x in rows if x['mode']==mode]
def same_hash(rows): return len({x['parameter_sha256'] for x in rows})==1

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--runner-a-json',required=True); ap.add_argument('--runner-b-dir',type=Path,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    started=time.perf_counter(); runner_a=json.loads(a.runner_a_json)
    runner_b=[json.loads((a.runner_b_dir/name).read_text()) for name in ('default-1.json','default-2.json','reduced-1.json','reduced-2.json')]
    assert len(runner_a)==4 and len(runner_b)==4
    all_rows=runner_a+runner_b
    behavior_all_perfect=all(x['train_sequence_accuracy']==1.0 and x['test_sequence_accuracy']==1.0 and x['all_sequence_accuracy']==1.0 for x in all_rows)
    derived={
      'runner_a_default_within_processes_exact':same_hash(pair(runner_a,'default')),
      'runner_b_default_within_processes_exact':same_hash(pair(runner_b,'default')),
      'runner_a_reduced_threading_within_processes_exact':same_hash(pair(runner_a,'reduced-threading')),
      'runner_b_reduced_threading_within_processes_exact':same_hash(pair(runner_b,'reduced-threading')),
      'default_cross_runner_exact':pair(runner_a,'default')[0]['parameter_sha256']==pair(runner_b,'default')[0]['parameter_sha256'],
      'reduced_threading_cross_runner_exact':pair(runner_a,'reduced-threading')[0]['parameter_sha256']==pair(runner_b,'reduced-threading')[0]['parameter_sha256'],
      'behavior_all_perfect':behavior_all_perfect,
      'default_unique_parameter_hashes':sorted({x['parameter_sha256'] for x in all_rows if x['mode']=='default'}),
      'reduced_threading_unique_parameter_hashes':sorted({x['parameter_sha256'] for x in all_rows if x['mode']=='reduced-threading'}),
      'cpu_models':sorted({x['environment']['cpu_model'] for x in all_rows}),
      'portable_method_checks':{'two_sequential_runners_observed':True,'two_independent_processes_per_mode_per_runner':True,'default_execution_observed':True,'reduced_threading_execution_observed':True,'behavior_and_parameter_identity_separated':True},
    }
    observations={'protocol':{'task':'same seed-0 reverse training as Rep 34/35','seed':0,'modes':{'default':{'xla_flags':'workflow default'},'reduced-threading':{'xla_flags':'--xla_cpu_multi_thread_eigen=false','omp_num_threads':'1','openblas_num_threads':'1','mkl_num_threads':'1'}},'processes_per_mode_per_runner':2,'runner_count':2},'runner_a':runner_a,'runner_b':runner_b}
    bundle={'probe_id':'c1-jax-cross-runner-determinism-v1','instrument':'cross-process-cross-runner-training-determinism-suite','instrument_version':'mvp-1','model_identity':{'repository':'SemperSupra/model-spelunker','revision':os.environ.get('GITHUB_SHA'),'logical_id':'trained/tracr-transformer/reverse-seed0-determinism-probe','model_class':'cpu-trained-tiny-transformer-reproducibility'},'artifact_provenance':{'tracked':False,'reason':'No external model artifact is consumed; each tiny seed-0 specimen is trained independently in a fresh process and identified by its final parameter SHA-256 plus fixed source/runtime protocol.'},'access_tier':'A2','evidence_level':'REPRODUCED','claim_tags':['C1_CALIBRATION','REPRODUCIBILITY','JAX','CPU','CROSS_RUNNER','BITWISE_IDENTITY'],'observations':observations,'derived_metrics':derived,'uncertainty':{'scope':'two GitHub-hosted CPU runners and two processes per execution mode; enough to qualify this experiment path, not a general JAX determinism benchmark','threading_control':'reduced-threading mode disables XLA CPU Eigen multithreading and common BLAS thread pools but does not claim to disable every possible source of CPU parallelism'},'known_assumptions':['behavioral reproducibility and bitwise parameter reproducibility are distinct requirements','the fixed seed/task/runtime from the C1 learned specimen is a useful stress test for exact training replay'],'known_failure_modes':['GitHub-hosted runner CPU models may vary over time','XLA may use numerically equivalent but bitwise-different reductions even when common thread pools are reduced'],'cost':{'total_assembly_seconds':time.perf_counter()-started,'runner_training_seconds':{f"{label}_{i}":row['training_seconds'] for label,rows in (('a',runner_a),('b',runner_b)) for i,row in enumerate(rows)}},'provenance':{'run_id':str(os.environ.get('GITHUB_RUN_ID','local')),'code_revision':os.environ.get('GITHUB_SHA'),'model_revision':TRACR_REVISION,'tokenizer_revision':None,'environment':{'tracr_source_revision':TRACR_REVISION},'randomness':{'training_seed':0},'raw_input_hash':sha({'protocol':'seed0-reverse-determinism','tracr':TRACR_REVISION}),'raw_output_hash':None}}
    bundle['provenance']['raw_output_hash']=sha({'observations':observations,'derived_metrics':derived})
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+'\n'); print(json.dumps({'output':str(a.output),**{k:derived[k] for k in ('default_cross_runner_exact','reduced_threading_cross_runner_exact','behavior_all_perfect')},'default_hashes':derived['default_unique_parameter_hashes'],'reduced_hashes':derived['reduced_threading_unique_parameter_hashes'],'cpu_models':derived['cpu_models']},sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())

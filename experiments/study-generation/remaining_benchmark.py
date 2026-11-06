"""Equal fixture workloads for candidate top-up and targeted TLS preparation."""
import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

parser=argparse.ArgumentParser()
parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[2])
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--narrow',action='store_true')
parser.add_argument('--samples',type=int,default=30)
args=parser.parse_args()
skill=args.source_root.resolve()/'skills/university-agent'
sys.path[:0]=[str(skill/'tests'),str(skill/'scripts'),str(skill)]
from test_study_pipeline import FilePipelineTests
from test_tls_optimization import run_sync,fixture_pages,snapshot
from features import sync_policy
import sync_tls

def topup():
    f=FilePipelineTests('test_chunk_boundaries_preserved_without_suffix_copy')
    f.setUp()
    try:
        request={'action':'request','selection':{'courseId':'course-1','resourceIds':['r0']},
                 'settings':{'count':10,'types':['mcq']*10}}
        prepared=f.session('seed').call(request)
        questions=[]
        for i in range(10):
            q=f.candidate(prepared)
            q.update(id=f'q{i}',question=q['question']+f' 기존 {i}')
            questions.append(q)
        f.extract_questions(f.session('seed'),prepared,questions)
        request['settings']={'count':30,'types':['mcq']*30}
        session=f.session('thirty')
        start=time.perf_counter()
        prepared=session.call(request)
        local=(time.perf_counter()-start)*1000
        requested=0
        reused_analysis=False
        while prepared.get('needsExtraction'):
            host=prepared['hostOnly']
            reused_analysis |= 'reusedAnalysis' in host
            count=host['settings']['count']
            requested += count
            questions=[]
            for i in range(count):
                q=f.candidate(prepared)
                q.update(id=f'q{i}',question=q['question']+f' 추가 {requested}-{i}')
                questions.append(q)
            prepared=f.extract_questions(session,prepared,questions)
        ids=prepared['hostOnly']['selectionPlan']['candidateIds']
        assert len(ids)==30
        assembled=session.call({'action':'assemble','candidateIds':ids})
        assert assembled['total']==30
        return {'request_local_ms':local,'new_candidates_requested':requested,
                'reused_facts':reused_analysis,'final_questions':30,'bank_candidates':prepared['totalCandidates']}
    finally:
        f.tearDown()
        f.doCleanups()

rows=[topup() for _ in range(args.samples)]
instant=datetime(2026,11,5,tzinfo=timezone.utc)
sync_rows=[]
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    pages=fixture_pages(8)
    seed=root/'seed.db'
    with patch.object(sync_policy,'now',return_value=instant):
        run_sync(sync_tls,pages,seed,'--full','--metadata-only')
    for i in range(args.samples):
        db=root/f'run{i}.db'
        shutil.copy2(seed,db)
        before=snapshot(db)
        flags=('--resource-only',) if args.narrow else ('--ensure',)
        with patch.object(sync_policy,'now',return_value=instant+timedelta(days=2)):
            start=time.perf_counter()
            result=run_sync(sync_tls,pages,db,*flags,'--resource-id','tls-resource-108')
            result['local_ms']=(time.perf_counter()-start)*1000
        after=snapshot(db)
        assert after['assignments']==before['assignments'] and after['lectures']==before['lectures']
        assert next(r for r in after['resources'] if r['id']=='tls-resource-108')['downloadStatus']=='DOWNLOADED'
        assert sum(r['downloadStatus']=='DOWNLOADED' for r in after['resources'])==1
        sync_rows.append(result)
result={'ai_latency_measured':False,'samples':args.samples,'narrow_scope':args.narrow,
    'topup':{'raw':rows,'median':{k:statistics.median(r[k] for r in rows) for k in rows[0]}},
    'resource_preparation':{'raw':sync_rows,'median_requests':statistics.median(r['requests'] for r in sync_rows),
        'median_local_ms':statistics.median(r['local_ms'] for r in sync_rows)}}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'topup':result['topup']['median'],'resource_requests':result['resource_preparation']['median_requests'],
                  'resource_local_ms':result['resource_preparation']['median_local_ms']},indent=2))

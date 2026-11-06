"""Measure actual CLI handoff projection; no AI or school access."""
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'skills/university-agent'),str(ROOT/'skills/university-agent/tests')]
from test_study_pipeline import FilePipelineTests
from features.study_pipeline import host_response
from features.secret_boundary import redact_output

def encode(value):
    return json.dumps(redact_output(value),ensure_ascii=False,separators=(',',':')).encode()

def measure(chars):
    fixture=FilePipelineTests('test_chunk_boundaries_preserved_without_suffix_copy')
    fixture.setUp()
    try:
        (fixture.files/'0.txt').write_text('가'*chars,encoding='utf-8')
        before=fixture.session('handoff-measure').call({'action':'request',
            'selection':{'courseId':'course-1','resourceIds':['r0']},
            'settings':{'count':30,'types':['mcq']*30}})
        after=host_response(before)
        assert before['hostOnly']['requests']==after['hostOnly']['requests']
        assert 'SOURCE' not in after['hostOnly'] and 'SOURCE' in before['hostOnly']
        assert sum(len(s['text']) for h in after['hostOnly']['requests'] for s in h['SOURCE'])==chars
        old_times,new_times=[],[]
        for i in range(30):
            pairs=[(before,old_times),(after,new_times)]
            for value,samples in pairs if i%2==0 else reversed(pairs):
                start=time.perf_counter()
                encode(value)
                samples.append((time.perf_counter()-start)*1000)
        a,b=len(encode(before)),len(encode(after))
        return {'source_chars':chars,'requests':len(after['hostOnly']['requests']),
            'legacy_bytes':a,'v2_bytes':b,'byte_reduction_percent':(1-b/a)*100,
            'redaction_serialization_ms':{'legacy_median':statistics.median(old_times),
                'v2_median':statistics.median(new_times),'legacy_samples':old_times,'v2_samples':new_times},
            'request_data_equal':True,'model_latency_measured':False}
    finally:
        fixture.tearDown()
        fixture.doCleanups()

if __name__=='__main__':
    result={'scope':'CLI output projection; direct StudySession API unchanged.',
            'scenarios':[measure(7703),measure(20000)]}
    out=Path(__file__).parent/'results/handoff-step12.json'
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{k:v for k,v in row.items() if k!='redaction_serialization_ms'} for row in result['scenarios']],indent=2))

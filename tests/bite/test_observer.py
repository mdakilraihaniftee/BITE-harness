"""Offline replay and geometry tests; no model workers or provider credentials."""
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path

from jsonschema import validate
from PIL import Image
import pytest
import requests
import numpy as np

from openvlharness.agent.agent import MainAgent
from openvlharness.bite import EvidenceObserver
from openvlharness.bite.geometry import crop_rectangle, compose, normalized_to_pixels, transform_box, translation
from openvlharness.bite.schemas import OBSERVATION_SCHEMA
from openvlharness.bite.serialization import Serializer
from openvlharness.capabilities.grounding import Capability as Grounding
from openvlharness.capabilities.zoom import Capability as Zoom
from openvlharness.contracts import VirtualCall
from openvlharness.memory.store import MemoryStore
from openvlharness.services.models import ModelAdapter
from openvlharness.services.tools.zoom_in_image_by_bbox.tool import Zoom_In_Tool

REFERENCE = json.loads((Path(__file__).parent / 'fixtures/reference_trace.json').read_text())


def image_url(size=(500, 333), color='white'):
    b = io.BytesIO()
    Image.new('RGB', size, color).save(b, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()


IMAGE = image_url()
QUESTION = [{'type': 'image', 'value': IMAGE}, {'type': 'text', 'value': 'Locate objects.'}]


def response(alias, text='', calls=()):
    if alias == 'gpt-6-luna':
        return {'output': ([{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}] if text else []) +
                [{'type': 'function_call', 'call_id': i, 'name': n, 'arguments': a} for i, n, a in calls]}
    msg = {'role': 'assistant', 'content': text,
           'tool_calls': [{'id': i, 'type': 'function', 'function': {'name': n, 'arguments': a}} for i, n, a in calls]}
    if alias == 'kimi-k3':
        msg['reasoning_content'] = 'Fixed provider reasoning.'
    return {'choices': [{'message': msg}]}


def raw_ground(query='person', *, empty=False):
    source = REFERENCE['turns'][0 if query == 'person' else 1]['grounding']
    return {'model': 'sam3-image', 'prompt': query, 'orig_img_h': 333, 'orig_img_w': 500,
            'pred_boxes': [] if empty else source['boxes'], 'pred_scores': [] if empty else source['scores'],
            'pred_masks': [] if empty else source['masks'], 'num_masks': 0 if empty else len(source['boxes']),
            'rendered_image_b64': image_url(color='red' if query == 'person' else 'blue').split(',')[1]}


class Client:
    def __init__(self, outcome='ok'):
        self.calls = []
        self.outcome = outcome

    def execute(self, name, args, *, tool_call_id):
        self.calls.append((name, copy.deepcopy(args), tool_call_id))
        if self.outcome == 'timeout':
            raise requests.Timeout('backend timeout')
        if self.outcome == 'failure':
            return {'ok': False, 'result': None, 'error': {'code': 'tool_execution_error', 'message': 'backend failure'}}
        if self.outcome == 'invalid_result':
            return {'ok': True, 'result': {'pred_boxes': [[1,2,3,4]], 'pred_scores': [.8], 'orig_img_w': 0, 'orig_img_h': 0}}
        if name == 'Zoom_In_Tool':
            result = Zoom_In_Tool().execute(**args)
        else:
            result = raw_ground(args['query'], empty=self.outcome == 'empty')
        return {'ok': True, 'result': copy.deepcopy(result), 'error': None, 'meta': {}}


def make_agent(alias='qwen3-vl-8b-instruct', responses=None, client=None, requester=None, **kwargs):
    client = client or Client()
    pending = copy.deepcopy(responses or [response(alias, '<answer>[]</answer>')])
    payloads = []

    def ask(payload):
        payloads.append(copy.deepcopy(payload))
        if requester:
            return requester(payload)
        item = pending.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    adapter = ModelAdapter({'alias': alias, 'base': 'http://fixture.invalid/v1', 'max_tokens': 4096}, requester=ask)
    caps = [Grounding(backend='sam3_segment', client_config={'base_url': 'http://fixture.invalid'}, client=client),
            Zoom(backend='zoom_in_image_by_bbox', client_config={'base_url': 'http://fixture.invalid'}, client=client)]
    return MainAgent(adapter, {c.name: c for c in caps}, MemoryStore, 'system', 'Question: {user_query}', **kwargs), payloads, client


def fixed_trace(alias):
    return [response(alias, turn['assistant']['content'], [(c['id'], c['name'], c['raw_arguments']) for c in turn['assistant']['tool_calls']])
            for turn in REFERENCE['turns']]


def events(data, kind):
    return [e for e in data['events'] if e['type'] == kind]


@pytest.mark.parametrize('alias', ['qwen3-vl-8b-instruct', 'gpt-6-luna', 'kimi-k3'])
def test_native_replay_equivalence_and_reference_scores(monkeypatch, alias):
    monkeypatch.delenv('BITE_OBSERVER_ENABLED', raising=False)
    off_agent, off_payloads, off_client = make_agent(alias, fixed_trace(alias))
    off = off_agent.generate(QUESTION, task_id='reference')
    assert 'bite_observer' not in off['extra_records']
    monkeypatch.setenv('BITE_OBSERVER_ENABLED', 'true')
    on_agent, on_payloads, on_client = make_agent(alias, fixed_trace(alias))
    on = on_agent.generate(QUESTION, task_id='reference')
    data = on['extra_records'].pop('bite_observer')
    assert on == off
    assert on_payloads == off_payloads
    assert on_client.calls == off_client.calls
    assert data['capture_complete']
    assert data['budget']['logical_tool_calls'] == 2
    assert data['budget']['model_iterations'] == 3
    assert [e['grounding']['detections'][0]['score'] for e in events(data, 'tool_observation')] == [.984375, .9765625]
    horses = events(data, 'tool_observation')[1]['grounding']['detections']
    assert horses[0]['bbox_local_xyxy'][0] < 0
    assert horses[1]['bbox_root_xyxy'][2] > 500
    assert all(d['mask']['sha256'] for e in events(data, 'tool_observation') for d in e['grounding']['detections'])
    assert {e['target'] for e in data['provenance_edges'] if e['relation'] == 'uses_backend'} == {'backend:sam3_segment'}
    assert sum(e['relation'] == 'shares_root_image' for e in data['provenance_edges']) == 2
    assert not any(e['relation'] == 'derived_from_observation' for e in data['provenance_edges'])
    validate(data, OBSERVATION_SCHEMA)


@pytest.mark.parametrize('outcome,expected_calls,rejected,category', [
    ('ok', 1, 0, None), ('empty', 1, 0, None), ('failure', 1, 0, 'tool_execution_error'),
    ('invalid_result', 1, 0, 'invalid_tool_result'),
    ('timeout', 1, 0, 'transport_timeout'), ('invalid', 0, 1, None), ('unknown', 0, 1, None),
    ('malformed', 0, 1, None), ('multiple', 0, 2, None), ('missing_image', 0, 1, None),
    ('no_tool', 0, 0, None),
])
def test_accounting_and_failures(monkeypatch, outcome, expected_calls, rejected, category):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED', 'true')
    monkeypatch.setenv('BITE_OBSERVER_REFERENCE_BUDGET', '0')
    name = 'Unknown_Tool' if outcome == 'unknown' else 'Visual_Grounding_Tool'
    args = '{' if outcome == 'malformed' else json.dumps({'query': 7 if outcome == 'invalid' else 'person',
                                                        'image_id': 'missing' if outcome == 'missing_image' else 'input_image_1'})
    calls = [('native_1', name, args)]
    if outcome == 'multiple':
        calls += [('native_2', name, args)]
    rs = [response('qwen3-vl-8b-instruct', calls=calls), response('qwen3-vl-8b-instruct', '<answer>[]</answer>')]
    if outcome == 'no_tool':
        rs = rs[1:]
    agent, _, client = make_agent(responses=rs, client=Client(outcome))
    # Two images disable the existing sole-image fallback for the unresolved-image case.
    question = QUESTION + ([{'type': 'image', 'value': image_url(color='green')}] if outcome == 'missing_image' else [])
    result = agent.generate(question)
    data = result['extra_records']['bite_observer']
    assert data['capture_complete']
    assert data['budget']['logical_tool_calls'] == expected_calls == len(client.calls)
    assert data['budget']['rejected_proposals'] == rejected
    assert data['budget']['remaining_budget'] == -expected_calls  # recording never blocks
    assert data['budget']['physical_backend_attempts'] is None
    assert len(events(data, 'tool_dispatch')) == len(events(data, 'tool_observation')) == expected_calls
    if expected_calls:
        observation = events(data, 'tool_observation')[0]
        assert observation['error_category'] == category
        assert observation['latency_ms'] >= 0
        if outcome == 'empty':
            assert observation['success'] and observation['grounding']['empty_detection']
        assert data['budget']['failed_tool_calls'] == int(outcome in ['failure', 'timeout', 'invalid_result'])


def test_per_question_concurrent_and_sequential_state(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED', 'true')
    agent, _, _ = make_agent(requester=lambda p: response('qwen3-vl-8b-instruct', '<answer>done</answer>'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: agent.generate(QUESTION, task_id=i), range(8)))
    results += [agent.generate(QUESTION, task_id='sequential')]
    states = [r['extra_records']['bite_observer'] for r in results]
    assert len({s['question_id'] for s in states}) == 9
    assert all(s['budget']['model_iterations'] == 1 and s['budget']['logical_tool_calls'] == 0 for s in states)
    assert all(s['events'][0]['event_id'] == 'event_0001' for s in states)
    assert not hasattr(agent, 'observer')


@pytest.mark.parametrize('coords,padding,size', [
    ([0,0,1000,1000],50,(600,320)), ([50,100,650,950],50,(600,320)),
    ([0,0,20,20],50,(600,320)), ([300,400,100,200],50,(600,320)),
    ([100.5,101.5,500.5,501.5],50,(999,777)), ([900,900,1000,1000],77.7,(23,37)),
])
def test_crop_matches_original_pixels(coords, padding, size):
    rectangle = crop_rectangle(coords, padding, *size)
    # A spatially varying image detects wrong offsets, not just wrong crop sizes.
    yy, xx = np.indices((size[1], size[0]))
    canvas = Image.fromarray(np.stack([xx % 251, yy % 251, (xx + 2*yy) % 251], axis=-1).astype('uint8'))
    encoded = io.BytesIO(); canvas.save(encoded, format='PNG')
    data = Zoom_In_Tool().execute(image_base64=base64.b64encode(encoded.getvalue()).decode(), coords=coords, padding=padding)
    with Image.open(io.BytesIO(base64.b64decode(data['cropped_image_base64']))) as crop:
        assert crop.size == (rectangle[2]-rectangle[0], rectangle[3]-rectangle[1])
        expected = canvas.crop(rectangle)
        assert crop.tobytes() == expected.tobytes()
    if coords == [50,100,650,950]:
        assert rectangle == (0,16,420,320)


def invoke_observed(observer, cap, memory, args, call_id):
    observer.proposal({'id':call_id,'name':cap.name,'args':args,'raw_arguments':json.dumps(args)},cap)
    call = VirtualCall(call_id,cap.name,args)
    memory._bite_observer = observer
    result = cap.invoke(call,memory)
    observer.result(call,result,memory)
    assert result.ok
    return result


def test_nested_crops_alias_and_direct_dependency():
    memory = MemoryStore(); memory.start([{'type':'image','value':image_url((600,320))}])
    observer = EvidenceObserver(); observer.initialize(memory)
    cap = Zoom(backend='zoom_in_image_by_bbox',client_config={'base_url':'http://fixture.invalid'},client=Client())
    first = invoke_observed(observer,cap,memory,{'coords':[50,100,650,950],'padding':50,'image_id':'image_1'},'one')
    child = first.data['image']
    second = invoke_observed(observer,cap,memory,{'coords':[100,100,900,900],'padding':50,'image_id':child},'two')
    data = observer.export(); a,b = events(data,'tool_observation')
    assert a['crop']['crop_rectangle_parent_xyxy'] == [0,16,420,320]
    assert b['crop']['root_image_id'] == 'input_image_1'
    transform = b['crop']['child_to_root_transform']
    assert transform == compose(a['crop']['child_to_root_transform'], b['crop']['child_to_parent_transform'])
    assert transform_box([-1.2,0,10,20],transform)[0] == transform[0][2]-1.2
    assert normalized_to_pixels([0,0,1000,1000],420,304) == [0,0,420,304]
    assert any(e['relation']=='derived_from_observation' and e['target']==a['observation_id'] for e in data['provenance_edges'])
    assert events(data,'tool_dispatch')[0]['image_inputs'][0]['resolved_image_id']=='input_image_1'
    # Grounding extraction must translate without rounding or clamping.
    out={'observation_id':'test'}
    frame,reason=observer.graph.frame(second.data['image'])
    observer._grounding(out,{'boxes':[[-.5,1,20,30]],'scores':[.82],'labels':['person'],'masks':None},
                        {'frame':frame,'frame_reason':reason},'record',0)
    assert out['grounding']['detections'][0]['bbox_root_xyxy']==transform_box([-.5,1,20,30],transform)
    class CropGroundClient:
        def execute(self,name,args,*,tool_call_id):
            with Image.open(io.BytesIO(base64.b64decode(args['image_base64'].split(',')[-1]))) as image:
                w,h=image.size
            return {'ok':True,'result':{'model':'sam3-image','prompt':args['query'],
                    'orig_img_w':w,'orig_img_h':h,'pred_boxes':[[-.25,1,w+.5,h+.5]],
                    'pred_scores':[.82],'pred_masks':None,'num_masks':None}}
    grounding=Grounding(backend='sam3_segment',client_config={'base_url':'http://fixture.invalid'},client=CropGroundClient())
    third=invoke_observed(observer,grounding,memory,{'query':'person','image_id':second.data['image']},'three')
    observation=events(observer.export(),'tool_observation')[-1]
    assert observation['grounding']['detections'][0]['bbox_root_xyxy']==transform_box(third.data['boxes'][0],transform)


def test_context_compaction_payload_equivalence(monkeypatch):
    outputs=[];payloads=[]
    for enabled in ['false','true']:
        monkeypatch.setenv('BITE_OBSERVER_ENABLED',enabled)
        agent,wire,_=make_agent()
        def compact(history,tools,choice):
            history[-1]['content']='[Truncated to save context]'
            return tools,choice
        agent.adapter._ensure_context_fits=compact
        result=agent.generate(QUESTION)
        observer=result['extra_records'].pop('bite_observer',None)
        if observer:
            assert events(observer,'context_change')[0]['reason']=='history_compacted_or_replaced'
        outputs.append(result);payloads.append(wire)
    assert outputs[0]==outputs[1] and payloads[0]==payloads[1]


def test_deduplicated_pixels_with_distinct_frames_are_ambiguous():
    memory=MemoryStore();memory.start([{'type':'image','value':image_url((100,100))}])
    obs=EvidenceObserver();obs.initialize(memory)
    cap=Zoom(backend='zoom_in_image_by_bbox',client_config={'base_url':'http://fixture.invalid'},client=Client())
    a=invoke_observed(obs,cap,memory,{'image_id':'input_image_1','coords':[100,100,300,300]},'a')
    b=invoke_observed(obs,cap,memory,{'image_id':'input_image_1','coords':[500,500,700,700]},'b')
    assert a.data['image']==b.data['image']
    frame,reason=obs.graph.frame(a.data['image'])
    assert frame is None and reason=='ambiguous_deduplicated_lineage'
    assert len(events(obs.export(),'tool_observation'))==2


@pytest.mark.parametrize('scores,masks', [(None,None),('bad','bad'),([],[]),([.8],['counts'])])
def test_optional_grounding_fields(scores,masks):
    obs=EvidenceObserver();item={'observation_id':'obs'}
    obs._grounding(item,{'boxes':[[1,2,3,4]],'scores':scores,'masks':masks,'size':[10,10]},None,'source',0)
    d=item['grounding']['detections'][0]
    assert d['bbox_local_xyxy']==[1,2,3,4] and d['bbox_root_xyxy'] is None
    assert d['score']==(.8 if scores==[.8] else None)


def test_secret_and_image_exclusion_and_nontruncating_numbers(monkeypatch):
    monkeypatch.setenv('EXAMPLE_API_KEY','very-private-secret')
    s=Serializer();out=s.clean({'api_key':'anything','raw':'{"api_key":"other-secret"}',
                               'text':'very-private-secret','image':IMAGE,'numbers':list(range(10000))})
    encoded=json.dumps(out)
    assert 'very-private-secret' not in encoded and 'other-secret' not in encoded
    assert 'data:image/' not in encoded
    assert len(out['numbers'])==10000


def test_observer_capture_failure_does_not_change_prediction(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED','true')
    monkeypatch.setattr(EvidenceObserver,'_grounding',lambda *a: (_ for _ in ()).throw(ValueError('private error')))
    agent,_,_=make_agent(responses=fixed_trace('qwen3-vl-8b-instruct'))
    result=agent.generate(QUESTION)
    assert result['prediction']==REFERENCE['prediction']
    data=result['extra_records']['bite_observer']
    assert not data['capture_complete'] and data['capture_errors']


def test_model_failure_and_extra_final_turn(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED','true')
    agent,_,_=make_agent(responses=[RuntimeError('request failed')])
    out=agent.generate(QUESTION)['extra_records']['bite_observer']
    assert events(out,'model_turn')[0]['status']=='request_failed'
    assert not events(out,'finalization')[0]['original_agent_final_response_valid']
    rs=[response('qwen3-vl-8b-instruct',calls=[('x','Visual_Grounding_Tool','{"query":"person","image_id":"input_image_1"}')]),
        response('qwen3-vl-8b-instruct','<answer>done</answer>')]
    agent,_,_=make_agent(responses=rs,max_iterations=1)
    data=agent.generate(QUESTION)['extra_records']['bite_observer']
    assert data['budget']['model_iterations']==2
    assert events(data,'model_turn')[1]['phase']=='final_text_only'


def test_logical_count_does_not_count_internal_attempts(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED','true')
    class Retrying(Client):
        attempts = 0
        def execute(self, *args, **kwargs):
            for attempt in range(3):
                self.attempts += 1
                if attempt == 2:
                    return super().execute(*args, **kwargs)
    client=Retrying()
    agent,_,_=make_agent(responses=fixed_trace('qwen3-vl-8b-instruct'),client=client)
    data=agent.generate(QUESTION)['extra_records']['bite_observer']
    assert client.attempts==6 and data['budget']['logical_tool_calls']==2
    assert data['budget']['physical_backend_attempts'] is None


def test_context_event_preserves_request_and_model_fallback(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED','true')
    rs=[RuntimeError('maximum input length'),response('qwen3-vl-8b-instruct','<answer>done</answer>')]
    agent,payloads,_=make_agent(responses=rs)
    data=agent.generate(QUESTION)['extra_records']['bite_observer']
    assert len(payloads)==2 and data['budget']['model_iterations']==1
    assert events(data,'context_change')[0]['reason']=='provider_context_error_fallback'
    assert data['budget']['logical_tool_calls']==0


def test_capability_exception_closes_dispatch_without_invented_result_ref(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED','true')
    monkeypatch.setattr(Grounding,'consume_result',lambda *a: (_ for _ in ()).throw(RuntimeError('normalization failed')))
    agent,_,_=make_agent(responses=fixed_trace('qwen3-vl-8b-instruct'))
    result=agent.generate(QUESTION)
    data=result['extra_records']['bite_observer']
    assert result['prediction'].startswith('Error:')
    assert data['budget']['logical_tool_calls']==data['budget']['failed_tool_calls']==1
    assert events(data,'tool_observation')[0]['canonical_result_ref'] is None


def test_sole_image_resolution_and_unknown_selection(monkeypatch):
    monkeypatch.setenv('BITE_OBSERVER_ENABLED','true')
    calls=[('x','Visual_Grounding_Tool','{"query":"person","image_id":"misspelled_alias"}')]
    agent,_,_=make_agent(responses=[response('qwen3-vl-8b-instruct',calls=calls),response('qwen3-vl-8b-instruct','<answer>done</answer>')])
    data=agent.generate(QUESTION)['extra_records']['bite_observer']
    dispatch=events(data,'tool_dispatch')[0]
    assert dispatch['image_inputs'][0]['requested_image_id']=='misspelled_alias'
    assert dispatch['image_inputs'][0]['resolved_image_id']=='input_image_1'
    assert dispatch['selection_dependency']=='unknown'


@pytest.mark.parametrize('sidecar_fails',[False,True])
def test_evaluator_observer_sidecar_separate_from_GT(tmp_path,sidecar_fails,monkeypatch):
    from evaluation_kit.runner import _make_committed_gen
    from evaluation_kit.utils import file_db
    import pandas as pd
    observer={'schema_version':'bite.observation.v1','capture_complete':True,'events':[]}
    original={'prediction':'[]','extra_records':{'bite_observer':observer}}
    dataset=type('Dataset',(),{'data':pd.DataFrame({'index':['sample'],'answer':['OFFLINE_GT']})})()
    real_write=file_db.atomic_write
    def write(path,*a,**kw):
        if sidecar_fails and 'bite_observations' in str(path):raise OSError('disk unavailable')
        return real_write(path,*a,**kw)
    monkeypatch.setattr(file_db,'atomic_write',write)
    gen=_make_committed_gen(lambda **kw:copy.deepcopy(original),work_dir=str(tmp_path),dataset=dataset,
                            dataset_name='fixture',model_name='model',agent_class='agent',save_images='files',
                            save_raw_trace=False,html_limit=0)
    result=gen(message='input',task_id='sample')
    assert result['prediction']=='[]'
    if not sidecar_fails:
        data=json.loads((tmp_path/'bite_observations/sample.json').read_text())
        assert data==observer and 'OFFLINE_GT' not in json.dumps(data)
    else:
        assert not result['extra_records']['bite_observer']['capture_complete']
    assert list(tmp_path.rglob('record.json'))

"""Synthetic geometry/label fixtures and an actual observer-v1 structural fixture.

No fixture GT is injected into observer/candidate construction. No services run.
"""
import ast
import copy
import json
from pathlib import Path

import pytest

from evaluation_kit.bite_calibration.actions import ACTION_SPEC, validate_action
from evaluation_kit.bite_calibration.candidate_association import associate, association_groups, compare
from evaluation_kit.bite_calibration.common import file_hash, iou
from evaluation_kit.bite_calibration.dataset_inventory import audit_sources
from evaluation_kit.bite_calibration.matching import GroundTruth, label_candidates, load_coco, load_dataset_ground_truth
from evaluation_kit.bite_calibration.outcomes import outcome
from evaluation_kit.bite_calibration.records import build_records, load_trace, runtime_records
from evaluation_kit.bite_calibration.split_integrity import audit_partitions, validate_partition_manifest
from evaluation_kit.bite_calibration.validation import validate_records

FIXTURE = json.loads((Path(__file__).parent/'fixtures/observer_v1.json').read_text())


def candidate(name='a', box=(0, 0, 10, 10), label='person', obs='one', score=.9):
    return {'candidate_id': name, 'bbox_root_xyxy': list(box) if box is not None else None,
            'class_name': label, 'source_group_id': 'image', 'root_image_id': 'root',
            'source_observation_id': obs, 'raw_scores': [score], 'association_status': 'new_distinct_candidate'}


def truth(boxes=((0,0,10,10),), flags=None, labels=None):
    annotations = []
    for index, box in enumerate(boxes):
        annotations.append({'id': index, 'image_id': 1, 'category_id': (labels or [1]*len(boxes))[index],
                            'bbox': [box[0],box[1],box[2]-box[0],box[3]-box[1]], 'bbox_xyxy': list(box),
                            'area': (box[2]-box[0])*(box[3]-box[1]), 'iscrowd': 0, 'ignore': 0,
                            **((flags or [{}]*len(boxes))[index])})
    return GroundTruth({'id':1, 'width':500, 'height':333}, [{'id':1,'name':'person'},{'id':2,'name':'horse'}],
                       annotations, {'source':'SYNTHETIC_TEST_ONLY'}, [])


def observer_calls(groups):
    """Synthetic proposals; labels are supplied separately through truth()."""
    observer = copy.deepcopy(FIXTURE)
    prototype = {e['type']:e for e in observer['events'] if e['type'] in ['tool_proposal','tool_dispatch','tool_observation']}
    observer['events'] = []
    for index, boxes in enumerate(groups):
        action = f'action_{index+1:04d}'; observation = f'observation_{index+1:04d}'; call = f'synthetic_native_{index}'
        for kind in ['tool_proposal','tool_dispatch','tool_observation']:
            event = copy.deepcopy(prototype[kind]); event['event_id']=f'event_{len(observer["events"])+1:04d}'
            event['logical_action_id']=action;event['provider_tool_call_id']=call
            if kind == 'tool_proposal':
                event['parsed_arguments']={'query':'person','image_id':'input_image_1'}
                event['raw_arguments']=json.dumps(event['parsed_arguments'])
            if kind == 'tool_observation':
                event['observation_id']=observation
                event['grounding'].update(query='person',empty_detection=not boxes,boxes_reason=None)
                event['grounding']['detections']=[{'detection_id':observation+f':detection_{i:04d}',
                    'bbox_local_xyxy':list(b),'bbox_root_xyxy':list(b),'score':.9-i*.01,'label':'person','mask':None} for i,b in enumerate(boxes)]
            observer['events'].append(event)
    return observer


def test_exact_image_hash_and_alias_overlap(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.write_bytes(b'identical');b.write_bytes(b'identical')
    assert file_hash(a)==file_hash(b)
    rows=[{'entry_id':'a','partition':'fit','image_path':str(a),'image_sha256':file_hash(a),'source_namespace':'data','source_image_id':'a'},
          {'entry_id':'b','partition':'test','image_path':str(b),'image_sha256':file_hash(b),'source_namespace':'data','source_image_id':'b'}]
    report=audit_partitions(rows)
    assert len(report['groups'])==1
    assert any(x['kind']=='image_sha256' for x in report['overlaps'])
    assert report['groups'][0]['assigned_partition'] is None


@pytest.mark.parametrize('feature',['image_path','source_image_id','scene_id','source_parent_id','annotation_file','annotation_sha256'])
def test_overlap_features(feature):
    a={'entry_id':'a','partition':'val','source_namespace':'source',feature:'same'}
    b={'entry_id':'b','partition':'test','source_namespace':'source',feature:'same'}
    result=audit_partitions([a,b])
    assert any(o['kind']==feature for o in result['overlaps'])


def test_source_numeric_ids_need_namespace_and_parents_group_crops():
    rows=[{'entry_id':'a','partition':'fit','source_namespace':'one','source_image_id':0},
          {'entry_id':'b','partition':'test','source_namespace':'two','source_image_id':0}]
    assert not audit_partitions(rows)['overlaps']
    rows=[{'entry_id':'root','partition':'fit','source_namespace':'s','source_image_id':'original'},
          {'entry_id':'crop','partition':'test','source_namespace':'s','source_image_id':'crop','source_parent_id':'original'}]
    assert len(audit_partitions(rows)['groups'])==1


def test_same_annotation_file_is_not_same_scene():
    rows=[{'entry_id':'a','partition':'fit','annotation_file':'labels.json','source_image_id':'a'},
          {'entry_id':'b','partition':'test','annotation_file':'labels.json','source_image_id':'b'}]
    assert len(audit_partitions(rows)['groups'])==2


def test_partition_manifest_rejects_shared_source_calls():
    m={'status':'frozen','entries':[{'source_group_id':'one','image_sha256':'sha','partition':'fit'},
                                   {'source_group_id':'one','image_sha256':'sha','partition':'test'}]}
    with pytest.raises(ValueError,match='multiple partitions'):validate_partition_manifest(m)
    m['entries'][1]['partition']='fit';assert validate_partition_manifest(m)
    m['status']='unassigned_provisional'
    with pytest.raises(ValueError,match='frozen'):validate_partition_manifest(m)


@pytest.mark.parametrize('other,status',[(candidate('b'),'likely_same_object'),
    (candidate('b',[30,30,40,40]),'spatially_distinct'),(candidate('b',[3,0,13,10]),'ambiguous_overlap'),
    (candidate('b',None),'unavailable_frame'),(candidate('b',label='horse'),'incompatible_class')])
def test_class_aware_association(other,status):
    assert compare(candidate(),other)['status']==status


def test_association_is_tentative_and_does_not_mutate_raw_proposals():
    proposals=[candidate('a'),candidate('b')];saved=copy.deepcopy(proposals)
    result=association_groups(proposals)
    assert len(result['groups'])==1 and result['groups'][0]['status']=='tentative_not_object_identity'
    assert proposals==saved
    assert associate(candidate('c'),proposals)['status']=='ambiguous_association'
    assert iou([0,0,10,10],[5,0,15,10])==pytest.approx(1/3)


def test_duplicate_geometric_validity_official_assignment_novelty():
    proposals=[candidate('a',score=.9),candidate('b',score=.8)]
    labels,_=label_candidates(proposals,truth())
    assert [labels[x][0]['geometric_valid'] for x in ['a','b']]==[True,True]
    assert [labels[x][0]['official_tp'] for x in ['a','b']]==[True,False]
    assert [labels[x][0]['novel_gt_instance'] for x in ['a','b']]==[True,False]
    assert labels['a'][0]['official_matched_gt_id']==0  # preserve original ID zero


def test_repeated_observations_have_explicit_assignment_scope():
    proposals=[candidate('a',obs='one'),candidate('b',obs='two')]
    labels,_=label_candidates(proposals,truth())
    assert labels['b'][0]['official_tp'] is True and labels['b'][0]['novel_gt_instance'] is False
    pooled,_=label_candidates(proposals,truth(),assignment_scope='trajectory')
    assert pooled['b'][0]['official_tp'] is False


def test_overlapping_real_objects_are_not_forced_into_one_identity():
    proposals=[candidate('a'),candidate('b',[3,0,13,10],score=.8)]
    labels,_=label_candidates(proposals,truth([[0,0,10,10],[3,0,13,10]]))
    assert all(labels[x][0]['official_tp'] for x in ['a','b'])
    assert labels['a'][0]['novel_gt_instance'] is None
    assert labels['a'][0]['novelty_reason']=='ambiguous_GT_or_candidate_association'


def test_thresholds_and_missed_gt_are_offline_only():
    labels,summary=label_candidates([candidate(box=[0,0,6,10])],truth([[0,0,10,10],[50,50,60,60]]))
    assert labels['a'][0]['geometric_valid'] is True
    assert labels['a'][1]['geometric_valid'] is False
    assert summary['uncovered_eligible_gt_ids']['0.5']==[1]
    assert summary['uncovered_eligible_gt_ids']['0.75']==[0,1]


@pytest.mark.parametrize('crowd',[0,1])
def test_ignore_crowd_native_semantics_are_explicit(crowd):
    labels,summary=label_candidates([candidate()],truth(flags=[{'ignore':1,'iscrowd':crowd}]))
    result=labels['a'][0]
    assert result['geometric_valid'] is False
    assert result['best_compatible_gt_including_ignored']['dataset_ignore'] is True
    assert result['official_ignored'] is bool(crowd)
    assert result['official_tp'] is (None if crowd else True)
    assert 'overwrites' in summary['explicit_ignore_semantics']


def test_crowd_uses_native_detection_area_overlap_and_allows_multiple_matches():
    labels,_=label_candidates([candidate('a',[1,1,3,3]),candidate('b',[4,4,6,6])],truth(flags=[{'iscrowd':1}]))
    assert all(labels[x][0]['official_ignored'] and labels[x][0]['official_matched_gt_id']==0 for x in ['a','b'])


@pytest.mark.parametrize('box,label,reason',[(None,'person','unknown_coordinate_frame'),([1,1,1,2],'person','invalid_box'),
    ([0,0,10,10],'unmapped','unknown_class_mapping')])
def test_unmatchable_proposals_are_unknown(box,label,reason):
    labels,_=label_candidates([candidate(box=box,label=label)],truth())
    assert labels['a'][0]['matching_status']==reason
    assert labels['a'][0]['geometric_valid'] is None and labels['a'][0]['official_tp'] is None


def test_unmatched_known_class_is_false_not_unknown():
    labels,_=label_candidates([candidate(box=[20,20,30,30])],truth())
    assert labels['a'][0]['max_eligible_iou']==0
    assert labels['a'][0]['geometric_valid'] is False and labels['a'][0]['official_tp'] is False


def test_clipping_preserves_raw_out_of_bounds_geometry():
    proposal=candidate(box=[-1,-2,10,10]);labels,_=label_candidates([proposal],truth())
    assert labels['a'][0]['bbox_raw_root_xyxy']==[-1,-2,10,10]
    assert labels['a'][0]['bbox_for_matching_xyxy']==[0,0,10,10]
    assert proposal['bbox_root_xyxy']==[-1,-2,10,10]


def test_reversed_box_matches_existing_evaluator_geometry_without_changing_raw():
    from evaluation_kit.dataset.eval_bridge import _xyxy_pixel_to_clipped_xywh
    proposal=candidate(box=[10,10,-1,-2]);labels,_=label_candidates([proposal],truth())
    used=labels['a'][0]['bbox_for_matching_xyxy']
    x,y,w,h=_xyxy_pixel_to_clipped_xywh(proposal['bbox_root_xyxy'],500,333)
    assert used==[x,y,x+w,y+h]==[0,0,10,10]
    assert labels['a'][0]['bbox_raw_root_xyxy']==[10,10,-1,-2]
    assert labels['a'][0]['raw_box_order_valid'] is False


def test_score_order_max_detections_and_missing_scores():
    labels,_=label_candidates([candidate('a',score=.1),candidate('b',score=.9)],truth(),max_dets=1)
    assert labels['b'][0]['official_tp'] is True
    assert labels['a'][0]['official_tp'] is None and labels['a'][0]['official_reason']=='max_detections_excluded'
    labels,_=label_candidates([candidate('a',score=None)],truth())
    assert labels['a'][0]['official_reason']=='score_order_unavailable'


def test_gt_loading_missing_invalid_and_zero_area(tmp_path):
    with pytest.raises(FileNotFoundError):load_coco(tmp_path/'missing.json',0)
    path=tmp_path/'labels.json';path.write_text('{}')
    with pytest.raises(ValueError):load_coco(path,0)
    doc={'images':[{'id':0,'width':10,'height':10}], 'categories':[{'id':1,'name':'person'}],
         'annotations':[{'id':0,'image_id':0,'category_id':1,'bbox':[0,0,0,2]}]}
    path.write_text(json.dumps(doc));gt=load_coco(path,0)
    assert gt.dropped_annotation_ids==[0] and gt.annotations==[]


def test_runtime_state_and_outcomes_have_no_hindsight():
    observer=observer_calls([[[0,0,10,10]],[[0,0,10,10]],[[50,50,60,60]]])
    before=copy.deepcopy(observer)
    a,_=build_records(observer,truth([[0,0,10,10],[50,50,60,60]]))
    b,_=build_records(observer,truth([[100,100,110,110]]))
    assert observer==before
    assert [r['outcome']['category'] for r in a]==['new_distinct_candidate','duplicate_existing_candidate','new_distinct_candidate']
    for x,y in zip(a,b):
        assert x['runtime_features']==y['runtime_features'] and x['action']==y['action'] and x['outcome']==y['outcome'] and x['state_id']==y['state_id']
    assert a[2]['offline_labels']['labels'][0]['novel_gt_instance'] is True
    assert a[1]['action']['name']=='repeated_grounding'
    assert validate_records(a)['records']==3
    assert build_records(observer,truth([[0,0,10,10],[50,50,60,60]]))[0]==a


def test_empty_failure_and_unexecuted_are_distinct():
    trace=observer_calls([[]]);rows,_=build_records(trace,truth())
    assert rows[0]['outcome']['category']=='no_detection' and rows[0]['runtime_features']['candidate'] is None
    trace['events'][-1].update(success=False,error_category='transport_timeout')
    rows,_=build_records(trace,truth())
    assert rows[0]['outcome']['category']=='execution_failure' and rows[0]['outcome']['failure_subtype']=='transport_timeout'
    assert outcome(None)=={'observed':False,'category':None,'reason':'not_executed','failure_subtype':None}


@pytest.mark.parametrize('ambiguous',[False,True])
def test_crop_root_geometry_novel_discovery_and_unknown(ambiguous):
    trace=observer_calls([[[0,0,10,10]],[[1,1,11,11]]])
    event=trace['events'][-1];source=event['image_inputs'][0]
    source['resolved_image_id']='crop_b'
    source['frame']=None if ambiguous else {'root_image_id':'input_image_1','child_to_root_transform':[[1,0,49],[0,1,49],[0,0,1]]}
    source['frame_reason']='ambiguous_deduplicated_lineage' if ambiguous else None
    event['grounding']['detections'][0]['bbox_root_xyxy']=None if ambiguous else [50,50,60,60]
    rows,_=build_records(trace,truth([[0,0,10,10],[50,50,60,60]]))
    label=rows[1]['offline_labels']['labels'][0]
    assert label['novel_gt_instance'] is (None if ambiguous else True)
    assert label['matching_status']==('unknown_coordinate_frame' if ambiguous else 'matchable')
    if ambiguous:assert rows[1]['outcome']['category']=='invalid_or_unavailable_observation'


@pytest.mark.parametrize('transform,child,category',[(None,'crop','crop_geometry_unavailable'),([[1,0,0],[0,1,0],[0,0,1]],'crop','crop_created'),(None,None,'crop_artifact_unavailable')])
def test_zoom_is_deterministic_artifact_outcome(transform,child,category):
    event={'success':True,'capability':'Zoom_In_Tool','crop':{'child_image_id':child,'child_to_root_transform':transform}}
    assert outcome(event)['category']==category


def test_structural_leakage_and_partition_checks():
    rows,_=build_records(observer_calls([[[0,0,10,10]],[[20,20,30,30]]]),truth())
    bad=copy.deepcopy(rows);bad[0]['runtime_features']['context']['matched_gt_id']=0
    with pytest.raises(Exception):validate_records(bad)
    bad=copy.deepcopy(rows);bad[0]['action']['arguments']['gt_boxes']=[0,0,10,10]
    with pytest.raises(ValueError,match='Offline-only'):validate_records(bad)
    bad=copy.deepcopy(rows);bad[1]['partition']='final_evaluation'
    with pytest.raises(ValueError,match='crosses'):validate_records(bad)
    with pytest.raises(ValueError,match='manifest'):build_records(observer_calls([[[0,0,10,10]]]),truth(),partition='calibration_fit')


def test_fixture_actual_observer_schema_and_canonical_resolution(tmp_path):
    trace=copy.deepcopy(FIXTURE)
    # Fixed numerical canonical data, not fabricated GT. Image bytes are not copied.
    reference=json.loads((Path(__file__).parents[1]/'bite/fixtures/reference_trace.json').read_text())
    canonical={'extra_records':{'bite_observer':{k:v for k,v in trace.items() if k!='origin'},
        'trajectory':{'chat_history':[{'memory_outputs':[{'canonical_result':turn['grounding']}]} for turn in reference['turns'][:2]]}}}
    root=tmp_path/'dataset';(root/'bite_observations').mkdir(parents=True);record=root/'results/shard'/trace['sample_id']/'record.json';record.parent.mkdir(parents=True)
    record.write_text(json.dumps(canonical));sidecar=root/'bite_observations'/f'{trace["sample_id"]}.json';sidecar.write_text(json.dumps(trace))
    observer,_,evidence=load_trace(sidecar)
    rows,proposals,_=runtime_records(observer)
    assert len(proposals)==3 and proposals[0]['raw_scores']==[.984375]
    assert proposals[1]['bbox_root_xyxy'][0]<0
    assert evidence['canonical_sha256']==file_hash(record)
    record.unlink()
    with pytest.raises(FileNotFoundError):load_trace(sidecar)


def test_action_space_and_prerequisites():
    assert not ACTION_SPEC['actions'][-1]['available']
    assert validate_action({'name':'root_grounding','arguments':{'image_id':'root','query':'person'}},images=['root'])
    with pytest.raises(ValueError,match='crop'):validate_action({'name':'focused_grounding','arguments':{'image_id':'root','query':'person'}},images=['root'])
    with pytest.raises(ValueError,match='unavailable'):validate_action({'name':'alternative_backend_verification'},images=[])
    with pytest.raises(ValueError,match='runtime-visible'):validate_action({'name':'crop_generation','arguments':{'image_id':'root'}},images=['root'])


def test_offline_code_not_imported_by_runtime():
    for path in Path('openvlharness').rglob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):assert 'bite_calibration' not in (node.module or '')
            if isinstance(node,ast.Import):assert all('bite_calibration' not in alias.name for alias in node.names)


def test_inventory_does_not_convert_count_labels_to_detection_gt(tmp_path):
    (tmp_path/'FSC147_val.tsv').write_text('index\timage_path\tquestion\tanswer\n0\ta.jpg\tCount\t3\n')
    inventory,_=audit_sources(tmp_path)
    assert inventory['tsvs'][0]['label_kind']=='count_or_other_not_detection_boxes'
    with pytest.raises(ValueError,match='annotation image ID|detection GT'):load_dataset_ground_truth(tmp_path,'FSC147_val','0')


def test_nested_crop_records_use_root_frame_and_focused_action():
    trace=observer_calls([[],[],[[1,2,11,12]]])
    observations=[e for e in trace['events'] if e['type']=='tool_observation']
    for index,(parent,child,tx,ty) in enumerate([('input_image_1','crop_a',20,30),('crop_a','crop_b',25,36)]):
        action_id=observations[index]['logical_action_id']
        for event in trace['events']:
            if event.get('logical_action_id')==action_id:
                event['capability']='Zoom_In_Tool'
                event['backend']='zoom_in_image_by_bbox'
        observations[index]['crop']={'parent_image_id':parent,'child_image_id':child,
            'child_to_parent_transform':[[1,0,20 if index==0 else 5],[0,1,30 if index==0 else 6],[0,0,1]],
            'child_to_root_transform':[[1,0,tx],[0,1,ty],[0,0,1]]}
    source=observations[2]['image_inputs'][0];source['resolved_image_id']='crop_b'
    source['frame']={'root_image_id':'input_image_1','child_to_root_transform':[[1,0,25],[0,1,36],[0,0,1]]}
    observations[2]['grounding']['detections'][0]['bbox_root_xyxy']=[26,38,36,48]
    rows,_=build_records(trace,truth([[26,38,36,48]]))
    assert rows[-1]['action']['name']=='focused_grounding'
    assert rows[-1]['runtime_features']['candidate']['bbox_local_xyxy']==[1,2,11,12]
    assert rows[-1]['offline_labels']['labels'][0]['geometric_valid'] is True
    assert all(r['outcome']['category']=='crop_created' for r in rows[:2])


def test_inconsistent_root_and_same_scene_different_frames_not_matched():
    trace=observer_calls([[[0,0,10,10]]]);event=trace['events'][-1]
    event['grounding']['detections'][0]['bbox_root_xyxy']=[100,100,110,110]
    rows,_=build_records(trace,truth([[100,100,110,110]]))
    candidate_record=rows[0]['runtime_features']['candidate']
    assert candidate_record['bbox_root_xyxy'] is None
    assert candidate_record['bbox_root_reported_xyxy']==[100,100,110,110]
    assert rows[0]['offline_labels']['labels'][0]['geometric_valid'] is None
    a=candidate();b=candidate('b');a['source_image_sha256']='first';b['source_image_sha256']='second'
    assert compare(a,b)['status']=='unavailable_frame'


def test_partition_mapping_uses_frozen_scene_group_and_image_hash():
    trace=observer_calls([[[0,0,10,10]]]);image_hash=next(a['sha256'] for a in trace['artifacts'] if a.get('image_id')=='input_image_1')
    manifest={'status':'frozen','entries':[{'source_group_id':'scene_one','image_sha256':image_hash,'partition':'calibration_fit'}]}
    rows,_=build_records(trace,truth(),partition='calibration_fit',partition_manifest=manifest)
    assert rows[0]['source_group_id']=='scene_one' and validate_records(rows)['valid']
    manifest['entries'][0]['image_sha256']='wrong'
    with pytest.raises(ValueError,match='absent'):build_records(trace,truth(),partition='calibration_fit',partition_manifest=manifest)


def test_new_observed_proposal_can_repeat_same_gt_instance():
    trace=observer_calls([[[0,0,10,10]],[[10,0,20,10]]])
    rows,_=build_records(trace,truth([[0,0,20,10]]))
    assert [r['outcome']['category'] for r in rows]==['new_distinct_candidate','new_distinct_candidate']
    assert rows[1]['offline_labels']['labels'][0]['novel_gt_instance'] is False


def test_unknown_class_aliases_and_pure_no_call_trace():
    gt=truth();gt.categories.append({'id':3,'name':'PERSON'})
    labels,_=label_candidates([candidate()],gt)
    assert labels['a'][0]['matching_status']=='unknown_class_mapping'
    trace=observer_calls([]);rows,summary=build_records(trace,truth())
    assert rows==[] and summary['candidate_count']==0


def test_missing_result_is_retained_as_unknown_not_a_negative_or_failure():
    trace=observer_calls([[[0,0,10,10]],[[20,20,30,30]]])
    trace['events'].pop()  # Actual dispatch exists; the result was not retained.
    trace['capture_complete']=False
    rows,summary=build_records(trace,truth())
    assert len(rows)==2 and rows[1]['runtime_features']['candidate'] is None
    assert rows[1]['action']['executed'] is True
    assert rows[1]['joint_observation_id'] is None
    assert rows[1]['outcome']=={'observed':False,'category':None,'reason':'dispatch_without_retained_result','failure_subtype':None}
    assert summary['missing_observation_action_ids']==['action_0002']
    assert validate_records(rows)['valid']

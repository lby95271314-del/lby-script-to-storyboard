#!/usr/bin/env python3
"""Fail-closed preflight and image-review evidence gate; does not perform vision inference."""
import argparse
import hashlib
import json
from pathlib import Path

FRAME_CHECKS = ('narrative_moment', 'characters', 'positions', 'pose_gaze', 'camera_scale_angle',
                'composition_occlusion', 'props_contact', 'scene_light', 'narrative_source')
PLAN_CHECKS = ('moment_defined', 'content_space_agreement', 'camera_composition_agreement',
               'reference_plan', 'continuity')
BOARD_CHECKS = ('narrative_cells', 'labels_timing', 'reference_separation')
ENTITY_FIELDS = ('screen_side', 'depth', 'pose', 'facing', 'gaze')
SHOT_FIELDS = ('id', 'start', 'end', 'duration', 'beat_ids', 'visible_characters', 'camera_id',
               'space', 'camera', 'content', 'dialogue_ids', 'events', 'previous_state', 'end_state')
FRAME_FIELDS = ('id', 'kind', 'shot_id', 'segment_id', 'time', 'keyframe_id', 'source_asset_ids', 'visible_characters', 'visual_contract')


def sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))


def file_sha(base, value):
    if not isinstance(value, str) or not value:
        return None
    path = base / value
    return sha(path.read_bytes()) if path.is_file() else None


def tasks(data, base):
    assets = {x['id']: x for x in data.get('assets', [])}
    frames = {x['id']: x for x in data.get('frames', [])}
    result = []
    for segment in data.get('segments', []):
        for shot in segment.get('shots', []):
            bound = [frames[fid] for fid in shot.get('frame_ids', []) if fid in frames]
            context = {
                'project': data.get('project', {}),
                'segment': {key: value for key, value in segment.items() if key not in ('shots', 'prompt', 'utterances')},
                'shot': {key: shot.get(key) for key in SHOT_FIELDS},
                'frames': [{key: f.get(key) for key in FRAME_FIELDS} for f in bound],
                'source_beats': [b for b in data.get('source_beats', []) if b.get('id') in shot.get('beat_ids', [])],
                'references': {aid: {'asset': assets.get(aid), 'sha256': file_sha(base, assets.get(aid, {}).get('path'))}
                               for f in bound for aid in f.get('source_asset_ids', [])},
            }
            result.append((segment, shot, bound, context, digest(context)))
    return result


def board_spec(data, base, segment):
    board = next((f for f in data.get('frames', []) if f.get('id') == segment.get('board_id')), {})
    return digest({'segment_id': segment['id'],
                   'shot_specs': [(shot['id'], spec) for seg, shot, bound, context, spec in tasks(data, base) if seg['id'] == segment['id']],
                   'source_frame_ids': board.get('source_frame_ids'),
                   'source_frames_sha256': board.get('source_frames_sha256')})


def pending_checks(keys):
    return {key: {'status': 'pending', 'expected': '', 'observed': ''} for key in keys}


def prepare(data, base):
    report = {'schema_version': 1, 'preflight': [], 'frames': [], 'boards': []}
    all_frames = {x['id']: x for x in data.get('frames', [])}
    for segment, shot, frames, context, spec_sha in tasks(data, base):
        report['preflight'].append({'shot_id': shot['id'], 'spec_sha256': spec_sha,
            'reviewer': '', 'text_inspected': False, 'checks': pending_checks(PLAN_CHECKS), 'verdict': 'pending',
            'context': context})
        for frame in frames:
            if frame.get('kind') != 'lineart':
                continue
            report['frames'].append({'frame_id': frame['id'], 'shot_id': shot['id'], 'spec_sha256': spec_sha,
                'image_sha256': file_sha(base, frame.get('path')), 'reviewer': '', 'method': 'vision',
                'image_opened': False, 'inspection_evidence': '', 'checks': pending_checks(FRAME_CHECKS),
                'observed_entities': {}, 'verdict': 'pending'})
    for segment in data.get('segments', []):
        board = all_frames.get(segment.get('board_id'), {})
        report['boards'].append({'frame_id': board.get('id'), 'image_sha256': file_sha(base, board.get('path')),
            'spec_sha256': board_spec(data, base, segment),
            'reviewer': '', 'method': 'vision', 'image_opened': False, 'inspection_evidence': '',
            'checks': pending_checks(BOARD_CHECKS), 'verdict': 'pending'})
    return report


def check(data, base, report, phase='delivery', shot_id=None):
    errors = []
    if phase not in ('preflight', 'delivery'):
        raise ValueError('unknown gate phase')
    if not isinstance(report, dict) or report.get('schema_version') != 1:
        return {'passed': False, 'delivery_allowed': False, 'errors': ['missing or unsupported visual review report']}

    def indexed(key, id_key):
        value = report.get(key, [])
        if not isinstance(value, list):
            errors.append(key + ': expected review list')
            return {}
        result = {}
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get(id_key), str):
                errors.append(key + ': invalid review record')
            elif item[id_key] in result:
                errors.append(key + ': duplicate review ' + item[id_key])
            else:
                result[item[id_key]] = item
        return result

    def filled(value):
        return isinstance(value, str) and bool(value.strip())

    def checks_pass(record, keys, label, vision=False):
        if not isinstance(record, dict):
            errors.append(label + ': review missing')
            return False
        start_errors = len(errors)
        if record.get('verdict') != 'pass' or not filled(record.get('reviewer')):
            errors.append(label + ': verdict/reviewer not accepted')
        if vision:
            if record.get('method') not in ('vision', 'human_visual') or record.get('image_opened') is not True or not filled(record.get('inspection_evidence')):
                errors.append(label + ': actual image inspection evidence missing')
        elif record.get('text_inspected') is not True:
            errors.append(label + ': plan not inspected')
        checks = record.get('checks', {})
        if not isinstance(checks, dict):
            checks = {}
        for key in keys:
            item = checks.get(key, {})
            if not isinstance(item, dict) or item.get('status') != 'pass' or not filled(item.get('expected')) or not filled(item.get('observed')):
                errors.append(label + ': ' + key + ' failed, uncertain or unreviewed')
        return len(errors) == start_errors

    plans, reviews, boards = indexed('preflight', 'shot_id'), indexed('frames', 'frame_id'), indexed('boards', 'frame_id')
    if shot_id and phase != 'preflight':
        raise ValueError('shot selection only allowed for preflight; delivery requires all shots')
    scene_tasks = [task for task in tasks(data, base) if not shot_id or task[1]['id'] == shot_id]
    if not scene_tasks:
        errors.append('no shots to review')
    frames_by_id = {x['id']: x for x in data.get('frames', [])}
    approved_frame_hashes = {}
    linked_frames = []
    for segment, shot, bound, context, spec_sha in scene_tasks:
        sid = shot['id']
        plan = plans.get(sid)
        checks_pass(plan, PLAN_CHECKS, sid + '/preflight')
        for aid, reference in context['references'].items():
            if reference['sha256'] is None:
                errors.append(sid + ': source reference missing: ' + aid)
        if not plan or plan.get('spec_sha256') != spec_sha:
            errors.append(sid + ': plan changed; preflight stale')
        if not bound or len(bound) != len(shot.get('frame_ids', [])):
            errors.append(sid + ': narrative frames missing or undefined')
        for frame in bound:
            fid = frame['id']
            linked_frames.append(fid)
            if frame.get('kind') != 'lineart' or frame.get('shot_id') != sid or frame.get('segment_id') != segment['id']:
                errors.append(fid + ': not this shot narrative frame')
            contract = frame.get('visual_contract')
            if not isinstance(contract, dict):
                errors.append(fid + ': visual contract missing')
                contract = {}
            for key in ('narrative_moment', 'camera', 'composition', 'props', 'scene'):
                if not filled(contract.get(key)):
                    errors.append(fid + ': expected ' + key + ' missing')
            entities = contract.get('entities')
            if not isinstance(entities, dict):
                errors.append(fid + ': expected entities missing (empty object only for empty shots)')
                entities = {}
            for name, entity in entities.items():
                if name not in data.get('characters', []) or not isinstance(entity, dict):
                    errors.append(fid + ': unknown/invalid expected character ' + name)
                    continue
                for key in ENTITY_FIELDS:
                    if not filled(entity.get(key)):
                        errors.append(fid + ': expected ' + name + '.' + key + ' missing')
                if entity.get('screen_side') not in ('left', 'center', 'right', 'offscreen'):
                    errors.append(fid + ': invalid expected screen side')
            visible = {name for name, entity in entities.items() if isinstance(entity, dict) and entity.get('screen_side') != 'offscreen'}
            expected_visible = set(frame.get('visible_characters', shot.get('visible_characters', [])))
            if not expected_visible.issubset(set(shot.get('visible_characters', []))) or visible != expected_visible:
                errors.append(fid + ': expected identities differ from shot visible_characters')
            if phase == 'preflight':
                continue
            start_errors = len(errors)
            review = reviews.get(fid)
            checks_pass(review, FRAME_CHECKS, fid, vision=True)
            image_hash = file_sha(base, frame.get('path'))
            if not review or not image_hash or review.get('image_sha256') != image_hash:
                errors.append(fid + ': missing/changed image; review stale')
            if not review or review.get('spec_sha256') != spec_sha:
                errors.append(fid + ': changed shot/contract/reference; review stale')
            if frame.get('status') != 'accepted':
                errors.append(fid + ': frame not accepted')
            observed = review.get('observed_entities') if review else None
            if observed != entities:
                errors.append(fid + ': observed identities/positions/pose/facing/gaze do not match expected entities')
            if len(errors) == start_errors and image_hash:
                approved_frame_hashes[fid] = image_hash
    if len(linked_frames) != len(set(linked_frames)):
        errors.append('narrative frame linked more than once')
    for frame in data.get('frames', []):
        if not shot_id and frame.get('kind') == 'lineart' and frame['id'] not in linked_frames:
            errors.append(frame['id'] + ': unlinked narrative frame; cannot hide failed frames in deliverables')
    if phase == 'delivery':
        for segment in data.get('segments', []):
            board = frames_by_id.get(segment.get('board_id'), {})
            bid = board.get('id', segment['id'] + '/missing-board')
            checks_pass(boards.get(bid), BOARD_CHECKS, str(bid), vision=True)
            if not boards.get(bid) or boards[bid].get('spec_sha256') != board_spec(data, base, segment):
                errors.append(str(bid) + ': storyboard labels/specification review stale')
            image_hash = file_sha(base, board.get('path'))
            if not image_hash or not boards.get(bid) or boards[bid].get('image_sha256') != image_hash:
                errors.append(str(bid) + ': storyboard file missing/changed')
            expected_ids = [fid for shot in segment.get('shots', []) for fid in shot.get('frame_ids', [])]
            if board.get('kind') != 'board' or board.get('status') != 'accepted' or board.get('segment_id') != segment['id']:
                errors.append(str(bid) + ': storyboard not accepted for this segment')
            if board.get('source_frame_ids') != expected_ids:
                errors.append(str(bid) + ': storyboard narrative order/source IDs differ')
            expected_hashes = {fid: approved_frame_hashes.get(fid) for fid in expected_ids}
            if any(value is None for value in expected_hashes.values()) or board.get('source_frames_sha256') != expected_hashes:
                errors.append(str(bid) + ': storyboard includes unapproved or stale source frames')
    return {'passed': not errors, 'generation_allowed': phase == 'preflight' and not errors, 'delivery_allowed': phase == 'delivery' and not errors, 'phase': phase,
            'errors': errors, 'scope': 'Enforces recorded visual inspection and hashes; requires actual image viewing, not pixel understanding by this script.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'check'):
        part = sub.add_parser(name)
        part.add_argument('storyboard', type=Path)
        part.add_argument('--reviews', required=True, type=Path)
        if name == 'check':
            part.add_argument('--phase', choices=('preflight', 'delivery'), default='delivery')
            part.add_argument('--shot-id', help='preflight one shot only')
    args = parser.parse_args()
    try:
        data = json.loads(args.storyboard.read_text(encoding='utf-8-sig'))
        base = args.storyboard.resolve().parent
        if args.command == 'prepare':
            report = prepare(data, base)
            with args.reviews.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
            result = {'prepared': True, 'delivery_allowed': False, 'reviews': str(args.reviews)}
        else:
            report = json.loads(args.reviews.read_text(encoding='utf-8-sig'))
            result = check(data, base, report, args.phase, args.shot_id)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {'passed': False, 'delivery_allowed': False, 'errors': [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('prepared') or result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())

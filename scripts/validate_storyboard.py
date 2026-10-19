#!/usr/bin/env python3
"""Validate storyboard data, references and linear timing; not visual or acting QA."""
import argparse
import json
import math
import sys
from pathlib import Path

EPS = 0.001


def validate(data, base, require_media=False):
    errors, warnings = [], []
    visual_complete = True

    def fail(message):
        errors.append(message)

    def rows(container, key):
        value = container.get(key, [])
        if not isinstance(value, list):
            fail(f'{key}: expected list')
            return []
        if any(not isinstance(x, dict) for x in value):
            fail(f'{key}: expected object entries')
        return [x for x in value if isinstance(x, dict)]

    def ids(container, key):
        value = container.get(key, [])
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            fail(f'{key}: expected string ID list')
            return []
        if len(value) != len(set(value)):
            fail(f'{key}: duplicate references')
        return value

    def index(items, label):
        result = {}
        for item in items:
            item_id = item.get('id')
            if not isinstance(item_id, str) or not item_id:
                fail(f'{label}: missing ID')
            elif item_id in result:
                fail(f'{label}: duplicate ID {item_id}')
            else:
                result[item_id] = item
        return result

    def number(value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            fail(f'{label}: expected finite number')
            return 0.0
        return float(value)

    def interval(item, label):
        start = number(item.get('start'), label + '.start')
        end = number(item.get('end'), label + '.end')
        if start < 0 or end <= start:
            fail(f'{label}: invalid interval {start}..{end}')
        return start, end

    def path_of(value):
        return base / value if isinstance(value, str) and value else None

    def media_exists(item, label, png_only=False):
        path = path_of(item.get('path'))
        if path is None or not path.is_file():
            fail(f'{label}: accepted media file missing')
            return False
        signature = path.read_bytes()[:16]
        png = signature.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        other = signature.startswith(bytes([255, 216, 255])) or (signature.startswith(b'RIFF') and signature[8:12] == b'WEBP')
        if not (png if png_only else png or other):
            fail(f'{label}: invalid image signature' + (' (board must be PNG)' if png_only else ''))
            return False
        return True

    def missing_media(message):
        nonlocal visual_complete
        visual_complete = False
        (errors if require_media else warnings).append(message)

    project = data.get('project', {})
    if not isinstance(project, dict):
        fail('project: expected object')
        project = {}
    characters = set(ids(data, 'characters'))
    beats = index(rows(data, 'source_beats'), 'source_beats')
    sources = index(rows(data, 'source_dialogues'), 'source_dialogues')
    assets = index(rows(data, 'assets'), 'assets')
    frames = index(rows(data, 'frames'), 'frames')
    segments = rows(data, 'segments')
    index(segments, 'segments')
    if not beats:
        fail('source_beats: required for coverage check')
    if not segments:
        fail('segments: must not be empty')
    for aid, asset in assets.items():
        if asset.get('available'):
            asset_path = path_of(asset.get('path'))
            if asset_path is None or not asset_path.is_file():
                fail(f'{aid}: available asset file missing')
    frame_ok = {}
    segment_ids = {x.get('id') for x in segments}
    for fid, frame in frames.items():
        kind, status = frame.get('kind'), frame.get('status')
        if kind not in {'lineart', 'board', 'reference'}:
            fail(f'{fid}: invalid frame kind')
        if status not in {'pending', 'needs_fix', 'accepted'}:
            fail(f'{fid}: invalid frame status')
        if kind in {'lineart', 'board'} and frame.get('segment_id') not in segment_ids:
            fail(f'{fid}: unknown segment')
        input_ids = ids(frame, 'source_asset_ids')
        for aid in input_ids:
            if aid not in assets:
                fail(f'{fid}: unknown source asset {aid}')
        if kind == 'lineart' and status == 'accepted' and input_ids and not frame.get('input_bound'):
            fail(f'{fid}: accepted reference-based lineart lacks input binding record')
        frame_ok[fid] = status == 'accepted' and media_exists(frame, fid, kind == 'board')

    claimed, fragments, seen_shots, seen_utterances = set(), {}, set(), set()
    cursor = 0.0
    for segment in segments:
        sid = str(segment.get('id', '?'))
        ss, se = interval(segment, sid)
        length = se - ss
        if abs(ss - cursor) > EPS:
            fail(f'{sid}: episode gap or overlap before segment')
        cursor = se
        shots = rows(segment, 'shots')
        local_shots = index(shots, sid + '.shots')
        if not shots:
            fail(f'{sid}: no shots')
        shot_intervals = {}
        cut = 0.0
        for shot in shots:
            qid = str(shot.get('id', '?'))
            if qid in seen_shots:
                fail(f'{qid}: duplicate global shot ID')
            seen_shots.add(qid)
            a, b = interval(shot, qid)
            shot_intervals[qid] = (a, b)
            if abs(a - cut) > EPS:
                fail(f'{qid}: shot gap or overlap')
            cut = b
            if b > length + EPS:
                fail(f'{qid}: shot exceeds segment')
            if abs(number(shot.get('duration'), qid + '.duration') - (b - a)) > EPS:
                fail(f'{qid}: duration differs from end-start')
            for bid in ids(shot, 'beat_ids'):
                if bid not in beats:
                    fail(f'{qid}: unknown source beat {bid}')
                claimed.add(bid)
            camera = shot.get('camera', {})
            for key in ('scale', 'lens', 'movement', 'depth', 'composition', 'speed', 'angle'):
                if not isinstance(camera, dict) or not isinstance(camera.get(key), str) or not camera.get(key, '').strip():
                    fail(f'{qid}: missing camera field {key}')
            audio = shot.get('audio', {})
            for key in ('ambience', 'action', 'human', 'music'):
                if not isinstance(audio, dict) or not isinstance(audio.get(key), str) or not audio.get(key, '').strip():
                    fail(f'{qid}: missing audio layer {key}')
            for key in ('camera_id', 'space', 'content', 'previous_state', 'end_state'):
                if not isinstance(shot.get(key), str) or not shot.get(key, '').strip():
                    fail(f'{qid}: missing shot description {key}')
            visible = ids(shot, 'visible_characters')
            if set(visible) - characters:
                fail(f'{qid}: unknown visible character')
            narrative = []
            for fid in ids(shot, 'frame_ids'):
                frame = frames.get(fid)
                if frame is None:
                    fail(f'{qid}: unknown frame {fid}')
                    continue
                if frame.get('kind') != 'lineart' or frame.get('shot_id') != qid or frame.get('segment_id') != segment.get('id'):
                    fail(f'{qid}: frame {fid} is not this shot narrative lineart')
                else:
                    t = number(frame.get('time'), fid + '.time')
                    if t < a - EPS or t > b + EPS:
                        fail(f'{fid}: frame time outside shot')
                    narrative.append(fid)
            if not any(frame_ok.get(fid) for fid in narrative):
                missing_media(f'{qid}: no accepted narrative lineart')
            for event in rows(shot, 'events'):
                ea, eb = interval(event, qid + '.event')
                if ea < a - EPS or eb > b + EPS:
                    fail(f'{qid}: event outside shot')
        if abs(cut - length) > EPS:
            fail(f'{sid}: shots do not cover segment duration')
        board = frames.get(segment.get('board_id'))
        if board is None or board.get('kind') != 'board' or board.get('segment_id') != segment.get('id') or not frame_ok.get(board.get('id')):
            missing_media(f'{sid}: no accepted PNG storyboard')

        spoken = []
        for utterance in rows(segment, 'utterances'):
            uid = str(utterance.get('id', '?'))
            if uid in seen_utterances:
                fail(f'{uid}: duplicate utterance ID')
            seen_utterances.add(uid)
            ua, ub = interval(utterance, uid)
            if ub > length + EPS:
                fail(f'{uid}: speech outside segment')
            mode = utterance.get('mode')
            if mode not in {'sync', 'vo', 'narration', 'inner', 'post'}:
                fail(f'{uid}: invalid speech mode')
            source_id = utterance.get('source_id')
            source = sources.get(source_id)
            if source is None:
                fail(f'{uid}: unknown source dialogue')
            else:
                text = source.get('text')
                if not isinstance(text, str):
                    fail(f'{source_id}: source dialogue text must be string')
                    text = ''
                pa, pb = utterance.get('part_start', 0), utterance.get('part_end', len(text))
                if type(pa) is not int or type(pb) is not int or not 0 <= pa < pb <= len(text):
                    fail(f'{uid}: invalid source text offsets')
                else:
                    if utterance.get('text') != text[pa:pb]:
                        fail(f'{uid}: dialogue differs from original')
                    fragments.setdefault(source_id, []).append((pa, pb, utterance, ss + ua))
                if utterance.get('speaker') != source.get('speaker'):
                    fail(f'{uid}: wrong speaker')
            if utterance.get('speaker') not in characters:
                fail(f'{uid}: unknown speaker')
            covered = set(ids(utterance, 'shot_ids'))
            expected = {qid for qid, (a, b) in shot_intervals.items() if min(ub, b) - max(ua, a) > EPS}
            if covered != expected:
                fail(f'{uid}: shot coverage differs from continuous speech interval')
            for qid in ids(utterance, 'lip_sync_shot_ids'):
                if qid not in covered or utterance.get('speaker') not in local_shots.get(qid, {}).get('visible_characters', []):
                    fail(f'{uid}: lip sync assigned to absent speaker or uncovered shot')
            for previous in spoken:
                if min(ub, previous.get('end', 0)) - max(ua, previous.get('start', 0)) > EPS and not (utterance.get('overlap_reason') or previous.get('overlap_reason')):
                    fail(f'{uid}: overlapping speech lacks explicit reason')
            spoken.append(utterance)
            if not utterance.get('timing_basis'):
                warnings.append(f'{uid}: speech timing basis not recorded')
        if not isinstance(segment.get('prompt'), str) or not segment.get('prompt', '').strip():
            warnings.append(f'{sid}: model prompt not prepared')

    for fid, frame in frames.items():
        if frame.get('kind') == 'lineart' and frame.get('shot_id') not in seen_shots:
            fail(f'{fid}: narrative frame references unknown shot')
    for bid in set(beats) - claimed:
        fail(f'{bid}: original beat not covered')
    for did, source in sources.items():
        if source.get('speaker') not in characters:
            fail(f'{did}: source speaker not in character list')
        text = source.get('text', '')
        if not isinstance(text, str):
            fail(f'{did}: source text must be string')
            continue
        chunks = sorted(fragments.get(did, []), key=lambda x: x[0])
        pos, time_cursor = 0, -1.0
        for a, b, utterance, absolute_start in chunks:
            if a != pos:
                fail(f'{did}: missing or duplicated dialogue characters')
            if absolute_start < time_cursor - EPS:
                fail(f'{did}: dialogue fragments played out of order')
            pos, time_cursor = b, absolute_start
            if len(chunks) > 1 and not utterance.get('continuity_plan'):
                fail(f'{did}: split utterance lacks continuity plan')
        if pos != len(text):
            fail(f'{did}: original dialogue not fully covered')
    target = project.get('target_duration')
    delta = None
    if target is not None:
        target = number(target, 'target_duration')
        delta = round(cursor - target, 6)
        if abs(delta) > EPS:
            message = f'target duration difference: {delta:+g}s'
            (errors if project.get('duration_mode') == 'strict' else warnings).append(message)
    if project.get('duration_mode', 'content_first') not in {'strict', 'content_first'}:
        fail('duration_mode: expected strict or content_first')
    return {'data_valid': not errors, 'visual_complete': visual_complete, 'duration': round(cursor, 6), 'target_delta': delta, 'errors': errors, 'warnings': warnings,
            'scope': 'Data relationships and file signatures only; acting, pixels, tool input binding, browser and video require actual review.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('json_path', type=Path)
    parser.add_argument('--require-media', action='store_true', help='legacy alias for strict delivery (default)')
    parser.add_argument('--draft', action='store_true', help='structure-only work in progress; never authorizes delivery')
    parser.add_argument('--reviews', type=Path, help='actual per-frame visual inspection report')
    args = parser.parse_args()
    if args.draft and args.require_media:
        parser.error('--draft and --require-media cannot be combined')
    try:
        data = json.loads(args.json_path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('root must be an object')
        base = args.json_path.resolve().parent
        result = validate(data, base, require_media=not args.draft)
        result['mode'] = 'draft' if args.draft else 'delivery'
        result['delivery_allowed'] = False
        result['media_files_complete'] = result.pop('visual_complete')
        if args.draft:
            result['scope'] = 'Structure-only draft; does not authorize image generation or delivery.'
            result['passed'] = result['data_valid']
        else:
            from visual_gate import check
            reviews = json.loads(args.reviews.read_text(encoding='utf-8-sig')) if args.reviews else {}
            gate = check(data, base, reviews)
            result['visual_gate'] = gate
            result['delivery_allowed'] = result['data_valid'] and gate['delivery_allowed']
            result['errors'].extend(gate['errors'])
            result['passed'] = result['delivery_allowed']
            result['scope'] = 'Structure plus hash-bound visual inspection evidence; actual image viewing remains mandatory.'
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {'data_valid': False, 'visual_complete': False, 'errors': [str(exc)], 'warnings': []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('passed', False) else 1


if __name__ == '__main__':
    sys.exit(main())

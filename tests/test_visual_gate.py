"""Evidence gate tests use synthetic reviews, NOT actual visual inspections."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import visual_gate as gate
import validate_storyboard as structural

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def fixture(base):
    for name in ('asset.png', 'frame.png', 'kf.png', 'board.png'):
        (base / name).write_bytes(PNG)
    entity = {'screen_side': 'left', 'depth': 'foreground', 'pose': '坐着', 'facing': '画右', 'gaze': '门'}
    contract = {'narrative_moment': '甲坐着看门', 'entities': {'甲': entity}, 'camera': '平视中景',
                'composition': '甲在画左，门在画右', 'props': '无道具', 'scene': '窗光从画左进入'}
    frames = [{'id': fid, 'kind': 'lineart', 'segment_id': 'S1', 'shot_id': 'S1-1', 'time': moment,
               'status': 'accepted', 'path': file, 'source_asset_ids': ['A1'], 'input_bound': True,
               'visual_contract': copy.deepcopy(contract)} for fid, file, moment in [('F1', 'frame.png', 0), ('F2', 'kf.png', 1)]]
    frames.append({'id': 'BOARD', 'kind': 'board', 'segment_id': 'S1', 'path': 'board.png', 'status': 'accepted',
                   'source_frame_ids': ['F1', 'F2'], 'source_frames_sha256': {fid: gate.file_sha(base, file) for fid, file in [('F1', 'frame.png'), ('F2', 'kf.png')]}})
    shot = {'id': 'S1-1', 'start': 0, 'end': 2, 'duration': 2, 'beat_ids': ['B1'], 'frame_ids': ['F1', 'F2'],
            'visible_characters': ['甲'], 'camera_id': 'CAM1', 'space': '甲画左，门画右',
            'camera': dict(scale='中景', lens='50mm', movement='固定', depth='中景深', composition='甲居左', speed='静止', angle='平视'),
            'content': '甲坐着看门', 'audio': dict(ambience='无', action='无', human='无', music='无'),
            'previous_state': '甲坐着', 'end_state': '甲仍坐着', 'events': []}
    return {'project': {'title': '测试夹具', 'target_duration': 2, 'duration_mode': 'strict'}, 'characters': ['甲'],
            'source_beats': [{'id': 'B1', 'text': '甲坐着看门'}], 'source_dialogues': [],
            'assets': [{'id': 'A1', 'path': 'asset.png', 'available': True}], 'frames': frames,
            'segments': [{'id': 'S1', 'start': 0, 'end': 2, 'board_id': 'BOARD', 'shots': [shot], 'utterances': [], 'prompt': '甲坐着看门。'}]}


def synthetic_pass(data, base):
    report = gate.prepare(data, base)
    for kind in ('preflight', 'frames', 'boards'):
        for item in report[kind]:
            item.update(reviewer='TEST_ONLY_SYNTHETIC', verdict='pass')
            if kind == 'preflight':
                item['text_inspected'] = True
            else:
                item.update(image_opened=True, inspection_evidence='TEST_ONLY_NO_REAL_IMAGE_REVIEW')
            for check in item['checks'].values():
                check.update(status='pass', expected='测试期望', observed='测试观察')
            if kind == 'frames':
                item['observed_entities'] = copy.deepcopy(next(f for f in data['frames'] if f['id'] == item['frame_id'])['visual_contract']['entities'])
    return report


class VisualGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.data = fixture(self.base)
        self.report = synthetic_pass(self.data, self.base)

    def check(self, phase='delivery'):
        return gate.check(self.data, self.base, self.report, phase)

    def test_valid_complete_case_and_structural_compatibility(self):
        self.assertTrue(structural.validate(self.data, self.base, True)['data_valid'])
        self.assertTrue(self.check()['delivery_allowed'])

    def test_prepare_never_auto_approves(self):
        self.report = gate.prepare(self.data, self.base)
        self.assertFalse(self.check()['delivery_allowed'])
        self.assertFalse(self.check('preflight')['generation_allowed'])

    def test_preflight_allows_generation_without_images_but_not_delivery(self):
        for frame in self.data['frames']:
            frame['status'] = 'pending'
        for name in ('frame.png', 'kf.png', 'board.png'):
            (self.base / name).unlink()
        self.assertTrue(self.check('preflight')['generation_allowed'])
        self.assertFalse(self.check()['delivery_allowed'])

    def test_preflight_text_contradiction_blocks_generation(self):
        self.report['preflight'][0]['checks']['content_space_agreement']['status'] = 'fail'
        self.assertFalse(self.check('preflight')['generation_allowed'])

    def test_missing_review_blocks_accepted_flag(self):
        self.report['frames'] = []
        self.assertFalse(self.check()['delivery_allowed'])

    def test_wrong_spatial_facts_block_even_overall_pass(self):
        for key, wrong in [('screen_side', 'right'), ('depth', 'background'), ('pose', '站着'), ('facing', '画左'), ('gaze', '镜头')]:
            with self.subTest(key=key):
                report = copy.deepcopy(self.report)
                report['frames'][0]['observed_entities']['甲'][key] = wrong
                self.assertFalse(gate.check(self.data, self.base, report)['delivery_allowed'])

    def test_failed_or_uncertain_composition_blocks(self):
        for status in ('fail', 'uncertain', 'pending'):
            with self.subTest(status=status):
                report = copy.deepcopy(self.report)
                report['frames'][0]['checks']['composition_occlusion']['status'] = status
                self.assertFalse(gate.check(self.data, self.base, report)['delivery_allowed'])

    def test_actual_image_opening_and_observations_required(self):
        self.report['frames'][0]['image_opened'] = False
        self.assertFalse(self.check()['delivery_allowed'])
        self.report['frames'][0]['image_opened'] = True
        self.report['frames'][0]['checks']['positions']['observed'] = ''
        self.assertFalse(self.check()['delivery_allowed'])

    def test_bad_keyframe_cannot_hide_behind_good_main_frame(self):
        self.report['frames'][1]['checks']['pose_gaze']['status'] = 'fail'
        self.assertFalse(self.check()['delivery_allowed'])

    def test_changed_image_invalidates_review(self):
        (self.base / 'frame.png').write_bytes(PNG + b'changed')
        self.assertFalse(self.check()['delivery_allowed'])

    def test_changed_description_invalidates_review(self):
        self.data['segments'][0]['shots'][0]['content'] = '甲站着看门'
        self.assertFalse(self.check()['delivery_allowed'])

    def test_changed_source_asset_invalidates_review(self):
        (self.base / 'asset.png').write_bytes(PNG + b'new reference')
        self.assertFalse(self.check()['delivery_allowed'])

    def test_changed_contract_invalidates_review(self):
        self.data['frames'][0]['visual_contract']['composition'] = '甲在画右'
        self.assertFalse(self.check()['delivery_allowed'])

    def test_old_storyboard_source_or_changed_png_blocks(self):
        self.data['frames'][-1]['source_frames_sha256']['F1'] = 'old'
        self.assertFalse(self.check()['delivery_allowed'])
        self.data = fixture(self.base)
        self.report = synthetic_pass(self.data, self.base)
        (self.base / 'board.png').write_bytes(PNG + b'changed board')
        self.assertFalse(self.check()['delivery_allowed'])

    def test_unknown_character_and_extra_person_block(self):
        self.report['frames'][0]['observed_entities']['路人'] = dict(screen_side='right')
        self.assertFalse(self.check()['delivery_allowed'])

    def test_delivery_cannot_be_scoped_to_hide_bad_shots(self):
        with self.assertRaises(ValueError):
            gate.check(self.data, self.base, self.report, 'delivery', shot_id='S1-1')
        self.assertTrue(gate.check(self.data, self.base, self.report, 'preflight', shot_id='S1-1')['generation_allowed'])

    def test_board_labels_review_invalidates_when_shot_changes(self):
        old_board_review = copy.deepcopy(self.report['boards'])
        self.data['segments'][0]['shots'][0]['camera']['scale'] = '近景'
        self.report = synthetic_pass(self.data, self.base)
        self.report['boards'] = old_board_review
        self.assertFalse(self.check()['delivery_allowed'])

    def test_missing_contract_prevents_generation(self):
        del self.data['frames'][0]['visual_contract']
        self.report = gate.prepare(self.data, self.base)
        self.assertFalse(self.check('preflight')['generation_allowed'])

    def test_prepare_cli_cannot_approve_or_overwrite(self):
        file = self.base / 'storyboard.json'
        file.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        review_file = self.base / 'prepared.json'
        command = [sys.executable, str(SCRIPTS / 'visual_gate.py'), 'prepare', str(file), '--reviews', str(review_file)]
        first = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        original = review_file.read_bytes()
        self.assertFalse(json.loads(first.stdout)['delivery_allowed'])
        self.assertEqual(json.loads(original)['frames'][0]['verdict'], 'pending')
        second = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(second.returncode, 1)
        self.assertEqual(review_file.read_bytes(), original)

    def test_cli_default_blocks_without_reviews_and_draft_never_releases(self):
        file = self.base / 'storyboard.json'
        file.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
        first = subprocess.run([sys.executable, str(SCRIPTS / 'validate_storyboard.py'), str(file)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(first.returncode, 1)
        self.assertFalse(json.loads(first.stdout)['delivery_allowed'])
        second = subprocess.run([sys.executable, str(SCRIPTS / 'validate_storyboard.py'), str(file), '--draft'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(second.returncode, 0)
        self.assertFalse(json.loads(second.stdout)['delivery_allowed'])
        report = self.base / 'review.json'
        report.write_text(json.dumps(self.report, ensure_ascii=False), encoding='utf-8')
        third = subprocess.run([sys.executable, str(SCRIPTS / 'validate_storyboard.py'), str(file), '--reviews', str(report)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.assertTrue(json.loads(third.stdout)['delivery_allowed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

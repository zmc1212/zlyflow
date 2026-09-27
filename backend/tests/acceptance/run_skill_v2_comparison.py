"""Compare the real Director B submission with unchanged satisfied prompt A.

Explicit manual acceptance utility. Never generates text or adopts production media.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.media_studio import provider_bridge
from backend.app.media_studio.db import query_one
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.workshop_h3_skill import split_complete_group_draft

OUT = ROOT / 'test-results/skill-v2-director-20260927'
FIX = ROOT / 'backend/tests/fixtures/director_ep1_2026-09-26'
AUTHOR_JOB = 'job-3f9c325ed132'
VIDEO_JOB = 'job-aca23f3c43d5'


def sha(value):
    return hashlib.sha256(value.encode('utf8')).hexdigest()


def payload(jid):
    row = query_one('SELECT project_id,payload_json FROM ai_project_jobs WHERE id=%s', (jid,))
    assert row['project_id'] == 'accept-7a4f330dc2594b34'
    return json.loads(row['payload_json'])


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / (name + '.json')
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    temp.replace(target)


def read(name):
    return json.loads((OUT / (name + '.json')).read_text(encoding='utf8'))


def rewrite_prompts(graph, parsed):
    inputs = graph['12']['inputs']
    inputs['global_prompt'] = parsed['common_prompt']
    timeline = json.loads(inputs['timeline_data'])
    timeline['global']['prompt'] = parsed['common_prompt']
    timeline['batchWorkspaces']['r2v']['globalCommon']['prompt'] = parsed['common_prompt']
    for segments in (timeline['segments'], timeline['batchWorkspaces']['r2v']['segments']):
        assert len(segments) == len(parsed['shots']) == 2
        for segment, body in zip(segments, parsed['shots']):
            segment['prompt'] = body
    inputs['timeline_data'] = json.dumps(timeline, ensure_ascii=False, sort_keys=True)


def main(phase):
    video = payload(VIDEO_JOB)
    current_url = provider_bridge.comfy_row()['base_url'].rstrip('/')
    assert current_url == video['comfy_base_url'].rstrip('/'), 'Provider changed; do not switch instance'
    client = ComfyVideoClient(current_url)
    if phase == 'prepare':
        assert not (OUT / 'A.json').exists(), 'A already attempted'
        author = payload(AUTHOR_JOB)
        raw = author['authoring']['writing_history'][-1]['raw']
        group = author['base_plan']['groups'][0]
        beats = author['beats']
        parsed_b = split_complete_group_draft(raw, beats, group)
        graph_b = video['workflow_request']
        timeline = json.loads(graph_b['12']['inputs']['timeline_data'])
        assert graph_b['12']['inputs']['global_prompt'] == parsed_b['common_prompt']
        assert [s['prompt'] for s in timeline['segments']] == parsed_b['shots'], 'Director rewrote raw body'
        assert [s['frameCount'] for s in timeline['segments']] == [192, 192]
        raw_a = (FIX / '01_satisfied_prompt.txt').read_text(encoding='utf8')
        parsed_a = split_complete_group_draft(raw_a, beats, group)
        graph_a = deepcopy(graph_b)
        rewrite_prompts(graph_a, parsed_a)
        graph_a['7']['inputs']['filename_prefix'] = 'video/ZLY_Skill_v2_AB_20260927_A'
        # Normalize only prompt text and the output name to prove same conditions.
        normalized_a, normalized_b = deepcopy(graph_a), deepcopy(graph_b)
        for graph in (normalized_a, normalized_b):
            rewrite_prompts(graph, {'common_prompt':'same', 'shots':['same','same']})
            graph['7']['inputs']['filename_prefix'] = 'same'
        assert normalized_a == normalized_b, 'Non-prompt conditions differ'
        assert client.preflight() == video['task_type']
        save('prepared', {'classification':'same_seed_current_director_AB', 'author_job':AUTHOR_JOB,
            'video_job':VIDEO_JOB, 'comfy_url':current_url, 'A_raw':raw_a, 'B_raw':raw,
            'A_raw_sha256':sha(raw_a), 'B_raw_sha256':sha(raw), 'A_graph':graph_a,
            'B_graph':graph_b, 'non_prompt_conditions_equal':True,
            'seed':video['seed'], 'historical_seed':888,
            'seed_note':'Real Director selected random seed; A copies B exactly. Not historical seed reproduction.',
            'authorization':'User granted continuing authorization for this plan on 2026-09-27'})
        save('B', {'state':'submitted', 'prompt_id':video['prompt_id'], 'director_job':VIDEO_JOB})
        print(json.dumps({'prepared':True, 'seed':video['seed'], 'B_prompt':video['prompt_id'],
                          'raw_preserved':True, 'same_conditions':True}))
    elif phase == 'submit-a':
        assert not (OUT / 'A.json').exists(), 'A already attempted; inspect receipt, never blindly retry'
        prepared = read('prepared')
        assert current_url == prepared['comfy_url']
        state = {'state':'submitting'}
        save('A', state)
        receipt = client.submit(prepared['A_graph'])
        state.update(state='submitted', prompt_id=receipt['prompt_id'], receipt=receipt)
        save('A', state)
        print(json.dumps(state))
    elif phase == 'submit-codex':
        assert not (OUT / 'C.json').exists(), 'C already attempted; inspect receipt before retry'
        from backend.app.media_studio.services import workshop_contract as contract
        from backend.app.media_studio.services.workshop_direct_input import build_input
        author = payload(AUTHOR_JOB)
        plan = deepcopy(author['base_plan'])
        group = plan['groups'][0]
        beats = author['beats']
        snapshot = build_input(plan, group, beats, author['source'])
        destination = FIX / '11_codex_author_2026-09-27'
        raw = (destination / 'prompt.txt').read_text(encoding='utf8')
        parsed = split_complete_group_draft(raw, beats, group)
        group.update(common_prompt=parsed['common_prompt'], contract_version=snapshot['version'])
        errors = [error for beat, body in zip(beats, parsed['shots'])
                  for error in contract.prompt_checks(body, beat, group, h3=True, ordered_beats=beats)]
        assert not errors, errors
        prepared = read('prepared')
        assert current_url == prepared['comfy_url']
        graph = deepcopy(prepared['B_graph'])
        rewrite_prompts(graph, parsed)
        graph['7']['inputs']['filename_prefix'] = 'video/ZLY_Codex_Skill_20260927_C'
        normalized_c, normalized_b = deepcopy(graph), deepcopy(prepared['B_graph'])
        for item in (normalized_c, normalized_b):
            rewrite_prompts(item, {'common_prompt':'same','shots':['same','same']})
            item['7']['inputs']['filename_prefix'] = 'same'
        assert normalized_c == normalized_b, 'Non-prompt conditions differ'
        assert client.preflight() == video['task_type']
        evidence = {'author':'Current Codex conversation assistant; no external author API call',
            'user_request':'Use the current Codex conversation model to author shots 1 and 2 and submit to ComfyUI',
            'context_limit':'This conversation has already seen the satisfied A prompt and A/B feedback; not a blind model comparison.',
            'skill_revision':snapshot['skill_revision'], 'system':snapshot['system'], 'user':snapshot['user'],
            'system_sha256':snapshot['system_sha256'], 'user_sha256':snapshot['user_sha256'],
            'raw_sha256':sha(raw), 'seed':prepared['seed'], 'reference_content_sha256':
            '704867f336816d2bd3d96f44f4cab4a760ae2e9687ce49509790c78c68b9e216',
            'validation_errors':errors,'non_prompt_conditions_equal_to_AB':True}
        (destination / 'input-and-provenance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
        state = {'state':'submitting','raw_sha256':sha(raw),'graph':graph}
        save('C', state)
        receipt = client.submit(graph)
        state.update(state='submitted',prompt_id=receipt['prompt_id'],receipt=receipt)
        save('C',state)
        (destination / 'submission.json').write_text(json.dumps({'prompt_id':receipt['prompt_id'],
            'state':'submitted','seed':prepared['seed'],'raw_sha256':sha(raw)},ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'prompt_id':receipt['prompt_id'],'state':'submitted','seed':prepared['seed'],
                          'validation_errors':errors,'same_non_prompt_conditions':True}))
    elif phase == 'export-evidence':
        destination = FIX / '10_v2_director_2026-09-27'
        destination.mkdir(exist_ok=True)
        for jid in ('job-3ec1fad9a9b7', 'job-5d27b58865d7', AUTHOR_JOB):
            authored = payload(jid)
            contract = next(iter(authored['authoring']['contracts'].values()))
            history = authored['authoring']['writing_history'][-1]
            evidence = {'job_id':jid, 'contract_version':contract['version'],
                'skill_revision':contract.get('skill_revision'), 'system':contract['system'],
                'user':contract['user'], 'system_sha256':contract['system_sha256'],
                'user_sha256':contract['user_sha256'], 'raw':history['raw'],
                'raw_sha256':sha(history['raw']), 'errors':history.get('errors'),
                'review':history.get('review'), 'content_call_count':history.get('content_call_count'),
                'candidate_count':len(authored['candidates'])}
            (destination / (jid + '.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
        prepared = read('prepared')
        summary = {k:prepared[k] for k in ('classification','author_job','video_job','A_raw_sha256',
            'B_raw_sha256','non_prompt_conditions_equal','seed','historical_seed','seed_note','authorization')}
        for label in ('A','B'):
            state = read(label)
            summary[label] = {k:state[k] for k in ('prompt_id','state','output') if k in state}
        (destination / 'comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
        print('Saved three author attempts and A/B receipts; no media or credentials exported.')
    elif phase == 'status':
        for label in ('A', 'B', 'C'):
            if not (OUT / (label + '.json')).exists():
                continue
            state = read(label)
            pid = state.get('prompt_id')
            if not pid:
                print(label, 'submission uncertain: inspect server queue, do not resubmit')
                continue
            response = client.session.get(current_url + '/history/' + pid, timeout=30)
            response.raise_for_status()
            history = response.json().get(pid)
            if history:
                output = client._find_video(history.get('outputs', {}))
                state.update(history=history, output=output,
                             state='completed' if output else 'failed')
                if output:
                    state['view_url'] = client.view_url(output)
                save(label, state)
            else:
                queue = client.session.get(current_url + '/queue', timeout=30)
                queue.raise_for_status()
                state['queue_present'] = pid in json.dumps(queue.json())
            print(json.dumps({k:v for k,v in state.items() if k not in ('history','receipt','graph')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True, choices=['prepare','submit-a','submit-codex','status','export-evidence'])
    main(parser.parse_args().phase)

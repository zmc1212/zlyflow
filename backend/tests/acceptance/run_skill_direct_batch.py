"""Explicitly authorized, one-shot P4 experiment; never adopts production data.

Run with --phase preflight|old|new|submit|status. Outputs are resumable and
fail closed if a model call or submission has an uncertain outcome.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.media_studio.db import query_one
from backend.app.media_studio import provider_bridge
from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services import workshop_group_prompts as prompts
from backend.app.media_studio.services import workshop_h3_skill as skill
from backend.app.media_studio.services.workshop_direct_input import build_input, VERSION
from backend.app.media_studio.services.llm_service import LlmService
from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient
from backend.app.media_studio.services.h3_prompt_builder import H3PromptBuilder

FIX = ROOT / 'backend/tests/fixtures/director_ep1_2026-09-26'
OUT = ROOT / 'test-results/skill-direct-20260927-authorized'


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / (name + '.json')
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    temp.replace(target)


def read(name):
    return json.loads((OUT / (name + '.json')).read_text(encoding='utf8'))


def context():
    frozen = json.loads((FIX / '08_skill_direct_controlled_snapshot.json').read_text(encoding='utf8'))
    source = deepcopy(frozen['source'])
    raw_source = (FIX / source.pop('text_file')).read_bytes()
    assert sha(raw_source) == source.pop('text_sha256')
    source['text'] = raw_source.decode('utf8')
    historical = query_one('SELECT payload_json FROM ai_project_jobs WHERE id=%s', (frozen['source_job_id'],))
    payload = json.loads(historical['payload_json'])
    plan = deepcopy(payload['base_plan'])
    group = deepcopy(plan['groups'][0])
    slot = deepcopy(group['reference_slots'][0])
    assert slot.get('asset_id') == frozen['reference']['asset_id']
    beats = deepcopy(frozen['beats'])
    group.update(id='isolated-skill-direct-ab', beat_ids=[b['id'] for b in beats],
                 reference_slots=[slot], timecode_mode='cumulative')
    plan.update(groups=[group], shot_prompts={}, max_shots_per_group=2,
                source_fingerprint=source['fingerprint'], aspect_ratio='16:9')
    url = provider_bridge.comfy_row()['base_url'].rstrip('/')
    client = ComfyVideoClient(url)
    row = query_one('SELECT data_json FROM ai_project_episodes WHERE id=%s', ('ep-4d89a8df80a4',))
    current = json.loads(row['data_json']).get('prompt_authoring', {}).get('director_plan', {})
    chosen = skill.writing_author(current.get('writing_author'))
    author = {k: chosen[k] for k in ('profile_id','base_url','model','reasoning_effort','supports_vision')}
    reference = client.session.get(slot['image_url'], timeout=90)
    reference.raise_for_status()
    assert sha(reference.content) == frozen['reference']['image_content_sha256'], 'Reference changed'
    remote = client.session.get(url + '/view', params={'filename': 'shenyan-modern-reference.png',
        'subfolder': 'zly/director/ep-4d89a8df80a4', 'type': 'input'}, timeout=90)
    remote.raise_for_status()
    assert sha(remote.content) == sha(reference.content), 'Remote reference changed'
    return frozen, source, plan, group, beats, client, author


class Captured(BaseException):
    pass


def author_once(which):
    assert not (OUT / (which + '.json')).exists(), 'Attempt already recorded; do not repeat'
    f, source, plan, group, beats, client, author = context()
    pre = read('preflight')
    assert author == pre['author'] and client.base_url == pre['comfy_url'], 'Configuration changed'
    captured = {}
    def capture(system, user, images, **kwargs):
        captured.update(system=system, user=user, images=images)
        raise Captured()
    snapshot = build_input(plan, group, beats, source) if which == 'new' else skill.writing_contract_snapshot(source['text'], 'cumulative')
    try:
        with patch.object(LlmService, 'author_group', side_effect=capture):
            prompts.generate_group(plan, group, beats, source_text=source['text'], author=author, contract_snapshot=snapshot)
    except Captured:
        pass
    result = {'state': 'started', 'contract_version': snapshot['version'], 'author': author,
              'system': captured['system'], 'user': captured['user'],
              'system_sha256': sha(captured['system']), 'user_sha256': sha(captured['user']),
              'image_content_sha256': f['reference']['image_content_sha256'], 'content_calls': 1}
    save(which, result)
    try:
        raw, meta = LlmService.author_group(captured['system'], captured['user'], captured['images'],
                                           author=author, max_tokens=24000, temperature=0.2)
        result.update(state='completed', raw=raw, raw_sha256=sha(raw), meta=meta)
        save(which, result)
        audit = {}
        # Replay the sole response through production parsing; no second model call.
        try:
            class NoExtraCall(BaseException):
                pass
            responses = [True]
            def replay(*args, **kwargs):
                if not responses:
                    raise NoExtraCall()
                responses.pop()
                return raw, meta
            with patch.object(LlmService, 'author_group', side_effect=replay):
                result['candidates'] = prompts.generate_group(plan, group, beats, source_text=source['text'],
                    author=author, contract_snapshot=snapshot, audit=audit)
        except NoExtraCall:
            result['validation_error'] = 'Legacy validator requested repair; experimental repair disabled'
        except Exception as err:
            result['validation_error'] = str(err)
        result['checks'] = [{k:v for k,v in entry.items() if k in ('errors','reason','parsed','review')}
                            for entry in audit.get('writing_history', []) if entry.get('raw')]
        save(which, result)
        print(json.dumps({'sample':which,'state':result['state'],'raw_chars':len(raw),
                          'validation_error':result.get('validation_error'),'meta':meta}, ensure_ascii=False), flush=True)
    except Exception as err:
        result.update(state='failed', error=str(err), meta=getattr(err, 'author_meta', {}))
        save(which, result)
        print(json.dumps({'sample':which,'state':'failed','error':str(err)},ensure_ascii=False),flush=True)


def compile_sample(label, raw, frozen, plan, group, beats, task_type):
    plan, group, beats = deepcopy(plan), deepcopy(group), deepcopy(beats)
    plan['groups'] = [group]
    parsed = skill.split_complete_group_draft(raw, beats, group)
    if label == 'A':
        # Historical control has its own literal dialogue; retain the original text.
        for beat, body in zip(beats, parsed['shots']):
            spoken = re.findall(r'<d>\s*\[中文\]\s*(.*?)</d>', body, re.S)
            assert len(spoken) == 1
            beat['dialogue'] = spoken[0]
    group.update(common_prompt=parsed['common_prompt'], contract_version=VERSION)
    for beat, body in zip(beats, parsed['shots']):
        plan['shot_prompts'][beat['id']] = {'h3_prompt':body, 'contract_version':VERSION,
            'fingerprint':contract.prompt_fingerprint(beat, group, plan),
            'content_digest':contract.digest([body, parsed['common_prompt'],plan['source_fingerprint'],VERSION])}
    shots, _ = contract.execution_shots({'beats':beats,'prompt_authoring':{'director_plan':plan}})
    for shot, body in zip(shots, parsed['shots']):
        compiled = H3PromptBuilder.compile_director_segment_prompt(parsed['common_prompt'], shot['h3_prompt'])
        assert compiled['segment_prompt'] == body
        shot.update(prompt=body, uploaded_refs=[{'imageFile':frozen['reference']['historical_comfy_file']}])
    opts = {**frozen['execution'], 'aspect_ratio':'16:9', 'global_prompt':parsed['common_prompt']}
    timeline = ComfyVideoClient.build_timeline(shots, task_type, options=opts)
    graph = ComfyVideoClient.build_workflow(timeline, task_type, 'video/ZLY_Skill_AB_20260927_' + label, options=opts)
    assert [s['frameCount'] for s in timeline['segments']] == [192,192]
    assert graph['12']['inputs']['width'] == 864 and graph['12']['inputs']['height'] == 480
    return graph


def main(phase):
    if phase in ('old','new'):
        return author_once(phase)
    if phase == 'preflight':
        assert not (OUT / 'preflight.json').exists(), 'Preflight already frozen'
        f, source, plan, group, beats, client, author = context()
        task = client.preflight()
        save('preflight', {'classification':'controlled_new_comparison','author':author,
            'comfy_url':client.base_url,'task_type':task,'reference_sha256':f['reference']['image_content_sha256'],
            'source_sha256':sha(source['text']),'skill_sha256':sha(skill.SKILL_PATH.read_bytes()),
            'authorization':'User authorized 2 author calls and one A/B pair on 2026-09-27',
            'execution':f['execution'],'adopted':False})
        print(json.dumps(read('preflight'),ensure_ascii=False),flush=True)
    elif phase == 'submit':
        f, source, plan, group, beats, client, author = context()
        pre = read('preflight')
        assert client.base_url == pre['comfy_url'] and author == pre['author']
        new = read('new')
        assert new['state'] == 'completed' and not new.get('validation_error'), 'B is not executable'
        graphs = {label:compile_sample(label, raw, f, plan, group, beats, pre['task_type'])
                  for label,raw in [('A',(FIX/'01_satisfied_prompt.txt').read_text(encoding='utf8')),('B',new['raw'])]}
        a,b = deepcopy(graphs['A']),deepcopy(graphs['B'])
        for g in (a,b):
            g['7']['inputs']['filename_prefix']='same'
            g['12']['inputs']['global_prompt']='same'
            tl=json.loads(g['12']['inputs']['timeline_data'])
            tl['global']['prompt']='same';tl['batchWorkspaces']['r2v']['globalCommon']['prompt']='same'
            for seg in tl['segments']:seg['prompt']='same'
            for seg in tl['batchWorkspaces']['r2v']['segments']:seg['prompt']='same'
            g['12']['inputs']['timeline_data']=json.dumps(tl,sort_keys=True)
        assert a == b, 'Non-prompt execution conditions differ'
        for label,graph in graphs.items():
            assert not (OUT/(label+'.json')).exists(), 'Submission already attempted'
            state={'state':'submitting','graph':graph,'graph_sha256':sha(json.dumps(graph,sort_keys=True,ensure_ascii=False))}
            save(label,state)
            state.update(state='submitted',submitted=client.submit(graph))
            save(label,state)
            print(label,state['submitted']['prompt_id'],flush=True)
    elif phase == 'status':
        pre=read('preflight');client=ComfyVideoClient(pre['comfy_url'])
        for label in ('A','B'):
            state=read(label);pid=state['submitted']['prompt_id']
            response=client.session.get(client.base_url+'/history/'+pid,timeout=20);response.raise_for_status()
            history=response.json().get(pid)
            if history:
                output=client._find_video(history.get('outputs',{}))
                state.update(history=history,state='completed' if output else 'failed',output=output)
                if output:state['view_url']=client.view_url(output)
                save(label,state)
            print(json.dumps({'sample':label,'prompt_id':pid,'state':state['state'],
                              'output':state.get('output'),'view_url':state.get('view_url')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',required=True,choices=['preflight','old','new','submit','status'])
    main(parser.parse_args().phase)

"""Create a named isolated Director acceptance project. Never calls AI or adopts media."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.app.media_studio.db import query_one, transaction_cursor, now_str
from backend.app.media_studio.services import workshop_contract as contract
from backend.app.media_studio.services.workshop_service import WorkshopService
from backend.app.media_studio.services.workshop_h3_skill import DIRECT_VERSION

NAME = '纯 Skill v2 两镜隔离验收 2026-09-27'
FIX = ROOT / 'backend/tests/fixtures/director_ep1_2026-09-26'


def prepare():
    existing = query_one('SELECT id FROM ai_projects WHERE name=%s', (NAME,))
    if existing:
        episode = query_one('SELECT id FROM ai_project_episodes WHERE project_id=%s', (existing['id'],))
        return {'project_id': existing['id'], 'episode_id': episode['id'], 'created': False}
    frozen = json.loads((FIX / '08_skill_direct_controlled_snapshot.json').read_text(encoding='utf8'))
    text_bytes = (FIX / frozen['source']['text_file']).read_bytes()
    assert hashlib.sha256(text_bytes).hexdigest() == frozen['source']['text_sha256']
    text = text_bytes.decode('utf8')
    source_job = json.loads(query_one('SELECT payload_json FROM ai_project_jobs WHERE id=%s', (frozen['source_job_id'],))['payload_json'])
    slot = deepcopy(source_job['base_plan']['groups'][0]['reference_slots'][0])
    project_id, episode_id, doc_id, asset_id = ['accept-' + uuid.uuid4().hex[:16] for _ in range(4)]
    source = {'document_id': doc_id, 'revision': frozen['source']['revision'], 'text': text,
              'source_type': 'adopted_document_episode'}
    source['fingerprint'] = contract.digest([doc_id, source['revision'], text])
    beats = deepcopy(frozen['beats'])
    for beat in beats:
        beat.update(id='accept-shot-' + uuid.uuid4().hex[:12], character_ids=[asset_id], prop_ids=[],
                    workshop_manual_bindings=['character_ids', 'prop_ids'],
                    character_look_ids={asset_id: frozen['reference']['identity_id']})
    plan = contract.new_plan(beats, 'minimax-h3-director-accel-r2v', source, maximum=2)
    slot.update(asset_id=asset_id, look_id=frozen['reference']['identity_id'])
    plan['groups'][0].update(reference_policy='manual', reference_slots=[slot], timecode_mode='cumulative',
                             common_prompt='', locked_common_lines=[], contract_version=DIRECT_VERSION)
    plan.update(aspect_ratio='16:9', shot_prompts={})
    data = {'beats': beats, 'workshop_flow': 7, 'source_document_id': doc_id,
            'script_revision': source['revision'], 'prompt_authoring': {'director_plan': plan},
            'acceptance': {'classification':'controlled_new_comparison', 'source_job_id':frozen['source_job_id'],
                           'expected_image_sha256':frozen['reference']['image_content_sha256'], 'adopt_production':False}}
    now = now_str()
    # Clone only the source document and the one character asset into a new project.
    with transaction_cursor() as cursor:
        cursor.execute("INSERT INTO ai_projects (id,name,description,status,settings_json,created_at,updated_at) VALUES (%s,%s,%s,'active','{}',%s,%s)",
                       (project_id, NAME, '两镜受控验收；与正式项目隔离；未生成、未采纳生产媒体。', now, now))
        for table, original_id, new_id in [('ai_project_assets', frozen['reference']['asset_id'], asset_id),
                                          ('ai_project_documents', frozen['source']['document_id'], doc_id)]:
            cursor.execute(f'SELECT * FROM {table} WHERE id=%s', (original_id,))
            row = dict(cursor.fetchone())
            row.update(id=new_id, project_id=project_id, created_at=now, updated_at=now)
            if table == 'ai_project_documents':
                analysis = json.loads(row.get('analysis_json') or '{}')
                analysis['episodes'] = [{'episode_num':1, 'title':'两镜纯 Skill 对照', 'body':text}]
                analysis['script_development'] = {**(analysis.get('script_development') or {}), 'revision':source['revision']}
                row['analysis_json'] = json.dumps(analysis, ensure_ascii=False)
            columns = list(row)
            cursor.execute(f"INSERT INTO {table} ({','.join('`'+key+'`' for key in columns)}) VALUES ({','.join(['%s']*len(columns))})", tuple(row[key] for key in columns))
        cursor.execute("INSERT INTO ai_project_episodes (id,project_id,episode_num,title,status,script_text,shots_count,data_json,created_at,updated_at) VALUES (%s,%s,1,%s,'script_ready',%s,2,%s,%s,%s)",
                       (episode_id, project_id, '两镜纯 Skill 对照', text, json.dumps(data,ensure_ascii=False), now, now))
    view = WorkshopService.view(project_id, episode_id)
    assert not view['source_changed']
    assert len(view['plan']['groups']) == 1 and not view['plan']['groups'][0]['reference_issues']
    assert len(view['plan']['groups'][0]['reference_slots']) == 1
    return {'project_id':project_id, 'episode_id':episode_id, 'created':True,
            'revision':view['plan']['revision'], 'shots':2, 'references':1, 'model_calls':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--create', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(prepare(), ensure_ascii=False))

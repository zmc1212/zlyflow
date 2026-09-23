"""Explicit live-model probe. Run only against a dedicated validation project.

python -X utf8 -m backend.tests.director_quality_probe --project-id <validation-project>
Creates one clearly named test episode and a normal preview job; never submits video.
Results and model settings remain in the normal project/job history for human review.
"""
from __future__ import annotations

import argparse
import json
from unittest.mock import patch

from backend.app.media_studio.db import query_one
from backend.app.media_studio.services.project_detail_service import ProjectDetailService
from backend.app.media_studio.services.prompt_expansion_service import PromptExpansionService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--retry-job", help="Resume this preview job from its saved checkpoint")
    args = parser.parse_args()
    if args.retry_job:
        with patch.object(PromptExpansionService, "kick"):
            resumed = PromptExpansionService.retry(args.project_id, args.retry_job)
        job_id = resumed["job_id"]
        print(json.dumps({"resuming": args.retry_job, "job_id": job_id}), flush=True)
        PromptExpansionService._run(job_id)
        print(json.dumps(query_one("SELECT status,error_message FROM ai_project_jobs WHERE id=%s", (job_id,)), ensure_ascii=False), flush=True)
        return
    title = "独立验收片段：取信与翻页"
    episode = query_one("SELECT id FROM ai_project_episodes WHERE project_id=%s AND title=%s", (args.project_id, title))
    if not episode:
        episode = ProjectDetailService.create_episode(args.project_id, {"episode_num": 99, "title": title,
            "script_text": "现代写实，旧车站值班室深夜。成年女保安阿宁穿深蓝制服坐在桌边。她右手从桌面拿起旧信，左手搭在桌边。随后右手将信翻到背面，目光停在纸上。全程无对白。戏剧目的：从发现旧信到确认线索。", "status": "script_ready"})
        beats = [
            {"id": episode["id"] + "-1", "sequence": 1, "scene": "旧车站值班室·深夜", "action": "阿宁右手拿起桌上的信。", "camera": "平视中近景，固定", "dialogue": "", "video_duration": 4,
             "opening_state": "坐在桌边，右手在信旁，左手搭桌边", "closing_state": "坐在桌边，右手持信正面朝自己，左手搭桌边"},
            {"id": episode["id"] + "-2", "sequence": 2, "scene": "旧车站值班室·深夜", "action": "阿宁右手将信翻到背面。", "camera": "平视近景，轻微推进", "dialogue": "", "video_duration": 4,
             "opening_state": "坐在桌边，右手持信正面朝自己，左手搭桌边", "closing_state": "坐在桌边，右手持信背面朝自己，左手搭桌边"},
        ]
        ProjectDetailService.replace_episode_beats(args.project_id, episode["id"], beats)
    with patch.object(PromptExpansionService, "kick"):
        job = PromptExpansionService.enqueue(args.project_id, episode["id"], {"workflow_id": "minimax-h3-director-accel-t2v", "language": "zh-CN", "aspect_ratio": "16:9", "target_segment_count": 2, "target": {"kind": "director_episode"}, "reference_slots": []})
    print(json.dumps({"episode_id": episode["id"], **job}, ensure_ascii=False), flush=True)
    if not job.get("duplicate"):
        PromptExpansionService._run(job["job_id"])
    row = query_one("SELECT status,error_message FROM ai_project_jobs WHERE id=%s", (job["job_id"],))
    print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

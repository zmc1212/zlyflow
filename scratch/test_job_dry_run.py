import sys
from unittest.mock import patch
sys.path.insert(0, ".")

from server.services.episode_video_service import EpisodeVideoService

# Mock _EXECUTOR.submit so we don't start the real background task to comfyui in this dry run test
with patch.object(EpisodeVideoService, "_run_job") as mock_run:
    with patch("server.services.episode_video_service.execute_sql") as mock_sql:
        result = EpisodeVideoService.create_job("proj-ebaf2e7234584b39", "ep-47eb930fa754", {"duration_per_beat": 8, "quality": "0.4"})
        print("create_job returned:", result)
        print("mock_sql called:", mock_sql.called)
        call_args = mock_sql.call_args[0][1]
        import json
        payload = json.loads(call_args[3])
        print("payload prompt_source:", payload.get("prompt_source"))
        print("payload llm_model:", payload.get("llm_model"))
        print("payload prompt_cache keys:", list(payload.get("prompt_cache", {}).keys()))
        print("payload shot count:", payload.get("shot_count"))

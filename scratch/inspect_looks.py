import json
import sys
sys.path.insert(0, ".")
from server.services.project_detail_service import ProjectDetailService

assets = ProjectDetailService.list_assets("proj-ebaf2e7234584b39")
characters = [a for a in assets if a.get("kind") == "character"]
for c in characters:
    print("Character:", c.get("id"), c.get("name"))
    extra = c.get("extra") if isinstance(c.get("extra"), dict) else {}
    print("  identities:", extra.get("identities"))
    print("  image_url:", c.get("image_url"))

detail = ProjectDetailService.get_episode_detail("proj-ebaf2e7234584b39", "ep-47eb930fa754")
for b in detail.get("beats", []):
    print("Beat:", b.get("id"), "char_look_ids:", b.get("character_look_ids"))

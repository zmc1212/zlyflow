"""Fetch the two current 花甲正少年 character look sheets from the project library."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymysql
import requests

from backend.app.media_studio.db import get_mysql_config


PROJECT_ID = "proj-6f99a10cd9de4cfb"
OUTPUT = Path(__file__).resolve().parents[2] / "test-results" / "blender-h3-fight-ue-huajia"
CHARACTERS = (("吴耐", "wu-nai-look.png"), ("沙丽丽", "sha-lili-look.png"))


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    connection = pymysql.connect(**get_mysql_config(), connect_timeout=5,
                                 cursorclass=pymysql.cursors.DictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id,name,extra_json FROM ai_project_assets "
                "WHERE project_id=%s AND kind='character'",
                (PROJECT_ID,),
            )
            assets = cursor.fetchall()
    finally:
        connection.close()

    manifest = []
    with requests.Session() as session:
        for name, filename in CHARACTERS:
            asset = next((item for item in assets if item["name"] == name), None)
            if asset is None:
                raise ValueError(f"项目角色不存在：{name}")
            extra = json.loads(asset["extra_json"] or "{}")
            looks = [item for item in extra.get("identities", []) if item.get("image_url")]
            if len(looks) != 1:
                raise ValueError(f"{name} 应有唯一的带图形象设定，实际 {len(looks)} 张")
            look = looks[0]
            response = session.get(look["image_url"], timeout=60)
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                raise ValueError(f"{name} 形象设定链接不是图片")
            data = response.content
            (OUTPUT / filename).write_bytes(data)
            manifest.append({
                "name": name,
                "asset_id": asset["id"],
                "look_id": look.get("id"),
                "look_name": look.get("name"),
                "file": filename,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            })
    (OUTPUT / "character-sources.json").write_text(
        json.dumps({"project_id": PROJECT_ID, "project_name": "花甲正少年",
                    "characters": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for item in manifest:
        print(f"{item['name']} / {item['look_name']}: {item['bytes']} bytes, {item['sha256'][:12]}")


if __name__ == "__main__":
    main()

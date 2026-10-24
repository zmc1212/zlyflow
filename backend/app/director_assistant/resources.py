from __future__ import annotations

import io
import re
import stat
import zipfile
from pathlib import PurePosixPath

from ..skill_packs.yaml_util import parse_yaml
from .repository import AssistantConflict, AssistantRepository, identifier


BUILTINS = [
    ("script", "剧本创作", "剧本", "把一个想法逐步发展为完整剧本", "按类型定位、世界观、冲突、人物、大纲、完整剧本六个创作节点引导。先了解用户已有内容，缺什么才问什么，每次默认只问一个关键问题。用户说帮我找方向时给贴合其题材的选项。可跳过、改方向、直接写稿，不强制重复六问。完整剧本使用中文 Markdown 台本：# 剧名、## 故事定位、## 主要人物、## 第N集、### 镜头N，并包含场景、人物、时长、动作、运镜、台词、音效、提示词。生成 script 草稿，用户采纳后再继续制作。"),
    ("assets", "资产提取", "资产", "整理角色、场景和道具设定", "阅读用户给出的剧本或通过 project_read 读取工程。提取角色、场景、道具，写清名称、描述与 visual_prompt。生成 assets 草稿，data.assets 每项为 {kind:character|scene|prop,name,description,visual_prompt,role}。只生成文字设定；图片通过媒体提案确认后生成。"),
    ("episodes", "分集规划", "剧本", "安排分集结构、节奏与悬念", "结合已确认剧本规划分集。仅在集数或时长确实未知时提问。生成 episodes 草稿，data.episodes 为 {episode_num,title,summary,script_text} 数组。不改写用户已确认的关键事实和台词。"),
    ("storyboard", "分镜设计", "分镜", "把剧情拆解成可制作的镜头", "先读取已采纳剧本、资产和分集，按集生成 storyboard 草稿。data.episodes 每项 {episode_num,title,episode_id,beats:[{id,sequence,scene,action,dialogue,camera,duration,prompt,character_ids,scene_id,prop_ids}]}。id 留空时交给平台生成，引用资产 ID 必须来自工程，不可编造。每镜动作、站位、光线、道具和连续性要可拍摄。时长匹配对白和调度，单镜2–15秒，长镜拆分。"),
    ("prompt", "提示词优化", "提示词", "把创作意图整理为清晰的生成提示词", "确认用户需要图片还是视频提示词，保留主体、构图、光线、动作、风格和约束。引用参考图时保留有序 <Picture n>。交付 prompt 草稿和可复制的正文，不凭空补充产品参数。"),
    ("production", "完整短剧制作", "全流程", "从创意、剧本到分镜与媒体制作", "按创意澄清、剧本、角色场景道具、分集、分镜、媒体制作推进。每个文字阶段生成对应结构化草稿，等待用户采纳；可按用户要求只做其中一步。下一阶段沿用已确认设定，结合 project_read。媒体制作提出 asset_image、storyboard_image、video、voice、compose 提案，不直接执行付费生成；缺少项目实体 ID、参考素材或配置时先引导补齐。"),
]
EXPERTS = [
    ("script", "剧本策划专家", "剧本", "关注人物动机、冲突递进和叙事节奏", "作为剧本策划专家，以人物动机、戏剧冲突、因果链和叙事节奏帮助用户做选择。用具体例子解释取舍，尊重用户最终创作方向，与所选 Skill 的方法配合。"),
    ("prompt", "提示词架构专家", "提示词", "让创作要求清楚、可控、可执行", "作为提示词架构专家，先澄清目标、素材、限制与交付格式，保持人物、空间和参考图关系明确。用自然中文沟通，技术细节按需解释，辅助所选 Skill 交付可执行内容。"),
    ("director", "分镜导演", "分镜", "关注镜头语言、调度和画面连续性", "作为分镜导演，从镜头尺度、视线、方向、人物调度与剪辑连续性提供判断。避免无法在单镜内完成的调度，保留对白与物理状态，辅助当前 Skill 完成创作。"),
]


class ResourceService:
    def __init__(self, repo: AssistantRepository):
        self.repo = repo
        for kind, items in [("skill", BUILTINS), ("expert", EXPERTS)]:
            for key, name, category, description, instructions in items:
                rid = f"builtin-{kind}-{key}"
                with repo.store.connection() as conn:
                    existing = conn.execute("SELECT id FROM ai_assistant_records WHERE id=?", (rid,)).fetchone()
                if not existing:
                    self.save("", {"resource_type": kind, "name": name, "category": category,
                                   "description": description, "instructions": instructions, "references": {}}, resource_id=rid, builtin=True)

    def catalog(self, owner: str) -> list[dict]:
        favorites = {x["resource_id"] for x in self.repo.list(owner, "favorite")}
        return [{**r, "favorite": r["id"] in favorites} for r in self.repo.list(owner, "resource", shared=True)]

    def save(self, owner: str, data: dict, *, resource_id=None, builtin=False) -> dict:
        kind = data.get("resource_type", "skill")
        if kind not in {"skill", "expert"}:
            raise ValueError("请选择 Skill 或专家")
        name, instructions = str(data.get("name") or "").strip(), str(data.get("instructions") or "").strip()
        if not name or len(name) > 100 or not instructions or len(instructions) > 100000:
            raise ValueError("名称需为1–100字，创作指令需为1–100000字")
        refs = data.get("references") or {}
        if not isinstance(refs, dict) or len(refs) > 100 or sum(len(str(v)) for v in refs.values()) > 1500000:
            raise ValueError("参考资料过多，请精简后导入")
        value = {"resource_type": kind, "name": name, "category": str(data.get("category") or "个人")[:30],
                 "description": str(data.get("description") or "")[:500], "instructions": instructions,
                 "references": {str(k): str(v) for k, v in refs.items()}, "builtin": builtin}
        with self.repo.transaction() as conn:
            current = None
            if resource_id and not builtin:
                current = self.repo.get(owner, resource_id, "resource", conn=conn, lock=True)
                if data.get("version") != current["version"]:
                    raise AssistantConflict("该资源已更新，请刷新后再编辑")
            revision = self.repo.insert(owner, "resource_version", value, parent=resource_id or "", conn=conn)
            value["version_id"] = revision["id"]
            if current:
                return self.repo.update(owner, current, value, conn=conn)
            return self.repo.insert(owner, "resource", value, record_id=resource_id, conn=conn)

    def favorite(self, owner: str, resource_id: str, enabled: bool) -> None:
        self.repo.get(owner, resource_id, "resource", shared=True)
        import hashlib
        fid = "fav-" + hashlib.sha256(f"{owner}:{resource_id}".encode()).hexdigest()
        with self.repo.transaction() as conn:
            row = conn.execute("SELECT id FROM ai_assistant_records WHERE id=? AND owner_id=?", (fid, owner)).fetchone()
            if enabled and not row:
                self.repo.insert(owner, "favorite", {"resource_id": resource_id}, record_id=fid, conn=conn)
            elif not enabled and row:
                conn.execute("DELETE FROM ai_assistant_records WHERE id=? AND owner_id=?", (fid, owner))

    @staticmethod
    def import_preview(filename: str, content: bytes) -> dict:
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("Skill 包最多5MB")
        files, ignored = {}, []
        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    infos = archive.infolist()
                    if len(infos) > 300 or sum(i.file_size for i in infos) > 10 * 1024 * 1024:
                        raise ValueError("Skill 包解压后最多10MB、300个文件")
                    for info in infos:
                        path = PurePosixPath(info.filename.replace("\\", "/"))
                        mode = (info.external_attr >> 16) & 0xFFFF
                        if path.is_absolute() or ".." in path.parts or ":" in str(path) or stat.S_ISLNK(mode):
                            raise ValueError("Skill 包包含不安全路径")
                        if info.is_dir():
                            continue
                        if path.name.lower() == "skill.md" or ("references" in path.parts and path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml"}):
                            files[str(path)] = archive.read(info).decode("utf-8-sig")
                        else:
                            ignored.append(str(path))
            except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
                raise ValueError("无法读取 Skill 包，请使用 UTF-8 文本与有效 ZIP") from exc
        elif filename.lower().endswith(".md"):
            try:
                files["SKILL.md"] = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("请使用 UTF-8 Markdown 文件") from exc
        else:
            raise ValueError("请选择 Markdown 或 ZIP")
        entries = [(k, v) for k, v in files.items() if PurePosixPath(k).name.lower() == "skill.md"]
        if len(entries) != 1:
            raise ValueError("每次导入需要且只能包含一个 SKILL.md")
        entry, text = entries[0]
        meta = {}
        match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
        if match:
            meta = parse_yaml(match.group(1)) or {}
            if not isinstance(meta, dict):
                raise ValueError("Skill 元信息必须为对象")
            text = text[match.end():]
        return {"resource_type": "expert" if meta.get("resource_type") == "expert" else "skill", "name": str(meta.get("name") or "导入的 Skill"),
                "description": str(meta.get("description") or ""), "category": "个人",
                "instructions": text, "references": {k: v for k, v in files.items() if k != entry},
                "ignored_files": ignored}

    def export(self, owner: str, resource_id: str) -> bytes:
        resource = self.repo.get(owner, resource_id, "resource", shared=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            import json
            archive.writestr("SKILL.md", f"---\nname: {json.dumps(resource['name'], ensure_ascii=False)}\ndescription: {json.dumps(resource['description'], ensure_ascii=False)}\nresource_type: {resource['resource_type']}\n---\n\n{resource['instructions']}")
            for i, (name, value) in enumerate(resource["references"].items()):
                # Never echo arbitrary editor paths into an archive.
                safe_name = re.sub(r"[^\w.\-\u3400-\u9fff]", "_", PurePosixPath(name.replace("\\", "/")).name)
                archive.writestr(f"references/{i + 1}-{safe_name}", value)
        return buf.getvalue()

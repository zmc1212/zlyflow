from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .yaml_util import SkillPackYamlError, parse_yaml

PACKS_ROOT = Path(__file__).resolve().parent
DEFAULT_PACK_ID = ""
HALF_NARRATED_PACK_ID = "half-narrated-live-action-short-drama"


class UnknownSkillPackError(ValueError):
    pass


class UnknownSkillStepError(ValueError):
    pass


@dataclass(frozen=True)
class PackingOverrides:
    allow_timeranges: bool = False
    allow_multi_camera_path: bool = False
    faithful_zh_pack: bool = False
    skip_program_pack: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "allow_timeranges": self.allow_timeranges,
            "allow_multi_camera_path": self.allow_multi_camera_path,
            "faithful_zh_pack": self.faithful_zh_pack,
            "skip_program_pack": self.skip_program_pack,
        }


@dataclass(frozen=True)
class R2VSlot:
    source: str
    role: str = ""

    @property
    def is_full_triptych(self) -> bool:
        return self.source in {"triptych", "triptych.full", "triptych_url"}


@dataclass(frozen=True)
class PackRecipe:
    id: str
    name: str
    summary: str = ""
    author: str = ""
    cover: str = ""
    surfaces: tuple[str, ...] = ()
    visual_lock: str = ""
    director2_overlay: dict[str, str] = field(default_factory=dict)
    workshop_shot: tuple[str, ...] = ()
    r2v_slots: tuple[R2VSlot, ...] = ()
    packing_overrides: PackingOverrides = field(default_factory=PackingOverrides)
    root: Path | None = None
    confirm_format: dict[str, Any] = field(default_factory=dict)

    @property
    def is_default(self) -> bool:
        return not self.id

    def skill_markdown(self) -> str:
        if not self.root:
            return ""
        path = self.root / "SKILL.md"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def reference_text(self, name: str) -> str:
        if not self.root:
            return ""
        path = self.root / "references" / name
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def declared_step_ids(self) -> tuple[str, ...]:
        steps: list[str] = []
        for value in self.director2_overlay.values():
            if value:
                steps.append(str(value))
        steps.extend(self.workshop_shot)
        return tuple(dict.fromkeys(steps))

    def steps_for(self, surface: str, *, stage: str | None = None) -> tuple[str, ...]:
        if surface == "workshop":
            return self.workshop_shot
        if surface == "director2":
            step = str(self.director2_overlay.get(stage or "") or "").strip()
            return (step,) if step else ()
        if surface == "optimize":
            if "optimize" not in self.surfaces:
                return ()
            steps = ["inject_craft"]
            if "polish_ref2va" in self.workshop_shot:
                steps.append("polish_ref2va")
            return tuple(steps)
        return ()


def default_recipe() -> PackRecipe:
    return PackRecipe(
        id=DEFAULT_PACK_ID,
        name="默认程序装箱",
        summary="不注入 Plaza 制作配方，工坊用程序装箱六段。",
        surfaces=("workshop",),
        workshop_shot=("render_ref2va_default",),
        packing_overrides=PackingOverrides(),
    )


def recipe_from_mapping(data: dict[str, Any], *, root: Path | None = None) -> PackRecipe:
    from .registry import registered_step_ids

    if not isinstance(data, dict):
        raise SkillPackYamlError("meta.yaml 必须是对象")
    pack_id = str(data.get("id") or "").strip()
    if not pack_id:
        raise SkillPackYamlError("meta.yaml 缺少 id")
    overlay_raw = data.get("director2_overlay") if isinstance(data.get("director2_overlay"), dict) else {}
    overlay = {str(key): str(value).strip() for key, value in overlay_raw.items() if str(value).strip()}
    workshop = _string_tuple(data.get("workshop_shot"))
    slots = tuple(_r2v_slot(item) for item in (data.get("r2v_slots") or []) if item)
    overrides_raw = data.get("packing_overrides") if isinstance(data.get("packing_overrides"), dict) else {}
    recipe = PackRecipe(
        id=pack_id,
        name=str(data.get("name") or pack_id).strip() or pack_id,
        summary=str(data.get("summary") or data.get("description") or "").strip(),
        author=str(data.get("author") or data.get("author-cn") or data.get("author-en") or "").strip(),
        cover=_http_url(data.get("cover") or data.get("cover_url") or data.get("cover-en")),
        surfaces=_string_tuple(data.get("surfaces")),
        visual_lock=str(data.get("visual_lock") or "").strip(),
        director2_overlay=overlay,
        workshop_shot=workshop,
        r2v_slots=slots,
        packing_overrides=PackingOverrides(
            allow_timeranges=bool(overrides_raw.get("allow_timeranges")),
            allow_multi_camera_path=bool(overrides_raw.get("allow_multi_camera_path")),
            faithful_zh_pack=bool(overrides_raw.get("faithful_zh_pack")),
            skip_program_pack=bool(overrides_raw.get("skip_program_pack")),
        ),
        root=root,
        confirm_format=dict(data.get("confirm_format") or {}) if isinstance(data.get("confirm_format"), dict) else {},
    )
    unknown = [step for step in recipe.declared_step_ids() if step not in registered_step_ids()]
    if unknown:
        raise UnknownSkillStepError(f"技能包 {pack_id} 声明了未注册步骤：{', '.join(unknown)}")
    return recipe


def load_recipe_file(path: Path) -> PackRecipe:
    text = path.read_text(encoding="utf-8")
    data = parse_yaml(text)
    if not isinstance(data, dict):
        raise SkillPackYamlError(f"{path} 必须是对象")
    return recipe_from_mapping(data, root=path.parent)


def scan_pack_recipes(root: Path | None = None) -> dict[str, PackRecipe]:
    base = root or PACKS_ROOT
    packs: dict[str, PackRecipe] = {}
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        meta = child / "meta.yaml"
        if not meta.is_file():
            continue
        recipe = load_recipe_file(meta)
        packs[recipe.id] = recipe
    return packs


_CACHE: dict[str, PackRecipe] | None = None


def reset_pack_cache() -> None:
    global _CACHE
    _CACHE = None


def all_packs() -> dict[str, PackRecipe]:
    global _CACHE
    if _CACHE is None:
        _CACHE = scan_pack_recipes()
    return _CACHE


def list_packs() -> list[PackRecipe]:
    return list(all_packs().values())


def get_pack(pack_id: str | None) -> PackRecipe:
    normalized = str(pack_id or "").strip()
    if not normalized:
        return default_recipe()
    pack = all_packs().get(normalized)
    if pack is None:
        raise UnknownSkillPackError(f"未知技能包：{normalized}")
    return pack


def require_pack(pack_id: str) -> PackRecipe:
    return get_pack(pack_id)


def pack_payload(pack: PackRecipe) -> dict[str, Any]:
    return {
        "id": pack.id,
        "name": pack.name,
        "summary": pack.summary,
        "author": pack.author,
        "cover": pack.cover,
        "surfaces": list(pack.surfaces),
        "visual_lock": pack.visual_lock,
        "workshop_shot": list(pack.workshop_shot),
        "packing_overrides": pack.packing_overrides.as_dict(),
        "confirm_format": dict(pack.confirm_format),
    }


def list_pack_payloads() -> list[dict[str, Any]]:
    return [pack_payload(pack) for pack in list_packs()]


def list_pack_catalog() -> list[dict[str, Any]]:
    return [pack_payload(default_recipe()), *list_pack_payloads()]


def packing_overrides_of(pack_id: str | None = None) -> dict[str, bool]:
    resolved = pack_id
    if resolved is None:
        from .context import active_skill_pack_id

        resolved = active_skill_pack_id()
    try:
        return get_pack(resolved).packing_overrides.as_dict()
    except UnknownSkillPackError:
        return PackingOverrides().as_dict()


def skip_program_pack_enabled(pack_id: str | None = None) -> bool:
    return bool(packing_overrides_of(pack_id).get("skip_program_pack"))


def _http_url(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith(("https://", "http://")):
        return text
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, Iterable) or isinstance(value, (bytes, dict)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _r2v_slot(raw: Any) -> R2VSlot:
    if isinstance(raw, str):
        return R2VSlot(source=raw.strip())
    if not isinstance(raw, dict):
        return R2VSlot(source=str(raw or "").strip())
    return R2VSlot(
        source=str(raw.get("source") or "").strip(),
        role=str(raw.get("role") or "").strip(),
    )

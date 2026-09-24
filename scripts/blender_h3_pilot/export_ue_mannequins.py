"""Read-only UE 5.7 asset export for the isolated H3 mannequin trial.

Run in full editor mode via UnrealEditor-Cmd.exe -ExecutePythonScript=<this file>.
The commandlet exporter crashes on these skeletal mesh assets. Use the
isolated UEFightTrial copy in test-results; the source UE project is untouched.
"""

import json
from pathlib import Path

import unreal

OUT = Path(__file__).resolve().parents[2] / "test-results" / "blender-h3-fight-ue"
OUT.mkdir(parents=True, exist_ok=True)

ASSETS = {
    "Skeleton": "/Game/Characters/Mannequins/Meshes/SK_Mannequin",
    "Manny": "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple",
    "Quinn": "/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple",
    "Attack_01": "/Game/Characters/Mannequins/Anims/Unarmed/Attack/MM_Attack_01",
    "Attack_02": "/Game/Characters/Mannequins/Anims/Unarmed/Attack/MM_Attack_02",
    "Attack_03": "/Game/Characters/Mannequins/Anims/Unarmed/Attack/MM_Attack_03",
    "ChargedAttack": "/Game/Characters/Mannequins/Anims/Unarmed/Attack/MM_ChargedAttack",
    "Idle": "/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle",
}

results = {}
for name, asset_path in ASSETS.items():
    try:
        asset = unreal.load_asset(asset_path)
        if not asset:
            raise RuntimeError("asset missing")
        skeleton = asset.get_editor_property("skeleton") if name != "Skeleton" else asset
        if name == "Skeleton":
            results[name] = {"source": asset_path, "class": asset.get_class().get_name()}
            continue
        if not skeleton:
            raise RuntimeError("asset has no linked Skeleton; FBX exporter would crash")
        exporter_type = (unreal.SkeletalMeshExporterFBX if name in ("Manny", "Quinn")
                         else unreal.AnimSequenceExporterFBX)
        task = unreal.AssetExportTask()
        task.object = asset
        task.filename = str(OUT / f"{name}.fbx")
        task.exporter = exporter_type()
        task.automated = True
        task.prompt = False
        task.replace_identical = True
        task.selected = False
        ok = unreal.Exporter.run_asset_export_task(task)
        file = OUT / f"{name}.fbx"
        results[name] = {"source": asset_path, "skeleton": skeleton.get_path_name(), "ok": bool(ok),
                         "bytes": file.stat().st_size if file.is_file() else 0}
    except Exception as error:
        results[name] = {"source": asset_path, "ok": False, "error": str(error)}
    unreal.log(f"H3_UE_EXPORT {name}: {results[name]}")

(OUT / "export-manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

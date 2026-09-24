"""Generate one H3 fight take using a photoreal still and Blender motion guide."""

from __future__ import annotations

import json
import argparse
import sys
import time
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.media_studio.services.comfy_video_client import ComfyVideoClient  # noqa: E402
from backend.app.minimax_h3_workflow import build_minimax_h3_workflow  # noqa: E402
from backend.app.models import JobMode  # noqa: E402
from scripts.blender_h3_pilot.pilot import OPTIONS, effective_comfy_url, preflight, upload_file  # noqa: E402

DEFAULT_OUT = ROOT / "test-results" / "blender-h3-fight"
SEED = 230924
PROMPT = (
    "[reference generation] [Shot 1] One continuous five-second photoreal live-action "
    "close two-person martial-arts practice on an outdoor running track. "
    "<Picture 1> defines exactly two adult performers: the man on screen left in a charcoal "
    "shirt, the woman on screen right in olive-brown training clothes, plus the red track, "
    "trees and daylight. Use it for identities, clothes, environment and photographic texture; "
    "its single frozen kick pose does not define the opening frame. "
    "Start with both people facing each other in a guarded stance. The man steps in with a "
    "left jab; the woman parries. He follows with a right straight punch; she slips low. "
    "She counters with one straight punch, then chambers her right knee and drives a "
    "waist-high side kick into his crossed forearm guard. He absorbs the contact and takes "
    "half a step back. She retracts the leg and both settle into guard. Every strike has "
    "preparation, extension, contact or parry, and recovery. Keep the two bodies distinct, "
    "consistent left-right screen positions, real human anatomy, feet and balance. "
    "A single camera gently tracks right and pushes closer around the exchange, no cuts. "
    "<Video 1> is the graybox choreography and camera guide: follow its exact order of "
    "punches, blocks, duck, counter, kick and recovery, and its framing, rhythm and camera "
    "direction. Replace all gray mannequin surfaces and plain gray floor with the real "
    "people, clothes and track from <Picture 1>. Controlled stunt sparring, no injury or blood. "
    "No extra people, frozen still image, gray CGI, duplicate limbs, text, dialogue or scene change."
)

PROMPT_UE = (
    "[reference generation] Photoreal live-action, five-second close martial-arts exchange "
    "between exactly two adult stunt performers on an outdoor red running track. "
    "<Picture 1> defines the real people, charcoal shirt for the man, olive-brown training "
    "clothes for the woman, trees, daylight and photographic texture. Its frozen kick pose "
    "does not define the first frame. <Video 1> is the UE Manny and Quinn skeletal "
    "animation and shot-by-shot camera guide; match its timing, choreography, screen "
    "direction, three camera cuts and framing while replacing the mannequins and gray "
    "studio with the people and running track from <Picture 1>. "
    "Shot 1, a tight diagonal tracking two-shot: guarded footwork, the man drives a jab "
    "and the woman parries and counters. Shot 2, a cut to an over-the-shoulder angle: "
    "he dips under her hook and comes back with a compact body punch; she covers. "
    "Shot 3, a cut to a low side angle and a short push-in: she chambers her knee, "
    "extends a waist-high side kick into his crossed forearm guard, holds one beat at "
    "contact, retracts and resets while he absorbs the strike and steps back. "
    "Keep anatomical limbs, one man and one woman, stable clothing and identities, "
    "physical weight transfer, preparation and recovery on every strike. Controlled "
    "stunt sparring, no injury, blood, extra people, gray CGI, text or scene change."
)

PROMPT_HUAJIA = (
    "[reference generation] A photoreal live-action five-second cinematic martial-arts "
    "exchange with exactly two characters from the same Chinese drama. "
    "<Picture 1> is Wu Nai, the elderly lean Chinese man with gray thinning hair, "
    "weathered face, worn light sleeveless shirt, dark trousers and black shoes. "
    "<Picture 2> is Sha Lili, the young Chinese woman with long dark brown hair, "
    "red satin camisole, black skirt, dark stockings and black heels. Preserve both "
    "specific faces, ages, hair and clothing throughout; do not make Wu Nai a young man "
    "or replace Sha Lili with the woman from any other reference. "
    "<Picture 3> gives the empty outdoor red running track, lane markings, green fence, "
    "trees, daylight and realistic location texture. Place the two characters there. "
    "<Video 1> is only the UE Manny/Quinn skeletal choreography, blocking and camera "
    "guide. Replace every mannequin and gray surface with these two characters and "
    "the track. Follow its three filmed shots and cuts: first a tight diagonal moving "
    "two-shot as Wu Nai steps in with a jab and Sha Lili parries and counters; second "
    "a cut to an over-the-shoulder angle as Wu Nai pivots, slips under a hook and "
    "returns a compact low counter; third a cut to a low side angle as Sha Lili "
    "chambers her knee and extends one waist-high side kick into Wu Nai's crossed "
    "forearm guard, then retracts while he takes a short step back. End with both "
    "in guard. Keep spatial continuity, preparation, contact, body weight and recovery "
    "clear. Dramatic choreographed stunt sparring, no injury, blood, extra people, "
    "gray CGI, duplicated limbs, studio white background, signs or text."
)

PROMPT_HUAJIA_PAIRED = (
    "[reference generation] Five-second photoreal Chinese drama fight, exactly two "
    "characters on an outdoor red running track. <Picture 1> is Wu Nai: keep the "
    "elderly lean Chinese man's recognizable aged face, gray thinning hair, worn "
    "light sleeveless shirt, dark pants and black shoes. <Picture 2> is Sha Lili: "
    "keep the young Chinese woman's recognizable face, long dark hair, red satin "
    "camisole, black skirt, dark stockings and black heels. <Picture 3> defines the "
    "empty running track, green fence, trees and daylight. These images define all "
    "appearance; never copy gray mannequin materials or the white studio. "
    "<Video 1> is a synchronized two-person fight and camera blocking guide. Follow "
    "the exact paired action beats and three camera angles: a diagonal close two-shot "
    "of Wu Nai stepping in with a short straight punch and Sha Lili parrying; cut to "
    "a shoulder-side close view as he throws a second punch, she slips and returns "
    "one compact counter while he lowers his guard; cut to a low side view as she "
    "chambers a knee and pushes one waist-level side kick into his crossed forearm "
    "guard, then retracts, he rocks back and both recover. Every move has visible "
    "preparation, readable contact, balance and recovery. Play this as controlled "
    "screen choreography suited to an older man and a woman wearing heels: compact "
    "technique and stable footing, no airborne acrobatics or head-height kicking. "
    "Keep both faces and costumes stable across the cuts. No extra actors, duplicated "
    "limbs, blood, injuries, text, gray CGI, or abrupt changes of location."
)

PROMPT_HUAJIA_CONTACT = (
    "[reference generation] Exactly two photoreal Chinese drama characters in one "
    "five-second choreographed fight on an outdoor red running track. "
    "<Picture 1> is Wu Nai's identity sheet: preserve the elderly Chinese man's "
    "weathered face, thinning gray hair, pale worn tank top and loose dark trousers. "
    "<Picture 2> is Sha Lili's identity sheet: preserve the young Chinese woman's "
    "recognizable face, long dark brown hair, red satin camisole, black skirt, sheer "
    "dark stockings and black heels. <Picture 3> is the exact shared-location and "
    "contact-composition reference: Wu Nai on the left, Sha Lili on the right, her "
    "side-kicking foot pressed firmly into his crossed forearm guard. It illustrates "
    "the climax only, not the opening frame. Preserve their identities, clothes, "
    "running-track location, close spacing and undeniable physical contact. "
    "<Video 1> gives the exact moving two-person choreography and three camera "
    "angles, not the visible mannequin look. Follow its order: diagonal close two-shot "
    "jab and parry; cut to a shoulder-side counterpunch and slip; cut to a low side "
    "angle around three seconds. At 3.4 seconds Sha Lili chambers one knee; at 3.75 "
    "to 4.1 seconds her kick lands squarely on Wu Nai's crossed forearms at the same "
    "distance and pose shown in <Picture 3>, compressing his guard and making him "
    "rock back. No visible gap between foot and arms. She retracts, both settle in "
    "guard by the end. Clear preparation, contact, recoil and stable feet; compact "
    "cinematic technique suitable for his age and her heels, no airborne acrobatics. "
    "No extra performers, identity swap, gray CGI, duplicate limbs, blood or text."
)


def build_graph(image_file: str | list[str], video_file: str, prompt: str = PROMPT) -> dict:
    image_files = [image_file] if isinstance(image_file, str) else image_file
    graph = build_minimax_h3_workflow(
        JobMode.MINIMAX_H3_R2V, prompt, image_files, dict(OPTIONS), SEED,
    )
    graph["18"] = {"class_type": "LoadVideo", "inputs": {"file": video_file}}
    graph["19"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["18", 0]}}
    graph["5"]["inputs"]["ref_videos.ref_video_0"] = ["19", 0]
    graph["14"]["inputs"]["filename_prefix"] = (
        "video/blender-h3-fight/huajia-contact-take-1" if prompt == PROMPT_HUAJIA_CONTACT
        else "video/blender-h3-fight/huajia-paired-take-1" if prompt == PROMPT_HUAJIA_PAIRED
        else "video/blender-h3-fight/huajia-take-1" if len(image_files) == 3
        else "video/blender-h3-fight/take-1"
    )
    return graph


def run(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    huajia = out.name.endswith("-huajia")
    contact = out.name == "blender-h3-fight-contact-huajia"
    image_paths = ([out / name for name in ("wu-nai-look.png", "sha-lili-look.png",
                                             "contact-reference.png" if contact else "track-clean.png")]
                   if huajia else [out / "fight-reference.png"])
    video_path = out / "blender-fight-preview.mp4"
    prompt = (PROMPT_HUAJIA_CONTACT if contact
              else PROMPT_HUAJIA_PAIRED if out.name == "blender-h3-fight-human-huajia"
              else PROMPT_HUAJIA if huajia
              else PROMPT_UE if out.name == "blender-h3-fight-ue" else PROMPT)
    for path in (*image_paths, video_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    base_url = effective_comfy_url()
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    with requests.Session() as session:
        manifest.update({
            "capability": preflight(session, base_url),
            "seed": SEED,
            "options": OPTIONS,
            "prompt": prompt,
            "appearance_references": [path.name for path in image_paths],
            "motion_reference": video_path.name,
        })
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        final_path = out / "h3-fight-take-1.mp4"
        if final_path.is_file() and manifest.get("result", {}).get("status") == "succeeded":
            print(f"已有成功视频：{final_path}")
            return
        folder = f"zly-ai-media/blender-h3-fight/{uuid.uuid4().hex[:12]}"
        uploaded_images = [upload_file(session, base_url, path, folder) for path in image_paths]
        uploaded_video = upload_file(session, base_url, video_path, folder)
        graph = build_graph(uploaded_images, uploaded_video, prompt)
        (out / "graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        start = time.monotonic()
        client = ComfyVideoClient(base_url)
        print(f"提交双人打斗 H3 到 {base_url}", flush=True)
        try:
            submitted, _, output = client.submit_and_wait(graph)
            final_path.write_bytes(client.download_output(output))
            manifest["result"] = {
                "status": "succeeded", "prompt_id": submitted["prompt_id"],
                "seconds": round(time.monotonic() - start, 2), "file": final_path.name,
            }
            print(f"成片：{final_path}")
        except Exception as error:
            manifest["result"] = {
                "status": "failed", "seconds": round(time.monotonic() - start, 2),
                "error": str(error),
            }
            raise
        finally:
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    run(args.output_dir.resolve())

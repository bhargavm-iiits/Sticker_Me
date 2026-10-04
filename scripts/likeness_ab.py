"""Fixed-seed local A/B evaluation; never mutates production graphs or packs.

Example: python -m scripts.likeness_ab --photo portrait.png --consent
A = former pipeline; B = larger dual references; C = B + retries/refine;
D = C + Q6 (default) or Q8; E adds geometry-preserving portrait shading.
Scores are advisory; inspect the contact sheets.
The engine must be idle, with no ordinary worker running during this benchmark.
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil
from PIL import Image, ImageDraw, ImageOps
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def baseline_prompt(intent, style, tone):
    from dataclasses import replace
    former_gestures = {"greeting": "raising one open hand and waving hello", "apology": "head slightly bowed and one hand over the heart", "congrats": "raising both fists in celebration with a few confetti pieces"}
    if intent.key in former_gestures:
        intent = replace(intent, gesture=former_gestures[intent.key])
    return (
        "Transform the person in the reference photo into one illustrated cartoon sticker. "
        "Faithfully preserve this specific person's face shape, facial features, hairstyle, skin tone and clothing colors. "
        "Keep the person's apparent age, gender and existing accessories exactly as shown in the reference. "
        "Do not invent new accessories or replace this person with a generic cartoon avatar. "
        "Style: clean 2D cartoon illustration, bold smooth outlines, simple flat colors, expressive face, sticker art. "
        "Mood: playful and energetic, expressive but friendly. "
        f"Change the facial expression to {intent.expression}. Change the pose to {intent.gesture}. "
        "Redraw the body and hands in this new pose; keep the same person. "
        "Show head, shoulders, upper torso and all requested hands completely with generous empty padding. "
        "One person only, anatomically plausible hands, plain solid white background. "
        "No text, captions, letters, logos, panels or duplicate people."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--consent", action="store_true", required=True)
    parser.add_argument("--variants", nargs="+", choices=list("ABCDE"), default=list("ABCDE"))
    parser.add_argument("--intents", nargs="+", default=["greeting", "laughter", "surprise"])
    parser.add_argument("--precision", choices=["Q6_K", "Q8_0"], default="Q6_K")
    parser.add_argument("--style", default="likeness")
    args = parser.parse_args()
    run = ROOT / "runtime" / "likeness-ab" / uuid4().hex
    os.environ["STICKERME_DATA_DIR"] = str(run)
    # Import only after relocation, keeping application data untouched.
    from backend.app import config, db, imaging, likeness, comfy, worker
    # A-E are explicitly drawn-route experiments, independent of production defaults.
    config.PHOTO_EDIT = False
    from backend.app.catalog import INTENT_BY_KEY, STYLES
    from scripts.services import service_alive
    imaging.U2NET_HOME = ROOT / "runtime" / "models"
    if args.style not in STYLES or any(key not in INTENT_BY_KEY for key in args.intents):
        parser.error("Unknown style or intent")
    production_record = ROOT / "runtime" / "services.json"
    if production_record.exists():
        owned = json.loads(production_record.read_text(encoding="utf-8"))
        if "worker" in owned and service_alive(owned["worker"]):
            raise RuntimeError("Stop the ordinary worker before benchmarking; it shares this GPU.")
    db.init_db()
    adapter = comfy.ComfyEngine(db.engine)
    def idle():
        queue = adapter.request("GET", "/queue").json()
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise RuntimeError("Engine is busy; benchmark will not submit images.")
    idle()
    raw_photo = args.photo.read_bytes()
    image = imaging.normalize_upload(raw_photo)
    face = imaging.face_reference(image)
    feature = likeness.embedding(image)
    if feature is None: raise ValueError("No usable reference face")
    body = imaging.body_reference(image)
    original_workflow, original_prompt = comfy.workflow, comfy.artwork_prompt
    original_upload = adapter.upload
    results = []
    try:
        for variant in args.variants:
            idle()
            config.FACE_REFINE = variant in {"C", "D", "E"}
            config.LIKENESS_RETRIES = 1 if variant in {"C", "D", "E"} else 0
            config.PORTRAIT_RENDER = variant == "E"
            model = f"flux-2-klein-4b-{args.precision}.gguf" if variant in {"D", "E"} else "flux-2-klein-4b-Q4_K_M.gguf"
            if not (ROOT / "runtime" / "comfyui" / "models" / "unet" / model).exists():
                raise RuntimeError(f"Model missing: {model}. Install this precision before benchmarking.")
            def graph_for_stage(stage, values):
                if variant == "A":
                    graph = json.loads((ROOT / "workflows" / "klein4b-baseline-api.json").read_text())
                    for key, field, value in [("4", "image", values["face"]), ("6", "text", values["prompt"]), ("10", "noise_seed", values["seed"]), ("16", "filename_prefix", values["prefix"])]:
                        graph[key]["inputs"][field] = value
                else:
                    graph = original_workflow(stage, values)
                graph["1"]["inputs"]["unet_name"] = model
                return graph
            comfy.workflow = graph_for_stage
            comfy.artwork_prompt = baseline_prompt if variant == "A" else original_prompt
            def upload(source, name):
                if variant == "A" and name.endswith("-face.png"):
                    with Image.open(io.BytesIO(raw_photo)) as original:
                        old_image = ImageOps.exif_transpose(original).convert("RGB")
                        old_image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                        source = ImageOps.pad(old_image, (512, 512), color="white", method=Image.Resampling.LANCZOS)
                return original_upload(source, name)
            adapter.upload = upload
            pack_id, job_id = str(uuid4()), str(uuid4())
            with Session(db.engine) as session:
                pack = db.Pack(id=pack_id, name=f"Likeness {variant}", language="en", mode="cartoon", style=args.style, tone="playful", status="processing")
                pack.jobs.append(db.Job(id=job_id, kind="benchmark", state="running", total=len(args.intents)))
                for index, key in enumerate(args.intents):
                    intent = INTENT_BY_KEY[key]
                    pack.stickers.append(db.Sticker(id=str(uuid4()), position=index, intent=key, emoji=intent.emoji, caption="", seed=20261003 + index))
                session.add(pack)
                session.commit()
                targets = [(s.id, s.intent, s.seed) for s in pack.stickers]
            directory = config.pack_dir(pack_id)
            for name, source in (("reference.png", image), ("face.png", face), ("body.png", body)):
                imaging.save_png(source, directory / name)
            likeness.save_embedding(feature, directory / "face-embedding.npy")
            samples, stopped = [], threading.Event()
            def monitor():
                while not stopped.wait(2):
                    try:
                        memory = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True, creationflags=0x08000000)
                        samples.append({"vram_mib": int(memory.splitlines()[0]), "ram_gib": psutil.virtual_memory().used / 1024**3})
                    except (OSError, subprocess.SubprocessError, ValueError): pass
            thread = threading.Thread(target=monitor, daemon=True)
            thread.start()
            row = {"variant": variant, "model": model, "pack_id": pack_id, "results": []}
            sheet = Image.new("RGB", (256 * (len(targets) + 1), 290), "#ede8f5")
            sheet.paste(face.resize((256, 256)), (0, 0))
            draw = ImageDraw.Draw(sheet)
            draw.text((12, 265), "REFERENCE FACE", fill="black")
            try:
                for index, (sticker_id, key, seed) in enumerate(targets, 1):
                    idle()
                    started = time.monotonic()
                    artwork, score, chosen_seed, note = worker.generate_likeness(adapter, job_id, sticker_id, pack_id, key, args.style, "playful", seed, 1)
                    path = directory / f"{key}.png"
                    imaging.save_png(artwork, path)
                    sheet.paste(artwork.resize((256, 256)), (index * 256, 0))
                    draw.text((index * 256 + 10, 263), f"{key}: {score:.3f}" if score is not None else f"{key}: manual", fill="black")
                    item = {"intent": key, "seconds": round(time.monotonic() - started, 2), "likeness_score": score, "seed": seed, "chosen_seed": chosen_seed, "note": note, "path": str(path)}
                    row["results"].append(item)
                    (run / "partial.json").write_text(json.dumps({"finished": results, "current": row}, indent=2))
                    print(json.dumps({"variant": variant, **item}), flush=True)
            finally:
                stopped.set()
                thread.join(timeout=5)
            row["peak_sampled_vram_mib"] = max((s["vram_mib"] for s in samples), default=None)
            row["peak_sampled_system_ram_gib"] = max((s["ram_gib"] for s in samples), default=None)
            row["contact_sheet"] = str(run / f"{variant}-contact-sheet.png")
            scores = [r["likeness_score"] for r in row["results"] if r["likeness_score"] is not None]
            row["median_likeness"] = float(np.median(scores)) if scores else None
            imaging.save_png(sheet, run / f"{variant}-contact-sheet.png")
            results.append(row)
            (run / "result.json").write_text(json.dumps({"photo_sha256": hashlib.sha256(raw_photo).hexdigest(), "results": results}, indent=2))
            with Session(db.engine) as session:
                session.get(db.Job, job_id).state = "done"
                session.get(db.Pack, pack_id).status = "ready"
                session.commit()
    finally:
        comfy.workflow, comfy.artwork_prompt = original_workflow, original_prompt
        adapter.close()
    print(f"Results: {run / 'result.json'}", flush=True)


if __name__ == "__main__":
    main()

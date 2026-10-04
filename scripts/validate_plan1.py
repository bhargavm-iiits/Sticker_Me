"""Isolated, staged GPU validation. Never approves stickers automatically.

python -m scripts.validate_plan1 --style cartoon --create
python -m scripts.validate_plan1 --select-design 0
python -m scripts.validate_plan1 --review greeting laughter surprise --continue-pack
Inspect saved artwork/contact sheets before each explicit review step.
"""
import argparse
import io
import json
import os
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=ROOT / "runtime" / "plan1-validation")
    parser.add_argument("--style", choices=["realistic", "likeness", "cartoon", "chibi", "comic"], default="cartoon")
    parser.add_argument("--photo", type=Path)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--select-design", type=int, choices=[0, 1])
    parser.add_argument("--review", nargs="*", default=[])
    parser.add_argument("--continue-pack", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--generate-all-unreviewed", action="store_true", help="Generate remaining reactions for QA without accepting any artwork")
    parser.add_argument("--tone", choices=["playful", "warm", "dramatic"], default="playful")
    parser.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args()
    args.run = args.run.resolve()
    if not args.run.is_relative_to(ROOT / "runtime"):
        parser.error("Validation data must stay under this workspace's runtime directory")
    os.environ["STICKERME_DATA_DIR"] = str(args.run)
    from fastapi.testclient import TestClient
    from PIL import Image, ImageDraw
    from skimage.data import astronaut
    from backend.app import imaging, worker
    from backend.app import db
    from sqlalchemy.orm import Session
    from backend.app.main import app
    from backend.app.comfy import ComfyEngine
    imaging.U2NET_HOME = ROOT / "runtime" / "models"
    adapter = ComfyEngine()
    queue = adapter.request("GET", "/queue").json()
    adapter.close()
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("Engine is busy; no GPU validation submitted")
    args.run.mkdir(parents=True, exist_ok=True)
    state_path = args.run / "pack.json"
    with TestClient(app) as client:
        if args.create:
            if state_path.exists():
                raise RuntimeError("Run already has a pack; use another --run directory")
            if args.photo:
                raw = args.photo.read_bytes()
            else:
                buffer = io.BytesIO()
                Image.fromarray(astronaut()).save(buffer, "PNG")
                raw = buffer.getvalue()
            response = client.post("/api/packs", files={"photo": ("sample.png", raw, "image/png")},
                                   data={"style": args.style, "tone": args.tone, "consent": "true", "name": "Plan 1 validation"})
            response.raise_for_status()
            state = response.json()
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            with Session(db.engine) as session:
                pack = session.get(db.Pack, state["id"])
                for sticker in pack.stickers:
                    sticker.seed = args.seed + sticker.position
                if pack.jobs[-1].kind == "design":
                    payload = json.loads(pack.jobs[-1].payload)
                    payload["seeds"] = [args.seed + 1000, args.seed + 1001]
                    pack.jobs[-1].payload = json.dumps(payload)
                session.commit()
            worker.run_once()
        else:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        pack_id = state["id"]
        if args.select_design is not None:
            response = client.post(f"/api/packs/{pack_id}/design", json={"candidate": args.select_design})
            response.raise_for_status()
            worker.run_once()
        state = client.get(f"/api/packs/{pack_id}").json()
        for sticker in state["stickers"]:
            if sticker["intent"] in args.review:
                client.post(f"/api/packs/{pack_id}/stickers/{sticker['id']}/review").raise_for_status()
        if args.generate_all_unreviewed:
            if state["status"] != "awaiting_approval":
                raise RuntimeError("Generate previews and inspect them before the full QA run")
            with Session(db.engine) as session:
                pack = session.get(db.Pack, pack_id)
                targets = [s.id for s in pack.stickers if s.status != "ready"]
                if targets:
                    pack.jobs.append(db.Job(id=str(uuid4()), kind="benchmark", total=len(targets), payload=json.dumps({"sticker_ids": targets})))
                    pack.status = "processing"
                    session.commit()
            if targets:
                worker.run_once()
        if args.continue_pack:
            client.post(f"/api/packs/{pack_id}/approve").raise_for_status()
            worker.run_once()
        state = client.get(f"/api/packs/{pack_id}").json()
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        directory = args.run / "packs" / pack_id
        tiles = [(directory / "face.png", "Original photo")]
        tiles += [(directory / f"design-{d['candidate']}.png", f"Design {d['candidate']}") for d in state["designs"]]
        tiles += [(directory / f"{s['id']}.png", f"{s['intent']} / {s['quality_status']}") for s in state["stickers"] if s["image_url"]]
        columns = 4
        sheet = Image.new("RGB", (256 * columns, 290 * ((len(tiles) + columns - 1) // columns)), "#ede8f5")
        draw = ImageDraw.Draw(sheet)
        for index, (path, label) in enumerate(tiles):
            with Image.open(path) as original:
                tile = original.convert("RGBA")
                tile.thumbnail((256, 256), Image.Resampling.LANCZOS)
            x, y = index % columns * 256, index // columns * 290
            sheet.paste(tile, (x + (256 - tile.width) // 2, y), tile)
            draw.text((x + 6, y + 265), label, fill="black")
        imaging.save_png(sheet, args.run / "contact-sheet.png")
        if args.export:
            response = client.get(f"/api/packs/{pack_id}/export")
            response.raise_for_status()
            (args.run / "export.zip").write_bytes(response.content)
        print(json.dumps({"status": state["status"], "error": state["error"], "pack_id": pack_id,
                          "contact_sheet": str(args.run / "contact-sheet.png")}), flush=True)
        if state["status"] == "failed":
            raise RuntimeError(state["error"])


if __name__ == "__main__":
    main()

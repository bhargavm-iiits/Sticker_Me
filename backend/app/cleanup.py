from .config import ROOT


def engine_assets(pack_id: str, attempt_ids: list[str]):
    from uuid import UUID

    try:
        if str(UUID(pack_id)) != pack_id:
            return
    except ValueError:
        return
    directory = ROOT / "runtime" / "comfyui"
    (directory / "input" / "StickerMe" / f"{pack_id}.png").unlink(missing_ok=True)
    for suffix in ("face", "body", "canvas", "face-clean"):
        (directory / "input" / "StickerMe" / f"{pack_id}-{suffix}.png").unlink(missing_ok=True)
    engine_attempt_assets(attempt_ids)


def engine_attempt_assets(attempt_ids: list[str]):
    from uuid import UUID

    directory = ROOT / "runtime" / "comfyui"
    for attempt_id in attempt_ids:
        try:
            valid = str(UUID(attempt_id)) == attempt_id
        except ValueError:
            valid = False
        if not valid:
            continue
        (directory / "input" / "StickerMe" / f"{attempt_id}-crop.png").unlink(missing_ok=True)
        (directory / "input" / "StickerMe" / f"{attempt_id}-design.png").unlink(missing_ok=True)
        for path in (directory / "output" / "StickerMe").glob(f"{attempt_id}_*.png"):
            path.unlink(missing_ok=True)

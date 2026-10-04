"""Expression transfer with LivePortrait; runs in the engine environment (torch).

The person's own photo is warped, never redrawn: canonical keypoints (face shape),
head pose, scale and appearance features come from the source crop; only the
expression deformation comes from the driver.

Usage: python scripts/liveportrait_runner.py request.json
request = {"device": "auto"|"cuda"|"cpu", "jobs": [{"source", "driver", "reference"?, "output", "multiplier"?}]}
All crops are 512x512 RGB images framed identically (the app crops them).
"""
import json
import hashlib
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LIVEPORTRAIT = ROOT / "runtime" / "liveportrait"
sys.path.insert(0, str(LIVEPORTRAIT))

from src.modules.appearance_feature_extractor import AppearanceFeatureExtractor  # noqa: E402
from src.modules.motion_extractor import MotionExtractor  # noqa: E402
from src.modules.spade_generator import SPADEDecoder  # noqa: E402
from src.modules.stitching_retargeting_network import StitchingRetargetingNetwork  # noqa: E402
from src.modules.warping_network import WarpingNetwork  # noqa: E402
from src.utils.camera import get_rotation_matrix, headpose_pred_to_degree  # noqa: E402


def checkpoint(name: str):
    return torch.load(LIVEPORTRAIT / "weights" / name, map_location="cpu", weights_only=True)


def without_ddp_prefix(state: dict) -> dict:
    return {key.removeprefix("module."): value for key, value in state.items()}


class PortraitAnimator:
    def __init__(self, device: str):
        params = yaml.safe_load((LIVEPORTRAIT / "src" / "config" / "models.yaml").read_text(encoding="utf-8"))["model_params"]
        self.device = device
        self.half = device.startswith("cuda")

        def load(model, name):
            model.load_state_dict(checkpoint(name))
            return model.to(device).eval()

        self.appearance = load(AppearanceFeatureExtractor(**params["appearance_feature_extractor_params"]), "appearance_feature_extractor.pth")
        self.motion = load(MotionExtractor(**params["motion_extractor_params"]), "motion_extractor.pth")
        self.warping = load(WarpingNetwork(**params["warping_module_params"]), "warping_module.pth")
        self.generator = load(SPADEDecoder(**params["spade_generator_params"]), "spade_generator.pth")
        stitcher = StitchingRetargetingNetwork(**params["stitching_retargeting_module_params"]["stitching"])
        stitcher.load_state_dict(without_ddp_prefix(checkpoint("stitching_retargeting_module.pth")["retarget_shoulder"]))
        self.stitcher = stitcher.to(device).eval()
        self.source_cache = None

    def autocast(self):
        return torch.autocast(device_type="cuda", dtype=torch.float16, enabled=self.half) if self.half else torch.autocast(device_type="cpu", enabled=False)

    def prepare(self, path: str) -> torch.Tensor:
        with Image.open(path) as image:
            array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        tensor = torch.from_numpy(array).permute(2, 0, 1)[None].to(self.device)
        return F.interpolate(tensor, size=(256, 256), mode="bilinear", align_corners=False).clamp(0, 1)

    @torch.no_grad()
    def keypoints(self, image: torch.Tensor) -> dict:
        with self.autocast():
            info = self.motion(image)
        info = {key: value.float() for key, value in info.items()}
        for key in ("pitch", "yaw", "roll"):
            info[key] = headpose_pred_to_degree(info[key])[:, None]
        info["kp"] = info["kp"].reshape(1, -1, 3)
        info["exp"] = info["exp"].reshape(1, -1, 3)
        info["R"] = get_rotation_matrix(info["pitch"], info["yaw"], info["roll"])
        return info

    @staticmethod
    def place(info: dict, expression: torch.Tensor) -> torch.Tensor:
        points = info["scale"][..., None] * (info["kp"] @ info["R"] + expression)
        points[..., :2] += info["t"][:, None, :2]
        return points

    @torch.no_grad()
    def animate(self, source: str, driver: str, reference: str | None, multiplier: float) -> Image.Image:
        source_key = hashlib.sha256(Path(source).read_bytes()).digest()
        if self.source_cache is None or self.source_cache[0] != source_key:
            source_image = self.prepare(source)
            source_info = self.keypoints(source_image)
            with self.autocast():
                features = self.appearance(source_image).float()
            self.source_cache = (source_key, source_info, features)
        _, source_info, features = self.source_cache
        driver_info = self.keypoints(self.prepare(driver))
        reference_info = self.keypoints(self.prepare(reference)) if reference else source_info
        source_points = self.place(source_info, source_info["exp"])
        # Relative expression: cancels whatever the driver shares with its reference (identity drift),
        # leaving only the change of expression, applied to the person's own keypoints.
        expression = source_info["exp"] + (driver_info["exp"] - reference_info["exp"]) * multiplier
        driving_points = self.place(source_info, expression)
        delta = self.stitcher(torch.cat([source_points.view(1, -1), driving_points.view(1, -1)], dim=1))
        count = source_points.shape[1]
        driving_points = driving_points + delta[..., : 3 * count].reshape(1, count, 3)
        driving_points[..., :2] += delta[..., 3 * count : 3 * count + 2].reshape(1, 1, 2)
        with self.autocast():
            warped = self.warping(features, kp_source=source_points, kp_driving=driving_points)
            output = self.generator(feature=warped["out"])
        array = (output.float()[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy() * 255).round().astype(np.uint8)
        return Image.fromarray(array)


def pick_device(requested: str) -> str:
    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        free, _ = torch.cuda.mem_get_info()
        if free >= 1.5 * 1024**3:
            return "cuda"
    return "cpu"


def execute(request, animator):
    results = []
    for job in request["jobs"]:
        image = animator.animate(job["source"], job["driver"], job.get("reference"), float(job.get("multiplier", 1.0)))
        output = Path(job["output"])
        temporary = output.with_name(f".{output.name}.tmp.png")
        image.save(temporary)
        temporary.replace(output)
        results.append(str(output))
    return {"device": animator.device, "outputs": results}


def main() -> None:
    if sys.argv[1] == "--serve":
        # CPU residency leaves the laptop GPU free for the next Klein request.
        animator = PortraitAnimator("cpu")
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if request.get("shutdown"):
                    break
                result = execute(request, animator)
            except Exception as exc:
                result = {"error": str(exc)}
            print(json.dumps(result), flush=True)
    else:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        animator = PortraitAnimator(pick_device(request.get("device", "auto")))
        print(json.dumps(execute(request, animator)), flush=True)


if __name__ == "__main__":
    main()

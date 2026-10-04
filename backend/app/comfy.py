import hashlib
import io
import json
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .catalog import INTENT_BY_KEY, artwork_prompt, expression_driver_prompt, face_refine_prompt, gesture_edit_prompt, design_prompt
from .db import JobAttempt
from .likeness import ensure_photo_references, ensure_references


class GenerationCancelled(RuntimeError):
    pass


class SubmissionUncertain(RuntimeError):
    pass


def workflow(name: str, values: dict) -> dict:
    path = config.WORKFLOW_PATH if name != "face" else config.WORKFLOW_PATH.with_name("klein4b-face-api.json")
    graph = json.loads(path.read_text(encoding="utf-8"))
    bindings = json.loads(path.with_name("bindings.json" if name != "face" else "bindings-face.json").read_text(encoding="utf-8"))
    for name, value in values.items():
        node, field = bindings[name]
        graph[node]["inputs"][field] = value
    return graph


class ComfyEngine:
    def __init__(self, database=None, transport=None):
        if urlparse(config.COMFY_URL).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("The generation engine must run on localhost")
        self.database = database
        self.client = httpx.Client(base_url=config.COMFY_URL, timeout=30, transport=transport, trust_env=False)

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 500:
            response.raise_for_status()
        if response.is_error:
            raise RuntimeError(f"ComfyUI {path}: {response.text[:1200]}")
        return response

    def doctor(self) -> dict:
        try:
            stats = self.request("GET", "/system_stats").json()
            nodes = self.request("GET", "/object_info").json()
            missing = []
            graphs = [json.loads(path.read_text(encoding="utf-8")) for path in (config.WORKFLOW_PATH, config.WORKFLOW_PATH.with_name("klein4b-face-api.json"))]
            for node in [node for graph in graphs for node in graph.values()]:
                kind = node["class_type"]
                if kind not in nodes:
                    missing.append(kind)
                    continue
                required = nodes[kind]["input"]["required"]
                for key in ("unet_name", "clip_name", "vae_name", "type"):
                    value = node["inputs"].get(key)
                    choices = required.get(key, [None])[0]
                    if value and isinstance(choices, list) and value not in choices:
                        missing.append(f"{kind}.{key}: {value}")
            for name in ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"):
                if not (config.FACE_MODELS_DIR / name).is_file(): missing.append(f"Face model missing: {name}")
            return {"ready": not missing, "error": ", ".join(sorted(set(missing))) or None, "devices": stats.get("devices", []), "url": config.COMFY_URL, "face_models": not any("Face model" in item for item in missing)}
        except (httpx.HTTPError, RuntimeError, KeyError, OSError) as exc:
            return {"ready": False, "error": str(exc), "url": config.COMFY_URL}

    def upload(self, image: Image.Image, name: str) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result = self.request("POST", "/upload/image", files={"image": (name, buffer.getvalue(), "image/png")}, data={"subfolder": "StickerMe", "overwrite": "true"}).json()
        return f"{result.get('subfolder', '')}/{result['name']}".lstrip("/")

    def queued(self, prompt_id: str):
        queue = self.request("GET", "/queue").json()
        for entry in queue.get("queue_running", []) + queue.get("queue_pending", []):
            if entry[1] == prompt_id:
                return entry
        return None

    def cancel(self, prompt_id: str, attempt_id: str) -> None:
        entry = self.queued(prompt_id)
        if entry is None or entry[3].get("stickerme_attempt") != attempt_id:
            return
        self.request("POST", "/queue", json={"delete": [prompt_id]})
        self.request("POST", "/interrupt", json={"prompt_id": prompt_id})
        deadline = time.monotonic() + 180
        while self.queued(prompt_id) is not None:
            if time.monotonic() > deadline:
                raise RuntimeError("Engine has not acknowledged cancellation; cleanup will reconnect before deletion")
            time.sleep(0.25)

    def set_attempt(self, attempt_id: str, state: str, error: str | None = None):
        with Session(self.database) as session:
            attempt = session.get(JobAttempt, attempt_id)
            if attempt:
                attempt.state, attempt.error = state, error
                session.commit()

    def generate(self, job_id: str, sticker_id: str, pack_id: str, intent: str, style: str, tone: str, seed: int, active, *, stage="pose", candidate=0, inputs=None, render_style=None, route="draw") -> Image.Image:
        """route "draw": references → new picture. route "photo": edit the real photo; the pose
        stage changes only arms/hands, the face stage draws an expression driver for LivePortrait."""
        if stage not in {"pose", "face", "design"} or route not in {"draw", "photo"}:
            raise ValueError("Unknown generation stage")
        with Session(self.database) as session:
            attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id, JobAttempt.sticker_id == sticker_id, JobAttempt.stage == stage, JobAttempt.candidate == candidate, JobAttempt.state.not_in(["failed", "cancelled", "abandoned"])).order_by(JobAttempt.created_at.desc()).limit(1))
            if attempt is None:
                if not active():
                    raise GenerationCancelled("Generation cancelled")
                face_path, body_path = ensure_references(pack_id)
                attempt_id, prompt_id = str(uuid4()), str(uuid4())
                # Register crop ownership before any engine upload, so an
                # interrupted upload cannot leave a crop without a cleanup key.
                attempt = JobAttempt(id=attempt_id, job_id=job_id, sticker_id=sticker_id, stage=stage, candidate=candidate, prompt_id=prompt_id, workflow="{}", reference_hash=hashlib.sha256(face_path.read_bytes() + body_path.read_bytes()).hexdigest())
                session.add(attempt)
                session.commit()
            if attempt.state == "prepared" and attempt.workflow == "{}":
                try:
                    face_path, body_path = ensure_references(pack_id)
                    with Image.open(face_path) as source:
                        face_image = source.convert("RGB")
                    if route == "photo":
                        canvas_path, clean_path = ensure_photo_references(pack_id)
                        with Image.open(clean_path) as source:
                            second = self.upload(source.convert("RGB"), f"{pack_id}-face-clean.png")
                        if stage == "face":
                            if not inputs or "crop" not in inputs:
                                raise ValueError("The expression driver requires a face crop")
                            first = self.upload(inputs["crop"], f"{attempt.id}-crop.png")
                            prompt = expression_driver_prompt(INTENT_BY_KEY[intent], tone)
                            buffer = io.BytesIO()
                            inputs["crop"].save(buffer, format="PNG")
                            first_bytes = buffer.getvalue()
                        else:
                            with Image.open(canvas_path) as source:
                                first = self.upload(source.convert("RGB"), f"{pack_id}-canvas.png")
                            if config.PHOTO_ANIMATION:
                                prompt = gesture_edit_prompt(INTENT_BY_KEY[intent], tone)
                            else:
                                from .catalog import photo_reaction_prompt
                                prompt = photo_reaction_prompt(INTENT_BY_KEY[intent], tone, (inputs or {}).get('intensity', 1.0))
                            first_bytes = canvas_path.read_bytes()
                        attempt.reference_hash = hashlib.sha256(first_bytes + clean_path.read_bytes()).hexdigest()
                    elif stage == "face":
                        if not inputs or "crop" not in inputs:
                            raise ValueError("Face refinement requires an artwork crop")
                        first = self.upload(inputs["crop"], f"{attempt.id}-crop.png")
                        second = self.upload(face_image, f"{pack_id}-face.png")
                        prompt = face_refine_prompt(INTENT_BY_KEY[intent], style)
                        buffer = io.BytesIO()
                        inputs["crop"].save(buffer, format="PNG")
                        attempt.reference_hash = hashlib.sha256(buffer.getvalue() + face_path.read_bytes()).hexdigest()
                    else:
                        first = self.upload(face_image, f"{pack_id}-face.png")
                        with Image.open(body_path) as source:
                            second = self.upload(source.convert("RGB"), f"{pack_id}-body.png")
                        prompt = design_prompt(style) if stage == "design" else artwork_prompt(INTENT_BY_KEY[intent], style, tone)
                    if inputs and inputs.get("correction"):
                        prompt += " " + inputs["correction"]
                    graph = workflow(stage, {"face": first, "body": second, "prompt": prompt, "seed": seed, "prefix": f"StickerMe/{attempt.id}"})
                    if inputs and "design" in inputs and stage in {"pose", "face"}:
                        design = self.upload(inputs["design"], f"{attempt.id}-design.png")
                        graph["20"] = {"class_type": "LoadImage", "inputs": {"image": design}}
                        graph["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["3", 0]}}
                        graph["22"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["19", 0], "latent": ["21", 0]}}
                        graph["13"]["inputs"]["positive"] = ["22", 0]
                        graph["8"]["inputs"]["conditioning"] = ["22", 0]
                        graph["6"]["inputs"]["text"] += " Image 3 is the approved character design: match its line work, shading, palette and character features."
                        graph["6"]["inputs"]["text"] += (" Image 2 remains the original identity reference. Image 1 defines the current expression and head geometry; preserve these while refining resemblance."
                                                            if stage == "face" else " Images 1 and 2 remain the original identity and clothing references.")
                        attempt.reference_hash = hashlib.sha256(attempt.reference_hash.encode() + inputs["design"].tobytes()).hexdigest()
                    if render_style:
                        graph["16"]["_meta"] = {"title": "SaveImage", "stickerme_render_style": render_style, "stickerme_renderer": "portrait-shading-v1"}
                    graph["16"].setdefault("_meta", {"title": "SaveImage"}).update(
                        stickerme_route="original-photo-face-v3" if route == "photo" else "approved-cartoon-v2" if inputs and "design" in inputs else "draw-v2",
                        stickerme_style=style, stickerme_tone=tone, stickerme_seed=seed,
                        stickerme_workflow_sha256=hashlib.sha256((config.WORKFLOW_PATH if stage != "face" else config.WORKFLOW_PATH.with_name("klein4b-face-api.json")).read_bytes()).hexdigest())
                    from .provenance import models
                    graph["16"]["_meta"]["stickerme_models"] = models(graph)
                    graph["16"]["_meta"]["stickerme_intent"] = intent
                    graph["16"]["_meta"]["stickerme_stage"] = stage
                    graph["16"]["_meta"]["stickerme_expression_strength"] = 0 if route == 'photo' and not config.PHOTO_ANIMATION else config.EXPRESSION_STRENGTH
                    if route == "photo":
                        graph["16"]["_meta"]["stickerme_route"] = "photo-edit+original-face-v3" if config.PHOTO_ANIMATION else "coherent-photo-edit-v4"
                    attempt.workflow = json.dumps(graph)
                    session.commit()
                except Exception as exc:
                    attempt.state, attempt.error = "failed", str(exc)
                    session.commit()
                    raise
            attempt_id, prompt_id, state, graph = attempt.id, attempt.prompt_id, attempt.state, json.loads(attempt.workflow)
        history = self.request("GET", f"/history/{prompt_id}").json().get(prompt_id)
        entry = self.queued(prompt_id)
        if state == "uncertain" or (state in {"submitting", "submitted", "completed"} and not history and not entry):
            message = "Engine has no record of the submitted image. Resume explicitly to allow a new attempt."
            self.set_attempt(attempt_id, "uncertain", message)
            raise SubmissionUncertain(message)
        if not history and not entry:
            if not active():
                raise GenerationCancelled("Generation cancelled")
            self.set_attempt(attempt_id, "submitting")
            try:
                result = self.request("POST", "/prompt", json={"prompt": graph, "prompt_id": prompt_id, "client_id": "StickerMe", "extra_data": {"stickerme_attempt": attempt_id, "stickerme_job": job_id}}).json()
                if result.get("prompt_id") != prompt_id:
                    raise SubmissionUncertain("Engine did not preserve the requested prompt ID")
            except httpx.HTTPError as exc:
                self.set_attempt(attempt_id, "uncertain", str(exc))
                raise SubmissionUncertain("Submission connection failed. Resume explicitly after checking engine status.") from exc
            except SubmissionUncertain as exc:
                self.set_attempt(attempt_id, "uncertain", str(exc))
                raise
            except RuntimeError as exc:
                self.set_attempt(attempt_id, "failed", str(exc))
                raise
            self.set_attempt(attempt_id, "submitted")
        deadline = time.monotonic() + 3600
        disconnected_since = None
        while not history:
            if not active():
                self.cancel(prompt_id, attempt_id)
                self.set_attempt(attempt_id, "cancelled")
                raise GenerationCancelled("Generation cancelled; completed stickers are retained")
            if time.monotonic() > deadline:
                self.cancel(prompt_id, attempt_id)
                self.set_attempt(attempt_id, "cancelled", "Generation exceeded one hour")
                raise RuntimeError("Generation exceeded one hour; inspect runtime/comfyui/engine.log")
            try:
                history = self.request("GET", f"/history/{prompt_id}").json().get(prompt_id)
                if not history and self.queued(prompt_id) is None:
                    self.set_attempt(attempt_id, "uncertain", "Prompt disappeared from engine")
                    raise SubmissionUncertain("Prompt disappeared from engine. Resume explicitly.")
                disconnected_since = None
            except httpx.HTTPError:
                disconnected_since = disconnected_since or time.monotonic()
                if time.monotonic() - disconnected_since > 60:
                    raise RuntimeError("Engine disconnected; restart it and resume to reconnect to this image")
            if not history:
                time.sleep(1)
        status = history.get("status", {})
        if status.get("status_str") == "error":
            errors = [str(message[1].get("exception_message", message[1])) for message in status.get("messages", []) if message[0] in {"execution_error", "execution_interrupted"}]
            message = "Engine generation failed: " + "; ".join(errors)
            self.set_attempt(attempt_id, "failed", message)
            raise RuntimeError(message)
        output_node = json.loads(config.WORKFLOW_PATH.with_name("bindings.json" if stage != "face" else "bindings-face.json").read_text(encoding="utf-8"))["output"]
        images = history.get("outputs", {}).get(output_node, {}).get("images", [])
        if not images:
            self.set_attempt(attempt_id, "failed", "No generated output")
            raise RuntimeError("Engine returned no generated image")
        data = self.request("GET", "/view", params=images[0]).content
        with Image.open(io.BytesIO(data)) as image:
            result = image.convert("RGB")
        self.set_attempt(attempt_id, "completed")
        return result


def engine_doctor() -> dict:
    adapter = ComfyEngine()
    try:
        return adapter.doctor()
    finally:
        adapter.close()

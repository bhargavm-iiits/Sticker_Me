import argparse
import json
import subprocess
import sys
import time
from datetime import datetime

import httpx
import psutil

from backend.app import config
from backend.app.db import init_db


RECORD = config.DATA_DIR / "services.json"


def records():
    return json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}


def owned(record):
    try:
        process = psutil.Process(record["pid"])
        return process if abs(process.create_time() - record["created"]) < 1 and process.exe().lower() == record["executable"].lower() else None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def process_record(process):
    return {"pid": process.pid, "created": process.create_time(), "executable": process.exe()}


def service_alive(record):
    return bool(owned(record) or any(owned(child) for child in record.get("children", [])))


def descendants(process):
    try:
        command = process.cmdline()[1:]
        return [process_record(child) for child in process.children(recursive=True) if child.create_time() >= process.create_time() and child.cmdline()[1:] == command]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def stop_owned(record):
    process = owned(record)
    children = record.get("children", []) + (descendants(process) if process else [])
    seen = set()
    for child_record in children:
        child = owned(child_record)
        if child and child.pid not in seen:
            seen.add(child.pid)
            child.terminate()
            try:
                child.wait(timeout=10)
            except psutil.TimeoutExpired:
                child.kill()
    if process and process.is_running():
        try:
            process.terminate()
            process.wait(timeout=10)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            process.kill()


def save(info):
    temporary = RECORD.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(info, indent=2), encoding="utf-8")
    temporary.replace(RECORD)


def launch(name, command, info):
    with (config.DATA_DIR / f"{name}.log").open("ab") as logfile:
        process = subprocess.Popen(command, cwd=config.ROOT, stdout=logfile, stderr=logfile, creationflags=0x08000000)
    details = psutil.Process(process.pid)
    info[name] = process_record(details)
    save(info)
    time.sleep(0.1)
    info[name]["children"] = descendants(details)
    save(info)
    return process


def engine_ready():
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get(config.COMFY_URL + "/system_stats")
            return response.is_success and "devices" in response.json()
    except (httpx.HTTPError, ValueError):
        return False


def start(engine_only=False):
    config.ensure_directories()
    init_db()
    stop_legacy_worker()
    info = {name: record for name, record in records().items() if service_alive(record)}
    if not engine_ready():
        if config.COMFY_URL != "http://127.0.0.1:8188":
            raise RuntimeError("Start the configured local external ComfyUI first; managed startup uses port 8188")
        executable = config.ROOT / "runtime" / "engine-env" / "Scripts" / "python.exe"
        if not executable.exists():
            raise RuntimeError("Run setup_engine.ps1 first")
        command = [str(executable), str(config.ROOT / "runtime" / "comfyui" / "main.py"), "--listen", "127.0.0.1", "--port", "8188", "--lowvram", "--disable-dynamic-vram", "--reserve-vram", "0.8", "--cpu-vae", "--preview-method", "none", "--disable-auto-launch", "--offline", "--verbose", "INFO", str(config.ROOT / "runtime" / "comfyui" / "engine.log")]
        process = None if "engine" in info else launch("engine", command, info)
        deadline = time.monotonic() + 180
        while not engine_ready():
            if process and process.poll() is not None:
                raise RuntimeError("Engine startup failed; inspect runtime/engine.log")
            if time.monotonic() > deadline:
                raise RuntimeError("Engine startup timed out; inspect runtime/engine.log")
            time.sleep(1)
    if not engine_only and "worker" not in info:
        process = launch("worker", [sys.executable, "-m", "backend.app.worker"], info)
        time.sleep(1)
        if process.poll() is not None:
            raise RuntimeError("Worker startup failed; inspect runtime/worker.log")
    for record in info.values():
        process = owned(record)
        if process:
            record["children"] = descendants(process)
    save(info)
    print("Local cartoon engine ready" if engine_only else "Local cartoon engine and worker ready", flush=True)


def stop_legacy_worker():
    legacy = config.DATA_DIR / "worker-process.json"
    if not legacy.exists():
        return
    record = json.loads(legacy.read_text(encoding="utf-8-sig"))
    try:
        process = psutil.Process(record["pid"])
        created = datetime.fromisoformat(record["started"].replace("Z", "+00:00")).timestamp()
        expected = str(config.ROOT / ".venv" / "Scripts" / "python.exe").lower()
        if abs(process.create_time() - created) < 2 and process.exe().lower() == expected and "backend.app.worker" in process.cmdline():
            stop_owned(process_record(process))
    except psutil.NoSuchProcess:
        pass
    legacy.unlink()


def stop():
    stop_legacy_worker()
    info = records()
    for name in ("worker", "engine"):
        if name not in info:
            continue
        stop_owned(info[name])
        info.pop(name, None)
    if RECORD.exists():
        RECORD.unlink()
    print("Stopped only StickerMe-owned services")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "start-engine", "stop", "status"])
    args = parser.parse_args()
    if args.action in {"start", "start-engine"}:
        start(engine_only=args.action == "start-engine")
    elif args.action == "stop":
        stop()
    else:
        print(json.dumps({"engine_ready": engine_ready(), "owned_services": {name: service_alive(record) for name, record in records().items()}}, indent=2))


if __name__ == "__main__":
    main()

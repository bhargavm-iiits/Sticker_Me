import json
import subprocess

from backend.app.main import doctor


def main() -> None:
    result = doctor()
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        result["gpu"] = gpu.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        result["gpu"] = "not detected"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

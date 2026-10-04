"""Cartoon validation now uses an explicitly reviewed character-design stage.

Initial call generates designs. Pass --select-design, --review, --continue-pack
or --export after inspecting the outputs; see scripts.validate_plan1 --help.
"""
import sys
from .validate_plan1 import ROOT, main


if __name__ == "__main__":
    args = sys.argv[1:] or ["--create", "--style", "cartoon"]
    if "--run" not in args:
        args = ["--run", str(ROOT / "runtime" / "cartoon-smoke"), *args]
    sys.argv = [sys.argv[0], *args]
    main()

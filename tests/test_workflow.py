import json
import pytest

from backend.app.config import ROOT
from backend.app.comfy import workflow


@pytest.mark.parametrize("stage,size,suffix", [("pose", 768, ""), ("face", 512, "-face")])
def test_workflow_bindings_and_canvas_links_match_api(stage, size, suffix):
    graph = workflow(stage, {"face": "StickerMe/person.png", "body": "StickerMe/body.png", "prompt": "Unique reaction", "seed": 12345, "prefix": "StickerMe/attempt"})
    assert graph["4"]["inputs"]["image"] == "StickerMe/person.png"
    assert graph["6"]["inputs"]["text"] == "Unique reaction"
    assert graph["10"]["inputs"]["noise_seed"] == 12345
    assert graph["16"]["inputs"]["filename_prefix"] == "StickerMe/attempt"
    assert graph["17"]["inputs"]["image"] == "StickerMe/body.png"
    assert graph["19"]["inputs"]["conditioning"] == ["7", 0]
    assert graph["13"]["inputs"]["positive"] == ["19", 0]
    for node in ("9", "11"):
        assert graph[node]["inputs"]["width"] == graph[node]["inputs"]["height"] == size
    canvas = json.loads((ROOT / "workflows" / f"klein4b{suffix}-human.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in canvas["nodes"]}
    assert len(nodes) == len(graph)
    for link_id, source, output_slot, target, input_slot, kind in canvas["links"]:
        field = nodes[target]["inputs"][input_slot]["name"]
        assert graph[str(target)]["inputs"][field] == [str(source), output_slot]
        assert link_id in nodes[source]["outputs"][output_slot]["links"]
        assert kind == nodes[source]["outputs"][output_slot]["type"]

"""Regenerate the checked-in API and importable canvas graphs together."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "workflows"


def main():
    old = json.loads((ROOT / "klein4b-api.json").read_text())
    baseline = ROOT / "klein4b-baseline-api.json"
    if not baseline.exists():
        baseline.write_text(json.dumps(old, indent=2) + "\n")
    graph = copy.deepcopy(old)
    graph["1"]["inputs"]["unet_name"] = "flux-2-klein-4b-Q6_K.gguf"
    graph["4"]["inputs"]["image"] = "face.png"
    graph["17"] = {"class_type": "LoadImage", "inputs": {"image": "body.png"}}
    graph["18"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["17", 0], "vae": ["3", 0]}}
    graph["19"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["7", 0], "latent": ["18", 0]}}
    graph["8"]["inputs"]["conditioning"] = ["19", 0]
    graph["13"]["inputs"]["positive"] = ["19", 0]
    templates = {n["type"]: n for n in json.loads((ROOT / "klein4b-human.json").read_text())["nodes"]}
    for suffix, size in (("", 768), ("-face", 512)):
        for node in ("9", "11"):
            graph[node]["inputs"].update(width=size, height=size)
        graph["4"]["inputs"]["image"] = "crop.png" if suffix else "face.png"
        graph["17"]["inputs"]["image"] = "face.png" if suffix else "body.png"
        (ROOT / f"klein4b{suffix}-api.json").write_text(json.dumps(graph, indent=2) + "\n")
        bindings = {"face": ["4", "image"], "body": ["17", "image"], "prompt": ["6", "text"], "seed": ["10", "noise_seed"], "output": "16", "prefix": ["16", "filename_prefix"]}
        (ROOT / f"bindings{suffix}.json").write_text(json.dumps(bindings, indent=2) + "\n")
        nodes, links = {}, []
        for order, (key, spec) in enumerate(graph.items()):
            node = copy.deepcopy(templates[spec["class_type"]])
            node.update(id=int(key), order=order, pos=[order % 5 * 380, order // 5 * 260])
            node["widgets_values"] = [v for v in spec["inputs"].values() if not isinstance(v, list)]
            # RandomNoise uses a frontend-only seed control widget.
            if spec["class_type"] == "RandomNoise": node["widgets_values"].append("fixed")
            for port in node.get("inputs", []): port["link"] = None
            for port in node.get("outputs", []): port["links"] = []
            nodes[int(key)] = node
        for key, spec in graph.items():
            for field, value in spec["inputs"].items():
                if not isinstance(value, list): continue
                source, slot = int(value[0]), value[1]
                target = int(key)
                input_slot = next(i for i, port in enumerate(nodes[target]["inputs"]) if port["name"] == field)
                link_id = len(links) + 1
                kind = nodes[source]["outputs"][slot]["type"]
                links.append([link_id, source, slot, target, input_slot, kind])
                nodes[target]["inputs"][input_slot]["link"] = link_id
                nodes[source]["outputs"][slot]["links"].append(link_id)
        canvas = {"last_node_id": max(nodes), "last_link_id": len(links), "nodes": list(nodes.values()), "links": links, "groups": [], "config": {}, "extra": {}, "version": 0.4}
        (ROOT / f"klein4b{suffix}-human.json").write_text(json.dumps(canvas, indent=2) + "\n")


if __name__ == "__main__":
    main()

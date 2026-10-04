"""Regenerate one isolated QA reaction; leave its new artwork unaccepted."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT / 'runtime' / 'cartoon-smoke')
    parser.add_argument('--intent', default='greeting')
    parser.add_argument('--correction', choices=['redraw', 'face', 'hands', 'expression'], default='redraw')
    parser.add_argument('--intensity', type=float, default=1.)
    args = parser.parse_args()
    args.run = args.run.resolve()
    if not args.run.is_relative_to(ROOT / 'runtime'):
        parser.error('QA data must stay under workspace runtime')
    os.environ['STICKERME_DATA_DIR'] = str(args.run)
    from fastapi.testclient import TestClient
    from backend.app import imaging
    from backend.app.comfy import ComfyEngine
    from backend.app.main import app
    from backend.app.worker import run_once
    imaging.U2NET_HOME = ROOT / 'runtime' / 'models'
    adapter = ComfyEngine()
    queue = adapter.request('GET', '/queue').json()
    adapter.close()
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise RuntimeError('Engine is busy; no regeneration submitted')
    state_path = args.run / 'pack.json'
    if state_path.exists():
        pack_id = json.loads(state_path.read_text())['id']
    else:
        pack_id = json.loads((args.run / 'result.json').read_text())['pack_id']
    directory = args.run / 'packs' / pack_id
    with TestClient(app) as client:
        state = client.get(f'/api/packs/{pack_id}').json()
        if state['status'] not in {'ready', 'awaiting_approval'}:
            raise RuntimeError(state['error'] or state['status'])
        selected = next(s for s in state['stickers'] if s['intent'] == args.intent and s['image_url'])
        base = f"/api/packs/{pack_id}/stickers/{selected['id']}"
        original_reference = digest(directory / 'reference.png')
        other_hashes = {s['id']: digest(directory / f"{s['id']}.png") for s in state['stickers'] if s['id'] != selected['id'] and s['image_url']}
        versions = client.get(base + '/versions').json()
        before_version = next(v for v in versions if v['revision'] == selected['revision'])
        before_hash = hashlib.sha256(client.get(before_version['image_url']).content).hexdigest()
        began = time.monotonic()
        response = client.post(base + '/regenerate', json={'correction': args.correction, 'intensity': args.intensity})
        response.raise_for_status()
        if not run_once():
            raise RuntimeError('Regeneration job was not claimed')
        state = client.get(f'/api/packs/{pack_id}').json()
        if state['status'] not in {'ready', 'awaiting_approval'}:
            raise RuntimeError(state['error'] or state['status'])
        updated = next(s for s in state['stickers'] if s['id'] == selected['id'])
        assert updated['revision'] > selected['revision']
        assert digest(directory / 'reference.png') == original_reference
        assert all(digest(directory / f'{key}.png') == value for key, value in other_hashes.items())
        assert hashlib.sha256(client.get(before_version['image_url']).content).hexdigest() == before_hash
        assert client.get(f'/api/packs/{pack_id}/export').status_code == 409
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
        result = {'pack_id': pack_id, 'intent': args.intent, 'seconds': round(time.monotonic()-began, 2),
                  'others_unchanged': len(other_hashes), 'reference_unchanged': True,
                  'immutable_version_unchanged': True, 'export_requires_review': True,
                  'quality_status': updated['quality_status']}
        (args.run / 'regeneration.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()

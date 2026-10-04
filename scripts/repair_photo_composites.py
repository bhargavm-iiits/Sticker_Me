"""Recompose saved photo animation inside the face, without new GPU generation.

First inspect the saved before/after sheet. --apply preserves the previous version
and updates matching stickers only when their pack has no active generation.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app import config, quality, portrait
from backend.app.db import engine, Pack, Sticker, Job
from backend.app.imaging import paste_head, remove_background, person_cutout, compose_sticker, save_png, align_face_patch
from backend.app.likeness import likeness
from backend.app.versions import snapshot


def repair(pack_id, intents=None, apply=False):
    directory = config.pack_dir(pack_id)
    out = config.DATA_DIR / 'overlap-debug' / pack_id
    out.mkdir(parents=True, exist_ok=True)
    with Session(engine) as session:
        pack = session.get(Pack, pack_id)
        if pack is None or pack.style not in {'realistic', 'likeness'}:
            raise ValueError('Choose an existing photographic pack')
        if session.scalar(select(Job.id).where(Job.pack_id == pack_id, Job.state.in_(['queued', 'running']))):
            raise ValueError('Wait for generation to finish or cancel it first')
        targets = [(s.id, s.intent, s.artwork_path, s.revision, s.caption, s.likeness_score) for s in pack.stickers
                   if s.artwork_path and (not intents or s.intent in intents)]
        style = pack.style
    reference = np.load(directory / 'face-embedding.npy', allow_pickle=False)
    tiles, rows, masks = [], [], {}
    for sticker_id, intent, artwork_path, revision, caption, old_score in targets:
        match = re.fullmatch(re.escape(sticker_id) + r'-art-(\d+)\.png', artwork_path)
        if not match:
            continue
        art_revision = int(match[1])
        base_path = directory / f'{sticker_id}-art-{art_revision}-base.png'
        candidates = []
        for folder in directory.glob(f'{sticker_id}-r{art_revision}-animation-*'):
            required = ['source.png', 'animated-raw.png', 'animation.json']
            if not all((folder/name).is_file() for name in required):
                continue
            candidate = folder.name.rsplit('-', 1)[1]
            report = directory / f'{sticker_id}-r{art_revision}-expression-{candidate}.json'
            score = json.loads(report.read_text())['checks']['identity']['score'] if report.exists() else None
            candidates.append((score if score is not None else -1, folder))
        if not base_path.is_file() or not candidates:
            rows.append({'intent': intent, 'state': 'skipped', 'reason': 'Saved pose/animation artifacts unavailable'})
            continue
        folder = max(candidates, key=lambda item: item[0])[1]
        with Image.open(base_path) as image:
            base = image.convert('RGB')
        face = portrait.single_face(base)
        if face is None:
            rows.append({'intent': intent, 'state': 'skipped', 'reason': 'Cannot safely locate a single face'})
            continue
        with Image.open(folder/'animated-raw.png') as image:
            patch = image.convert('RGB').resize((512,512), Image.Resampling.LANCZOS)
        with Image.open(folder/'source.png') as image:
            source = image.convert('RGB')
        source_hash = hashlib.sha256((folder/'source.png').read_bytes()).hexdigest()
        if source_hash not in masks:
            masks[source_hash] = remove_background(source).getchannel('A')
        metadata = json.loads((folder/'animation.json').read_text())
        matrix = np.asarray(metadata['target_transform'], np.float32)
        aligned = align_face_patch(base, patch, matrix, masks[source_hash])
        if aligned is None:
            rows.append({'intent': intent, 'state': 'skipped', 'reason': 'Saved animated face cannot safely align'})
            continue
        patch, mask = aligned
        regions = quality.hand_regions(base) or []
        fixed = paste_head(base, patch, matrix, face, source_mask=mask, protected_regions=[box for box,_ in regions])
        if style == 'likeness':
            from backend.app.imaging import portrait_render
            fixed = portrait_render(fixed, style)
        score = likeness(reference, fixed)
        cutout = person_cutout(fixed)
        composed = compose_sticker(cutout, caption, 'en')
        note = 'Recomposed the saved expression inside the face; kept one generated hair/head/body silhouette. Review face and mask edges.'
        report = quality.evaluate(fixed, score, intent, style, note)
        report['checks']['mask'] = quality.mask_report(cutout)
        report['route'] = 'original-photo-face-v3'
        report['repair'] = {'source_artwork': artwork_path, 'saved_animation': folder.name, 'new_gpu_generation': False}
        for name, image in [('art', fixed), ('cutout', cutout), ('sticker', composed)]:
            save_png(image, out / f'{intent}-{name}.png')
        with Image.open(directory/artwork_path) as image:
            before = image.convert('RGB')
        with Image.open(directory/f'{sticker_id}.png') as image:
            old_sticker = image.convert('RGBA')
        tiles += [(before, f'{intent}: previous art'), (fixed, f'{intent}: corrected art'),
                  (old_sticker, 'Previous sticker'), (composed, 'Corrected sticker')]
        row = {'intent': intent, 'sticker_id': sticker_id, 'previous_revision': revision,
               'old_score': old_score, 'score': score, 'state': report['status'], 'applied': False}
        if apply:
            with Session(engine) as session:
                session.execute(text('BEGIN IMMEDIATE'))
                if session.scalar(select(Job.id).where(Job.pack_id == pack_id, Job.state.in_(['queued', 'running']))):
                    raise ValueError('Generation started during repair; remaining stickers left unchanged')
                sticker = session.get(Sticker, sticker_id)
                if sticker is None or sticker.revision != revision or sticker.artwork_path != artwork_path:
                    raise ValueError('Sticker changed during repair; recompute before applying')
                snapshot(session, sticker)
                sticker.revision += 1
                sticker.artwork_path = f'{sticker_id}-art-{sticker.revision}.png'
                sticker.cutout_path = f'{sticker_id}-cutout-{sticker.revision}.png'
                save_png(fixed, directory/sticker.artwork_path)
                save_png(cutout, directory/sticker.cutout_path)
                save_png(composed, directory/f'{sticker_id}.png')
                sticker.likeness_score, sticker.likeness_note = score, note
                sticker.quality_status, sticker.quality_report = report['status'], json.dumps(report)
                snapshot(session, sticker)
                session.commit()
                row['applied'] = True
        rows.append(row)
        print(json.dumps(row), flush=True)
    if tiles:
        sheet = Image.new('RGB',(256*4,286*((len(tiles)+3)//4)), '#ede8f5')
        for index,(image,label) in enumerate(tiles):
            tile = image.convert('RGBA')
            tile.thumbnail((256,256),Image.Resampling.LANCZOS)
            x,y=index%4*256,index//4*286
            sheet.paste(tile,(x+(256-tile.width)//2,y),tile)
            ImageDraw.Draw(sheet).text((x+5,y+265),label,fill='black')
        save_png(sheet,out/'before-after.png')
    (out/'repair.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack',required=True)
    parser.add_argument('--intents',nargs='+')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    repair(args.pack,args.intents,args.apply)


if __name__ == '__main__':
    main()

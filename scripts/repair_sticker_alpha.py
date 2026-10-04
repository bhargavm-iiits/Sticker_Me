"""Preview or repair doubled grey edges without changing artwork or masks."""
import argparse
import hashlib
import json
import sqlite3

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app import config, quality
from backend.app.db import engine, Pack, Sticker, Job
from backend.app.imaging import compose_sticker, save_png
from backend.app.versions import snapshot


def checker(image):
    yy,xx=np.mgrid[:image.height,:image.width]
    pixels=np.where(((xx//24+yy//24)%2)[...,None],np.array([233,220,251]),np.array([246,240,255])).astype(np.uint8)
    return Image.alpha_composite(Image.fromarray(pixels).convert('RGBA'),image.convert('RGBA'))


def repair(pack_ids, apply=False):
    output=config.DATA_DIR/'alpha-fix'
    output.mkdir(parents=True,exist_ok=True)
    backup=output/'before.sqlite3'
    if apply and not backup.exists():
        with sqlite3.connect(config.DB_PATH) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
    results=[]
    for pack_id in pack_ids:
        with Session(engine) as session:
            pack=session.get(Pack,pack_id)
            if pack is None:raise ValueError('Pack not found')
            if session.scalar(select(Job.id).where(Job.pack_id==pack_id,Job.state.in_(['queued','running']))):
                raise ValueError('Wait for active generation to finish')
            language=pack.language
            targets=[(s.id,s.intent,s.revision,s.artwork_path,s.cutout_path,s.caption) for s in pack.stickers if s.artwork_path and s.cutout_path]
        directory=config.pack_dir(pack_id)
        out=output/pack_id
        out.mkdir(parents=True,exist_ok=True)
        tiles=[]
        for sticker_id,intent,revision,art_path,cutout_path,caption in targets:
            with Image.open(directory/art_path) as image:fixed=image.convert('RGBA')
            with Image.open(directory/cutout_path) as image:previous_cutout=image.convert('RGBA')
            if fixed.size!=previous_cutout.size:raise ValueError('Artwork and mask sizes differ; repair manually')
            fixed.putalpha(previous_cutout.getchannel('A'))
            composed=compose_sticker(fixed,caption,language)
            with Image.open(directory/(sticker_id+'.png')) as image:previous=image.convert('RGBA')
            for name,image in [('cutout',fixed),('sticker',composed)]:save_png(image,out/f'{intent}-{name}.png')
            for image,label in [(previous,'Previous'),(composed,'Corrected')]:
                tiles.append((checker(image),f'{intent}: {label}'))
                dark=Image.new('RGBA',image.size,'#171717')
                tiles.append((Image.alpha_composite(dark,image),f'{intent}: {label} / dark'))
            row={'pack_id':pack_id,'sticker_id':sticker_id,'intent':intent,'previous_revision':revision,'artwork_sha256':hashlib.sha256((directory/art_path).read_bytes()).hexdigest(),'previous_image_sha256':hashlib.sha256((directory/(sticker_id+'.png')).read_bytes()).hexdigest(),'mask_unchanged':True,'applied':False}
            if apply:
                with Session(engine) as session:
                    session.execute(text('BEGIN IMMEDIATE'))
                    if session.scalar(select(Job.id).where(Job.pack_id==pack_id,Job.state.in_(['queued','running']))):raise ValueError('Generation started; remaining stickers unchanged')
                    sticker=session.get(Sticker,sticker_id)
                    if sticker.revision!=revision or sticker.artwork_path!=art_path or sticker.cutout_path!=cutout_path or sticker.caption!=caption:raise ValueError('Sticker changed; recompute repair')
                    snapshot(session,sticker)
                    sticker.revision+=1
                    sticker.cutout_path=f'{sticker_id}-alpha-{sticker.revision}.png'
                    save_png(fixed,directory/sticker.cutout_path)
                    save_png(composed,directory/(sticker_id+'.png'))
                    report=json.loads(sticker.quality_report or '{}')
                    report.setdefault('checks',{})['mask']=quality.mask_report(fixed)
                    report['parameters']={**report.get('parameters',{}),'renderer':'straight-alpha-border-v3','mask_cleanup':'straight-alpha-v3'}
                    report['alpha_repair']={'prior_cutout':cutout_path,'artwork_changed':False,'mask_changed':False}
                    sticker.quality_status='blocked' if sticker.quality_status=='blocked' else 'needs_review'
                    report['status']=sticker.quality_status
                    report.pop('reviewed',None)
                    sticker.quality_report=json.dumps(report)
                    snapshot(session,sticker)
                    session.commit()
                    row['applied']=True
                    row['revision']=sticker.revision
            results.append(row)
            print(json.dumps(row),flush=True)
        if tiles:
            sheet=Image.new('RGB',(320*4,350*((len(tiles)+3)//4)),'white')
            for i,(image,label) in enumerate(tiles):
                image=image.convert('RGB').resize((320,320),Image.Resampling.LANCZOS)
                x,y=i%4*320,i//4*350
                sheet.paste(image,(x,y));ImageDraw.Draw(sheet).text((x+5,y+327),label,fill='black')
            save_png(sheet,out/'before-after.png')
    (output/('applied.json' if apply else 'preview.json')).write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packs',nargs='+',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    repair(args.packs,args.apply)

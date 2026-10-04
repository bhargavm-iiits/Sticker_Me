import json

from sqlalchemy.orm import Session

from backend.app import config, db, worker
from tests.test_cutout_flow import client, create_pack
from tests.test_cartoon_flow import cartoon_engine, ready_pack


def flag_sticker(sticker_id):
    with Session(db.engine) as session:
        sticker=session.get(db.Sticker,sticker_id)
        sticker.quality_status='blocked'
        report=json.loads(sticker.quality_report)
        report['status']='blocked'
        report['checks']['anatomy']={'state':'blocked','detected_hands':3,'note':'Possible extra hand detected'}
        sticker.quality_report=json.dumps(report)
        session.commit()


def test_flagged_preview_can_be_explicitly_reviewed_without_erasing_findings(client, cartoon_engine):
    pack=create_pack(client,legacy=False)
    assert worker.run_once()
    state=client.get(f"/api/packs/{pack['id']}").json()
    sticker=next(s for s in state['stickers'] if s['image_url'])
    flag_sticker(sticker['id'])
    path=f"/api/packs/{pack['id']}/stickers/{sticker['id']}/review"
    assert client.post(path).status_code==409
    assert client.post(path,json={'override_detected':True}).status_code==409
    response=client.post(path,json={'override_detected':True,'revision':sticker['revision']})
    assert response.status_code==200,response.text
    item=next(s for s in response.json()['stickers'] if s['id']==sticker['id'])
    assert item['quality_status']=='accepted'
    assert item['quality_report']['checks']['anatomy']['state']=='blocked'
    assert item['quality_report']['review']=={'decision':'accepted','revision':sticker['revision'],'overrode_automated_check':True}


def test_review_rejects_stale_revision_and_unfinished_sticker(client, cartoon_engine):
    pack=create_pack(client,legacy=False)
    assert worker.run_once()
    state=client.get(f"/api/packs/{pack['id']}").json()
    ready=next(s for s in state['stickers'] if s['image_url'])
    pending=next(s for s in state['stickers'] if not s['image_url'])
    base=f"/api/packs/{pack['id']}/stickers"
    assert client.post(f"{base}/{ready['id']}/review",json={'revision':ready['revision']+1}).status_code==409
    assert client.post(f"{base}/{pending['id']}/review",json={'override_detected':True,'revision':0}).status_code==409


def test_remaining_nine_can_be_reviewed_after_generation_and_exported(client, cartoon_engine):
    pack=ready_pack(client)
    remaining=[s for s in pack['stickers'] if s['intent'] not in {'greeting','laughter','surprise'}]
    assert len(remaining)==9
    directory=config.pack_dir(pack['id'])
    original={s['id']:(directory/f"{s['id']}.png").read_bytes() for s in pack['stickers']}
    for sticker in remaining:flag_sticker(sticker['id'])
    assert client.get(f"/api/packs/{pack['id']}/export").status_code==409
    for sticker in remaining:
        response=client.post(f"/api/packs/{pack['id']}/stickers/{sticker['id']}/review",json={'override_detected':True,'revision':sticker['revision']})
        assert response.status_code==200,response.text
    assert all(s['quality_status']=='accepted' for s in response.json()['stickers'])
    assert client.get(f"/api/packs/{pack['id']}/export").status_code==200
    assert len(cartoon_engine.calls)==12
    assert all((directory/f'{sticker_id}.png').read_bytes()==png for sticker_id,png in original.items())

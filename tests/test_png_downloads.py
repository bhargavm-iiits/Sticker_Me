import io
import zipfile

from PIL import Image
from sqlalchemy.orm import Session

from backend.app import config, db, worker
from tests.test_cutout_flow import client, create_pack, fake_cutout
from tests.test_cartoon_flow import cartoon_engine, ready_pack


def test_png_pack_download_includes_blocked_and_unreviewed_without_accepting(client, cartoon_engine):
    pack = ready_pack(client)
    with Session(db.engine) as session:
        first = session.get(db.Sticker, pack['stickers'][0]['id'])
        first.quality_status = 'blocked'
        second = session.get(db.Sticker, pack['stickers'][1]['id'])
        second.quality_status = 'needs_review'
        session.commit()
    before = client.get(f"/api/packs/{pack['id']}").json()
    assert client.get(f"/api/packs/{pack['id']}/export").status_code == 409
    response = client.get(f"/api/packs/{pack['id']}/export/png")
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    assert '-png.zip' in response.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 12
        for sticker in before['stickers']:
            name = f"{sticker['position'] + 1:02d}-{sticker['intent']}.png"
            png = archive.read(name)
            assert png == client.get(sticker['image_url']).content
            with Image.open(io.BytesIO(png)) as image:
                assert image.format == 'PNG' and image.size == (512, 512)
                assert image.getchannel('A').getextrema() == (0, 255)
    assert client.get(f"/api/packs/{pack['id']}").json() == before


def test_partial_preview_can_download_only_saved_pngs(client, cartoon_engine):
    pack = create_pack(client, legacy=False)
    assert worker.run_once()
    before = client.get(f"/api/packs/{pack['id']}").json()
    assert before['status'] == 'awaiting_approval' and not before['approved']
    response = client.get(f"/api/packs/{pack['id']}/export/png")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 3
    pending = next(s for s in before['stickers'] if not s['image_url'])
    assert client.get(f"/api/packs/{pack['id']}/stickers/{pending['id']}/download").status_code == 409
    assert client.get(f"/api/packs/{pack['id']}").json() == before


def test_single_png_download_is_latest_caption_and_checks_pack_ownership(client, cartoon_engine):
    pack = create_pack(client, legacy=False)
    assert worker.run_once()
    state = client.get(f"/api/packs/{pack['id']}").json()
    sticker = next(s for s in state['stickers'] if s['image_url'])
    old = client.get(sticker['image_url']).content
    response = client.patch(f"/api/packs/{pack['id']}/stickers/{sticker['id']}", json={'caption':'Saved PNG'})
    assert response.status_code == 200
    current = next(s for s in response.json()['stickers'] if s['id'] == sticker['id'])
    response = client.get(f"/api/packs/{pack['id']}/stickers/{sticker['id']}/download")
    assert response.status_code == 200 and response.content != old
    assert response.content == client.get(current['image_url']).content
    assert response.headers['content-type'] == 'image/png'
    assert f"{sticker['intent']}.png" in response.headers['content-disposition']
    other = create_pack(client, legacy=False)
    assert client.get(f"/api/packs/{other['id']}/stickers/{sticker['id']}/download").status_code == 404


def test_empty_or_missing_pack_returns_download_error(client):
    pack = create_pack(client, legacy=False)
    assert client.get(f"/api/packs/{pack['id']}/export/png").status_code == 409
    assert client.get('/api/packs/does-not-exist/export/png').status_code == 404


def test_legacy_cutout_pack_can_download_pngs(client, monkeypatch):
    monkeypatch.setattr(worker, 'remove_background', fake_cutout)
    pack = create_pack(client)
    assert worker.run_once()
    response = client.get(f"/api/packs/{pack['id']}/export/png")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 12
        assert all(name.endswith('.png') for name in archive.namelist())

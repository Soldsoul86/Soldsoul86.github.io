import io
import os
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

os.environ['RELAY_DATA_DIR']=tempfile.mkdtemp(prefix='relay-chain-tests-')
import app
from video import probe_duration

@pytest.fixture(scope='module')
def client():
    with TestClient(app.app) as c: yield c

@pytest.fixture(scope='module')
def clips(tmp_path_factory):
    root=tmp_path_factory.mktemp('clips')
    for n,color in enumerate(('red','blue','green')):
        out=root/f'{n}.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
            '-f','lavfi','-i',f'color=c={color}:s=360x640:r=24:d=1.2',
            '-f','lavfi','-i','sine=frequency=400:sample_rate=44100:duration=1.2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(out)],check=True)
    return [x.read_bytes() for x in (root/'0.mp4',root/'1.mp4',root/'2.mp4')]

def post_clip(client,path,contents):
    return client.post(path,files={'clip':('clip.mp4',contents,'video/mp4')})

def test_three_friend_chain_and_sharing(client,clips):
    landing=client.get('/')
    assert landing.status_code==200
    assert 'relay-config' in landing.text and 'relay.js' in landing.text

    first=post_clip(client,'/api/new',clips[0]);assert first.status_code==201,first.text
    url=first.json()['watch_url'];owner=first.json()['delete_url']
    watch=client.get(url);assert watch.status_code==200
    token=url.rsplit('/',1)[1]
    info=client.get('/api/watch/'+token).json()
    assert info['clips']==1 and info['can_continue']
    assert client.get(info['video_url'].replace('http://testserver','')).status_code==200
    assert client.get(info['invite_url'].replace('http://testserver','')).status_code==200
    assert client.get('/poster/'+info['invite_url'].rsplit('/',1)[1]+'.jpg').status_code==200

    invite1=info['invite_url'].rsplit('/',1)[1]
    second=post_clip(client,'/api/join/'+invite1,clips[1])
    assert second.status_code==201,second.text
    second_url=second.json()['watch_url'];second_token=second_url.rsplit('/',1)[1]
    info2=client.get('/api/watch/'+second_token).json()
    assert info2['clips']==2 and info2['can_continue']
    assert client.get('/join/'+invite1).status_code==404
    # Old participants still have a working video link.
    assert client.get(info['video_url'].replace('http://testserver','')).status_code==200
    third_invite=info2['invite_url'].rsplit('/',1)[1]
    third=post_clip(client,'/api/join/'+third_invite,clips[2]);assert third.status_code==201,third.text
    third_token=third.json()['watch_url'].rsplit('/',1)[1]
    info3=client.get('/api/watch/'+third_token).json()
    assert info3['clips']==3 and info3['can_continue']
    video_response=client.get(info3['video_url'].replace('http://testserver',''))
    assert video_response.status_code==200
    assert video_response.headers['content-type'].startswith('video/mp4')
    output=Path(tempfile.mkdtemp())/'movie.mp4';output.write_bytes(video_response.content)
    assert 3.1 < probe_duration(output) < 6.2
    assert client.get('/api/watch/'+token).json()['is_latest']==False
    # Owner can delete every version and invalidate all links.
    deleted=client.post('/api'+owner.split('testserver')[-1])
    assert deleted.status_code==200
    assert client.get('/api/watch/'+third_token).status_code==404


def test_invalid_clip_refused(client):
    created=client.post('/api/new',files={'clip':('clip.mp4',b'not a real video' * 200,'video/mp4')})
    assert created.status_code==422


def test_only_one_wins_concurrent_upload(client,clips):
    first=post_clip(client,'/api/new',clips[0]);assert first.status_code==201
    token=first.json()['watch_url'].rsplit('/',1)[1]
    join=client.get('/api/watch/'+token).json()['invite_url'].rsplit('/',1)[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:post_clip(client,'/api/join/'+join,clips[1]),range(2)))
    assert sorted(r.status_code for r in results)==[201,409]

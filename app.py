"""Relay V0.2: WhatsApp-first, browser recording + automatic incremental video chain.

Private, experimental and NOT approved for public consumer launch.
"""
from __future__ import annotations
import asyncio
import json
import os
import secrets
import shutil
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from html import escape
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from video import VideoError, normalize, probe, stitch, thumbnail

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('RELAY_DATA_DIR',ROOT/'.data')).resolve()
FILES=DATA/'media'
FILES.mkdir(parents=True,exist_ok=True)
DB=DATA/'relays.db'
MAX_CLIPS=8
MAX_UPLOAD=15*1024*1024
LIFETIME=int(os.environ.get('RELAY_LIFETIME_HOURS','48'))*3600
PILOT_CODE=os.environ.get('RELAY_PILOT_CODE','')
PUBLIC_URL=os.environ.get('RELAY_PUBLIC_URL','').rstrip('/')
MAX_ACTIVE_CHAINS=int(os.environ.get('RELAY_MAX_ACTIVE_CHAINS','6'))
MAX_HTTP_BODY=16*1024*1024
if os.environ.get('RELAY_REQUIRE_PILOT_CODE')=='1' and not PILOT_CODE:
    raise RuntimeError('A private pilot requires RELAY_PILOT_CODE')


def conn():
    c=sqlite3.connect(DB,timeout=15,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=15000')
    return c

with conn() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('''CREATE TABLE IF NOT EXISTS chains(
        id TEXT PRIMARY KEY, owner TEXT UNIQUE NOT NULL, created REAL NOT NULL,
        expires REAL NOT NULL, step INTEGER NOT NULL, invite TEXT UNIQUE,
        view TEXT UNIQUE NOT NULL, processing INTEGER NOT NULL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS views(
        token TEXT PRIMARY KEY, chain_id TEXT NOT NULL, step INTEGER NOT NULL)''')

def sweep():
    with conn() as c:
        expired=c.execute('SELECT id FROM chains WHERE expires < ?', (time.time(),)).fetchall()
        for x in expired:
            c.execute('DELETE FROM views WHERE chain_id=?',(x['id'],))
            c.execute('DELETE FROM chains WHERE id=?',(x['id'],))
            shutil.rmtree(FILES/x['id'],ignore_errors=True)

@asynccontextmanager
async def lifespan(app):
    async def routine():
        while True:
            try: await asyncio.to_thread(sweep)
            except Exception as err: print('Cleanup error',repr(err))
            await asyncio.sleep(3600)
    task=asyncio.create_task(routine())
    try: yield
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)

app=FastAPI(title='Relay private chain pilot',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.middleware('http')
async def headers(request,call_next):
    # Reject oversized uploads before multipart parsing can spool to disk.
    if request.method=='POST' and request.url.path.startswith('/api/'):
        supplied=request.headers.get('content-length')
        if supplied:
            try:
                if int(supplied)>MAX_HTTP_BODY: raise HTTPException(413,'Recording is too large.')
            except ValueError:
                raise HTTPException(400,'Invalid content length')
    resp=await call_next(request)
    resp.headers.update({
        'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
        'X-Robots-Tag':'noindex, nofollow, noarchive',
        'X-Frame-Options':'DENY',
        'Permissions-Policy':'geolocation=(), camera=(self), microphone=(self)',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'"
    })
    if request.url.path != '/health':
        resp.headers['Cache-Control']='private, no-store'
    return resp

def row_by(column:str,token:str):
    if column not in ('invite','view','owner'): raise RuntimeError('bad lookup')
    if len(token)>128: raise HTTPException(404,'Not found')
    with conn() as c:
        if column=='view':
            v=c.execute('SELECT * FROM views WHERE token=?',(token,)).fetchone()
            row=c.execute('SELECT * FROM chains WHERE id=?',(v['chain_id'],)).fetchone() if v else None
        else:
            row=c.execute(f'SELECT * FROM chains WHERE {column}=?',(token,)).fetchone()
    if not row or row['expires']<time.time(): raise HTTPException(404,'This private Relay has expired.')
    return row

def full_url(request:Request,path:str):
    return (PUBLIC_URL or str(request.base_url).rstrip('/'))+path

def movie_url(request:Request,view:str):
    return full_url(request,f'/video/{view}.mp4')

def render_page(request,mode,token=None,**data):
    page={'mode':mode,'token':token,**data}
    # Safe JSON placed in executable script: escape < to prevent script termination.
    payload=json.dumps(page,separators=(',',':')).replace('<','\\u003c')
    markup=(ROOT/'static'/'index.html').read_text(encoding='utf-8')
    markup=markup.replace('/*__DATA__*/',payload)
    # ensure safe share title in preview (no personal names)
    if mode=='join':
        # Do not expose a participant's thumbnail to WhatsApp link-preview crawlers.
        markup=markup.replace('<!--OG_IMAGE-->','<meta property="og:title" content="Join our private Relay"/><meta property="og:description" content="Watch a short video. Add three seconds. Pass it to a friend."/>')
    else:
        markup=markup.replace('<!--OG_IMAGE-->','')
    return HTMLResponse(markup)

@app.get('/health')
def health(): return {'ok':True,'mode':'private-chain-pilot','max_clips':MAX_CLIPS}

@app.get('/')
def home(request:Request): return render_page(request,'start',protected=bool(PILOT_CODE))

@app.get('/join/{token}')
def join_page(request:Request,token:str):
    row=row_by('invite',token)
    return render_page(request,'join',token,step=row['step'],movie_url=movie_url(request,row['view']),clips=row['step']+1)

@app.get('/watch/{token}')
def watch_page(request:Request,token:str):
    row=row_by('view',token)
    return render_page(request,'watch',token)

@app.get('/api/watch/{token}')
def watch_info(request:Request,token:str):
    row=row_by('view',token)
    with conn() as c:
        v=c.execute('SELECT step FROM views WHERE token=?',(token,)).fetchone()
    current=(v['step']==row['step'])
    return {'step':v['step'],'clips':v['step']+1,'is_latest':current,
        'video_url':movie_url(request,token),
        'invite_url':full_url(request,'/join/'+row['invite']) if current and row['invite'] else None,
        'can_continue': bool(current and row['step']<MAX_CLIPS-1 and row['invite'])}

@app.get('/video/{token}.mp4')
def get_video(token:str):
    row=row_by('view',token)
    with conn() as c: v=c.execute('SELECT step FROM views WHERE token=?',(token,)).fetchone()
    path=FILES/row['id']/f'movie_{v["step"]:02d}.mp4'
    if not path.exists(): raise HTTPException(404,'Video not found')
    return FileResponse(path,media_type='video/mp4',filename='Relay.mp4',content_disposition_type='inline')

@app.get('/poster/{token}.jpg')
def poster(token:str):
    row=row_by('invite',token)
    path=FILES/row['id']/f'poster_{row["step"]:02d}.jpg'
    if not path.exists(): raise HTTPException(404,'Poster not available')
    return FileResponse(path,media_type='image/jpeg')

async def save_video(upload:UploadFile,path:Path):
    content_type=upload.content_type or ''
    if not content_type.startswith('video/') and not (upload.filename or '').lower().endswith(('.mp4','.mov','.webm','.3gp','.m4v')):
        raise HTTPException(415,'Please use a video from your phone.')
    size=0
    try:
        with path.open('wb') as out:
            while chunk:=await upload.read(1024*1024):
                size+=len(chunk)
                if size>MAX_UPLOAD: raise HTTPException(413,'Keep your recording under 15 MB.')
                out.write(chunk)
        if size<1000: raise HTTPException(422,'Empty recording')
        try: await asyncio.to_thread(probe,path)
        except VideoError as err: raise HTTPException(422,str(err)) from err
    finally: await upload.close()

@app.post('/api/new',status_code=201)
async def new_chain(request:Request,clip:UploadFile=File(...),pilot_code:str=Form('')):
    if PILOT_CODE and not secrets.compare_digest(pilot_code,PILOT_CODE):
        raise HTTPException(403,'Pilot code required for the first recording.')
    sweep()
    with conn() as c:
        active=c.execute('SELECT COUNT(*) FROM chains WHERE expires >= ?', (time.time(),)).fetchone()[0]
    if active >= MAX_ACTIVE_CHAINS:
        raise HTTPException(429,'The private pilot is full for now.')
    rid=uuid.uuid4().hex
    folder=FILES/rid
    folder.mkdir()
    uploaded=folder/'original.part'
    try:
        await save_video(clip,uploaded)
        await asyncio.to_thread(normalize,uploaded,folder/'segment_00.mp4')
        await asyncio.to_thread(stitch,[folder/'segment_00.mp4'],folder/'movie_00.mp4')
        await asyncio.to_thread(thumbnail,folder/'movie_00.mp4',folder/'poster_00.jpg')
    except VideoError as exc:
        shutil.rmtree(folder,ignore_errors=True)
        raise HTTPException(422,str(exc)) from exc
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise
    finally: uploaded.unlink(missing_ok=True)
    owner=secrets.token_urlsafe(25);invite=secrets.token_urlsafe(25);view=secrets.token_urlsafe(25)
    now=time.time()
    with conn() as c:
        c.execute('INSERT INTO chains(id,owner,created,expires,step,invite,view,processing) VALUES(?,?,?,?,?,?,?,0)',(rid,owner,now,now+LIFETIME,0,invite,view))
        c.execute('INSERT INTO views(token,chain_id,step) VALUES(?,?,?)',(view,rid,0))
    return {'watch_url':full_url(request,'/watch/'+view),'delete_url':full_url(request,'/delete/'+owner)}

@app.post('/api/join/{token}',status_code=201)
async def add_to_chain(request:Request,token:str,clip:UploadFile=File(...)):
    row=row_by('invite',token)
    if row['step']>=MAX_CLIPS-1: raise HTTPException(409,'The first Relay pilot allows eight people per chain.')
    with conn() as c:
        claimed=c.execute("UPDATE chains SET processing=1 WHERE id=? AND invite=? AND processing=0 AND step=?",(row['id'],token,row['step']))
        if claimed.rowcount!=1: raise HTTPException(409,'Someone has already added a clip. Open the latest Relay.')
    step=row['step']+1
    folder=FILES/row['id']
    uploaded=folder/f'original_{step:02d}.part'
    segment=folder/f'segment_{step:02d}.mp4'
    combined=folder/f'movie_{step:02d}.mp4'
    try:
        await save_video(clip,uploaded)
        await asyncio.to_thread(normalize,uploaded,segment)
        segments=[folder/f'segment_{i:02d}.mp4' for i in range(step+1)]
        await asyncio.to_thread(stitch,segments,combined)
        await asyncio.to_thread(thumbnail,combined,folder/f'poster_{step:02d}.jpg')
        next_invite=secrets.token_urlsafe(25) if step<MAX_CLIPS-1 else None
        next_view=secrets.token_urlsafe(25)
        with conn() as c:
            c.execute('BEGIN IMMEDIATE')
            updated=c.execute('UPDATE chains SET processing=0,step=?,invite=?,view=? WHERE id=? AND processing=1 AND invite=? AND step=?',
                (step,next_invite,next_view,row['id'],token,row['step']))
            if updated.rowcount!=1:
                c.execute('ROLLBACK');raise HTTPException(409,'The chain changed during processing.')
            c.execute('INSERT INTO views(token,chain_id,step) VALUES(?,?,?)',(next_view,row['id'],step))
            c.execute('COMMIT')
        return {'watch_url':full_url(request,'/watch/'+next_view)}
    except VideoError as exc:
        segment.unlink(missing_ok=True);combined.unlink(missing_ok=True)
        (folder/f'poster_{step:02d}.jpg').unlink(missing_ok=True)
        with conn() as c: c.execute('UPDATE chains SET processing=0 WHERE id=? AND step=? AND invite=?',(row['id'],row['step'],token))
        raise HTTPException(422,str(exc)) from exc
    except Exception:
        segment.unlink(missing_ok=True);combined.unlink(missing_ok=True)
        (folder/f'poster_{step:02d}.jpg').unlink(missing_ok=True)
        with conn() as c: c.execute('UPDATE chains SET processing=0 WHERE id=? AND step=? AND invite=?',(row['id'],row['step'],token))
        raise
    finally: uploaded.unlink(missing_ok=True)

@app.get('/delete/{owner}')
def delete_page(request:Request,owner:str):
    row=row_by('owner',owner)
    return render_page(request,'delete',owner)

@app.post('/api/delete/{owner}')
def delete_chain(owner:str):
    row=row_by('owner',owner)
    with conn() as c:
        c.execute('DELETE FROM views WHERE chain_id=?',(row['id'],))
        c.execute('DELETE FROM chains WHERE id=?',(row['id'],))
    shutil.rmtree(FILES/row['id'],ignore_errors=True)
    return {'deleted':True}

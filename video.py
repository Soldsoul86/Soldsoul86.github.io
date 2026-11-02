"""Bounded, normalized phone video segments with fast concat-copy assembly.

This is an experimental trusted-invite implementation, not a video sandbox.
"""
import json
import shutil
import subprocess
from pathlib import Path

WIDTH, HEIGHT, FPS, MAX_SECONDS = 360, 640, 24, 3.25

class VideoError(Exception):
    pass

def run(args, timeout=50):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise VideoError('Video processing is unavailable or timed out') from e
    if p.returncode:
        raise VideoError('Could not process this recording. Try a shorter phone video.')
    return p.stdout

def probe(path: Path):
    try:
        result = json.loads(run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)],timeout=12))
    except (ValueError, VideoError) as exc:
        raise VideoError('This is not a supported video. Please record again.') from exc
    streams = result.get('streams') or []
    videos = [s for s in streams if s.get('codec_type')=='video']
    if not videos or (videos[0].get('width') or 0) > 4096 or (videos[0].get('height') or 0) > 4096:
        raise VideoError('Expected a video under 4K resolution.')
    duration = float(result.get('format',{}).get('duration') or 0)
    if not 0.35 <= duration <= 30:
        raise VideoError('Record between 1 and 30 seconds; Relay keeps the first three seconds.')
    return {'duration':duration,'has_audio':any(s.get('codec_type')=='audio' for s in streams)}

def normalize(source: Path, dest: Path):
    info=probe(source)
    has_audio=info['has_audio']
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(source)]
    if not has_audio:
        cmd+=['-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100']
    vf=(f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
        f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p')
    cmd += ['-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0',
        '-vf',vf,'-t',str(MAX_SECONDS),'-r',str(FPS),'-c:v','libx264','-preset','veryfast','-crf','29',
        '-pix_fmt','yuv420p','-c:a','aac','-b:a','72k','-ar','44100','-ac','2','-movflags','+faststart',
        '-shortest',str(dest)]
    run(cmd, timeout=55)
    if not dest.is_file() or dest.stat().st_size < 2000:
        raise VideoError('Could not make the segment')
    return probe_duration(dest)

def probe_duration(path: Path):
    return float(json.loads(run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],timeout=8))['format']['duration'])

def stitch(clips: list[Path], destination: Path):
    """All clips already use the same codec, dimensions, rate, audio format."""
    if not 1 <= len(clips) <= 8:
        raise VideoError('Invalid number of clips')
    manifest=destination.with_suffix('.txt')
    manifest.write_text(''.join("file '"+str(p.resolve()).replace("'","'\\''")+"'\n" for p in clips),encoding='utf-8')
    try:
        run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-f','concat','-safe','0',
            '-i',str(manifest),'-c','copy','-movflags','+faststart',str(destination)],timeout=35)
    finally:
        manifest.unlink(missing_ok=True)
    if not destination.exists() or destination.stat().st_size<2000:
        raise VideoError('Could not merge the clips')
    return probe_duration(destination)

def thumbnail(movie:Path, poster:Path):
    try:
        run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-ss','0.8', '-i',str(movie),'-frames:v','1','-q:v','4',str(poster)],timeout=15)
    except VideoError:
        pass

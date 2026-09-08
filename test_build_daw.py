"""build_daw.py 오프라인 테스트 — GarageBand 용 WAV/무음 영상 준비와, 내보낸 mix.wav 에서 곡 경계를 복원하는 align_cues 를 ffmpeg 합성 미디어로 검증"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import playlist_dl as pdl
import build_timeline as bt
import build_daw as bd

FFMPEG = shutil.which("ffmpeg"); assert FFMPEG, "ffmpeg 가 PATH 에 없음"
def ff(*a): subprocess.run([FFMPEG, "-v", "error", "-y", *a], check=True)
def streams(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,sample_rate", "-of", "json", str(p)], capture_output=True, text=True).stdout
    return [(s["codec_type"], s["codec_name"], s.get("sample_rate")) for s in json.loads(out)["streams"]]

print("== 프로젝트 준비 (곡마다 다른 리듬의 진폭 변조 → 라우드니스 곡선이 서로 다름) ==")
root = Path(tempfile.mkdtemp()); proj = root / "01.테스트"; dl = proj / "downloads"; dl.mkdir(parents=True)
def song(path, dur, freq, mod, video=False):
    src = f"aevalsrc=sin({freq}*2*PI*t)*(0.55+0.45*sin(2*PI*{mod}*t))*(0.6+0.4*sin(2*PI*{mod/3.7}*t)):s=48000:d={dur}"
    if video:
        ff("-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={dur}", "-f", "lavfi", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))
    else:
        ff("-f", "lavfi", "-i", src, "-c:a", "aac", "-b:a", "192k", str(path))
song(dl / "01.가수-노래.m4a", 8.0, 440, 0.53)
song(dl / "02.둘-Second_Song.m4a", 6.0, 660, 1.31)
song(dl / "03.Band-Live_Show.mp4", 7.0, 330, 0.87, video=True)
def dec(i, vid, title, name, ch, mode, artist):
    return pdl.Decision(index=i, id=vid, title=title, name=name, channel=ch, duration=2, mode=mode, reason="r",
                        url=f"https://www.youtube.com/watch?v={vid}", artist=artist)
items = [dec(1, "aaa", "노래", "가수-노래", "가수 - Topic", "audio", "가수"),
         dec(2, "bbb", "Second Song", "둘-Second Song", "둘 - Topic", "audio", "둘"),
         dec(3, "ccc", "Band - Live Show", "Band-Live Show", "BandVEVO", "video", "Band")]
pdl.write_manifest(proj, "https://x/pl", "테스트 목록", items)

print("== build (GarageBand 용 소스 준비) ==")
res = bd.build(proj)
daw = proj / "build" / "daw"
wavs = [daw / "audio" / f for f in ("01.가수-노래.wav", "02.둘-Second_Song.wav", "03.Band-Live_Show.wav")]
assert all(w.exists() for w in wavs) and [t.wav for t in res.tracks] == wavs, list((daw / "audio").iterdir())
assert all(streams(w) == [("audio", "pcm_s24le", "48000")] for w in wavs)
vid = daw / "video" / "03.Band-Live_Show.mp4"
assert res.tracks[2].video == vid and vid.exists() and res.tracks[0].video is None
assert [s[0] for s in streams(vid)] == ["video"] and streams(vid)[0][1] == "h264"
assert [t.label for t in res.tracks] == ["가수 - 노래", "둘 - Second Song", "Band - Live Show"]
assert not (daw / "session.rpp").exists() and not hasattr(res, "session")          # Reaper 산출물 없음
durs = [bt.probe(w)["duration"] for w in wavs]
assert [t.length for t in res.tracks] == durs
print("  OK")

print("== align_cues: GarageBand 에서 순서 바꾸고(3,1,2) 볼륨 낮추고 1번 앞 0.8초 잘라 내보낸 믹스 ==")
mix = daw / "mix.wav"
ff("-i", str(wavs[2]), "-i", str(wavs[0]), "-i", str(wavs[1]),
   "-filter_complex",
   "[0:a]volume=0.5[s3];[1:a]atrim=start=0.8,asetpts=PTS-STARTPTS[s1];[2:a]volume=0.7[s2];"
   "aevalsrc=0:s=48000:d=1.0[g1];aevalsrc=0:s=48000:d=0.6[g2];"
   "[s3][g1][s1][g2][s2]concat=n=5:v=0:a=1[out]", "-map", "[out]", "-c:a", "pcm_s16le", str(mix))
cues = bd.align_cues(mix, res.tracks)
assert [c.index for c in cues] == [3, 1, 2], [c.index for c in cues]
exp_start = [0.0, durs[2] + 1.0, durs[2] + 1.0 + (durs[0] - 0.8) + 0.6]
for c, e in zip(cues, exp_start):
    assert abs(c.start - e) < 0.25, (c.index, c.start, e)
c1 = next(c for c in cues if c.index == 1)
assert abs(c1.offset - 0.8) < 0.25, c1                                             # 앞 트림이 소스 오프셋으로
assert abs(c1.length - (durs[0] - 0.8)) < 0.35 and abs(cues[0].length - durs[2]) < 0.35, [(c.index, c.length) for c in cues]
assert [c.label for c in cues] == ["Band - Live Show", "가수 - 노래", "둘 - Second Song"] and cues[1].file == wavs[0]
assert all(c.score > 0.6 for c in cues), [c.score for c in cues]
print("  OK")

print("== cues.json 저장/로드 ==")
cj = daw / "cues.json"; bd.save_cues(cj, cues); loaded = bd.load_cues(cj, res.tracks)
assert [(c.index, round(c.start, 3), round(c.length, 3), round(c.offset, 3)) for c in loaded] == [(c.index, round(c.start, 3), round(c.length, 3), round(c.offset, 3)) for c in cues]
assert loaded[1].file == wavs[0] and loaded[1].label == "가수 - 노래"
print("  OK")

shutil.rmtree(root, ignore_errors=True)
print("\nALL OK")

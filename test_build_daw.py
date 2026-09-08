"""build_daw.py 오프라인 테스트 — ffmpeg 로 초소형 미디어를 만들어 WAV 디코드·무음 영상 분리·Reaper 세션(.rpp) 생성/파싱을 검증"""
import json, re, shutil, subprocess, sys, tempfile
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

print("== 프로젝트 준비 ==")
root = Path(tempfile.mkdtemp()); proj = root / "01.테스트"; dl = proj / "downloads"; dl.mkdir(parents=True)
ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2.5", "-c:a", "aac", str(dl / "01.가수-노래.m4a"))
ff("-f", "lavfi", "-i", "sine=frequency=880:duration=1.0", "-c:a", "aac", str(dl / "02.둘-Second_Song.m4a"))
ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1.5", "-f", "lavfi", "-i", "sine=frequency=660:duration=1.5",
   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dl / "03.Band-Live_Show.mp4"))
def dec(i, vid, title, name, ch, mode, artist):
    return pdl.Decision(index=i, id=vid, title=title, name=name, channel=ch, duration=2, mode=mode, reason="r",
                        url=f"https://www.youtube.com/watch?v={vid}", artist=artist)
items = [dec(1, "aaa", "노래", "가수-노래", "가수 - Topic", "audio", "가수"),
         dec(2, "bbb", "Second Song", "둘-Second Song", "둘 - Topic", "audio", "둘"),
         dec(3, "ccc", "Band - Live Show", "Band-Live Show", "BandVEVO", "video", "Band")]
pdl.write_manifest(proj, "https://x/pl", "테스트 목록", items)

print("== build_daw (gap 0) ==")
res = bd.build(proj)
daw = proj / "build" / "daw"
assert res.session == daw / "session.rpp" and res.session.exists()
wavs = [daw / "audio" / f for f in ("01.가수-노래.wav", "02.둘-Second_Song.wav", "03.Band-Live_Show.wav")]
assert all(w.exists() for w in wavs), list((daw / "audio").iterdir())
assert [t.wav for t in res.tracks] == wavs
assert all(streams(w) == [("audio", "pcm_s24le", "48000")] for w in wavs), [streams(w) for w in wavs]        # 48k/24bit WAV
vid = daw / "video" / "03.Band-Live_Show.mp4"
assert res.tracks[2].video == vid and vid.exists() and res.tracks[0].video is None
assert [s[0] for s in streams(vid)] == ["video"] and streams(vid)[0][1] == "h264", streams(vid)              # 무음 + 재인코딩 없음
durs = [bt.probe(w)["duration"] for w in wavs]
assert [t.length for t in res.tracks] == durs and [t.start for t in res.tracks] == [0.0, durs[0], durs[0] + durs[1]], res.tracks
assert [t.label for t in res.tracks] == ["가수 - 노래", "둘 - Second Song", "Band - Live Show"]
rpp = res.session.read_text(encoding="utf-8")
assert rpp.startswith("<REAPER_PROJECT") and "SAMPLERATE 48000" in rpp and rpp.count("<TRACK") == 1 and rpp.count("<ITEM") == 3
assert rpp.count("<SOURCE WAVE") == 3 and rpp.count("\nMARKER") + rpp.count("  MARKER") >= 3
assert "<NOTES 0 2\n    |테스트 목록\n  >" in rpp and "\n  NOTES " not in rpp        # 노트는 청크 형식 (REAPER Project Load Warning 재현 방지)
assert 'NAME "01 가수 - 노래"' in rpp and f'FILE "{wavs[0]}"' in rpp
print("  산출물·배치 OK")

print("== parse_rpp (생성 직후 → 라운드트립) ==")
cues = bd.parse_rpp(res.session)
assert [(c.index, c.label) for c in cues] == [(1, "가수 - 노래"), (2, "둘 - Second Song"), (3, "Band - Live Show")], cues
assert [c.start for c in cues] == [0.0, durs[0], durs[0] + durs[1]] and [c.length for c in cues] == durs and all(c.offset == 0.0 for c in cues)
assert [c.file for c in cues] == wavs
print("  라운드트립 OK")

print("== build_daw (gap 1.5) ==")
res2 = bd.build(proj, gap=1.5)
assert [t.start for t in res2.tracks] == [0.0, durs[0] + 1.5, durs[0] + durs[1] + 3.0]
print("  OK")

print("== 편집된 RPP 파싱 (Reaper 에서 이동·트림·순서 변경했다고 가정) ==")
edited = daw / "edited.rpp"
txt = res.session.read_text(encoding="utf-8")
# 2번 곡 아이템 블록만 골라 위치 200.5, 길이 0.6, 앞 0.25 초 트림(SOFFS)
chunks = txt.split("<ITEM")
k = next(i for i, c in enumerate(chunks) if 'NAME "02 ' in c)
c = chunks[k]
c = re.sub(r"(\n\s*POSITION )\S+", r"\g<1>200.5", c, count=1)
c = re.sub(r"(\n\s*LENGTH )\S+", r"\g<1>0.6", c, count=1)
c = re.sub(r"(\n\s*SOFFS )\S+", r"\g<1>0.25", c, count=1)
chunks[k] = c; txt = "<ITEM".join(chunks)
edited.write_text(txt, encoding="utf-8")
cues = bd.parse_rpp(edited)
c2 = next(c for c in cues if c.index == 2)
assert (c2.start, c2.length, c2.offset) == (200.5, 0.6, 0.25), c2
assert [c.index for c in cues] == [1, 3, 2], [c.index for c in cues]            # 타임라인 순서(위치순)로 정렬
print("  OK")

shutil.rmtree(root, ignore_errors=True)
print("\nALL OK")

#!/usr/bin/env python3
"""
build_timeline.py — 매니페스트(classification.json)대로 DaVinci Resolve 용 타임라인 템플릿을 만든다.

  python3 build_timeline.py 01.욕망은오랜병                 # → 01.욕망은오랜병/build/
  python3 build_timeline.py 01.욕망은오랜병 --fps 25 --gap 1.0
  python3 build_timeline.py 01.욕망은오랜병 --audio build/daw/mix.wav [--cues build/daw/cues.json]   # GarageBand 선편집 결과 반영 (mix 모드)

mix 모드: GarageBand 로 내보낸 믹스를 --audio 로 주면 build_daw.align_cues 가 믹스에서 곡 경계(시작·길이·앞 트림)를 복원해
  build/daw/cues.json 에 저장하고(--cues 로 손으로 고친 파일을 대신 줄 수 있다), A1 = mix 한 클립(스파인),
  V1 = 커버 정지 이미지/무음 영상(build/daw/video/)을 그 경계에 맞춰 연결(lane 1). 마커·SRT·description 도 같은 경계.

산출물 (build/ 는 절대경로가 들어가고 매니페스트에서 언제든 재생성되므로 gitignore):
  timeline.fcpxml   재생목록 순서대로 일렬 배치, 크로스페이드 없음(곡 사이 간격은 --gap 초).
                    음원 곡: V1 에 앨범아트 정지 이미지(곡 길이만큼) + A1 에 음원.  영상 곡: mp4 그대로.
                    곡 시작마다 "nn 아티스트 - 곡명" 마커.  1920x1080, --fps (기본 30).
  tracklist.srt     곡 구간마다 "아티스트 - 곡명" — Resolve 자막 트랙으로 불러와 '지금 재생 중' 표시용
  description.md    YouTube 설명문 초안: 챕터 타임스탬프 + 크레딧(파일 태그의 "Provided to YouTube by …", 원본 URL)
  covers/           m4a 에 임베드된 커버 추출 (없으면 black.png)

Resolve 에서: File > Import > Timeline > Import AAF, EDL, XML… 로 timeline.fcpxml 을 열고 (미디어는 downloads/ 절대경로로 자동 연결),
File > Import > Subtitle 로 tracklist.srt. 다른 머신에서는 playlist_dl.py --restore 뒤 이 스크립트를 다시 돌린다.

의존성: ffprobe/ffmpeg (brew install ffmpeg). 표준 라이브러리만 사용.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from playlist_dl import MEDIA_EXTS, Decision, read_manifest, safe_stem

STILL_CODECS = {"png", "mjpeg", "bmp", "gif", "webp"}  # 임베드된 커버(정지 이미지) 스트림으로 보는 코덱
_PROVIDER = re.compile(r"Provided to YouTube by (.+)")


class BuildError(RuntimeError):
    pass


@dataclass
class Track:
    decision: Decision
    path: Path  # 미디어 파일 (절대경로)
    label: str  # "아티스트 - 곡명"
    kind: str  # "audio" | "video" — 파일의 실제 영상 스트림 유무로 판단
    frames: int  # 길이 (프레임)
    start: int  # 타임라인 시작 프레임 (gap 포함)
    cover: Path | None  # 음원 곡의 배경 정지 이미지
    provider: str  # "Provided to YouTube by X" 의 X, 없으면 ""
    src_start: int = 0  # 영상 곡의 소스 시작 프레임 (mix 모드에서 앞 트림 반영)
    hold: int = 0  # 커버 정지 이미지를 화면에 두는 프레임 (0 이면 frames). mix 모드에선 다음 곡 시작까지 채워 V1 이 비지 않게


@dataclass
class BuildResult:
    fcpxml: Path
    srt: Path
    description: Path
    covers: Path
    tracks: list[Track]


# --------------------------------------------------------------------------- 시간 표기


def frame_time(frames: int, fps: int) -> str:
    """FCPXML 유리수 시간 ('75/30s'). 프레임 경계에 맞춰야 Resolve 가 받아준다"""
    return "0s" if frames == 0 else f"{frames}/{fps}s"


def chapter_ts(frames: int, fps: int) -> str:
    """YouTube 챕터용 'mm:ss' / 'h:mm:ss'"""
    s = frames // fps
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def srt_ts(frames: int, fps: int) -> str:
    ms = round(frames * 1000 / fps)
    h, r = divmod(ms, 3_600_000)
    m, r = divmod(r, 60_000)
    s, ms = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def track_label(d: Decision) -> str:
    """'아티스트 - 곡명'. 구버전 항목(artist 없음)은 name 그대로"""
    if d.artist and d.name.startswith(d.artist + "-"):
        return f"{d.artist} - {d.name[len(d.artist) + 1:]}"
    return d.name


# --------------------------------------------------------------------------- ffprobe / ffmpeg


def probe(path: Path, ffprobe: str = "ffprobe") -> dict:
    """duration(초), format 태그, 커버 스트림 (index, codec), 실제 영상 스트림 유무"""
    exe = shutil.which(ffprobe) or ffprobe
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration:format_tags=description,comment:stream=index,codec_type,codec_name",
         "-of", "json", str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise BuildError(f"ffprobe 실패: {path.name}: {proc.stderr.strip()}")
    d = json.loads(proc.stdout)
    vids = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    cover = next(((s["index"], s["codec_name"]) for s in vids if s.get("codec_name") in STILL_CODECS), None)
    return {
        "duration": float(d["format"]["duration"]),
        "tags": d.get("format", {}).get("tags", {}) or {},
        "cover": cover,
        "has_video": any(s.get("codec_name") not in STILL_CODECS for s in vids),
    }


def extract_cover(path: Path, cover: tuple[int, str], out_dir: Path, index: int, ffmpeg: str) -> Path | None:
    stream, codec = cover
    out = out_dir / f"{index:02d}{'.png' if codec == 'png' else '.jpg'}"
    proc = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(path), "-map", f"0:{stream}", "-frames:v", "1", "-c", "copy", str(out)],
                          capture_output=True, text=True)
    return out if proc.returncode == 0 and out.exists() else None


def black_png(out_dir: Path, ffmpeg: str) -> Path:
    out = out_dir / "black.png"
    if not out.exists():
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080", "-frames:v", "1", str(out)], check=True)
    return out


def provider_of(tags: dict) -> str:
    m = _PROVIDER.search(tags.get("description") or tags.get("comment") or "")
    return m.group(1).strip() if m else ""


# --------------------------------------------------------------------------- 산출물


def write_fcpxml(path: Path, title: str, tracks: list[Track], fps: int, gap_frames: int, total: int,
                 mix: tuple[Path, int] | None = None) -> None:
    """mix=(mix.wav, 프레임수) 이면 스파인은 mix 한 클립이고 곡 클립은 lane 1 에 연결된다"""
    root = ET.Element("fcpxml", version="1.8")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", name=f"FFVideoFormat1080p{fps}", frameDuration=f"1/{fps}s", width="1920", height="1080")
    ids: dict[str, str] = {}

    def asset(p: Path, **attrs: str) -> str:
        key = str(p)
        if key not in ids:
            ids[key] = f"r{len(ids) + 2}"
            ET.SubElement(res, "asset", id=ids[key], name=p.stem, src=p.as_uri(), start="0s", **attrs)
        return ids[key]

    project = ET.SubElement(ET.SubElement(ET.SubElement(root, "library"), "event", name=title), "project", name=title)
    seq = ET.SubElement(project, "sequence", format="r1", duration=frame_time(total, fps), tcStart="0s", tcFormat="NDF",
                        audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")
    if mix:
        mix_path, mix_frames = mix
        parent = ET.SubElement(spine, "asset-clip", ref=asset(mix_path, duration=frame_time(mix_frames, fps), hasVideo="0", hasAudio="1",
                                                              audioSources="1", audioChannels="2"),
                               offset="0s", name=title, start="0s", duration=frame_time(mix_frames, fps), audioRole="music")
        for t in tracks:  # 곡 클립은 mix 위 lane 1 (V1) 에 연결
            dur, offset = frame_time(t.frames, fps), frame_time(t.start, fps)
            if t.kind == "video":
                clip = ET.SubElement(parent, "asset-clip", ref=asset(t.path, duration=frame_time(t.src_start + t.frames, fps), hasVideo="1", hasAudio="0"),
                                     lane="1", offset=offset, name=t.label, start=frame_time(t.src_start, fps), duration=dur)
            else:
                clip = ET.SubElement(parent, "video", ref=asset(t.cover, duration="0s", hasVideo="1", hasAudio="0"),
                                     lane="1", offset=offset, name=t.label, start="0s", duration=frame_time(t.hold or t.frames, fps))
            ET.SubElement(clip, "marker", start=frame_time(t.src_start, fps), duration=frame_time(1, fps), value=f"{t.decision.index:02d} {t.label}")
        ET.indent(root)
        path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
        return
    for i, t in enumerate(tracks):
        if i and gap_frames:
            ET.SubElement(spine, "gap", name="Gap", offset=frame_time(t.start - gap_frames, fps), start="0s", duration=frame_time(gap_frames, fps))
        dur, offset = frame_time(t.frames, fps), frame_time(t.start, fps)
        if t.kind == "video":
            clip = ET.SubElement(spine, "asset-clip", ref=asset(t.path, duration=dur, hasVideo="1", hasAudio="1", audioSources="1", audioChannels="2"),
                                 offset=offset, name=t.label, start="0s", duration=dur, audioRole="music")
        else:  # 스파인에는 커버 정지 이미지, 음원은 아래 lane 에 연결 → V1 이 비지 않는다
            clip = ET.SubElement(spine, "video", ref=asset(t.cover, duration="0s", hasVideo="1", hasAudio="0"),
                                 offset=offset, name=t.label, start="0s", duration=dur)
            ET.SubElement(clip, "asset-clip", ref=asset(t.path, duration=dur, hasVideo="0", hasAudio="1", audioSources="1", audioChannels="2"),
                          lane="-1", offset="0s", name=t.label, start="0s", duration=dur, audioRole="music")
        ET.SubElement(clip, "marker", start="0s", duration=frame_time(1, fps), value=f"{t.decision.index:02d} {t.label}")
    ET.indent(root)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")


def write_srt(path: Path, tracks: list[Track], fps: int) -> None:
    blocks = [f"{i}\n{srt_ts(t.start, fps)} --> {srt_ts(t.start + t.frames, fps)}\n{t.label}" for i, t in enumerate(tracks, 1)]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_description(path: Path, title: str, playlist_url: str, tracks: list[Track], fps: int) -> None:
    lines = [f"# {title}", ""]
    if playlist_url:
        lines += [f"Playlist: {playlist_url}", ""]
    lines += ["## Tracklist", *(f"{chapter_ts(t.start, fps)} {t.label}" for t in tracks), "", "## Credits"]
    for t in tracks:
        source = f"Provided to YouTube by {t.provider}" if t.provider else (t.decision.channel or "")
        lines.append(" · ".join(x for x in (f"- {t.label}", source, t.decision.url) if x))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- 빌드


def locate_media(project_dir: Path, items: list[Decision]) -> dict[str, Path]:
    """downloads/ 에서 매니페스트 항목의 미디어 파일을 찾는다 (id → 경로). 하나라도 없으면 BuildError"""
    dl = project_dir / "downloads"
    files: dict[str, Path] = {}
    missing: list[str] = []
    for d in items:
        f = next((c for c in (dl / (safe_stem(d.index, d.name) + ext) for ext in sorted(MEDIA_EXTS)) if c.exists()), None)
        if f is None:
            missing.append(f"{d.index:02d} {d.name}")
        else:
            files[d.id] = f
    if missing:
        raise BuildError("downloads/ 에 파일이 없는 곡: " + ", ".join(missing)
                         + f"\n먼저 python3 playlist_dl.py --restore {project_dir.name} 으로 받으세요.")
    return files



def build(project_dir: Path | str, fps: int = 30, gap: float = 0.0, ffprobe: str | None = None, ffmpeg: str | None = None,
          audio: Path | str | None = None, cues: Path | str | None = None) -> BuildResult:
    """audio(GarageBand 믹스) 를 주면 mix 모드: 믹스에서 복원한(또는 cues.json 의) 곡 경계로 배치, A1 은 mix 하나"""
    ffprobe_exe, ffmpeg_exe = shutil.which(ffprobe or "ffprobe"), shutil.which(ffmpeg or "ffmpeg")
    if not ffprobe_exe or not ffmpeg_exe:
        raise BuildError("ffprobe/ffmpeg 를 찾을 수 없습니다 (brew install ffmpeg, 또는 --ffprobe/--ffmpeg 로 경로 지정)")
    project_dir = Path(project_dir).absolute()  # resolve() 는 macOS /var → /private/var 로 바꿔 호출자의 경로와 어긋난다
    meta, items = read_manifest(project_dir)
    files = locate_media(project_dir, items)

    build_dir = project_dir / "build"
    covers = build_dir / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    gap_frames = round(gap * fps)
    tracks: list[Track] = []
    mix: tuple[Path, int] | None = None

    def make_track(d: Decision, f: Path, frames: int, start: int, src_start: int = 0, video_path: Path | None = None) -> Track:
        info = probe(f, ffprobe_exe)
        kind = "video" if info["has_video"] else "audio"
        cover = None
        if kind == "audio":
            cover = extract_cover(f, info["cover"], covers, d.index, ffmpeg_exe) if info["cover"] else None
            cover = cover or black_png(covers, ffmpeg_exe)
        elif video_path is not None:
            if not video_path.exists():
                raise BuildError(f"무음 영상이 없습니다: {video_path.name} — 먼저 python3 build_daw.py {project_dir.name} 를 실행하세요.")
            f = video_path
        return Track(d, f, track_label(d), kind, frames, start, cover, provider_of(info["tags"]), src_start)

    if audio is not None or cues is not None:
        if audio is None:
            raise BuildError("--cues 에는 --audio (GarageBand 로 내보낸 mix.wav) 가 필요합니다.")
        import build_daw  # build_daw 가 이 모듈을 import 하므로 여기서 지연 import

        daw = build_daw.build(project_dir, ffmpeg=ffmpeg_exe, ffprobe=ffprobe_exe)  # WAV·무음 영상 (이미 있으면 건너뜀)
        mix_path = Path(audio).absolute()
        if cues is not None:
            cue_list = build_daw.load_cues(Path(cues), daw.tracks)
        else:
            cue_list = build_daw.align_cues(mix_path, daw.tracks, ffmpeg_exe)
            build_daw.save_cues(build_dir / "daw" / "cues.json", cue_list)
        by_index = {d.index: d for d in items}
        mix_frames = max(1, round(probe(mix_path, ffprobe_exe)["duration"] * fps))
        video_dir = build_dir / "daw" / "video"
        for c in cue_list:
            d = by_index[c.index]
            f = files[d.id]
            tracks.append(make_track(d, f, max(1, round(c.length * fps)), round(c.start * fps), round(c.offset * fps),
                                     video_dir / (safe_stem(d.index, d.name) + f.suffix)))
        total = max([mix_frames, *(t.start + t.frames for t in tracks)])
        for i, tr in enumerate(tracks):  # 커버 이미지는 다음 곡(또는 믹스 끝)까지
            if tr.kind == "audio":
                nxt = tracks[i + 1].start if i + 1 < len(tracks) else total
                tr.hold = max(tr.frames, nxt - tr.start)
        mix = (mix_path, mix_frames)
    else:
        pos = 0
        for d in items:
            f = files[d.id]
            frames = max(1, round(probe(f, ffprobe_exe)["duration"] * fps))
            tracks.append(make_track(d, f, frames, pos))
            pos += frames + gap_frames
        total = pos - gap_frames if tracks else 0  # 마지막 곡 뒤에는 gap 없음

    title = meta.get("title") or project_dir.name
    res = BuildResult(build_dir / "timeline.fcpxml", build_dir / "tracklist.srt", build_dir / "description.md", covers, tracks)
    write_fcpxml(res.fcpxml, title, tracks, fps, gap_frames, total, mix)
    write_srt(res.srt, tracks, fps)
    write_description(res.description, title, meta.get("url") or "", tracks, fps)
    return res


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dir", help="프로젝트 폴더 (classification.json 과 downloads/ 가 있는 곳)")
    p.add_argument("--fps", type=int, default=30, choices=[24, 25, 30, 60], help="타임라인 프레임레이트 (기본 30)")
    p.add_argument("--gap", type=float, default=0.0, metavar="SEC", help="곡 사이 간격 초 (기본 0)")
    p.add_argument("--audio", metavar="WAV", help="GarageBand 로 내보낸 믹스 (mix 모드). 곡 경계는 build_daw.align_cues 로 복원 → build/daw/cues.json")
    p.add_argument("--cues", metavar="JSON", help="align 결과를 손으로 고친 cues.json 을 대신 사용 (--audio 와 함께)")
    p.add_argument("--ffprobe", metavar="PATH")
    p.add_argument("--ffmpeg", metavar="PATH")
    args = p.parse_args()
    try:
        res = build(args.dir, fps=args.fps, gap=args.gap, ffprobe=args.ffprobe, ffmpeg=args.ffmpeg, audio=args.audio, cues=args.cues)
    except BuildError as e:
        sys.exit(str(e))
    for t in res.tracks:
        tag = "▶ VIDEO" if t.kind == "video" else "♪ AUDIO"
        print(f"[{t.decision.index:02d}] {chapter_ts(t.start, args.fps):>8}  {tag}  {t.label}  ({t.frames / args.fps:.1f}s)")
    last = res.tracks[-1] if res.tracks else None
    total = (last.start + last.frames) if last else 0
    print(f"\n총 {len(res.tracks)}곡 {chapter_ts(total, args.fps)}  →  {res.fcpxml.parent}/")
    print("  timeline.fcpxml   Resolve: File > Import > Timeline > Import AAF, EDL, XML…")
    print("  tracklist.srt     Resolve: File > Import > Subtitle")
    print("  description.md    YouTube 설명문 초안 (챕터 + 크레딧)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

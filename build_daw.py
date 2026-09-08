#!/usr/bin/env python3
"""
build_daw.py — 매니페스트(classification.json)대로 Reaper 세션을 만든다 (음원 선편집용).

  python3 build_daw.py 01.욕망은오랜병              # → 01.욕망은오랜병/build/daw/
  python3 build_daw.py 01.욕망은오랜병 --gap 1.0

산출물 (build/ 는 gitignore, 언제든 재생성):
  daw/audio/{nn}.{어간}.wav   19곡 전부 48kHz/24bit WAV 로 디코드 (영상 곡은 mp4 에서 오디오만). Reaper 가 확실히 읽고 샘플 단위 편집이 깔끔하다.
  daw/video/{nn}.{어간}.mp4   영상 곡을 무음으로 (재인코딩 없음, 임베드 커버 스트림 제외) — Resolve V1 용
  daw/session.rpp             Reaper 프로젝트: 트랙 1개에 재생목록 순서대로 일렬, 곡 시작 마커, 클릭 방지용 10ms 페이드, 크로스페이드 없음 (--gap 은 곡 간격)

흐름: Reaper 로 session.rpp 열어 편집(간격·트림·볼륨·페이드) → 저장 → File > Render 로 daw/mix.wav
  → python3 build_timeline.py DIR --session build/daw/session.rpp --audio build/daw/mix.wav
  (build_timeline 이 저장된 RPP 의 아이템 위치·길이·트림을 읽어 Resolve 템플릿의 곡 경계를 맞춘다. 마커 내보내기 불필요)

의존성: ffmpeg/ffprobe. 표준 라이브러리만 사용.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from build_timeline import BuildError, locate_media, probe, track_label
from playlist_dl import Decision, read_manifest, safe_stem

FADE_SEC = 0.01  # 아이템 양끝 페이드 (클릭 방지용, 크로스페이드 아님)


@dataclass
class DawTrack:
    decision: Decision
    wav: Path
    video: Path | None  # 영상 곡의 무음 mp4
    label: str
    start: float  # 초
    length: float  # 초


@dataclass
class DawResult:
    session: Path
    audio_dir: Path
    video_dir: Path
    tracks: list[DawTrack]


@dataclass
class Cue:
    """편집된 세션에서 읽은 곡 하나의 타임라인 정보 (초)"""
    index: int
    label: str
    start: float
    length: float
    offset: float  # 소스 시작 오프셋 (앞부분 트림)
    file: Path


# --------------------------------------------------------------------------- ffmpeg


def decode_wav(src: Path, dst: Path, ffmpeg: str) -> None:
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s24le", str(dst)], check=True)


def strip_audio(src: Path, dst: Path, ffmpeg: str) -> None:
    """첫 영상 스트림만 복사 (임베드 커버 png 스트림·오디오 제외)"""
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-an", "-c:v", "copy", str(dst)], check=True)


def _fresh(dst: Path, src: Path) -> bool:
    return dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime


# --------------------------------------------------------------------------- RPP 쓰기


def _guid() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _quote(s: str) -> str:
    """Reaper 문자열 인용: 큰따옴표가 있으면 작은따옴표, 둘 다 있으면 백틱"""
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    return "`" + s.replace("`", "'") + "`"


def write_rpp(path: Path, title: str, tracks: list[DawTrack]) -> None:
    fade = f"1 {FADE_SEC:g} 0 1 0 0 0"
    lines = [f'<REAPER_PROJECT 0.1 "7.0/macOS-arm64" {int(time.time())}',
             "  RIPPLE 0", "  GROUPOVERRIDE 0 0 0", "  AUTOXFADE 0", "  SAMPLERATE 48000 0 0", "  TEMPO 120 4 4",
             "  <NOTES 0 2", f"    |{title}", "  >"]  # 프로젝트 노트는 청크 형식이어야 한다 (평문 NOTES 줄은 REAPER 가 "not understood" 경고)
    for i, t in enumerate(tracks, 1):
        lines.append(f"  MARKER {i} {t.start:.6f} {_quote(f'{t.decision.index:02d} {t.label}')} 0 0 1 R {_guid()} 0")
    lines += [f"  <TRACK {_guid()}", f"    NAME {_quote(title)}", "    PEAKCOL 16576", "    VOLPAN 1 0 -1 -1 1", "    MUTESOLO 0 0 0"]
    for i, t in enumerate(tracks, 1):
        lines += ["    <ITEM",
                  f"      POSITION {t.start:.6f}", "      SNAPOFFS 0", f"      LENGTH {t.length:.6f}", "      LOOP 0", "      ALLTAKES 0",
                  f"      FADEIN {fade}", f"      FADEOUT {fade}", "      MUTE 0 0", "      SEL 0",
                  f"      IGUID {_guid()}", f"      IID {i}", f"      NAME {_quote(f'{t.decision.index:02d} {t.label}')}",
                  "      VOLPAN 1 0 1 -1", "      SOFFS 0", "      PLAYRATE 1 1 0 -1 0 0.0025", "      CHANMODE 0",
                  f"      GUID {_guid()}", "      <SOURCE WAVE", f"        FILE {_quote(str(t.wav))}", "      >", "    >"]
    lines += ["  >", ">"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- RPP 읽기

_ITEM_NAME = re.compile(r"^(\d+)\s+(.*)$")


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        return s[1:-1]
    return s


def parse_rpp(path: Path) -> list[Cue]:
    """저장된 .rpp 에서 아이템(POSITION/LENGTH/SOFFS/NAME/FILE)을 읽어 타임라인 순서의 Cue 목록으로.
    곡 번호는 아이템 이름의 'nn ' 접두어에서 온다 (우리가 붙인 그대로 두면 된다)."""
    cues: list[Cue] = []
    depth, item_depth, cur = 0, None, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("<"):
            depth += 1
            if line.startswith("<ITEM"):
                item_depth, cur = depth, {}
            continue
        if line == ">":
            if cur is not None and depth == item_depth:
                m = _ITEM_NAME.match(cur.get("NAME", ""))
                if m and "FILE" in cur:
                    cues.append(Cue(int(m.group(1)), m.group(2).strip(), float(cur.get("POSITION", 0)), float(cur.get("LENGTH", 0)),
                                    float(cur.get("SOFFS", 0)), Path(cur["FILE"])))
                cur, item_depth = None, None
            depth -= 1
            continue
        if cur is not None:
            key, _, val = line.partition(" ")
            if key in ("POSITION", "LENGTH", "SOFFS"):
                cur[key] = val.split()[0]
            elif key in ("NAME", "FILE") and key not in cur:  # 첫 FILE (SOURCE) 만
                cur[key] = _unquote(val)
    return sorted(cues, key=lambda c: c.start)


# --------------------------------------------------------------------------- 빌드


def build(project_dir: Path | str, gap: float = 0.0, ffmpeg: str | None = None, ffprobe: str | None = None) -> DawResult:
    ffmpeg_exe, ffprobe_exe = shutil.which(ffmpeg or "ffmpeg"), shutil.which(ffprobe or "ffprobe")
    if not ffmpeg_exe or not ffprobe_exe:
        raise BuildError("ffmpeg/ffprobe 를 찾을 수 없습니다 (brew install ffmpeg)")
    project_dir = Path(project_dir).absolute()
    meta, items = read_manifest(project_dir)
    files = locate_media(project_dir, items)
    daw = project_dir / "build" / "daw"
    audio_dir, video_dir = daw / "audio", daw / "video"
    audio_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    tracks: list[DawTrack] = []
    pos = 0.0
    for d in items:
        src = files[d.id]
        stem = safe_stem(d.index, d.name)
        wav = audio_dir / f"{stem}.wav"
        if not _fresh(wav, src):
            decode_wav(src, wav, ffmpeg_exe)
        video = None
        if probe(src, ffprobe_exe)["has_video"]:
            video = video_dir / f"{stem}{src.suffix}"
            if not _fresh(video, src):
                strip_audio(src, video, ffmpeg_exe)
        length = probe(wav, ffprobe_exe)["duration"]
        tracks.append(DawTrack(d, wav, video, track_label(d), pos, length))
        pos += length + gap

    session = daw / "session.rpp"
    write_rpp(session, meta.get("title") or project_dir.name, tracks)
    return DawResult(session, audio_dir, video_dir, tracks)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dir", help="프로젝트 폴더 (classification.json 과 downloads/)")
    p.add_argument("--gap", type=float, default=0.0, metavar="SEC", help="곡 사이 간격 초 (기본 0)")
    p.add_argument("--ffmpeg", metavar="PATH")
    p.add_argument("--ffprobe", metavar="PATH")
    args = p.parse_args()
    try:
        res = build(args.dir, gap=args.gap, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    except BuildError as e:
        sys.exit(str(e))
    for t in res.tracks:
        m, s = divmod(int(t.start), 60)
        print(f"[{t.decision.index:02d}] {m:02d}:{s:02d}  {t.label}  ({t.length:.1f}s){'  +video' if t.video else ''}")
    print(f"\n{len(res.tracks)}곡 → {res.session}")
    print("  Reaper 로 열어 편집 → 저장 → File > Render 로 build/daw/mix.wav (48kHz)")
    print(f"  그다음: python3 build_timeline.py {Path(args.dir)} --session build/daw/session.rpp --audio build/daw/mix.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())

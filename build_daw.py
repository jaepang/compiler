#!/usr/bin/env python3
"""
build_daw.py — GarageBand 에서 음원을 선편집하기 위한 소스 준비와, 내보낸 믹스에서 곡 경계 복원.

  python3 build_daw.py 01.욕망은오랜병                          # build/daw/audio/*.wav, build/daw/video/*.mp4 준비 + 순서표 출력
  python3 build_daw.py 01.욕망은오랜병 --align build/daw/mix.wav   # GarageBand 로 내보낸 믹스에서 곡 경계 복원 → build/daw/cues.json

산출물 (build/ 는 gitignore, 언제든 재생성):
  daw/audio/{nn}.{어간}.wav   19곡 전부 48kHz/24bit WAV (영상 곡은 오디오만) — GarageBand 에 순서대로 끌어다 놓는다
  daw/video/{nn}.{어간}.mp4   영상 곡을 무음으로 (재인코딩 없음, 임베드 커버 스트림 제외) — Resolve V1 용
  daw/cues.json              --align 결과. 곡별 시작·길이·앞 트림·매칭 점수. 손으로 고쳐 build_timeline --cues 로 넘길 수 있다

흐름: GarageBand 에 WAV 를 순서대로 배치·편집(간격·트림·볼륨·페이드) → Share > Export Song to Disk (WAV/AIFF, 48kHz) → daw/mix.wav
  → python3 build_timeline.py DIR --audio build/daw/mix.wav
  GarageBand 는 마커를 내보내지 못하므로 곡 경계는 믹스에서 복원한다: 원곡 중간 부분의 라우드니스 곡선(ebur128, 0.1s)을 믹스에서
  상관으로 찾아 곡 전체를 정렬한 뒤, 두 곡선이 같아지는 구간으로 시작(앞 트림)·끝을 정한다 (순서 변경·볼륨 변경·트림·간격 0 에 강함).

의존성: ffmpeg/ffprobe. 표준 라이브러리만 사용.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from build_timeline import BuildError, locate_media, probe, track_label
from playlist_dl import Decision, read_manifest, safe_stem

TEMPLATE_SEC = 15.0  # 매칭에 쓰는 원곡 구간 길이 (곡 중앙)
MATCH_WIN_SEC = 2.0  # 시작/끝 판정 창
MATCH_DB = 4.0  # 정렬된 믹스·원곡 곡선의 창 평균 차이가 이 아래면 "같은 소리"
EDGE_DB = 3.0  # 경계 샘플 자체는 이 안이어야 한다 (창 평균만 보면 첫 샘플의 무음이 뒤 샘플에 상쇄돼 0.4s 이르게 잡힌다)
FLOOR_DB = -70.0  # ebur128 이 무음/창 미충족 구간에 주는 바닥값 (-inf 를 이걸로 바닥 처리)
MOMENTARY_SEC = 0.4  # ebur128 Momentary 창 길이. 소리가 시작된 뒤 이만큼 지나야 곡선이 온전해지므로 경계에서 되돌린다
REFINE = 6  # 템플릿 정렬 미세 보정 범위 (샘플, 0.1s 단위)


@dataclass
class DawTrack:
    decision: Decision
    wav: Path
    video: Path | None  # 영상 곡의 무음 mp4
    label: str
    length: float  # 초


@dataclass
class DawResult:
    audio_dir: Path
    video_dir: Path
    tracks: list[DawTrack]


@dataclass
class Cue:
    """믹스 안에서 곡 하나의 위치 (초)"""
    index: int
    label: str
    start: float
    length: float
    offset: float  # 원곡 앞에서 잘린 길이 (소스 시작 오프셋)
    file: Path
    score: float = 1.0  # 라우드니스 곡선 상관 (1 에 가까울수록 확실)


# --------------------------------------------------------------------------- ffmpeg


def decode_wav(src: Path, dst: Path, ffmpeg: str) -> None:
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s24le", str(dst)], check=True)


def strip_audio(src: Path, dst: Path, ffmpeg: str) -> None:
    """첫 영상 스트림만 복사 (임베드 커버 png 스트림·오디오 제외)"""
    subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-an", "-c:v", "copy", str(dst)], check=True)


def _fresh(dst: Path, src: Path) -> bool:
    return dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime


_EBUR = re.compile(r"t:\s*([\d.]+)\s+TARGET:\S+\s+LUFS\s+M:\s*(-?[\d.]+|-inf|nan)")


def loudness_envelope(path: Path, ffmpeg: str) -> tuple[list[float], list[float]]:
    """(시각, 순간 라우드니스 dB) — ebur128 의 100ms Momentary. 무음은 -70 으로 바닥"""
    proc = subprocess.run([ffmpeg, "-nostats", "-i", str(path), "-af", "ebur128=peak=none", "-f", "null", "-"], capture_output=True, text=True)
    ts, vals = [], []
    for m in _EBUR.finditer(proc.stderr):
        v = m.group(2)
        ts.append(float(m.group(1)))
        vals.append(max(-70.0, float(v)) if v not in ("-inf", "nan") else -70.0)
    if len(ts) < 2:
        raise BuildError(f"라우드니스 곡선을 얻지 못했습니다: {path.name}")
    return ts, vals


# --------------------------------------------------------------------------- 정렬 (곡 경계 복원)


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sxx = syy = 0.0
    for a, b in zip(x, y):
        da, db = a - mx, b - my
        sxy += da * db
        sxx += da * da
        syy += db * db
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def _best_match(mix: list[float], tmpl: list[float]) -> tuple[int, float]:
    """tmpl 이 mix 안에서 가장 잘 맞는 위치(인덱스)와 상관. 거친 탐색(뭉치 평균) 뒤 그 근처만 정밀 탐색"""
    n, m = len(mix), len(tmpl)
    if m > n:
        return 0, 0.0
    factor = max(1, m // 40)
    if factor > 1:
        cm = [sum(mix[i:i + factor]) / factor for i in range(0, n - factor + 1, factor)]
        ct = [sum(tmpl[i:i + factor]) / factor for i in range(0, m - factor + 1, factor)]
        best_c, best_r = 0, -2.0
        for p in range(len(cm) - len(ct) + 1):
            r = _pearson(cm[p:p + len(ct)], ct)
            if r > best_r:
                best_r, best_c = r, p
        lo, hi = max(0, best_c * factor - 2 * factor), min(n - m, best_c * factor + 2 * factor)
    else:
        lo, hi = 0, n - m
    best_p, best_r = lo, -2.0
    for p in range(lo, hi + 1):
        r = _pearson(mix[p:p + m], tmpl)
        if r > best_r:
            best_r, best_p = r, p
    return best_p, best_r


def align_cues(mix: Path, tracks: list[DawTrack], ffmpeg: str | None = None) -> list[Cue]:
    """GarageBand 가 내보낸 믹스에서 각 곡의 시작·길이·앞 트림을 찾는다. 결과는 타임라인 순서.

    1) 원곡 중앙 TEMPLATE_SEC 의 라우드니스 곡선을 믹스에서 상관으로 찾아 곡 전체를 믹스 시간축에 정렬한다.
    2) 정렬된 두 곡선의 차이 D=|믹스-원곡-이득| 을 보고, 앞에서부터 MATCH_WIN_SEC 창 평균 D 가 MATCH_DB 아래로
       처음 들어오는 지점을 시작(= 앞 트림), 뒤에서부터 같은 조건의 마지막 지점을 끝으로 잡는다.
       무음 감지에 의존하지 않으므로 조용한 인트로/아웃트로나 간격 0 에도 흔들리지 않는다."""
    ffmpeg_exe = shutil.which(ffmpeg or "ffmpeg")
    if not ffmpeg_exe:
        raise BuildError("ffmpeg 를 찾을 수 없습니다")
    mix = Path(mix)
    mt, menv = loudness_envelope(mix, ffmpeg_exe)
    step, n_mix = mt[1] - mt[0], len(menv)
    W = max(3, int(MATCH_WIN_SEC / step))

    cues: list[Cue] = []
    for t in tracks:
        st, senv = loudness_envelope(t.wav, ffmpeg_exe)
        n = len(senv)
        span = max(5, min(n // 2, int(TEMPLATE_SEC / step)))  # 곡 중앙 50% (최대 TEMPLATE_SEC) — 조용한 인트로·트림된 앞부분·창 미충족 구간을 피한다
        a = max(0, (n - span) // 2)
        p, r = _best_match(menv, senv[a:a + span])
        diffs = sorted(menv[p + i] - senv[a + i] for i in range(span))
        gain = diffs[span // 2]

        def d_at(base_: int, i: int) -> float:
            j = base_ + i
            if not 0 <= j < n_mix:
                return 99.0
            if senv[i] <= FLOOR_DB + 1 and menv[j] <= FLOOR_DB + 1:
                return 0.0  # 둘 다 디지털 무음 — 이득 보정을 적용하면 |gain| 만큼 어긋난 것처럼 보이므로 같은 것으로 본다
            return abs(menv[j] - senv[i] - gain)

        # 템플릿 상관은 0.1~0.5s 어긋날 수 있다 → ±REFINE 범위에서 곡 전체 '일치 샘플 수' 가 최대인 정렬로 보정
        base = max(range(p - a - REFINE, p - a + REFINE + 1),
                   key=lambda b: sum(1 for i in range(n) if senv[i] > FLOOR_DB + 5 and d_at(b, i) < EDGE_DB))

        def d(i: int) -> float:
            return d_at(base, i)

        def matches(i: int) -> bool:  # [i, i+W) 창 평균 차이가 임계 아래
            return sum(d(k) for k in range(i, i + W)) / W < MATCH_DB

        # 곡 앞 MOMENTARY_SEC 는 창이 채워지기 전이라 -70 이 찍히는 인공 구간 → 탐색에서 뺀다 (믹스의 무음과 "일치"해 보이는 것을 막음).
        # 조용한 인트로는 둘 다 조용해서 d 가 작으니 정상적으로 시작으로 잡힌다.
        i_min = min(a, int(round(MOMENTARY_SEC / step)))
        i0 = next((i for i in range(i_min, a + 1) if d(i) < EDGE_DB and matches(i)), a)
        i1 = next((i for i in range(n - W, a + span - W - 1, -1) if d(i + W - 1) < EDGE_DB and matches(i)), a + span - W) + W  # 마지막으로 맞는 창의 끝 (exclusive)
        # 샘플 i 의 창은 [st[i]-MOMENTARY, st[i]] 를 본다. 첫 탐색 샘플에서 바로 맞으면 트림 없음(0), 아니면 창 시작이 실제 소리 시작
        onset = 0.0 if i0 == i_min else max(0.0, st[i0] - MOMENTARY_SEC)
        origin = base * step  # 원곡 시각 0 이 놓이는 믹스 시각 (두 곡선의 시간축이 같은 격자라 st[0] == mt[0])
        start = max(0.0, origin + onset)
        end = min(origin + st[i1 - 1], mt[-1])
        cues.append(Cue(t.decision.index, t.label, start, max(0.1, end - start), onset, t.wav, r))
    return sorted(cues, key=lambda c: c.start)


def save_cues(path: Path, cues: list[Cue]) -> None:
    path.write_text(json.dumps([{**asdict(c), "file": str(c.file)} for c in cues], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_cues(path: Path, tracks: list[DawTrack]) -> list[Cue]:
    """cues.json (손으로 고친 것 포함) → Cue. file/label 은 index 로 트랙에서 다시 채운다"""
    by_index = {t.decision.index: t for t in tracks}
    cues = []
    for d in json.loads(Path(path).read_text(encoding="utf-8")):
        t = by_index.get(int(d["index"]))
        if t is None:
            raise BuildError(f"cues.json 의 index {d['index']} 에 해당하는 곡이 없습니다")
        cues.append(Cue(t.decision.index, d.get("label") or t.label, float(d["start"]), float(d["length"]), float(d.get("offset", 0.0)),
                        t.wav, float(d.get("score", 1.0))))
    return sorted(cues, key=lambda c: c.start)


# --------------------------------------------------------------------------- 소스 준비


def build(project_dir: Path | str, ffmpeg: str | None = None, ffprobe: str | None = None) -> DawResult:
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
        tracks.append(DawTrack(d, wav, video, track_label(d), probe(wav, ffprobe_exe)["duration"]))
    return DawResult(audio_dir, video_dir, tracks)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dir", help="프로젝트 폴더 (classification.json 과 downloads/)")
    p.add_argument("--align", metavar="MIX", help="GarageBand 로 내보낸 믹스(wav/aiff)에서 곡 경계를 복원해 build/daw/cues.json 에 저장")
    p.add_argument("--ffmpeg", metavar="PATH")
    p.add_argument("--ffprobe", metavar="PATH")
    args = p.parse_args()
    try:
        res = build(args.dir, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
        if args.align:
            cues = align_cues(Path(args.align), res.tracks, args.ffmpeg)
            out = Path(args.dir) / "build" / "daw" / "cues.json"
            save_cues(out, cues)
            for c in cues:
                m, s = divmod(int(c.start), 60)
                flag = "" if c.score >= 0.6 else "  ← 점수 낮음, cues.json 확인"
                print(f"[{c.index:02d}] {m:02d}:{s:02d}  {c.label}  ({c.length:.1f}s, 앞 트림 {c.offset:.1f}s, 점수 {c.score:.2f}){flag}")
            print(f"\n{len(cues)}곡 → {out}\n  다음: python3 build_timeline.py {args.dir} --audio {args.align}")
            return 0
    except BuildError as e:
        sys.exit(str(e))
    for t in res.tracks:
        print(f"[{t.decision.index:02d}] {t.label}  ({t.length:.1f}s){'  +video' if t.video else ''}")
    print(f"\n{len(res.tracks)}곡 → {res.audio_dir}")
    print("  GarageBand: 빈 프로젝트에 위 순서대로 WAV 를 끌어다 놓고 편집 → Share > Export Song to Disk (WAV, 48kHz) → build/daw/mix.wav")
    print(f"  그다음: python3 build_timeline.py {Path(args.dir)} --audio build/daw/mix.wav")
    return 0


if __name__ == "__main__":
    sys.exit(main())

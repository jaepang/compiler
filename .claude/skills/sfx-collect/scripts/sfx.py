#!/usr/bin/env python3
"""sfx.py — 레포 루트 sfx/ 효과음 라이브러리와 sfx/manifest.json 관리 (표준 라이브러리 + ffprobe/ffmpeg).

  sfx.py add FILE --kind oneshot|loop|ambience --category vinyl --source pixabay --page-url URL --license "…"
             [--download-url URL] [--attribution "…"] [--tags a,b] [--id slug] [--note "…"] [--wav]
  sfx.py list [--tags a,b] [--kind …]
  sfx.py credits [--all]            표기 필요한 항목의 크레딧 문구 (설명문용)
  sfx.py restore                    download_url 이 있는데 파일이 없는 항목을 curl 로 다시 받는다
  sfx.py check ID|FILE              길이·평균 볼륨·(루프) 앞뒤 라우드니스 차

레포 루트는 이 스크립트 위치(.claude/skills/sfx-collect/scripts)에서 올라가 찾는다. 오디오는 gitignore, manifest.json 만 커밋.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # …/.claude/skills/sfx-collect/scripts → 레포 루트
SFX = ROOT / "sfx"
MANIFEST = SFX / "manifest.json"
KINDS = ("oneshot", "loop", "ambience")


def load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"items": []}


def save(doc: dict) -> None:
    SFX.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "sound"


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=sample_rate,codec_name,channels",
                          "-of", "json", str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"ffprobe 실패: {path}: {out.stderr.strip()}")
    d = json.loads(out.stdout)
    a = next((s for s in d.get("streams", []) if s.get("codec_name")), {})
    return {"duration": round(float(d["format"]["duration"]), 3), "sample_rate": int(a.get("sample_rate") or 0),
            "codec": a.get("codec_name", ""), "channels": int(a.get("channels") or 0)}


def mean_volume(path: Path, ss: float | None = None, t: float | None = None) -> float:
    cmd = ["ffmpeg", "-nostats", "-i", str(path)]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    if t is not None:
        cmd += ["-t", str(t)]
    cmd += ["-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", err)
    return float(m.group(1)) if m else -99.0


def cmd_add(a: argparse.Namespace) -> int:
    src = Path(a.file).expanduser()
    if not src.exists():
        sys.exit(f"파일이 없습니다: {src}")
    if a.kind not in KINDS:
        sys.exit(f"--kind 는 {KINDS} 중 하나")
    doc = load()
    sid = slugify(a.id or f"{src.stem}-{a.source}")
    if any(i["id"] == sid for i in doc["items"]):
        sys.exit(f"이미 있는 id: {sid} (다른 --id 를 주거나 list 로 확인)")
    category = slugify(a.category)
    dest_dir = SFX / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    if a.wav:
        dest = dest_dir / f"{sid}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ar", "48000", "-c:a", "pcm_s24le", str(dest)], check=True)
    else:
        dest = dest_dir / f"{sid}{src.suffix.lower()}"
        shutil.copy2(src, dest)
    info = probe(dest)
    attribution = a.attribution or ""
    item = {"id": sid, "kind": a.kind, "category": category, "tags": [t.strip() for t in (a.tags or "").split(",") if t.strip()],
            "file": str(dest.relative_to(SFX)), "source": a.source, "source_id": a.source_id or "", "page_url": a.page_url,
            "download_url": a.download_url or "", "license": a.license, "attribution_required": bool(attribution),
            "attribution": attribution, "duration": info["duration"], "sample_rate": info["sample_rate"], "codec": info["codec"],
            "added": dt.date.today().isoformat(), "note": a.note or ""}
    doc["items"].append(item)
    save(doc)
    vol = mean_volume(dest)
    print(f"등록: sfx/{item['file']}  {info['duration']:.1f}s  {info['sample_rate']}Hz {info['codec']}  mean {vol:.1f}dB  [{a.license}]")
    if vol < -60:
        print("  ! 평균 볼륨이 -60dB 아래 — 무음/깨진 파일일 수 있음")
    if attribution:
        print(f"  크레딧 필요: {attribution}")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    want = {t.strip() for t in (a.tags or "").split(",") if t.strip()}
    for i in load()["items"]:
        if a.kind and i["kind"] != a.kind:
            continue
        if want and not want & set(i["tags"]):
            continue
        flag = "표기" if i["attribution_required"] else "무표기"
        exists = "" if (SFX / i["file"]).exists() else "  (파일 없음 → restore)"
        print(f"{i['id']:40s} {i['kind']:8s} {i['duration']:7.1f}s  {i['source']:9s} {flag:4s}  sfx/{i['file']}{exists}")
    return 0


def cmd_credits(a: argparse.Namespace) -> int:
    for i in load()["items"]:
        if i["attribution_required"]:
            print(f"- {i['attribution']}")
        elif a.all:
            print(f"- {i['id']}: {i['license']} ({i['source']}, {i['page_url']})")
    return 0


def cmd_restore(a: argparse.Namespace) -> int:
    missing = 0
    for i in load()["items"]:
        dest = SFX / i["file"]
        if dest.exists():
            continue
        missing += 1
        if i["download_url"]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"받는 중: {i['id']} ← {i['download_url']}")
            subprocess.run(["curl", "-L", "-sS", "-o", str(dest), i["download_url"]], check=True)
        else:
            print(f"브라우저 다운로드 필요: {i['id']} → {i['page_url']} (sfx-collect 스킬로 다시 받아 같은 --id 로 add)")
    print("누락 없음" if not missing else f"누락 {missing}개 처리")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    doc = load()
    item = next((i for i in doc["items"] if i["id"] == a.target), None)
    path = SFX / item["file"] if item else Path(a.target)
    info = probe(path)
    vol = mean_volume(path)
    print(f"{path.name}: {info['duration']:.2f}s {info['sample_rate']}Hz {info['codec']} mean {vol:.1f}dB")
    if (item and item["kind"] == "loop") or a.loop:
        head, tail = mean_volume(path, 0, 1.0), mean_volume(path, max(0.0, info["duration"] - 1.0), 1.0)
        print(f"  루프 이음새: 앞 1초 {head:.1f}dB / 뒤 1초 {tail:.1f}dB  (차이 {abs(head - tail):.1f}dB — 3dB 안이면 무난)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add"); s.add_argument("file"); s.add_argument("--kind", required=True); s.add_argument("--category", required=True)
    s.add_argument("--source", required=True); s.add_argument("--source-id"); s.add_argument("--page-url", required=True); s.add_argument("--license", required=True)
    s.add_argument("--download-url"); s.add_argument("--attribution"); s.add_argument("--tags"); s.add_argument("--id"); s.add_argument("--note"); s.add_argument("--wav", action="store_true")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("list"); s.add_argument("--tags"); s.add_argument("--kind"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("credits"); s.add_argument("--all", action="store_true"); s.set_defaults(fn=cmd_credits)
    s = sub.add_parser("restore"); s.set_defaults(fn=cmd_restore)
    s = sub.add_parser("check"); s.add_argument("target"); s.add_argument("--loop", action="store_true"); s.set_defaults(fn=cmd_check)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

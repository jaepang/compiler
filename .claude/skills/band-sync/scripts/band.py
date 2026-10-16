#!/usr/bin/env python3
"""band.py — GarageBand 프로젝트(.band) 원본은 iCloud Drive 에, 레포 프로젝트 폴더에는 심볼릭 링크만 (표준 라이브러리만).

  band.py status [PROJECT]          프로젝트마다 .band 상태 (linked / unlinked / local / broken / diverged, 미다운로드 파일 수)
  band.py adopt PROJECT [--force]   이 맥의 실제 .band 를 iCloud 로 옮기고 그 자리에 링크
  band.py link [PROJECT] [--force]  iCloud 에 있는 .band 를 레포의 같은 폴더에 링크 + iCloud 다운로드 강제

원본: ~/Library/Mobile Documents/com~apple~CloudDocs/compiler/<PROJECT>/<이름>.band  (BAND_ICLOUD_ROOT 로 대체 가능 — 테스트용)
링크: <레포>/<PROJECT>/<이름>.band → 원본 절대경로. *.band 는 gitignore 라 링크도 커밋되지 않는다.
GarageBand 가 실행 중이면 adopt/link 는 멈춘다 (--force 로 무시). 같은 프로젝트를 두 맥에서 동시에 열지 않는다 — iCloud 가 충돌 사본을 만든다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BAND_REPO") or Path(__file__).resolve().parents[4])  # …/.claude/skills/band-sync/scripts → 레포 루트
ICLOUD = Path(os.environ.get("BAND_ICLOUD_ROOT") or Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/compiler")
APP = os.environ.get("BAND_APP_NAME", "GarageBand")
SF_DATALESS = 0x40000000  # iCloud 가 내용을 비워 둔(아직 안 받은) 파일의 st_flags


def projects() -> list[Path]:
    return sorted(d for d in ROOT.iterdir() if d.is_dir() and (d / "classification.json").exists())


def pending(pkg: Path) -> list[Path]:
    """아직 iCloud 에서 내려오지 않은 파일 — 구버전 `.이름.icloud` 자리표시자 또는 dataless 플래그."""
    out = []
    for p in pkg.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        if p.name.endswith(".icloud") or getattr(p.lstat(), "st_flags", 0) & SF_DATALESS:
            out.append(p)
    return out


def state(link: Path, cloud: Path) -> str:
    if link.is_symlink():
        if not link.exists():
            return "broken"
        return "linked" if link.resolve() == cloud.resolve() else "foreign"
    if link.is_dir():
        return "diverged" if cloud.exists() else "local"
    return "unlinked" if cloud.exists() else "none"


def bands(proj: Path) -> list[str]:
    names = {p.name for p in proj.glob("*.band")}
    if (ICLOUD / proj.name).is_dir():
        names |= {p.name for p in (ICLOUD / proj.name).glob("*.band")}
    return sorted(names)


def pick(name: str | None) -> list[Path]:
    if name is None:
        return projects()
    proj = ROOT / name.rstrip("/")
    if not proj.is_dir():
        sys.exit(f"프로젝트 폴더 없음: {proj}")
    return [proj]


def app_guard(force: bool) -> None:
    if force:
        return
    if subprocess.run(["pgrep", "-x", APP], capture_output=True).returncode == 0:
        sys.exit(f"{APP} 가 실행 중이다 — 프로젝트를 닫고 앱을 종료한 뒤 다시 실행 (무시하려면 --force)")


def materialize(pkg: Path) -> list[Path]:
    """brctl 로 다운로드를 요청하고, 남은 dataless 파일은 끝까지 읽어 내려받게 한다. 남은 파일 목록을 돌려준다."""
    if shutil.which("brctl"):
        subprocess.run(["brctl", "download", str(pkg)], capture_output=True)
    for p in pending(pkg):
        if p.name.endswith(".icloud"):
            continue  # 자리표시자는 읽어도 원본이 안 온다 — brctl/Finder 에 맡긴다
        try:
            with p.open("rb") as f:
                while f.read(1 << 20):
                    pass
        except OSError as e:
            print(f"  ! 읽기 실패 {p.name}: {e}")
    return pending(pkg)


def cmd_status(a: argparse.Namespace) -> int:
    print(f"iCloud: {ICLOUD}")
    for proj in pick(a.project):
        for name in bands(proj):
            link, cloud = proj / name, ICLOUD / proj.name / name
            st = state(link, cloud)
            extra = ""
            if st == "linked":
                n = len(pending(cloud))
                extra = f"  미다운로드 {n}개 — band.py link {proj.name}" if n else ""
            elif st == "diverged":
                extra = "  ! 레포 쪽이 실제 폴더로 바뀜(GarageBand 저장이 링크를 덮었을 수 있다) — 어느 쪽이 최신인지 확인 필요"
            elif st == "local":
                extra = f"  → band.py adopt {proj.name}"
            elif st == "unlinked":
                extra = f"  → band.py link {proj.name}"
            elif st == "foreign":
                extra = f"  ! 다른 곳을 가리킴: {os.readlink(link)}"
            print(f"{st:9} {proj.name}/{name}{extra}")
    return 0


def cmd_adopt(a: argparse.Namespace) -> int:
    app_guard(a.force)
    proj = pick(a.project)[0]
    moved = 0
    for name in bands(proj):
        link, cloud = proj / name, ICLOUD / proj.name / name
        st = state(link, cloud)
        if st == "linked":
            print(f"이미 링크됨: {proj.name}/{name}")
            continue
        if st != "local":
            sys.exit(f"adopt 불가 ({st}): {proj.name}/{name} — band.py status 로 확인")
        cloud.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(link), str(cloud))  # 같은 볼륨이면 rename 이라 복사 없음
        link.symlink_to(cloud)
        print(f"adopt: {proj.name}/{name} → {cloud}")
        moved += 1
    if not moved and not bands(proj):
        print(f"{proj.name} 에 .band 없음")
    return 0


def cmd_link(a: argparse.Namespace) -> int:
    app_guard(a.force)
    if not ICLOUD.is_dir():
        sys.exit(f"iCloud 폴더 없음: {ICLOUD} — 이 맥이 같은 Apple ID 로 iCloud Drive 에 로그인돼 있는지 확인")
    found = 0
    for proj in pick(a.project):
        for cloud in sorted((ICLOUD / proj.name).glob("*.band")) if (ICLOUD / proj.name).is_dir() else []:
            link = proj / cloud.name
            st = state(link, cloud)
            if st in ("diverged", "local"):
                print(f"건너뜀 ({st}): {proj.name}/{cloud.name} 가 실제 폴더 — 덮어쓰지 않는다. 내용을 확인하고 직접 정리")
                continue
            if st in ("broken", "foreign"):
                link.unlink()
            if not link.is_symlink():
                link.symlink_to(cloud)
            left = materialize(cloud)
            note = f"  ! 미다운로드 {len(left)}개 — Finder 에서 '지금 다운로드' 후 다시 실행" if left else "  다운로드 완료"
            print(f"link: {proj.name}/{cloud.name}{note}")
            found += 1
    missing = sorted(d.name for d in ICLOUD.iterdir() if d.is_dir() and not (ROOT / d.name).is_dir()) if a.project is None else []
    for name in missing:
        print(f"! iCloud 에만 있는 프로젝트: {name} — 레포에 폴더가 없다(git pull 확인)")
    if not found:
        print("링크할 .band 없음")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("status"); s.add_argument("project", nargs="?"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("adopt"); s.add_argument("project"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_adopt)
    s = sub.add_parser("link"); s.add_argument("project", nargs="?"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_link)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

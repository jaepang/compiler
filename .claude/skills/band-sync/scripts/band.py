#!/usr/bin/env python3
"""band.py — GarageBand 프로젝트(.band) 원본은 iCloud Drive 에, 레포 프로젝트 폴더에는 심볼릭 링크만 (표준 라이브러리만).

  band.py status [PROJECT]          프로젝트마다 .band 상태 (linked / unlinked / local / broken / diverged, 미다운로드 파일 수)
  band.py adopt PROJECT [--force]   이 맥의 실제 .band 를 iCloud 로 옮기고 그 자리에 링크
  band.py link [PROJECT] [--force]  iCloud 에 있는 .band 를 레포의 같은 폴더에 링크 + iCloud 다운로드 강제
  band.py verify [PROJECT] [--wait S]  iCloud 원본이 실제로 업로드됐는지 (fileproviderctl). --wait 면 S 초까지 기다린다

원본: ~/Library/Mobile Documents/com~apple~CloudDocs/compiler/<PROJECT>/<이름>.band  (BAND_ICLOUD_ROOT 로 대체 가능 — 테스트용)
링크: <레포>/<PROJECT>/<이름>.band → 원본 절대경로. *.band 는 gitignore 라 링크도 커밋되지 않는다.
GarageBand 가 실행 중이면 adopt/link 는 멈춘다 (--force 로 무시). 같은 프로젝트를 두 맥에서 동시에 열지 않는다 — iCloud 가 충돌 사본을 만든다.

FilmCraft: <PROJECT>/filmcraft/*.fcproj 는 작아서 git 에 커밋하고, 큰 소재만 <PROJECT>/filmcraft/media/ 에 둔다.
media/ 는 .band 와 같은 방식(원본 iCloud compiler/<PROJECT>/filmcraft/media, 레포엔 링크)이고, .fcproj 는 소재를 "media/…" 상대경로로
가리켜야 다른 맥에서도 열린다(FilmCraft 는 상대경로를 .fcproj 위치 기준으로 푼다). adopt 가 절대경로 소재를 media/ 로 복사하고 경로를 고친다.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("BAND_REPO") or Path(__file__).resolve().parents[4])  # …/.claude/skills/band-sync/scripts → 레포 루트
ICLOUD = Path(os.environ.get("BAND_ICLOUD_ROOT") or Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/compiler")
APP = os.environ.get("BAND_APP_NAME", "GarageBand")
FC_APP = os.environ.get("BAND_FC_APP_NAME", "FilmCraft")
FPCTL = os.environ.get("BAND_FPCTL", "fileproviderctl")  # 업로드 상태 조회 (테스트는 가짜 스크립트)
FC = "filmcraft"  # <PROJECT>/filmcraft/ — .fcproj 는 git, media/ 는 iCloud 링크
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


def fc_pair(proj: Path) -> tuple[Path, Path] | None:
    """FilmCraft 소재 폴더 (레포 링크, iCloud 원본). 어느 쪽에도 filmcraft/ 가 없으면 None."""
    link, cloud = proj / FC / "media", ICLOUD / proj.name / FC / "media"
    return (link, cloud) if (proj / FC).is_dir() or cloud.exists() else None


def fc_paths(node) -> list[dict]:
    """.fcproj JSON 안에서 "path" 문자열을 가진 객체(소재 참조)를 모두 찾는다."""
    out = []
    if isinstance(node, dict):
        if isinstance(node.get("path"), str):
            out.append(node)
        for v in node.values():
            out += fc_paths(v)
    elif isinstance(node, list):
        for v in node:
            out += fc_paths(v)
    return out


def fc_problems(proj: Path) -> list[str]:
    """다른 맥에서 안 열릴 참조 — 절대경로, 또는 상대경로인데 파일이 없음."""
    out = []
    for f in sorted((proj / FC).glob("*.fcproj")):
        for ref in fc_paths(json.loads(f.read_text(encoding="utf-8"))):
            path = ref["path"]
            if os.path.isabs(path):
                out.append(f"{f.name}: 절대경로 {path}")
            elif not (f.parent / path).exists():
                out.append(f"{f.name}: 소재 없음 {path}")
    return out


def fc_relativize(proj: Path, link: Path, cloud: Path) -> None:
    """.fcproj 의 절대경로 소재를 media/ 로 옮겨 담고(밖에 있으면 복사) "media/이름" 으로 바꾼다."""
    roots = [str(link), str(cloud), str(cloud.resolve())]
    for f in sorted((proj / FC).glob("*.fcproj")):
        data = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for ref in fc_paths(data):
            src = ref["path"]
            if not os.path.isabs(src):
                continue
            inside = next((src[len(r) + 1:] for r in roots if src.startswith(r + "/")), None)
            if inside is None:
                name = Path(src).name
                dst = cloud / name
                if dst.exists():
                    if dst.stat().st_size != Path(src).stat().st_size:
                        sys.exit(f"media/{name} 가 이미 있고 크기가 다르다 — {src} 를 다른 이름으로 바꿔 다시 실행")
                elif Path(src).exists():
                    shutil.copy2(src, dst)
                    print(f"  복사: {src} → media/{name}")
                else:
                    print(f"  ! {f.name}: 소재가 없어 그대로 둠 {src}")
                    continue
                inside = name
            ref["path"] = f"media/{inside}"
            changed = True
        if changed:
            f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"  상대경로로: {proj.name}/{FC}/{f.name}")


def upload_state(path: Path) -> tuple[bool, str]:
    """(업로드 완료 여부, 업로드 오류 설명). iCloud Drive 가 아니면 (False, 사유)."""
    r = subprocess.run([FPCTL, "evaluate", str(path)], capture_output=True, text=True)
    m = re.search(r"isUploaded = (\d);", r.stdout)
    if not m:
        lines = (r.stderr or r.stdout).strip().splitlines()
        return False, lines[-1] if lines else "상태 조회 실패"
    err = re.search(r'NSDebugDescription = \\?"([^"\\]+)', r.stdout) or re.search(r"uploadingError = (.+?);?$", r.stdout, re.M)
    return m.group(1) == "1", err.group(1).strip('"') if err else ""


def synced(proj: Path) -> list[Path]:
    """이 프로젝트에서 iCloud 로 동기화되는 원본 (.band 패키지, FilmCraft media 폴더)."""
    out = [ICLOUD / proj.name / n for n in bands(proj) if (ICLOUD / proj.name / n).exists()]
    pair = fc_pair(proj)
    if pair and pair[1].is_dir():
        out.append(pair[1])
    return out


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
    for app in (APP, FC_APP):
        if subprocess.run(["pgrep", "-x", app], capture_output=True).returncode == 0:
            sys.exit(f"{app} 가 실행 중이다 — 프로젝트를 닫고 앱을 종료한 뒤 다시 실행 (무시하려면 --force)")


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
        pair = fc_pair(proj)
        if pair:
            link, cloud = pair
            st = state(link, cloud)
            hint = {"local": f"  → band.py adopt {proj.name}", "unlinked": f"  → band.py link {proj.name}",
                    "broken": f"  → band.py link {proj.name}", "foreign": f"  ! 다른 곳을 가리킴: {os.readlink(link) if link.is_symlink() else ''}",
                    "diverged": "  ! 레포 쪽이 실제 폴더 — 어느 쪽이 최신인지 확인 필요"}.get(st, "")
            if st == "linked" and (n := len(pending(cloud))):
                hint = f"  미다운로드 {n}개 — band.py link {proj.name}"
            print(f"{st:9} {proj.name}/{FC}/media{hint}")
            for p in fc_problems(proj):
                print(f"  ! {p}" + (f" — band.py adopt {proj.name}" if "절대경로" in p else ""))
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
    pair = fc_pair(proj)
    if pair:
        link, cloud = pair
        st = state(link, cloud)
        if st in ("local", "none"):
            cloud.parent.mkdir(parents=True, exist_ok=True)
            if st == "local":
                shutil.move(str(link), str(cloud))
            else:
                cloud.mkdir()
            link.symlink_to(cloud)
            print(f"adopt: {proj.name}/{FC}/media → {cloud}")
        elif st != "linked":
            sys.exit(f"adopt 불가 ({st}): {proj.name}/{FC}/media — band.py status 로 확인")
        fc_relativize(proj, link, cloud)
        moved += 1
    if not moved and not bands(proj):
        print(f"{proj.name} 에 .band·FilmCraft 프로젝트 없음")
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
        pair = fc_pair(proj)
        if pair and pair[1].is_dir():
            link, cloud = pair
            st = state(link, cloud)
            if st in ("diverged", "local"):
                print(f"건너뜀 ({st}): {proj.name}/{FC}/media 가 실제 폴더 — 덮어쓰지 않는다. 내용을 확인하고 직접 정리")
            else:
                if st in ("broken", "foreign"):
                    link.unlink()
                if not link.is_symlink():
                    link.parent.mkdir(exist_ok=True)
                    link.symlink_to(cloud)
                left = materialize(cloud)
                note = f"  ! 미다운로드 {len(left)}개 — Finder 에서 '지금 다운로드' 후 다시 실행" if left else "  다운로드 완료"
                print(f"link: {proj.name}/{FC}/media{note}")
                for p in fc_problems(proj):
                    print(f"  ! {p}")
                found += 1
    missing = sorted(d.name for d in ICLOUD.iterdir() if d.is_dir() and not (ROOT / d.name).is_dir()) if a.project is None else []
    for name in missing:
        print(f"! iCloud 에만 있는 프로젝트: {name} — 레포에 폴더가 없다(git pull 확인)")
    if not found:
        print("링크할 .band·FilmCraft 소재 없음")
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    """iCloud 원본의 파일마다 업로드 완료 여부를 본다. 하나라도 안 올라갔으면 exit 1."""
    import time
    deadline = time.monotonic() + min(a.wait, 600)
    while True:
        bad: list[tuple[Path, str]] = []
        items: list[Path] = []
        for proj in pick(a.project):
            for root in synced(proj):
                items += [root.parent, root]
                if root.suffix != ".band":  # .band 패키지는 iCloud 에서 항목 하나 — 안쪽 파일은 따로 조회되지 않는다
                    items += [p for p in sorted(root.rglob("*")) if not p.is_symlink() and p.name != ".DS_Store"]
        if items:
            items.insert(0, ICLOUD)  # 업로드 오류는 위쪽 폴더에 붙어 있기도 하다
        items = list(dict.fromkeys(items))
        total = len(items)
        for p in items:
            ok, err = upload_state(p)
            if not ok:
                bad.append((p, err))
        if not bad or time.monotonic() >= deadline:
            break
        print(f"  업로드 대기 중: {len(bad)}/{total}개 남음")
        time.sleep(min(30, max(1, deadline - time.monotonic())))
    if not total:
        print("검사할 iCloud 원본 없음")
        return 0
    print(f"업로드 완료 {total - len(bad)}/{total}")
    errs = sorted({e for _, e in bad if e})
    for p, _ in bad[:10]:
        print(f"  미업로드: {p.relative_to(ICLOUD.parent)}")
    if len(bad) > 10:
        print(f"  … 외 {len(bad) - 10}개")
    for e in errs:
        print(f"  ! 업로드 오류: {e}")
    if any("com.apple.bird" in e for e in errs):
        print("  → iCloud Drive 데몬(bird) 연결 실패: launchctl print-disabled gui/$(id -u) | grep bird 로 확인."
              " bird 가 이미 떠 있는데도 이 오류면 예전 실패가 남은 것 — iCloud 의 compiler 폴더 이름을 잠깐 바꿨다 되돌린다")
    return 1 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("status"); s.add_argument("project", nargs="?"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("adopt"); s.add_argument("project"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_adopt)
    s = sub.add_parser("link"); s.add_argument("project", nargs="?"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_link)
    s = sub.add_parser("verify"); s.add_argument("project", nargs="?"); s.add_argument("--wait", type=float, default=0); s.set_defaults(fn=cmd_verify)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

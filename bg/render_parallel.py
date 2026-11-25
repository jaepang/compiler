#!/usr/bin/env python3
"""Render one LP video with several generator processes at once and join the pieces.

Every frame depends only on its index, so the frame range is split into --jobs pieces,
each piece is rendered by its own lp_generator_v37_integrated.py process with
--frame-start/--frame-end, and the pieces are joined with ffmpeg's concat demuxer
(stream copy, no re-encode). Each piece starts on a keyframe.

  .venv/bin/python render_parallel.py --jobs 6 -- \\
      --duration 00:19:48 --fps 30 --resolution 1920x1080 --seed 12345 --dot "#FFFFFF" \\
      --bg-mode transparent --alpha-codec vp9 --output ../01.fine/build/lp/lp_B_white.webm

Everything after "--" goes to the generator unchanged. --duration, --fps and --output
are required there. The joined file gets the usual <stem>_settings.json / <stem>_seed.txt;
per-piece logs stay in <stem>_parts/ until the join succeeds.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENERATOR = HERE / "lp_generator_v37_integrated.py"
sys.path.insert(0, str(HERE))
from lp_generator_v37_integrated import parse_duration  # noqa: E402


def option(args: list[str], name: str) -> str:
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    raise SystemExit(f"생성기 인자에 {name} 가 필요합니다.")


def without(args: list[str], name: str) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a == name:
            skip = True
            continue
        if a.startswith(name + "="):
            continue
        out.append(a)
    return out


def frame_count(path: Path) -> int:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return int(r.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description="LP 생성기를 프레임 구간별로 동시에 돌려 한 파일로 잇는다")
    parser.add_argument("--jobs", type=int, default=4, help="동시에 돌릴 생성기 프로세스 수")
    parser.add_argument("gen_args", nargs=argparse.REMAINDER, help="-- 뒤에 생성기 인자")
    args = parser.parse_args()
    gen = args.gen_args[1:] if args.gen_args[:1] == ["--"] else args.gen_args

    total = int(round(parse_duration(option(gen, "--duration")) * int(option(gen, "--fps"))))
    output = Path(option(gen, "--output"))
    parts_dir = output.parent / (output.stem + "_parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    base = without(gen, "--output")

    jobs = max(1, min(args.jobs, total))
    bounds = [round(total * k / jobs) for k in range(jobs + 1)]
    procs = []
    for k in range(jobs):
        part = parts_dir / f"part_{k:02d}{output.suffix}"
        log = open(parts_dir / f"part_{k:02d}.log", "w")
        cmd = [sys.executable, "-u", str(GENERATOR), *base, "--output", str(part),
               "--frame-start", str(bounds[k]), "--frame-end", str(bounds[k + 1])]
        procs.append((part, bounds[k + 1] - bounds[k], subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT), log))
    print(f"{total:,} 프레임을 {jobs}개로 나눠 렌더 중 (로그: {parts_dir})", flush=True)

    failed = []
    for part, want, proc, log in procs:
        code = proc.wait()
        log.close()
        if code != 0:
            failed.append(f"{part.name}: 종료 코드 {code}")
        elif (got := frame_count(part)) != want:
            failed.append(f"{part.name}: 프레임 {got} (기대 {want})")
    if failed:
        raise SystemExit("조각 렌더 실패:\n  " + "\n  ".join(failed))

    listing = parts_dir / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p, _, _, _ in procs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", str(output)], check=True)
    if (got := frame_count(output)) != total:
        raise SystemExit(f"이은 파일 프레임 {got} (기대 {total}). 조각은 {parts_dir} 에 남겨 둔다.")

    first = procs[0][0]
    settings = json.loads(first.with_name(first.stem + "_settings.json").read_text(encoding="utf-8"))
    settings["output_file"] = output.name
    settings["parallel_jobs"] = jobs
    output.with_name(output.stem + "_settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy(first.with_name(first.stem + "_seed.txt"), output.with_name(output.stem + "_seed.txt"))
    shutil.rmtree(parts_dir)
    print(f"완료: {output} ({total:,} 프레임)")


if __name__ == "__main__":
    main()

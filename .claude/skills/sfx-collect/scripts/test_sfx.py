"""sfx.py 테스트 — 임시 레포 루트(SFX_ROOT)에서 add/link/unlink/list 를 검증 (ffmpeg 합성 오디오)"""
import json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
root = Path(tempfile.mkdtemp())
env = {**os.environ, "SFX_ROOT": str(root)}
def sfx(*args):
    r = subprocess.run([sys.executable, str(HERE / "sfx.py"), *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout
FF = shutil.which("ffmpeg"); assert FF

print("== 준비: 가짜 프로젝트 2개 + 합성 소리 2개 ==")
for name in ("01.첫영상", "02.둘째"):
    (root / name).mkdir(); (root / name / "classification.json").write_text('{"playlist": {"url": "u", "title": "%s"}, "items": []}' % name, encoding="utf-8")
src = root / "dl"; src.mkdir()
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "pcm_s16le", str(src / "needle.wav")], check=True)
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3", "-c:a", "pcm_s16le", str(src / "projector.wav")], check=True)
sfx("add", str(src / "needle.wav"), "--kind", "oneshot", "--category", "vinyl", "--source", "mixkit", "--page-url", "https://x/p", "--license", "Mixkit Sound Effects Free License", "--id", "needle-test", "--download-url", "https://x/needle.wav")
sfx("add", str(src / "projector.wav"), "--kind", "loop", "--category", "film", "--source", "mixkit", "--page-url", "https://x/q", "--license", "Mixkit Sound Effects Free License", "--id", "projector-test")
assert (root / "sfx/vinyl/needle-test.wav").exists() and (root / "sfx/manifest.json").exists()

print("== link: 프로젝트에 상대 심볼릭 링크 + sfx.json ==")
out = sfx("link", "needle-test", "projector-test", "--project", "01.첫영상")
links = sorted((root / "01.첫영상/sfx").iterdir())
assert [l.name for l in links] == ["needle-test.wav", "projector-test.wav"], links
for l in links:
    assert l.is_symlink() and not os.readlink(l).startswith("/"), os.readlink(l)                 # 상대 링크
    assert l.resolve() == (root / "sfx" / ("vinyl" if "needle" in l.name else "film") / l.name).resolve()
uses = json.loads((root / "01.첫영상/sfx.json").read_text(encoding="utf-8"))
assert uses == {"sounds": ["needle-test", "projector-test"]}, uses
assert "01.첫영상/sfx/needle-test.wav" in out and "01.첫영상/sfx/projector-test.wav" in out

print("== link 재실행(멱등) / 링크 폴더 삭제 후 sfx.json 만으로 재생성 ==")
sfx("link", "needle-test", "--project", "01.첫영상")
assert json.loads((root / "01.첫영상/sfx.json").read_text(encoding="utf-8"))["sounds"] == ["needle-test", "projector-test"]
shutil.rmtree(root / "01.첫영상/sfx")
sfx("link", "--project", "01.첫영상")
assert sorted(p.name for p in (root / "01.첫영상/sfx").iterdir()) == ["needle-test.wav", "projector-test.wav"]

print("== list --project / unlink ==")
out = sfx("list", "--project", "01.첫영상"); assert "needle-test" in out and "projector-test" in out
out = sfx("list", "--project", "02.둘째"); assert "needle-test" not in out
sfx("unlink", "projector-test", "--project", "01.첫영상")
assert not (root / "01.첫영상/sfx/projector-test.wav").exists() and (root / "01.첫영상/sfx/needle-test.wav").exists()
assert json.loads((root / "01.첫영상/sfx.json").read_text(encoding="utf-8"))["sounds"] == ["needle-test"]

print("== 잘못된 입력 ==")
r = subprocess.run([sys.executable, str(HERE / "sfx.py"), "link", "no-such-id", "--project", "01.첫영상"], capture_output=True, text=True, env=env)
assert r.returncode != 0 and "no-such-id" in (r.stdout + r.stderr)
r = subprocess.run([sys.executable, str(HERE / "sfx.py"), "link", "needle-test", "--project", "99.없음"], capture_output=True, text=True, env=env)
assert r.returncode != 0 and "99.없음" in (r.stdout + r.stderr)

print("== remove: 프로젝트 링크 해제 + 파일 삭제 + 매니페스트 제거 ==")
sfx("link", "needle-test", "--project", "02.둘째")
out = sfx("remove", "needle-test")
assert not (root / "sfx/vinyl/needle-test.wav").exists(), "파일이 남아 있음"
assert "needle-test" not in [i["id"] for i in json.loads((root / "sfx/manifest.json").read_text(encoding="utf-8"))["items"]]
for proj in ("01.첫영상", "02.둘째"):
    assert not (root / proj / "sfx/needle-test.wav").exists() and "needle-test" not in json.loads((root / proj / "sfx.json").read_text(encoding="utf-8"))["sounds"], proj
assert "02.둘째" in out and "01.첫영상" in out
r = subprocess.run([sys.executable, str(HERE / "sfx.py"), "remove", "needle-test"], capture_output=True, text=True, env=env)
assert r.returncode != 0 and "needle-test" in (r.stdout + r.stderr)

print("== loopify: 원샷 꼬리를 조각내 무작위로 이어붙인 베드 루프 생성·등록 ==")
# 소스: 앞 0.5초 큰 클릭 + 뒤 4초 잡음(크래클 흉내). 꼬리(1.0s~)만 써야 하니 결과에 클릭 크기의 피크가 없어야 한다
subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.02:seed=7:d=4.5", "-f", "lavfi", "-i", "sine=frequency=200:duration=0.05",
                "-filter_complex", "[1:a]volume=20dB,apad=whole_dur=0.5[c];[c][0:a]concat=n=2:v=0:a=1[o]", "-map", "[o]", "-ar", "48000", "-c:a", "pcm_s16le", str(src / "drop.wav")], check=True)
sfx("add", str(src / "drop.wav"), "--kind", "oneshot", "--category", "vinyl", "--source", "mixkit", "--page-url", "https://x/d", "--license", "CC0 1.0", "--id", "drop-test")
out = sfx("loopify", "drop-test", "--start", "1.0", "--length", "20", "--min-seg", "0.4", "--max-seg", "0.9", "--xfade", "0.03", "--seed", "3", "--id", "bed-test")
bed = root / "sfx/vinyl/bed-test.wav"
assert bed.exists() and "bed-test" in out, out
probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=sample_rate,codec_name", "-of", "json", str(bed)], capture_output=True, text=True).stdout)
assert abs(float(probe["format"]["duration"]) - 20.0) < 0.05 and probe["streams"][0]["sample_rate"] == "48000" and probe["streams"][0]["codec_name"] == "pcm_s24le", probe
item = next(i for i in json.loads((root / "sfx/manifest.json").read_text(encoding="utf-8"))["items"] if i["id"] == "bed-test")
assert item["kind"] == "loop" and item["license"] == "CC0 1.0" and item["derived"]["from"] == "drop-test" and item["derived"]["seed"] == 3 and item["source"] == "derived:mixkit", item
# 레벨: 소스 꼬리와 같은 수준(±2dB), 클릭(+20dB)은 섞이지 않음, 앞뒤 1초 차이 작음
def mean_db(p, ss=None, t=None):
    cmd = [FF, "-nostats"] + (["-ss", str(ss)] if ss is not None else []) + (["-t", str(t)] if t is not None else []) + ["-i", str(p), "-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    return float(re.search(r"mean_volume:\s*(-?[\d.]+)", err).group(1)), float(re.search(r"max_volume:\s*(-?[\d.]+)", err).group(1))
src_mean, _ = mean_db(src / "drop.wav", 1.0, 3.5); bed_mean, bed_max = mean_db(bed)
assert abs(bed_mean - src_mean) < 1.0, (bed_mean, src_mean)   # 채널 수 유지 → 레벨 보존
assert bed_max < mean_db(src / "drop.wav", 0.0, 0.5)[1] - 10, ("클릭이 섞임", bed_max)
head, _ = mean_db(bed, 0, 1.0); tail, _ = mean_db(bed, 19.0, 1.0); assert abs(head - tail) < 3.0, (head, tail)
# 단순 반복이 아님: 0~2초와 2~4초 파형이 다르다
raw = subprocess.run([FF, "-v", "error", "-i", str(bed), "-t", "4", "-f", "s16le", "-ac", "1", "-ar", "8000", "-"], capture_output=True).stdout
assert raw[: 16000 * 2] != raw[16000 * 2: 16000 * 4]
# 같은 seed 면 재현, 다른 seed 면 다름 (restore 가 레시피로 재생성할 수 있어야 한다)
sfx("loopify", "drop-test", "--start", "1.0", "--length", "20", "--min-seg", "0.4", "--max-seg", "0.9", "--xfade", "0.03", "--seed", "3", "--id", "bed-test-b")
assert (root / "sfx/vinyl/bed-test-b.wav").read_bytes() == bed.read_bytes()
bed.unlink(); sfx("restore")
assert bed.exists() and bed.read_bytes() == (root / "sfx/vinyl/bed-test-b.wav").read_bytes(), "restore 가 레시피로 재생성해야 한다"
print("  OK")

print("== projects: classification.json 을 가진 폴더 목록 ==")
out = sfx("projects"); assert "01.첫영상" in out and "02.둘째" in out and not any(l.startswith("dl") for l in out.splitlines()), out
shutil.rmtree(root, ignore_errors=True)
print("\nALL OK")

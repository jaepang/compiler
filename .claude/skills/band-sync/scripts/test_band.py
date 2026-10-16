"""band.py 테스트 — 임시 레포(BAND_REPO)와 가짜 iCloud(BAND_ICLOUD_ROOT)에서 adopt/link/status 를 검증"""
import os, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp())
repo, cloud = tmp / "repo", tmp / "icloud"
repo.mkdir()
env = {**os.environ, "BAND_REPO": str(repo), "BAND_ICLOUD_ROOT": str(cloud), "BAND_APP_NAME": "NoSuchApp-band-test"}
def band(*args, ok=True):
    r = subprocess.run([sys.executable, str(HERE / "band.py"), *args], capture_output=True, text=True, env=env)
    assert (r.returncode == 0) == ok, r.stdout + r.stderr
    return r.stdout + r.stderr

def make_band(path: Path):
    (path / "Media/Audio Files").mkdir(parents=True)
    (path / "Media/Audio Files/01.곡.wav").write_bytes(b"RIFF" + b"\0" * 64)
    (path / "projectData").write_bytes(b"data")

print("== 준비: 프로젝트 2개, 01 에만 실제 .band ==")
for name in ("01.첫영상", "02.둘째"):
    (repo / name).mkdir(); (repo / name / "classification.json").write_text("{}", encoding="utf-8")
p1 = repo / "01.첫영상"
make_band(p1 / "01.첫영상.band")
assert "local     01.첫영상/01.첫영상.band" in band("status")

print("== adopt: iCloud 로 이동 + 링크 ==")
out = band("adopt", "01.첫영상")
link, orig = p1 / "01.첫영상.band", cloud / "01.첫영상/01.첫영상.band"
assert link.is_symlink() and link.resolve() == orig.resolve(), out
assert (orig / "Media/Audio Files/01.곡.wav").read_bytes().startswith(b"RIFF")
assert "linked    01.첫영상/01.첫영상.band" in band("status")
assert "이미 링크됨" in band("adopt", "01.첫영상")                               # 재실행 안전

print("== 다른 기기 흉내: 링크 없음 → link 가 다시 만든다 ==")
link.unlink()
assert "unlinked  01.첫영상/01.첫영상.band" in band("status")
out = band("link")
assert link.is_symlink() and link.resolve() == orig.resolve() and "다운로드 완료" in out, out
assert "linked" in band("status", "01.첫영상")

print("== 미다운로드 자리표시자는 status/link 가 보고한다 ==")
ph = orig / "Media/Audio Files/.02.곡.wav.icloud"; ph.write_bytes(b"")
assert "미다운로드 1개" in band("status") and "미다운로드 1개" in band("link")
ph.unlink()

print("== broken / foreign 링크는 link 가 고친다 ==")
link.unlink(); link.symlink_to(tmp / "없는곳.band")
assert "broken" in band("status")
band("link", "01.첫영상"); assert link.resolve() == orig.resolve()

print("== diverged: 레포 쪽이 실제 폴더면 link 가 덮어쓰지 않는다 ==")
link.unlink(); make_band(link)
assert "diverged" in band("status")
out = band("link"); assert "건너뜀 (diverged)" in out and not link.is_symlink(), out
band("adopt", "01.첫영상", ok=False)                                            # iCloud 에 이미 있으면 adopt 거부
assert (link / "projectData").exists() and (orig / "projectData").exists()      # 양쪽 다 그대로

print("== iCloud 에만 있는 프로젝트 / iCloud 없음 ==")
(cloud / "03.없는폴더").mkdir()
assert "iCloud 에만 있는 프로젝트: 03.없는폴더" in band("link")
env["BAND_ICLOUD_ROOT"] = str(tmp / "nope")
band("link", ok=False)
env["BAND_ICLOUD_ROOT"] = str(cloud)

print("== 앱 실행 중이면 adopt/link 거부 (--force 로 통과) ==")
busy = subprocess.Popen(["sleep", "30"]); env["BAND_APP_NAME"] = "sleep"           # 실행 중인 앱 흉내
try:
    assert "실행 중" in band("link", ok=False)
    band("link", "--force")
finally:
    busy.kill()

print("OK")

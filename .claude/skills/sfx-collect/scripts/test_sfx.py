"""sfx.py 테스트 — 임시 레포 루트(SFX_ROOT)에서 add/link/unlink/list 를 검증 (ffmpeg 합성 오디오)"""
import json, os, shutil, subprocess, sys, tempfile
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

print("== projects: classification.json 을 가진 폴더 목록 ==")
out = sfx("projects"); assert "01.첫영상" in out and "02.둘째" in out and not any(l.startswith("dl") for l in out.splitlines()), out
shutil.rmtree(root, ignore_errors=True)
print("\nALL OK")

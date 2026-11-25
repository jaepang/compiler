#!/bin/sh
# 사이드 B 배경. side_a_bg.png(필름 그레인 정지 화면)를 아주 밝게만 만든다 — 그레인·스크래치·비네트는 그대로.
# 방법: 원본 밝기 평균 m 을 기준으로 out = T + k*(in - m) (sRGB 8bit 값 기준, RGB 같은 값).
#   T: 목표 평균 밝기, k: 평균에서의 편차(그레인·비네트·스크래치) 배율. 밝은 배경일수록 같은 편차가 덜 보이므로 k 를 키운다.
#   양자화 빗살 무늬를 막으려고 +-0.5 삼각 디더를 더하고(seed 고정), 0..255 로 자른다(잘리는 픽셀은 1개 남짓).
# 후보 mid(100,1.3)·light(140,1.5)·pale(180,1.7)·vlight(210,1.8) 중 vlight 로 정했다(2026-11-26). 이 위에는 검은 점 LP·검은 제목을 얹는다.
#
#   ./side_b_bg.sh             side_b_bg.png (T=210 k=1.8)
#   ./side_b_bg.sh T k [출력]   다른 값으로 (후보 미리보기용)
set -eu
cd "$(dirname "$0")"
PY=../../bg/.venv/bin/python

T=${1:-210}
K=${2:-1.8}
OUT=${3:-side_b_bg.png}

"$PY" - "$T" "$K" "$OUT" <<'PYEOF'
import sys, cv2, numpy as np
T, k, dst = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
src = cv2.imread("side_a_bg.png", cv2.IMREAD_COLOR).astype(np.float64)
m = src.mean()
rng = np.random.default_rng(1)
d = rng.random(src.shape[:2]) - rng.random(src.shape[:2])  # 삼각 디더 -1..1 → 0.5 배
out = T + k * (src - m) + 0.5 * d[..., None]
clip = int(((out < 0) | (out > 255)).sum())
out = np.clip(np.rint(out), 0, 255).astype(np.uint8)
cv2.imwrite(dst, out)
print(f"{dst} T={T} k={k} clipped={clip}")
PYEOF

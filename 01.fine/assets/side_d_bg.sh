#!/bin/sh
# 사이드 D 배경과 그 위의 "Fine" 화면. side_a_bg.png(필름 그레인 정지 화면)를 많이 어둡게 만든다 — 그레인·스크래치는 최대한 살린다.
# 방법(sRGB 8bit 값 기준, 채널별 같은 변환):
#   low  = 가우스 블러(sigma 20) — 비네트·밝기 얼룩 같은 큰 변화
#   high = in - low              — 그레인·세로 스크래치 같은 잔 변화
#   out  = low * (T / m) + kh * high + 0.5*삼각디더   (m = 원본 평균 밝기)
#   큰 변화는 비율로 줄여 비네트 모양을 유지하고, 잔 변화는 kh 배로만 줄여 어두워져도 그레인이 뭉개지지 않게 한다.
#   +-0.5 삼각 디더(seed 고정)로 빗살 무늬를 막고 0..255 로 자른다.
# 후보 d32(32,1.0)·d22(22,1.0)·d14(14,0.9)·d8(8,0.75) 중 d22 로 정했다(2026-11-26). 이 위에는 흰 점 LP·흰 제목을 얹는다.
# fine_frame_d.png 는 이 배경 한가운데 흰 "Fine"(fine_frame.png 와 같은 글씨: Times New Roman Bold Italic 180pt)을 얹은 것이다.
#
#   ./side_d_bg.sh              side_d_bg.png (T=22 kh=1.0) + fine_frame_d.png
#   ./side_d_bg.sh T kh [출력]   다른 값으로 배경만 (후보 미리보기용)
set -eu
cd "$(dirname "$0")"
PY=../../bg/.venv/bin/python
FONT="/System/Library/Fonts/Supplemental/Times New Roman Bold Italic.ttf"

T=${1:-22}
KH=${2:-1.0}
OUT=${3:-side_d_bg.png}

"$PY" - "$T" "$KH" "$OUT" <<'PYEOF'
import sys, cv2, numpy as np
T, kh, dst = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
src = cv2.imread("side_a_bg.png", cv2.IMREAD_COLOR).astype(np.float64)
m = src.mean()
low = cv2.GaussianBlur(src, (0, 0), 20)
high = src - low
rng = np.random.default_rng(1)
d = rng.random(src.shape[:2]) - rng.random(src.shape[:2])  # 삼각 디더 -1..1 → 0.5 배
out = low * (T / m) + kh * high + 0.5 * d[..., None]
clip = int(((out < 0.5) | (out > 254.5)).sum())
out = np.clip(np.rint(out), 0, 255).astype(np.uint8)
cv2.imwrite(dst, out)
print(f"{dst} T={T} kh={kh} zero_or_clipped_samples={clip}")
PYEOF

if [ $# -eq 0 ]; then
  magick "$OUT" -font "$FONT" -pointsize 180 -fill white -gravity center -annotate +0+0 "Fine" PNG24:fine_frame_d.png
  echo fine_frame_d.png
fi

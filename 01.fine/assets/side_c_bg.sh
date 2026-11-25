#!/bin/sh
# 사이드 C 배경 두 장. side_a_bg.png(필름 그레인 정지 화면)의 그레인·스크래치·비네트를 그대로 두고 색만 입힌다.
#   side_c_bg_orange.png  Muse "Origin of Symmetry" 표지 하늘색 #DEA21C (표지 하늘 평평한 곳 40x60px 중앙값 222,162,28)
#   side_c_bg_red.png     #FF0000
# 타임라인에서 사이드 C 동안 주황 → 빨강으로 서서히 바뀐다(빨강 클립 불투명도 0→100 키프레임).
# 방법: 원본 밝기(RGB 평균)의 중앙값 m 과의 편차 d 를 쓴다(sRGB 8bit 값 기준). 중앙값 픽셀은 정확히 목표색이 된다.
#   d<0(어두운 쪽): out = C * (1 + k*d/max(C))           — 검정 쪽으로, 가장 큰 채널이 k*d 만큼 내려간다.
#   d>0(밝은 쪽):   out = C + (255-C) * k*d/(255-min(C)) — 흰색 쪽으로, 가장 작은 채널이 k*d 만큼 올라간다.
#   그래서 R 이 255 인 #FF0000 도 밝은 그레인이 G·B 로 올라가 R 에서 잘려 납작해지지 않는다.
#   양자화 빗살 무늬를 막으려고 +-0.5 삼각 디더를 더하고(seed 고정), 0..255 로 자른다(디더 전에 범위를 넘는 값의 수를 출력).
#
#   ./side_c_bg.sh          두 장 (k=1.6)
#   ./side_c_bg.sh k        다른 그레인 배율로
set -eu
cd "$(dirname "$0")"
PY=../../bg/.venv/bin/python

K=${1:-1.6}

"$PY" - "$K" <<'PYEOF'
import sys, cv2, numpy as np
k = float(sys.argv[1])
src = cv2.imread("side_a_bg.png", cv2.IMREAD_COLOR).astype(np.float64)
lum = src.mean(axis=2)
d = (lum - np.median(lum))[..., None]
for name, rgb in (("orange", (222, 162, 28)), ("red", (255, 0, 0))):
    C = np.array(rgb[::-1], np.float64)  # BGR
    dark = C * (1 + k * d / C.max())
    light = C + (255 - C) * k * d / (255 - C.min())
    out = np.where(d < 0, dark, light)
    clip = int(((out < 0) | (out > 255)).sum())  # 디더 전 값 기준 (#FF0000 의 R=255·G=B=0 은 디더로만 넘는다)
    rng = np.random.default_rng(1)
    n = rng.random(src.shape[:2]) - rng.random(src.shape[:2])  # 삼각 디더 -1..1 → 0.5 배
    out = out + 0.5 * n[..., None]
    out = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    dst = f"side_c_bg_{name}.png"
    cv2.imwrite(dst, out)
    print(f"{dst} #{''.join(f'{v:02X}' for v in rgb)} k={k} clipped={clip}")
PYEOF

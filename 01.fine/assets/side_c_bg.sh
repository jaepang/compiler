#!/bin/sh
# 사이드 C 배경 두 장. side_a_bg.png(필름 그레인 정지 화면)의 그레인·스크래치·비네트를 그대로 두고 색만 입힌다.
#   side_c_bg_orange.png  시작색. 기본 Muse "Origin of Symmetry" 표지 하늘색 #DEA21C (표지 하늘 평평한 곳 40x60px 중앙값 222,162,28)
#   side_c_bg_red.png     끝색. 기본 #FF0000
# 파일 이름은 색과 상관없이 같으므로, 색을 바꿔 다시 만들면 .fcproj 는 고치지 않아도 된다.
# 타임라인에서 사이드 C 동안 주황 → 빨강으로 서서히 바뀐다(빨강 클립 불투명도 0→100 키프레임).
# 방법: 원본 밝기(RGB 평균)의 중앙값 m 과의 편차 d 를 쓴다(sRGB 8bit 값 기준). 중앙값 픽셀은 정확히 목표색이 된다.
#   d<0(어두운 쪽): out = C * (1 + k*d/max(C))           — 검정 쪽으로, 가장 큰 채널이 k*d 만큼 내려간다.
#   d>0(밝은 쪽):   out = C + (255-C) * k*d/(255-min(C)) — 흰색 쪽으로, 가장 작은 채널이 k*d 만큼 올라간다.
#   그래서 R 이 255 인 #FF0000 도 밝은 그레인이 G·B 로 올라가 R 에서 잘려 납작해지지 않는다.
#   양자화 빗살 무늬를 막으려고 +-0.5 삼각 디더를 더하고(seed 고정), 0..255 로 자른다(디더 전에 범위를 넘는 값의 수를 출력).
#
#   ./side_c_bg.sh                          두 장 (#DEA21C → #FF0000, k=1.6)
#   ./side_c_bg.sh [시작색] [끝색] [k]       예: ./side_c_bg.sh DEA21C B00000  (# 는 있어도 없어도 된다)
set -eu
cd "$(dirname "$0")"
PY=../../bg/.venv/bin/python

START=${1:-DEA21C}
END=${2:-FF0000}
K=${3:-1.6}

"$PY" - "$START" "$END" "$K" <<'PYEOF'
import sys, cv2, numpy as np
hexrgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
start, end, k = hexrgb(sys.argv[1]), hexrgb(sys.argv[2]), float(sys.argv[3])
src = cv2.imread("side_a_bg.png", cv2.IMREAD_COLOR).astype(np.float64)
lum = src.mean(axis=2)
d = (lum - np.median(lum))[..., None]
for name, rgb in (("orange", start), ("red", end)):
    C = np.array(rgb[::-1], np.float64)  # BGR
    dark = C * (1 + k * d / max(C.max(), 1))
    light = C + (255 - C) * k * d / max(255 - C.min(), 1)
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

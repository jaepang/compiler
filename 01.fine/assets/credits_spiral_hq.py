"""credits_spiral_6688.png -> credits_spiral_hq.png (크레딧 롤 맨 밑 나선).

credits_spiral_6688.png 는 credits_spiral.png(1672x941) 와 같은 그림의 6688x3764 판이다(4배 확대본이라 디테일이
크게 늘지는 않지만 620px 로 줄일 때 점 가장자리가 더 또렷하다). 보이는 영역(x 1772~4799, y 336~3535)만 잘라
검정 위 합성 밝기 v 로 바꾸고 높이 620 으로 줄인 뒤, 가볍게 선명화한다(sigma 0.8, 0.5배, 3x3 최소값 아래로 안 내려감).

FilmCraft 는 합성을 선형광으로 한다. 반투명 회색 점을 그대로 넣으면 검정 위에서 밝기 13 이 46 으로 떠서
점 사이가 회색 안개처럼 뿌옇게 보였다. alpha 를 선형(v) 로 바꾸는 방법은 FilmCraft 가 PNG 를 8bit 로 읽어 어두운 쪽이
밝기 0·13·18… 계단이 된다. 그래서 나선 사각형 전체를 불투명(alpha 255)하게 하고 RGB 에 v 를 그대로 넣는다.
크레딧 롤 아래는 순수 검정 Color Matte 라 사각형 테두리는 보이지 않는다(배경이 검정이 아니게 되면 다시 생각할 것).

  ../../bg/.venv/bin/python credits_spiral_hq.py
"""
import os
import cv2
import numpy as np

os.chdir(os.path.dirname(os.path.abspath(__file__)))
H = 620
im = cv2.imread("credits_spiral_6688.png", cv2.IMREAD_UNCHANGED)[336:3536, 1772:4800]
a = im[..., 3:4].astype(np.float64) / 255
v = (im[..., :3].astype(np.float64) / 255 * a).mean(2)
w = round(v.shape[1] * H / v.shape[0])
v = np.clip(cv2.resize(v, (w, H), interpolation=cv2.INTER_AREA), 0, 1)
sharp = v + 0.5 * (v - cv2.GaussianBlur(v, (0, 0), 0.8))
v = np.clip(np.maximum(sharp, cv2.erode(v, np.ones((3, 3), np.uint8))), 0, 1)
out = np.empty((H, w, 4), np.uint8)
out[..., :3] = np.round(v * 255).astype(np.uint8)[..., None]
out[..., 3] = 255
cv2.imwrite("credits_spiral_hq.png", out)
print("credits_spiral_hq.png", f"{w}x{H}")

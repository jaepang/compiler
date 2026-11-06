LP V37 통합 생성기

필수 파일 2개를 같은 폴더에 둡니다:
- lp_generator_v37_integrated.py
- lp_density_reference.png

설치:
  pip install numpy opencv-python pycairo

FFmpeg도 PATH에 설치되어 있어야 합니다.

대화형 실행:
  python lp_generator_v37_integrated.py

현재 권장 radial 배경 예시:
  python lp_generator_v37_integrated.py --duration 00:30:00 --dot "#FFFFFF" --bg-mode radial-gradient --radial-center "#2F6BFF" --radial-outer "#EEF3FF" --radial-lp-radius 1.06 --radial-start 0.28 --radial-end 2.25 --radial-curve 1.38 --radial-glow 0.02 --radial-grain 0.055 --radial-underlay "#183A9A" --radial-underlay-opacity 0.10 --resolution 3840x2160 --fps 30 --output playlist_bg.mp4

생성 결과:
- playlist_bg.mp4
- playlist_bg_settings.json
- playlist_bg_seed.txt

배경 모드:
- solid
- image
- radial-gradient
- transparent (배경 없이 LP 만, ProRes 4444 .mov 알파 채널 — 편집기에서 다른 배경 위에 합성용. 용량이 매우 큼)

자세한 프로젝트 맥락은 HANDOFF_LP_V37.md 참고.

# LP V37 프로젝트 핸드오프

## 목적
이 문서는 다른 에이전트가 현재 세션을 이어받아 **유튜브 플레이리스트용 장시간 LP 점묘 애니메이션 생성기**를 계속 개발할 수 있도록 작성된 핸드오프다.

사용자는 디자인을 이미 확정했다. **LP 본체/파편 디자인을 임의로 재설계하지 말 것.** 이후 작업은 주로 배경 모드, 파라미터 UX, 렌더 성능, 장시간 안정성, 음원 합성 등이다.

---

## 현재 핵심 파일

- `lp_generator_v37_integrated.py`
  - 현재 통합 생성기.
  - 문법 검사 완료.
  - 1초 / 5fps / 640x360 출력으로 실제 smoke test 완료.
  - 장시간 20~40분 풀 렌더는 아직 이 환경에서 검증하지 않음.
- `lp_density_reference.png`
  - LP의 고정된 화면 공간 밀도/광택장을 위한 필수 참조 파일.
  - 생성기와 같은 폴더에 있어야 함.
- `LP_v37_white_dots_visibility_tuned_preview5s_1920x1080.mp4`
  - 현재 배경+흰 점 조합의 시각 기준 프리뷰.
- `LP_v37_white_dots_visibility_tuned_preview5s_1920x1080.png`
  - 위 프리뷰의 첫 프레임.

---

## 사용자 목표

- YouTube 플레이리스트 배경 영상.
- 실제 사용 시간은 매번 약 **20~40분**.
- 10초 루프를 억지로 맞추는 방식은 버림.
- **V37 느낌을 유지한 채 장시간 연속 생성**하는 방향이 최종 결정.
- 출력 기본값은 **3840x2160 / 30fps**.
- 재생 시간 입력 형식은 `HH:MM:SS`.
- seed는 직접 입력 가능. 비우면 랜덤 생성.
- 렌더 결과와 함께:
  - `<stem>_seed.txt`
  - `<stem>_settings.json`
  를 저장해서 재현 가능하게 함.

---

## LP 디자인: 확정 상태

### 기본 스타일
- 16:9.
- 원형 점만 사용.
- 점이 네모/타원/뭉침으로 보이지 않도록 Cairo vector circle 렌더 사용.
- 큰 중심 홀.
- 동심원 트랙 리듬.
- 외곽은 하드한 원 테두리로 끝나지 않고 파편으로 자연스럽게 해체됨.
- 시계 방향 회전.
- 파편은 LP 자체 점들이 떨어져나가는 느낌이어야 함.

### 파편 핵심
- 파편은 광택/고밀도 쪽에서 더 자연스럽게 떨어져나오는 구조.
- 멀어질수록 수는 줄지만 **멀리까지 빠져나가는 long-tail 점**은 반드시 남김.
- 하단 파편이 상단보다 약해 보였던 문제를 V37에서 보강.
- 이동 파편이 서로 붙어 타원처럼 보이지 않도록 인접 거리 기반 반지름 제한.
- 30fps 기준으로 잔상/타원 느낌 완화.

### 점 원형 유지
과거 문제:
- 고밀도 광택부에서 큰 점이 서로 뭉쳐 사각 블록처럼 보임.
- 파편 점이 붙어서 타원처럼 보임.

현재 해결:
- Cairo vector circle.
- 광택부의 아주 큰 점만 soft cap.
- 움직이는 파편은 약간만 반지름 축소.
- 같은 링에서 인접점 거리 기반 overlap 제한.

**이 디자인은 사용자가 “완벽하다. 디자인 확정”이라고 한 상태다.**

---

## 현재 배경 모드

통합 생성기는 3개 모드를 지원한다.

### 1. `solid`
- 단색 배경.
- 점 색과 완전히 독립.

### 2. `image`
- 이미지 배경.
- 기본 fit: `cover`.
- 지원:
  - cover / contain / stretch
  - blur
  - brightness
  - opacity
  - matte
  - overlay color / opacity
  - 이미지 누락/실패 시 단색 fallback

### 3. `radial-gradient`
현재 가장 선호되는 모드.

기본값:
```text
center_color             = #2F6BFF
outer_color              = #EEF3FF
lp_radius_ratio          = 1.06
gradient_start_ratio     = 0.28
gradient_end_ratio       = 2.25
gradient_curve           = 1.38
glow_strength            = 0.02
grain_strength           = 0.055
underlay_color           = #183A9A
underlay_opacity         = 0.10
dot_color                = #FFFFFF
```

의도:
- 화면 중앙에서 LP 중심과 겹치며 원형으로 퍼지는 radial gradient.
- 중심은 블루.
- 바깥은 pure white가 아니라 약간 푸른 `#EEF3FF`.
- 원은 화면 밖으로 잘리며 크게 차는 느낌.
- grain은 반드시 유지.
- 저주파 얼룩/큰 랜덤 텍스처는 사용하지 않음.
- 흰 점 가시성을 위해 LP 영역에 약한 네이비 underlay 10%.

---

## 매우 중요한 색상 처리 이력

한 번 radial 배경이 블루여야 하는데 그린으로 나온 버그가 있었다.
원인은 OpenCV BGR / Cairo RGB-BGRA / FFmpeg 픽셀 포맷 혼용이었다.

현재 통합 코드의 원칙:
- HEX 입력은 항상 `#RRGGBB` 의미.
- OpenCV 배경 이미지는 BGR.
- Cairo에는 HEX를 RGB float로 전달.
- Cairo ARGB32 메모리는 little-endian에서 premultiplied BGRA로 취급.
- premultiplied BGRA를 BGR 배경에 직접 compositing.
- FFmpeg 입력은 `bgr24`.

**이 경로를 임의로 바꾸지 말 것. 색상 회귀 테스트 필요.**

---

## 현재 통합 코드의 사용자 파라미터

### 공통
- `--duration HH:MM:SS`
- `--dot #RRGGBB`
- `--resolution 3840x2160`
- `--fps 30`
- `--seed N`
- `--output file.mp4`
- `--bg-mode solid|image|radial-gradient`

### solid
- `--bg #RRGGBB`

### image
- `--bg-image PATH`
- `--bg-image-fit cover|contain|stretch`
- `--bg-image-blur FLOAT`
- `--bg-image-brightness FLOAT`
- `--bg-image-opacity 0..1`
- `--bg-image-matte #RRGGBB`
- `--bg-image-overlay #RRGGBB`
- `--bg-image-overlay-opacity 0..1`
- `--bg-image-fallback #RRGGBB`

### radial-gradient
- `--radial-center #RRGGBB`
- `--radial-outer #RRGGBB`
- `--radial-lp-radius FLOAT`
- `--radial-start FLOAT`
- `--radial-end FLOAT`
- `--radial-curve FLOAT`
- `--radial-glow FLOAT`
- `--radial-grain FLOAT`
- `--radial-underlay #RRGGBB`
- `--radial-underlay-opacity 0..1`

---

## 현재 권장 실행 예시

```bash
python lp_generator_v37_integrated.py \
  --duration 00:30:00 \
  --dot "#FFFFFF" \
  --bg-mode radial-gradient \
  --radial-center "#2F6BFF" \
  --radial-outer "#EEF3FF" \
  --radial-lp-radius 1.06 \
  --radial-start 0.28 \
  --radial-end 2.25 \
  --radial-curve 1.38 \
  --radial-glow 0.02 \
  --radial-grain 0.055 \
  --radial-underlay "#183A9A" \
  --radial-underlay-opacity 0.10 \
  --resolution 3840x2160 \
  --fps 30 \
  --output playlist_bg.mp4
```

seed를 생략하면 인터랙티브 입력에서 Enter 시 랜덤 생성한다.

---

## 로컬 설치

```bash
pip install numpy opencv-python pycairo
```

그리고 FFmpeg가 PATH에 있어야 한다.

---

## 테스트 상태

확인 완료:
- Python syntax compile OK.
- `--help` 실행 OK.
- radial-gradient 모드 실제 1초 smoke render 성공.
- smoke test 조건:
  - 640x360
  - 5fps
  - seed=12345
  - 흰 점
  - 현재 radial 기본값

아직 확인 필요:
- 20~40분 장시간 렌더 안정성.
- 4K / 30fps 전체 렌더 속도와 파일 크기.
- Windows/macOS의 pycairo 설치 편의성.
- 필요하면 체크포인트/중단 후 이어렌더 기능.

---

## 다음 에이전트에게 권장되는 우선순위

1. **디자인은 손대지 말고** 현재 통합 코드의 장시간 안정성 테스트/최적화.
2. 10~20초 로컬 프리뷰를 먼저 렌더하도록 빠른 preview 옵션 추가 고려.
3. 필요하면 `--preset` 추가:
   - `blue-white`
   - `white-black`
   - `image`
4. 장시간 렌더 중 중단 시 이어서 렌더/구간 렌더 기능 검토.
5. 그 다음 단계에서 사용자가 원할 경우 음원 합성(FFmpeg) 기능 추가.

---

## 하지 말아야 할 것

- 10초 루프를 다시 억지로 맞추지 말 것.
- V37 파편 배치/곡률/밀도/하단 보강을 임의 재설계하지 말 것.
- 점을 raster integer circle로 되돌리지 말 것.
- 광택부 점을 큰 점 위주로 과도하게 키우지 말 것.
- radial 배경에 저주파 얼룩 텍스처를 넣지 말 것.
- grain은 제거하지 말 것.
- HEX 색상 입력의 RGB/BGR 순서를 혼동하지 말 것.

---

## 대화 스타일

- 사용자 언어: 한국어.
- 짧고 직접적인 응답 선호.
- 설명보다 실제 프리뷰/파일 생성과 빠른 반복을 선호.
- 사용자가 디자인을 확정한 뒤에는 새 디자인 제안보다 구현/안정화에 집중할 것.

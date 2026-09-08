# 재생목록 다운로드 (yt-dlp CLI)

`playlist_dl.py` 는 brew 로 설치한 `yt-dlp` 명령을 subprocess 로 호출한다. pip 의 yt_dlp 모듈은 필요 없다.

```bash
brew install yt-dlp ffmpeg          # 이미 있으면 생략. brew 의 yt-dlp 는 썸네일 임베드용 mutagen 포함
cd ~/code/compiler
python3 playlist_dl.py --cookies-from-browser chrome --dry-run   # 분류·파일명·선택 포맷 확인 (다운로드 없음)
python3 playlist_dl.py --cookies-from-browser chrome             # 실제 다운로드 → 01.욕망은오랜병/downloads/
python3 playlist_dl.py --restore --cookies-from-browser chrome   # 다른 머신에서: classification.json 대로 그대로 다시 받기 (TUI 로 프로젝트 선택)
```

- 브라우저는 프리미엄 로그인된 쪽으로: `chrome` / `whale` / `safari` / `firefox`
- yt-dlp 가 PATH 에 없으면 `--yt-dlp /opt/homebrew/bin/yt-dlp`
- 포맷 기본값은 **YouTube 영상 제작·업로드 호환**: 음원은 AAC `.m4a`(프리미엄 256k), 영상은 H.264 + AAC `.mp4` (YouTube 권장 업로드 사양과 동일, Final Cut/Premiere/DaVinci/iMovie 에서 바로 열림)
  - 최고 품질(VP9/AV1 4K, opus)을 원하면 `--video-container mkv --audio-codec best`
- 파일명: `{nn}.{아티스트(한글 우선·간략)}-{영상명(한글 우선)}.{확장자}`, 공백은 `_`  예) `01.사뮈-아침의_빛.m4a`, `03.이적-병.m4a`, `12.Nothing_But_Thieves-Ban_All_the_Music_(Live_at_The_O2).mp4`
- 파일명 규칙이나 `ARTIST_OVERRIDES` 를 고친 뒤에는 `python3 playlist_dl.py --rename 01.욕망은오랜병 --cookies-from-browser chrome --dry-run` 으로 미리 보고, `--dry-run` 을 빼면 downloads/ 파일 rename + classification.json 갱신 (재다운로드 없음)
- dry-run 에서 음원이 `141  mp4a.40.2 256k` 로 나오면 프리미엄 포맷이 잡힌 것. `140 … 128k` 만 나오면 쿠키가 안 읽힌 상태(카탈로그 음원 기준)
- 분류 규칙과 결과는 `playlist_dl.py` 상단 docstring 과 실행 후 생기는 `01.욕망은오랜병/classification.json` 참고
- 선택: `pip install pillow` 하면 규칙 5(스토리보드로 정지 이미지 판별)까지 동작. 이 재생목록 19곡은 규칙 1~4 로 모두 결정되므로 없어도 됨
- 오프라인 테스트: `python3 test_offline.py` (fixture_meta.json 의 실제 메타데이터 + `--load-info-json` 으로 yt-dlp 인자 검증. pillow 없으면 스토리보드 섹션은 건너뜀), `python3 test_build_timeline.py` (ffmpeg 로 초소형 미디어를 합성해 타임라인 생성 검증)
- 다른 머신에서 복원: `git clone` 후 `python3 playlist_dl.py --restore [DIR ...]`. 재생목록 조회·분류 없이 `classification.json` 의 index/name/mode/url 그대로 받으므로 재생목록이 바뀌어도 원본과 같은 파일명·포맷. DIR 생략 시 curses TUI 에서 프로젝트를 고른다(`전부 복원` 행 포함). `--only ID`·`--dry-run` 조합 가능
- git: `downloads/`·`archive_*.txt`·미디어 확장자는 `.gitignore`. 커밋되는 산출물은 각 프로젝트의 `classification.json`(복원 매니페스트)만. archive 는 머신 로컬 상태라 커밋하면 다른 머신에서 전부 스킵되니 올리지 말 것

## DaVinci Resolve 타임라인 템플릿 (`build_timeline.py`)

```bash
python3 build_timeline.py 01.욕망은오랜병
python3 build_timeline.py 01.욕망은오랜병 --fps 25 --gap 1.0
```

- `01.욕망은오랜병/build/` 에 `timeline.fcpxml`(재생목록 순서대로 일렬 배치, 크로스페이드 없음, 곡마다 마커), `tracklist.srt`("지금 재생 중" 자막용), `description.md`(YouTube 챕터 타임스탬프 + 크레딧), `covers/`(m4a 임베드 커버) 생성
- 음원 곡은 V1 에 앨범아트 정지 이미지 + A1 에 음원, 영상 곡은 mp4 그대로. 1080p, `--fps` 24/25/30/60, `--gap` 초 단위 곡 간격
- Resolve: File > Import > Timeline > Import AAF, EDL, XML… 로 fcpxml, File > Import > Subtitle 로 srt. 미디어는 downloads/ 절대경로로 연결되므로 `build/` 는 gitignore — 다른 머신은 `--restore` 뒤 다시 생성

## GarageBand 음원 선편집 → Resolve (`build_daw.py`, mix 모드)

```bash
python3 build_daw.py 01.욕망은오랜병
```

- `build/daw/audio/{nn}.{어간}.wav`(19곡 48kHz/24bit, 영상 곡은 오디오만) 와 `build/daw/video/`(영상 곡을 무음으로) 를 만들고 순서표를 출력한다. GarageBand 는 mp4 를 받지 않으니 WAV 를 순서대로 끌어다 놓는다.
- GarageBand 에서 간격·트림·볼륨·페이드 편집 → Share > Export Song to Disk (WAV, 48kHz) → `build/daw/mix.wav`
- `python3 build_timeline.py 01.욕망은오랜병 --audio build/daw/mix.wav` — GarageBand 는 마커를 내보내지 못하므로 믹스에서 곡 경계를 복원한다(원곡 중간 라우드니스 곡선을 믹스에서 상관으로 찾고 곡 사이 무음으로 다듬음. 순서 변경·볼륨 변경·앞 트림에 강함). 결과는 `build/daw/cues.json` 에 저장되고, 점수가 낮은 곡은 손으로 고쳐 `--cues build/daw/cues.json` 으로 넘길 수 있다. 미리 보기만 하려면 `python3 build_daw.py DIR --align build/daw/mix.wav`.
- Resolve 템플릿은 A1 = mix 한 클립, V1 = 커버/무음 영상을 곡 경계에 맞춰(영상 트림 반영), 마커·SRT·챕터도 같은 경계. 테스트: `python3 test_build_daw.py`

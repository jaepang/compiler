# compiler — 유튜브 플레이리스트 채널 소스 다운로더

YouTube 재생목록을 yt-dlp 로 내려받아 **유튜브 영상 제작 소스**로 쓰는 프로젝트. 재광님이 직접 운영.
이 문서는 Cowork(claude.ai 데스크톱) 세션에서 만든 작업을 로컬 Claude Code 로 넘기기 위한 인수인계 메모다. (2026-09-07)

## 폴더 구조

```
compiler/
  playlist_dl.py        메인 스크립트 (yt-dlp CLI 를 subprocess 로 호출, pip yt_dlp 모듈 안 씀)
  test_offline.py       네트워크 없이 분류·파일명·yt-dlp 인자 검증 (python3 test_offline.py)
  build_timeline.py     매니페스트 → DaVinci Resolve 용 build/ (timeline.fcpxml·tracklist.srt·description.md·covers/) 생성. --audio [--cues] 로 mix 모드
  build_daw.py          GarageBand 선편집용 소스(build/daw/audio/*.wav, video/*.mp4) 준비 + 내보낸 믹스에서 곡 경계 복원(align_cues → cues.json)
  test_build_daw.py     ffmpeg 합성 미디어로 build_daw 검증 (python3 test_build_daw.py)
  test_build_timeline.py  ffmpeg 로 초소형 미디어를 합성해 build_timeline 검증 (python3 test_build_timeline.py)
  fixture_meta.json     19곡 실제 메타데이터 (제목/채널/설명/태그/기대 파일명) — 테스트용
  README.md, requirements.txt(선택 의존성 pillow 만)
  01.욕망은오랜병/       재생목록 1개 = 폴더 1개, "{nn}.{재생목록이름}" 규칙
    downloads/          {nn}.{아티스트}-{영상명}.{확장자} (공백은 _)  — 음원·영상 구분 없이 한 폴더 (gitignore)
    archive_audio.txt, archive_video.txt   yt-dlp --download-archive (모드별, 재실행 시 중복 방지. 머신 로컬 상태 — gitignore)
    classification.json                    영상별 분류·파일명 결과표 = 복원 매니페스트 {"playlist": {url,title}, "items": [...]} — 커밋 대상
    build/                                 build_timeline.py 산출물 — 절대경로 포함, 매니페스트에서 재생성 (gitignore)
    *.band                                 GarageBand 프로젝트 — 여기(프로젝트 폴더)에 두고 편집하되 gitignore. 내보낸 믹스는 build/daw/mix.wav
```

새 재생목록을 추가할 때는 `02.{이름}/` 처럼 번호를 이어서 만들고, `python3 playlist_dl.py <URL> --out 02.{이름}` 으로 받는다.
(스크립트의 PLAYLIST_URL / DEFAULT_OUT 기본값은 1번 재생목록 기준이므로 새 재생목록은 URL 과 --out 을 명시.)

## 다른 머신에서 복원 (`--restore`)

`git clone` 후 yt-dlp/ffmpeg 만 있으면 `classification.json` 만 보고 원본과 같은 파일명·포맷으로 다시 받는다.
재생목록 조회·분류를 하지 않으므로 재생목록이 바뀌어도 `{nn}` 이 밀리지 않고, pillow 유무에도 영향받지 않는다.

```bash
python3 playlist_dl.py --restore --cookies-from-browser chrome
python3 playlist_dl.py --restore 01.욕망은오랜병 --cookies-from-browser chrome
```

- DIR 생략 시 현재 폴더의 `*/classification.json` 을 찾아 curses TUI 로 고른다 (`전부 복원` 행, space 토글, a 전부, Enter 확정, q 취소). tty 가 아니면 DIR 을 요구한다.
- `--only ID`·`--dry-run`·포맷 옵션은 그대로 조합 가능. url 위치 인자와 `--out` 은 무시된다.
- `archive_*.txt` 는 gitignore 라 새 머신엔 없어 전부 내려받고, 원본 머신에서는 전부 스킵된다.
- 01 번 매니페스트는 구버전(항목 리스트만) 형식으로 만들어졌던 것을 2026-09-08 에 새 형식으로 감쌌다. `read_manifest` 는 리스트 형식도 그대로 읽는다.

## Resolve 타임라인 템플릿 (`build_timeline.py`)

영상 제작 파이프라인의 다음 칸. 매니페스트 순서대로 DaVinci Resolve 에 일렬로 들어가는 FCPXML 1.8 을 만든다 (크로스페이드 없음 — 재광님 결정. 곡 간격만 `--gap`).

```bash
python3 build_timeline.py 01.욕망은오랜병
python3 build_timeline.py 01.욕망은오랜병 --fps 25 --gap 1.0
```

- `build/timeline.fcpxml`: 1920x1080, `--fps` 24/25/30/60(기본 30). 음원 곡은 스파인에 커버 정지 이미지(`<video>`, asset duration 0s) + `lane="-1"` 에 음원 `<asset-clip>`, 영상 곡은 mp4 `<asset-clip>`. 곡마다 `nn 아티스트 - 곡명` 마커. 길이는 ffprobe 실측을 프레임으로 반올림, 경로는 `file://` 절대경로.
- `build/tracklist.srt`: 곡 구간마다 "아티스트 - 곡명" (자막 트랙으로 불러와 '지금 재생 중'). `build/description.md`: 챕터 타임스탬프 + 크레딧 (m4a `description` 태그의 `Provided to YouTube by …`, 없으면 채널명, + 원본 URL). `build/covers/`: m4a 임베드 커버 추출, 없으면 black.png.
- Resolve: File > Import > Timeline > Import AAF, EDL, XML… → fcpxml, File > Import > Subtitle → srt.
- 곡 파일이 없으면 BuildError 로 멈춘다 (`--restore` 먼저).
- **Resolve 21.0.4(App Store 판)에서 import 확인 (2026-09-08)**: 타임라인 `욕망은 오랜 병` 01:30:48:01(빌드 합계와 일치), V1 19클립(정지 17 + mp4 2), A1 19클립. 음원 `lane="-1"` → A1, 정지 이미지 → 곡 길이, mp4 → 영상 클립, 마커 → 각 V1 클립의 클립 마커(Index 패널 `M` 행)로 들어온다.
- Resolve 는 dotfiles `homebrew.masApps`(App Store 판, id 571213070)로 설치. 샌드박스라 첫 import 때 "Grant Access To Folder?" 가 뜨면 프로젝트 폴더를 선택한다(그 폴더가 Media Storage 위치로도 등록됨). Import 는 File > Import > Timeline 메뉴로만 가능하고 Import Media·컨텍스트 메뉴·Media Storage 드래그는 fcpxml 을 받지 않는다.
- 알려진 시각 이슈: 추출 커버는 YouTube 썸네일(1280x720)이라 정방형 아트 양옆에 회색 띠가 있다 — 중앙 crop 옵션 또는 V1 배경 교체로 해결 예정.

## GarageBand 선편집 왕복 (`build_daw.py` + `build_timeline.py --audio [--cues]`)

음원 편집은 DAW 에서 먼저 하고 싶다는 요청(2026-09-08). 처음엔 Reaper(.rpp 평문 생성·파싱)로 만들었지만 재광님이 GarageBand 로 결정해 Reaper 부분은 폐기(앱은 dotfiles cask 에서 빼고 rebuild 로 제거). GarageBand 는 프로젝트 생성도, 마커 내보내기도 안 되므로 **내보낸 믹스에서 곡 경계를 복원**하는 방식이다.

```bash
python3 build_daw.py 01.욕망은오랜병                                   # build/daw/{audio/*.wav, video/*.mp4} + 순서표
python3 build_daw.py 01.욕망은오랜병 --align build/daw/mix.wav          # 경계 복원 미리보기 → build/daw/cues.json
python3 build_timeline.py 01.욕망은오랜병 --audio build/daw/mix.wav [--cues build/daw/cues.json]
```

- `build_daw.build`: 19곡 48kHz/24bit WAV(영상 곡은 오디오만, ~1.5GB), 영상 곡은 `-map 0:v:0 -an -c copy` 로 무음 mp4(임베드 커버 png 스트림 제외). 소스 mtime 보다 새 산출물은 건너뛴다.
- `align_cues(mix, tracks)`: ffmpeg `ebur128` 의 100ms Momentary 라우드니스 곡선(dB, 무음은 -70 바닥)을 쓴다. (1) 원곡 **중앙 50%(최대 15초)** 를 템플릿으로 믹스에서 피어슨 상관 탐색(뭉치 평균 거친 탐색 → 근처 정밀 탐색, 91분 믹스 19곡에 약 11초). 곡 전체를 템플릿으로 쓰면 조용한 인트로·트림된 앞부분이 상관을 왜곡해 0.5초 어긋난다. (2) 템플릿 위치 ±0.6초에서 곡 전체의 '일치 샘플 수' 가 최대인 정렬로 미세 보정. (3) 정렬된 두 곡선의 차이 D=|믹스-원곡-이득| 로 경계를 잡는다 — 앞에서부터 2초 창 평균 D<4dB 이고 경계 샘플 D<3dB 인 첫 지점이 시작(=앞 트림), 뒤에서부터 같은 조건의 마지막 지점이 끝. 무음 감지(silencedetect)는 쓰지 않는다(조용한 인트로/아웃트로를 무음으로 먹어 최대 11초 잘랐음).
- 함정 세 가지(전부 테스트로 고정): ebur128 은 t=0.1 부터 값을 내되 0.4초 창이 채워지기 전엔 -70 이라 곡 앞 0.4초는 탐색에서 제외하고 시작 시각은 창 시작(st-0.4)으로 되돌린다 / 둘 다 -70 바닥이면 이득 보정을 적용하지 말고 같은 것으로 본다(안 그러면 볼륨을 바꾼 곡의 무음 인트로가 |gain| 만큼 어긋나 보임) / 조용한 인트로는 둘 다 조용해 정상적으로 일치하므로 "들릴 만큼 커야 한다" 같은 조건을 넣으면 시작이 늦어진다.
- 검증(2026-09-08): 실제 19곡 WAV 로 GarageBand 결과를 흉내 낸 91분 믹스(순서 두 쌍 교환, 곡 사이 1초, 1번 앞 3초 트림, 2번 볼륨 0.6) → 순서 19/19, 시작·길이 오차 최대 0.1초, 트림 2.9/3.0. 실제 GarageBand 내보내기(페이드·리버브 등 가공 포함)로는 아직 안 돌려봤다. 두 곡의 라우드니스 곡선이 아주 비슷하면(같은 곡 반복 등) 오인 가능 → cues.json 을 손으로 고쳐 `--cues`.
- mix 모드 `build_timeline`: `--audio` 만 주면 `build_daw.build` → `align_cues` → `build/daw/cues.json` 저장, `--cues` 를 주면 그 파일을 쓴다. FCPXML 은 스파인 = mix 한 `<asset-clip>`(A1), 곡마다 `lane="1"` 연결 클립(커버 `<video>` 또는 무음 mp4 `<asset-clip start=트림>`) + 마커. SRT·description 도 큐 기준. `--gap` 은 무시.
- 순환 import 주의: `build_daw` 가 `build_timeline` 을 import 하므로 `build_timeline.build` 는 `build_daw` 를 함수 안에서 지연 import 한다.
- **미검증**: 실제 GarageBand 내보내기로 `align_cues` 검증, mix 모드 FCPXML(스파인 오디오 + lane 1 영상, 커버는 다음 곡까지 `hold`)을 Resolve 가 A1/V1 로 받는지 — 첫 import 때 확인. 어긋나면 `align_cues` 상수(TEMPLATE_SEC·MATCH_DB·EDGE_DB·REFINE) 또는 `write_fcpxml` 의 mix 분기만 고치면 된다.

## 실행 (반드시 로컬 터미널 — 프리미엄 쿠키가 Chrome 에 있음)

```bash
brew install yt-dlp ffmpeg          # 이미 설치됨. brew yt-dlp 는 mutagen 포함(썸네일 임베드)
cd ~/code/compiler
python3 playlist_dl.py --cookies-from-browser chrome --dry-run   # 분류·파일명·포맷 확인
python3 playlist_dl.py --cookies-from-browser chrome             # 다운로드
```

- python3 는 Nix 것(3.11, pip 없음). 스크립트는 표준 라이브러리만 사용.
- 쿠키 브라우저는 chrome. (whale/safari 도 yt-dlp 가 지원)
- 명령 뒤에 `# 주석` 을 붙여 복사하면 인자로 들어가 argparse 에러가 난다. 주석 없이 한 줄씩.
- 클라우드/샌드박스 환경에서는 youtube.com 이 프록시 403 으로 막혀 있어 절대 실행 불가 — 로컬에서만.

## 포맷 정책 (유튜브 제작·업로드 호환이 최우선)

- **음원**: AAC `.m4a`. `-f "bestaudio[acodec^=mp4a]/bestaudio/best" -S abr -x --audio-format m4a` → 프리미엄이면 141(256k). 재인코딩 없음.
- **영상**: H.264 + AAC `.mp4`. `-S vcodec:h264,res,fps,hdr:12,acodec:aac --merge-output-format mp4 --remux-video mp4` (yt-dlp `-t mp4` 프리셋과 동일). YouTube 의 H.264 는 1080p 가 최대.
- 최고 품질(VP9/AV1 4K, opus)이 필요할 때만 `--video-container mkv --audio-codec best`.
- 둘 다 `--embed-thumbnail --embed-metadata` (커버 아트, 제목/아티스트/앨범 태그).
- yt-dlp 기본 정렬은 비트레이트보다 코덱 선호(opus>aac)를 먼저 보므로 `-S` 를 꼭 준다. (`-S abr` 없으면 256k AAC 대신 160k opus 를 고르는 것을 확인함)

## 음원/영상 분류 규칙 (playlist_dl.py `classify`)

1. `MANUAL_OVERRIDES` (영상 ID → "audio"/"video") 최우선
2. 채널명 `- Topic` / 설명 `Provided to YouTube by … Auto-generated by YouTube.` → audio
3. 제목에 live/실황/공연/MV/Official Video 등 → video
4. 제목에 Official Audio/Lyric/가사/Inst/MR 등 → audio
5. 스토리보드(미리보기 썸네일 띠) 프레임 변화량 < 10 → 정지 이미지 → audio (pillow 있을 때만; 실측 정지 0.8 / Topic 앨범아트 6 / 실황 20~60)
6. 기본값 video

## 파일명 규칙 `{nn}.{아티스트}-{곡명}.{확장자}` (`name_parts` / `safe_stem`)

파일명에서 공백은 `_` (`01.사뮈-아침의_빛.m4a`, `12.Nothing_But_Thieves-Ban_All_the_Music_(Live_at_The_O2).mp4`). 매니페스트의 `name` 은 공백 그대로(`사뮈-아침의 빛`)이고 `artist` 도 따로 기록한다.

**아티스트 (`artist_name`, 한글 우선·간략)**
1. `ARTIST_OVERRIDES` (영상 ID → 이름) 최우선
2. Topic 음원: 태그 2번째가 한글이고 앨범/트랙명이 아니면 그것 (`혁오 (HYUKOH)` → `혁오`, `넬(NELL)` → `넬`), 없으면 채널명에서 `- Topic` 제거 (`Muse`, `wave to earth`)
3. 비-Topic: yt-dlp `artist` → 제목 `Artist - Song` 접두어 (`Nothing But Thieves`, `NELL`) → 업로더(`VEVO` 제거)
4. 공통: 첫 아티스트만 (`,` `·` `feat.` `ft.` ` x ` 에서 끊음. `&` 는 밴드명에 흔해 안 끊음), 끝 괄호 보조표기 제거
5. 제목 접두어가 그 아티스트면 곡명에서 뗀다 (`Muse - Stockholm Syndrome [Live …]` → `Muse-Stockholm Syndrome [Live …]`)

**곡명 (`display_name`, 한글 우선)**
1. `Disease (병)` 처럼 영문 (한글) → 괄호 안 한글 `병`
2. 제목에 한글 있으면 그대로
3. Topic 음원은 태그 배열 [아티스트, 아티스트(한글), 앨범, 앨범(한글), 트랙, 트랙(한글)] 에서 트랙 한글명 (Light Of Morning → 아침의 빛, Agog → 아고그, Stranger → 이방인)
4. `X (X)` 중복 괄호 제거 (Loosing Control (Loosing Control) → Loosing Control)
5. 없으면 원제. YouTube 의 hl=ko 현지화 제목은 19곡 모두 없었음.

규칙이나 오버라이드를 고친 뒤에는 `python3 playlist_dl.py --rename <DIR> --cookies-from-browser chrome --dry-run` 으로 미리 보고 `--dry-run` 을 빼서 적용한다 — 항목별 메타데이터를 다시 조회해 downloads/ 의 `{nn}.*` 미디어 파일을 rename 하고 매니페스트를 갱신한다(재다운로드 없음). 쿠키 없이는 YouTube 봇 체크에 걸린다.

## 1번 재생목록 상태 (완료)

- '욕망은 오랜 병' (PLeRwSHXhNq6s, 송드리퍼, 19곡) — 19/19 다운로드 완료, ffprobe 로 길이·코덱·태그 검증 완료.
- video 2곡: 12 Nothing But Thieves Live at The O2 (1080p), 14 Muse Stockholm Syndrome Wembley (480p, 2008 업로드 — 원본 한계로 추정, `yt-dlp -F 9wV9_je85DE` 로 확인 가능)
- audio 17곡: 16곡 AAC 256k, 18 빈도시 인스트만 128k(그 영상의 AAC 최고치)
- 분류 규칙을 바꾸거나 오버라이드를 추가해 다시 받을 때는 archive_*.txt 에서 해당 ID 줄을 지워야 재다운로드된다.
- 2026-09-08 `--rename` 으로 19곡을 `{nn}.{아티스트}-{곡명}` 규칙으로 소급 적용 (재다운로드 없이 rename, 매니페스트 갱신).

## 남은 것 / 메모

- `~/Music/_to_delete_playlist_dl/` 에 초기 버전 스크립트 사본이 남아 있음 — 지워도 됨.
- git 저장소 (2026-09-08 init, main). `downloads/`·`archive_*.txt`·미디어 확장자는 `.gitignore` — 커밋되는 산출물은 `*/classification.json` 만.
- 코드 변경 후에는 `python3 test_offline.py` (yt-dlp 가 PATH 에 있어야 CLI 검증 단계까지 통과. pillow 없으면 스토리보드 섹션은 건너뛴다 — 스크립트와 같은 정책). `build_timeline.py` 를 고쳤으면 `python3 test_build_timeline.py`, `build_daw.py` 는 `python3 test_build_daw.py` (둘 다 ffmpeg 필요).
- 대화 언어는 한국어.

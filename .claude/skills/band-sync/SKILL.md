---
name: band-sync
description: 영상 프로젝트의 GarageBand 프로젝트(.band)를 iCloud Drive 원본 + 레포 프로젝트 폴더의 심볼릭 링크로 관리하는 스킬. 다른 맥에서 "그 프로젝트 가져와", "개러지밴드 프로젝트 불러와", ".band 연결해줘", "iCloud 에서 band 받아와" 라고 하거나, 새로 만든 .band 를 iCloud 로 올리자고 할 때, .band 상태·링크가 깨졌는지 물을 때 — "스킬"이라고 말하지 않아도 이 스킬을 쓴다.
---

# band-sync — .band 원본은 iCloud, 레포에는 링크

`.band` 는 음원 사본을 패키지 안(`Media/Audio Files/`)에 들고 있어 수 GB 이고 저장할 때마다 바이너리가 바뀌므로 git 에 넣지 않는다(`*.band` gitignore, 파일 하나가 GitHub 100MB 한도를 넘는다).
대신 원본은 iCloud Drive `compiler/<프로젝트>/<이름>.band` 에 두고, 레포의 `<프로젝트>/<이름>.band` 는 그걸 가리키는 심볼릭 링크로 둔다 — compiler 폴더 안에서 그대로 열고, 동기화는 iCloud 가 한다.

스크립트: `python3 .claude/skills/band-sync/scripts/band.py status|adopt|link` (자세한 건 `--help`). 테스트: `python3 .claude/skills/band-sync/scripts/test_band.py`.

## 요청별 절차

**다른 맥에서 가져오기** ("그 프로젝트 가져와")
1. `band.py status` 로 현재 상태를 본다. 레포에 프로젝트 폴더가 없으면 먼저 `git pull`.
2. `band.py link [프로젝트]` — 프로젝트를 말하지 않았으면 인자 없이 전부. iCloud 에 있는 .band 마다 링크를 만들고 패키지를 끝까지 읽어 iCloud 가 내려받게 한다(수 GB 면 몇 분 걸린다 → Bash `timeout` 을 넉넉히, 10분 상한).
3. 출력에 `미다운로드 N개` 가 남으면 Finder 에서 해당 .band 우클릭 → "지금 다운로드" 를 부탁하고 다시 `link`. iCloud 폴더 자체가 없으면 그 맥이 같은 Apple ID 로 iCloud Drive 를 켰는지 묻는다.
4. 보고: 링크한 .band, 다운로드 상태, "GarageBand 에서 `<프로젝트>/<이름>.band` 를 열면 된다" 한 줄.

**새 .band 를 iCloud 로 올리기** — GarageBand 로 레포 프로젝트 폴더 안에 새로 만든 경우: 앱을 종료하게 한 뒤 `band.py adopt <프로젝트>`. 같은 볼륨 안 이동이라 복사가 없다.

**상태 확인** — `band.py status`. 상태 의미:

| 상태 | 뜻 | 할 일 |
|---|---|---|
| `linked` | 정상 | — |
| `unlinked` | iCloud 에만 있음 | `link` |
| `local` | 레포에 실제 폴더만 있음 | `adopt` |
| `broken` / `foreign` | 링크가 없는 곳/다른 곳을 가리킴 | `link` 가 고친다 |
| `diverged` | iCloud 에도 있고 레포 쪽도 실제 폴더 | 아래 참고 — 자동으로 고치지 않는다 |

## 지키는 것

- GarageBand 가 실행 중이면 `adopt`/`link` 는 멈춘다. 열린 프로젝트를 옮기면 저장이 엉뚱한 곳으로 간다. `--force` 는 사용자가 앱에 다른 프로젝트만 열려 있다고 확인했을 때만.
- 같은 프로젝트를 두 맥에서 동시에 열지 않는다 — iCloud 가 `이름 2.band` 같은 충돌 사본을 만든다. 충돌 사본이 보이면 어느 쪽이 최신인지 사용자에게 묻는다.
- `diverged` 는 GarageBand 저장이 링크를 실제 폴더로 바꿨거나 누가 복사해 넣은 경우다. 두 폴더의 `Alternatives/000/ProjectData` 수정 시각을 보여주고 어느 쪽을 남길지 묻는다. 지우는 쪽은 휴지통(`mv ~/.Trash/`)으로 — `rm -rf` 하지 않는다.
- 링크는 iCloud 원본의 절대경로다. 사용자 이름이 다른 맥이면 그 맥에서 `link` 를 다시 돌리면 된다.

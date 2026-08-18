# 14health — 저장소 함정 메모

가족 건강기록을 옵시디안(Obsidian) vault로 관리하는 로컬 전용 도구.
CLI는 `pip install -e .` 후 `14health` 명령으로 사용한다.

## 개인정보 보호 규칙 (최우선 — 모델과 무관하게 항상 유효)

1. **건강 데이터는 vault에만**: 수치(혈압·혈당·체중 등)·증상·처방약·진단·분석
   본문은 로컬 옵시디안 vault의 노트에만 기록한다. 다음 어디에도 포함 금지:
   - git 커밋/푸시 (vault는 저장소 밖에 있어야 함)
   - 웹 검색 쿼리, 외부 API 호출
   - 노션 (마스킹된 이력 5개 필드만 허용 — `vault관리` 스킬 참조)
2. **실명 금지**: 개인은 관계호칭(나/부인/아들/딸/어머니 …)으로만 기록한다.
   입력 자료에 실명이 있으면 저장 전에 관계호칭으로 치환한다
   (`14health alias add <실명> <관계호칭>` 등록 시 자동 치환).
3. **vault 경로 확인**: 파일을 쓰기 전에 vault가 이 저장소 밖인지 확인한다 (`14health config show`).
4. 의학 정보 안내 시 항상 "참고 정보이며 진단이 아님"을 고지한다.

이 4개는 실증된 실패 모드가 있는 안전 규칙이라 모델 세대와 무관하게 그대로 적용한다.

## 모델별 동작 (2026-07-25, Anthropic Claude 5 컨텍스트 엔지니어링 가이드 반영)

위 개인정보 규칙 외의 나머지는 **함정만** 담는다. 절차는 `.claude/skills/`에 있고 필요할 때만 연다.

- **Opus 5 / Fable 5**(`claude-opus-5`, `claude-fable-5`): 금지령이 아니라 배경지식으로 읽고 스스로 판단.
- **Sonnet 5 이하 · Haiku · 타사 모델**: 스킬을 **먼저 열어** 절차대로 수행 (Gemini CLI는 `GEMINI.md`).
- 원본 규칙: second-brain 볼트 `14rae_work/00_지침/2026-07-25_모델별-운영규칙.md` (`/doctor`로 주기 점검)

## 스킬

| 스킬 | 용도 |
|---|---|
| `/건강입력` | 대화로 검진 수치·진료 기록·가족력 입력 |
| `/검진분석` | 결과지 이미지·캡쳐 판독 → 확인 → 저장 |
| `/위험분석` | 위험도 분석·추천 리포트 생성 + 해설 |
| `/대시보드` | 시각화 HTML 갱신, 카톡 공유 PNG |
| `/vault관리` | 경로 설정, 기기이동 내보내기/가져오기, 노션 이력 동기화 |
| `/github-14health` | 커밋 전 확인 · 푸시 |

## 함정

- 소스 `src/health14/` · 테스트 `python3 -m pytest tests/ -q`
- **수치 기준은 한 곳에만**: `src/health14/data/guidelines/*.yaml`(국가건강검진 기준) — 기준 변경 시 여기만 수정.
- **템플릿은 단일 자립형**: `templates/dashboard.html`, `templates/app.html` 에 외부 CDN·폰트·API 참조를
  추가하지 말 것.
- **webapp은 얇은 API 레이어**: 새 로직은 CLI 모듈에 넣고 webapp은 호출만 한다. 상세 `docs/webapp.md`.
- 테스트는 `HEALTH14_CONFIG` 환경변수로 실제 사용자 설정과 격리돼 있다(`tests/conftest.py`).
- **보험 노트에 증권번호·고객번호 필드를 추가하지 말 것** — `insurance.FIELDS` 화이트리스트
  밖은 저장되지 않도록 설계돼 있고 테스트가 이를 고정한다.
- **노트 쓰기는 항상 `vault.write_note()`** — Syncthing 대비 원자적 쓰기(`os.replace`)와
  파싱 캐시 무효화가 여기 묶여 있다. `path.write_text()` 직접 호출 금지.
- `vault.read_note()` 는 mtime/size 기반 캐시를 쓴다(노트 2,400개에서 1.7초 → 67ms).
  결과는 복사본이므로 자유롭게 변형해도 된다.
- 배포·자동화 문서: `docs/tabs9-배포.md`(Tab S9 proot), `docs/n8n-워크플로우.md`,
  `docs/아키텍처.md`(APK 검토·성능 실측·외부 API 판정), `docs/APK-로드맵.md`.

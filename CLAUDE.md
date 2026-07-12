# 14health — Claude Code 작업 규칙

가족 건강기록을 옵시디안(Obsidian) vault로 관리하는 로컬 전용 도구.
CLI는 `pip install -e .` 후 `14health` 명령으로 사용한다.

## 개인정보 보호 규칙 (최우선 — 반드시 준수)

1. **건강 데이터는 vault에만**: 수치(혈압·혈당·체중 등)·증상·처방약·진단·분석
   본문은 로컬 옵시디안 vault의 노트에만 기록한다. 다음 어디에도 포함 금지:
   - git 커밋/푸시 (vault는 저장소 밖에 있어야 함)
   - 웹 검색 쿼리, 외부 API 호출
   - 노션 (마스킹된 이력 5개 필드만 허용 — vault관리 스킬 참조)
2. **실명 금지**: 개인은 관계호칭(나/부인/아들/딸/어머니 …)으로만 기록한다.
   입력 자료에 실명이 있으면 저장 전에 관계호칭으로 치환한다
   (`14health alias add <실명> <관계호칭>` 등록 시 자동 치환).
3. **vault 경로 확인**: 파일을 쓰기 전에 vault가 이 저장소 밖인지 확인한다.
   경로는 `14health config show` 로 확인.
4. 의학 정보 안내 시 항상 "참고 정보이며 진단이 아님"을 고지한다.

## 스킬

| 스킬 | 용도 |
|---|---|
| `/건강입력` | 대화로 검진 수치·진료 기록·가족력 입력 |
| `/검진분석` | 결과지 이미지·캡쳐 판독 → 확인 → 저장 |
| `/위험분석` | 위험도 분석·추천 리포트 생성 + 해설 |
| `/대시보드` | 시각화 HTML 갱신, 카톡 공유 PNG |
| `/vault관리` | 경로 설정, 기기이동 내보내기/가져오기, 노션 이력 동기화 |

## 로컬 웹앱

`14health app` (`src/health14/webapp.py` + `templates/app.html`) — 표준 라이브러리
`http.server`만 사용하는 `127.0.0.1` 전용 GUI. 최초 실행 시 `/api/state`의
`hasVault`가 false면 Vault 생성 화면을 보여주고, 생성 후에는 config에 경로가
저장되어 재실행해도 다시 뜨지 않는다. CLI(`intake.py`, `vault.py`, `analysis.py`
등)를 그대로 재사용하는 얇은 API 레이어이므로 새 로직은 가능한 한 CLI 모듈에
추가하고 webapp은 호출만 하도록 유지한다.

## 개발

- 소스: `src/health14/` · 테스트: `python3 -m pytest tests/ -q`
- 가이드라인 데이터: `src/health14/data/guidelines/*.yaml`
  (국가건강검진 기준 — 수치 기준 변경 시 여기만 수정)
- 대시보드/앱 템플릿: `src/health14/templates/dashboard.html`, `templates/app.html`
  (단일 자립형 — 외부 CDN·폰트·API 참조를 추가하지 말 것)
- 테스트 실행 시 실제 사용자 설정을 건드리지 않도록 `HEALTH14_CONFIG` 환경변수로
  격리되어 있다 (tests/conftest.py).

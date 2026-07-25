# 14health — Gemini CLI 작업 규칙

가족 건강기록을 옵시디안(Obsidian) vault로 관리하는 로컬 전용 도구.
CLI는 `pip install -e .` 후 `14health` 명령으로 사용한다.

## 개인정보 보호 규칙 (최우선 — 반드시 준수)

1. **건강 데이터는 vault에만**: 수치(혈압·혈당·체중 등)·증상·처방약·진단·분석
   본문은 로컬 옵시디안 vault의 노트에만 기록한다. git 커밋, 웹 검색 쿼리,
   외부 API 호출, 노션 본문 어디에도 포함하지 않는다.
2. **실명 금지**: 개인은 관계호칭(나/부인/아들/딸/어머니 …)으로만 기록한다.
   입력 자료의 실명은 저장 전에 관계호칭으로 치환한다
   (`14health alias add <실명> <관계호칭>` 등록 시 자동 치환).
3. **vault 경로 확인**: vault가 이 저장소 밖인지 확인 (`14health config show`).
4. 의학 정보 안내 시 항상 "참고 정보이며 진단이 아님"을 고지한다.

※ Gemini로 이미지를 분석하면 이미지가 Google 서버로 전송된다. 민감한 결과지는
사용자에게 이 점을 먼저 알리고 진행 여부를 확인한다.

## 지침을 따르는 방식 (2026-07-25)

`CLAUDE.md` 는 Claude Opus 5 / Fable 5 세대를 기준으로 "함정만 남기고 절차는 스킬로 분리"돼 있다.
**Gemini를 포함한 타사 모델은 그 완화 대상이 아니다** — 작업 전에 해당 절차 문서
(`.claude/skills/<이름>/SKILL.md`, 이 저장소에서는 `.gemini/commands/*.toml` 이 `@`로 물고 있다)를
**먼저 열어 단계대로 수행하고, 판단으로 단계를 건너뛰지 않는다.**

배경: [Anthropic — Claude 5 세대 컨텍스트 엔지니어링](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models)
(원본 규칙은 second-brain 볼트 `14rae_work/00_지침/2026-07-25_모델별-운영규칙.md`)

## 커스텀 명령

`.gemini/commands/` 에 정의됨: `/건강입력` `/검진분석` `/위험분석` `/대시보드` `/vault관리`

## 주요 CLI

```bash
14health app                                 # 로컬 웹앱 GUI (최초실행 시 Vault 생성 화면)
14health init --vault <경로>                 # vault 생성·경로 등록
14health member add <관계호칭> --birth 1980 --sex M
14health checkup add <관계호칭> --year 2025 --field 혈압=120/80 --field 체중=72
14health visit add <관계호칭> --date 2026-07-01 --hospital 내과 --symptom 기침
14health history add --relation 부 --disease 고혈압
14health note write <관계호칭> --json <파일>   # 이미지 판독 결과 구조화 저장
14health analyze <관계호칭>                   # 위험도 분석 리포트
14health dashboard                           # 시각화 HTML
14health share <관계호칭>                     # 카톡 첨부용 PNG
14health export / import <zip> --vault <경로> # 기기 이동
14health log [--sync-notion]                 # 이력 조회·노션 동기화(마스킹)
```

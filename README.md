# 14health — 가족 건강기록 옵시디안 관리

가족(나·부인·아들·딸 + 기타 관계호칭)의 **건강검진 결과·진료 기록·가족력**을
이미지/첨부파일/대화로 입력받아 **옵시디안(Obsidian) 마크다운 노트로만** 저장하고,

- 주요 질병 위험도 분석
- 연령·가족력 맞춤 검진 항목·주기 추천 (국가건강검진 기준)
- 생애주기별 건강관리·생활습관 권고
- 추천 진료과·병원 방문 주기

를 제안하는 **개인용 로컬 도구**입니다.

## 개인정보 보호 원칙

| 원칙 | 구현 |
|---|---|
| 건강 데이터는 로컬에만 | 모든 수치·증상·처방은 옵시디안 vault(로컬 폴더)에만 저장. 서버·클라우드 없음 |
| 실명 미저장 | 관계호칭(나/부인/아들/딸/어머니 …)만 사용. 입력 자료의 실명은 자동 치환(`alias`) |
| 외부 업데이트 금지 | 유일한 예외는 노션 **마스킹 이력**(날짜·대상·작업유형·제목·옵시디안 링크 — 수치·실명 없음) |
| vault는 저장소 밖 | git에 건강 데이터가 올라가지 않음 (`.gitignore` 이중 방어) |

## 설치

```bash
git clone https://github.com/vierzhen-del/14health
cd 14health
pip install -e ".[share]"        # share PNG 기능 포함 (Pillow)
```

## 시작하기 — 앱(GUI)으로 시작하는 가장 쉬운 방법

```bash
14health app
```

브라우저가 자동으로 열립니다 (`http://127.0.0.1:8420`, 외부 접속 불가).
**최초 실행 시** "옵시디안 Vault 만들기" 버튼이 있는 시작 화면이 뜹니다 — 경로를 확인하고
누르면 vault가 생성됩니다. **한 번 생성된 뒤에는 앱을 다시 실행해도 이 화면이 다시 뜨지
않고** 바로 가족 건강 현황으로 진입합니다(설정이 로컬 config에 저장되기 때문). 앱 안에서
구성원 등록·검진/진료/가족력 입력·위험도 분석·대시보드·내보내기까지 전부 처리할 수 있습니다.

옵션: `14health app --port 9000` (포트 지정) · `--no-browser` (자동 오픈 안 함)

## 시작하기 — CLI로 시작하기

```bash
# 1) vault 생성 (기존 옵시디안 vault 경로를 지정해도 됨)
14health init --vault ~/Documents/건강vault

# 2) 가족 등록 — 관계호칭만 사용
14health member add 나   --birth 1978 --sex M
14health member add 부인 --birth 1981 --sex F
14health member add 아들 --birth 2008 --sex M
14health member add 딸   --birth 2012 --sex F

# 3) 가족력
14health history add --relation 부 --disease 고혈압

# 4) 검진 수치 입력 (혈압은 120/80 형태, 신장+체중 시 BMI 자동)
14health checkup add 나 --year 2025 --field 혈압=138/88 --field 공복혈당=115 \
    --field 체중=80 --field 신장=174 --field LDL=152

# 5) 진료 기록
14health visit add 딸 --date 2026-06-20 --hospital 소아과 \
    --symptom 기침 --symptom 발열 --diagnosis 급성기관지염 --rx 해열제

# 6) 분석·시각화
14health analyze 나          # 위험도 분석 노트 생성
14health dashboard           # <vault>/대시보드.html 생성
14health share 나            # 카톡 첨부용 요약 PNG
```

## 입력 방식 4가지

| 방식 | 사용법 | 이미지 분석 |
|---|---|---|
| **로컬 웹앱** | `14health app` → 브라우저 GUI (구성원/검진/진료/가족력 폼, 홈·가족·일정·설정 탭) | 지원 안 함 (수치는 직접 입력) |
| **Claude Code** (대화·이미지 권장) | 이 저장소에서 Claude Code 실행 → `/건강입력` `/검진분석` `/위험분석` `/대시보드` `/vault관리` | Claude가 세션 안에서 직접 판독 |
| **Gemini CLI** | 같은 명령이 `.gemini/commands/` 에 정의됨 | Google 서버 전송 수반 — 실행 전 경고 표시 |
| **Python CLI 단독** | 위 `14health` 명령 직접 사용 | 로컬 OCR: `14health ocr <이미지/폴더>` (tesseract 필요) |

네 가지 방식은 같은 vault를 공유합니다 — 웹앱으로 입력한 데이터를 Claude 스킬로 분석하거나,
CLI로 넣은 데이터를 웹앱 대시보드에서 바로 확인할 수 있습니다.

## 시각화 대시보드

`14health dashboard` → `<vault>/대시보드.html` (단일 파일, **외부 네트워크 요청 없음**)

- **홈**: 가족 건강 현황 카드 — 혈압/혈당/BMI + 정상·주의·위험 배지 + 추이 스파크라인
- **가족**: 구성원 선택 시 연도별 수치 차트(기준선 표시)·위험도·추천 검진·생활습관 전환
- **일정**: 향후 1년 분기별(Q1~Q4) 검진 계획 + 생애주기(영유아기~노년기) 검진 타임라인
- **공유 이미지 저장** 버튼: 브라우저에서 PNG 생성 → 카카오톡에 직접 첨부

## 기기변경 (vault 이동)

```bash
14health export                          # vault 전체 zip (90-내보내기/)
# zip을 새 기기로 복사 후:
14health import <zip> --vault <새 경로>   # 압축 해제 + 경로 자동 전환
```

앱 데이터는 vault와 로컬 설정 파일이 전부이므로 zip 하나로 이동이 끝납니다.
기존 옵시디안 vault를 계속 쓰려면 `14health config set vault <경로>` 로 연결만 하면 됩니다.

## 노션 이력 동기화 (선택)

노션에는 **작업 이력만** 올라갑니다: 날짜 · 대상(관계호칭) · 작업유형 · 제목(수치 마스킹) ·
옵시디안 링크. 상세 내용은 옵시디안에서만 볼 수 있습니다.

```bash
14health config set notion_token <integration 토큰>
14health config set notion_database_id <"14health 이력" DB ID>
14health log --sync-notion
```

Claude Code 사용 시에는 토큰 없이 Notion MCP로 `/vault관리` 스킬이 처리합니다.

## Vault 구조

```
<vault>/
├── 00-가족/            가족구성.md · 가족력.md · 이력.md
├── 구성원/<관계호칭>/
│   ├── 프로필.md
│   ├── 검진/2025-건강검진.md      (frontmatter 수치 → 추이 분석)
│   ├── 진료/2026-06-20-소아과.md
│   └── 분석/2026-07-위험도분석.md
├── 90-내보내기/         export zip · 공유 PNG
└── 대시보드.html
```

## 면책

본 도구의 분석·추천은 국가건강검진 기준을 참고한 **규칙 기반 참고 정보**이며
의학적 진단이 아닙니다. 이상 소견은 반드시 의료진과 상담하세요.

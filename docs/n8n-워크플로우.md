# n8n 워크플로우 설계 (Tab S9)

Tab S9의 proot Ubuntu 안에서 n8n(포트 5678)과 14health가 **같은 파일시스템**을
공유하므로, n8n은 HTTP가 아니라 **Execute Command 노드로 CLI를 직접 호출**하는 것이
가장 단순하고 빠르다. 네트워크를 타지 않으니 건강 데이터가 프로세스 밖으로 나가지 않는다.

```
[Schedule Trigger] → [Execute Command: 14health … --json] → [Code: 가공]
                                                            ├→ [Write File: vault에 리포트]
                                                            └→ [Telegram: 마스킹 요약]
```

## 공통 규칙

1. **모든 실행은 Tab S9 로컬** — 클라우드 n8n·cloudflared 터널로 내보내지 않는다.
2. **텔레그램에는 수치·병명을 보내지 않는다.** "3건 확인 필요" 수준의 마스킹 요약만.
   상세는 옵시디안 노트를 직접 열어 본다.
3. Execute Command 노드는 proot 안에서 실행되므로 `14health` 가 PATH에 있어야 한다.
   없으면 절대경로(`/usr/local/bin/14health`)를 쓴다.
4. n8n이 vault에 직접 쓰지 않는다 — 항상 14health CLI를 거친다(익명화·검증 통과).

## 사용하는 CLI (모두 `--json` 지원)

```bash
14health recommend --json            # 가족 전체 예방검진 추천
14health recommend 나 --json --save  # 개인, 분석 노트로 저장까지
14health claims --json               # 실비 미청구 목록(시효 포함)
14health member list                 # 구성원 목록
14health insurance list              # 보험 목록
```

---

## 1. 주간 가족 건강 리포트

**트리거**: Schedule — 매주 일요일 21:00

```
Schedule
 → Execute Command:  14health recommend --json --save
 → Code:             결과를 마크다운 리포트로 조립
 → Write Binary File: /root/obsidian/14health-vault/90-리포트/주간-{{$now.format('yyyy-MM-dd')}}.md
 → Telegram:         "이번 주 가족 건강 리포트가 준비됐습니다 (구성원 N명)"
```

Code 노드 예시:

```javascript
const { results } = JSON.parse($input.first().json.stdout);
const lines = [`# 주간 가족 건강 리포트 (${new Date().toISOString().slice(0,10)})`, ''];
for (const r of results) {
  lines.push(`## ${r.display} (${r.age}세 · ${r.stage})`);
  lines.push(r.opinion, '');
  if (r.risks.length) {
    lines.push('| 항목 | 판정 |', '|---|---|');
    for (const x of r.risks) lines.push(`| ${x.metric} | ${x.status} — ${x.label} |`);
    lines.push('');
  }
  const recs = r.recommendations.slice(0, 5)
    .map(x => `- ${x.name} (${x.interval_years}년 주기)`);
  if (recs.length) lines.push('**권장 검진**', ...recs, '');
}
lines.push('> 규칙 기반 참고 정보이며 의학적 진단이 아닙니다.');
return [{ json: { markdown: lines.join('\n'), count: results.length } }];
```

텔레그램 메시지는 `{{$json.count}}명 리포트 생성` 처럼 **건수만** 보낸다.
각 결과의 `summary.masked` 필드("위험 1건 · 주의 2건 · 개선 1건")는 수치·항목명이
없는 사전 마스킹 요약이라 텔레그램 본문에 그대로 써도 안전하다.

## 2. 검진 주기 알림

**트리거**: Schedule — 매월 1일 09:00

```
Schedule
 → Execute Command:  14health recommend --json
 → Code:             주기가 도래한 검진만 필터 (아래)
 → IF (건수 > 0)
 → Telegram:         "이번 달 받아야 할 검진이 있는 가족: 아버지, 큰아들"
```

```javascript
const { results } = JSON.parse($input.first().json.stdout);
const due = results
  .filter(r => (r.quarters?.Q1 || []).length || (r.recommendations || []).length)
  .map(r => ({ display: r.display, items: (r.recommendations || []).slice(0, 3).map(x => x.name) }));
return due.map(d => ({ json: d }));
```

## 3. 실비 미청구 알림 ⭐

보험 기능과 직접 연결된다. 실손 청구권 소멸시효는 3년이라, 놓치면 돈이 사라진다.

**트리거**: Schedule — 매주 월요일 09:00

```
Schedule
 → Execute Command:  14health claims --json
 → Code:             urgent(시효 임박) / expired(경과) 분류
 → IF (urgent 또는 미청구 존재)
 → Telegram:         "실비 미청구 4건 · 그중 1건은 시효 임박. 앱에서 확인하세요"
```

```javascript
const pending = JSON.parse($input.first().json.stdout);
const urgent  = pending.filter(p => p.urgent && !p.expired);
const expired = pending.filter(p => p.expired);
// 금액·병원명은 텔레그램에 넣지 않는다 — 건수만
return [{ json: {
  total: pending.length - expired.length,
  urgent: urgent.length,
  expired: expired.length,
  message: `실비 미청구 ${pending.length - expired.length}건`
    + (urgent.length ? ` · ⚠️ ${urgent.length}건 시효 임박` : '')
    + (expired.length ? ` · ❌ ${expired.length}건 시효 경과` : ''),
}}];
```

## 4. 영수증 폴더 감시 (반자동)

카메라로 찍은 영수증이 다운로드 폴더에 쌓이면 초안을 만들어 확인을 요청한다.
**자동 저장은 하지 않는다** — OCR 오독 가능성이 있어 사람이 확인한 뒤 저장한다.

**트리거**: Local File Trigger — `/root/obsidian/../Download` 에 새 이미지

```
Local File Trigger (added)
 → Execute Command:  14health ocr "{{$json.path}}"
 → Code:             자동매칭된 구성원·문서종류 추출
 → Telegram:         "영수증 1장 인식 — 큰아들 / 약국영수증. 앱 입력 탭에서 확인하세요"
```

앱을 열어 **입력 → 📷 사진**에서 같은 파일을 고르면 자동매칭 + 폼 프리필까지 이어진다.

---

## Claude CLI로 워크플로우 만들기

Tab S9의 proot 안에 `n8n-mcp` 가 이미 등록돼 있으므로(`claude mcp add n8n-mcp`),
Claude에게 자연어로 시키면 n8n API를 통해 워크플로우를 직접 만들고 활성화할 수 있다.

```bash
proot-distro login ubuntu
cd /root/14health && claude
```

```
docs/n8n-워크플로우.md 의 3번(실비 미청구 알림)을 n8n에 만들어줘.
Execute Command 노드는 `14health claims --json` 을 쓰고,
텔레그램에는 건수만 보내야 해. 만든 뒤 Active로 켜줘.
```

Claude가 n8n-mcp로 워크플로우를 생성하면, n8n 웹 UI(`http://127.0.0.1:5678`
또는 Tailscale `http://100.x.y.z:5678`)에서 결과를 확인한다.

## 점검 목록

- [ ] `14health` 가 proot의 PATH에 있는지 (`which 14health`)
- [ ] `HEALTH14_CONFIG` 가 n8n 프로세스에도 보이는지 — 안 보이면 Execute Command에
      `HEALTH14_CONFIG=/root/.config/14health/config.yaml 14health …` 로 명시
- [ ] 리포트 저장 경로가 Syncthing 폴더 안인지 (다른 기기에서도 보이게)
- [ ] 텔레그램 메시지에 수치·병명·실명이 없는지 **직접 눈으로 확인**
- [ ] 워크플로우 Active 토글 ON, 수동 1회 실행 성공

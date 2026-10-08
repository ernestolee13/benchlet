# 형식 계약

스킬로 만들든 손으로 만들든 **게시하려면 이 형식이어야 한다.** `bench_validate` 가 검사한다.

## 최소 형식 (손으로 만들 때는 이것만, 2026-09-30 사용자 결정)

벤치 하나는 셋으로 돌아간다. **공통 가이드**(벤치당 하나), **항목**(입력과 정답), **응답 형태**(선택지). 나머지는 도구가 채운다.

```yaml
# bench.yaml
name: sns-numbers-sourced
guide: >
  이 칼럼 본문에 주어진 리서치에 없는 수치, 기관명, 인용문이 있는가.
  수치·기관명·직접 인용만 본다. 설명이나 기전 같은 일반 서술은 세지 않는다.
  리서치의 수치를 그대로 쓴 것, 리서치에 있는 기관을 다시 언급한 것은 「없다」다.
  입력은 [리서치 요약] 다음에 [칼럼 본문]이다.
choices: [있다, 없다]          # 첫 번째가 질문의 「예」
items:                          # 또는 items.jsonl
  - input: "[리서치 요약] … [칼럼 본문] …"
    target: 0
    evidence: "본문 2파트 「응답자 52%」, 리서치에는 41%"   # 권장. 없으면 검수가 안 된다
    class: P-number                                        # 권장. 없으면 실패 구조가 안 보인다
```

도구가 채우는 것: `id`, `type`(선택지 2개면 binary), `question`(= guide), `label_source`(안 적으면 judged), `cluster`, `provenance`, `difficulty`, 매니페스트의 서명·해시·판본. 실행 함정(reasoning 끄기, provider 핀, 극성 반전, 셔플, 글자 접두)은 러너가 처리하고 작성자는 모른다.

**권장 세 칸.** `evidence` 는 라벨을 남이 따질 수 있게 하고, `class` 는 「전부 그렇다」 같은 실패 구조를 보이게 하며, `label_source` 는 결과를 얼마나 믿을지를 정한다. 셋이 없어도 돌아가지만 갤러리에는 「검수 정보 없음」으로 표시된다.

## 확장 형식 (도구가 내부에서 쓰는 항목, JSONL 한 줄)

```json
{"id": "audit-017", "input": "<상태 또는 본문>", "question": "이 글 본문에 발행 전 지워야 할 잔재가 남아 있는가",
 "choices": ["있다", "없다"], "target": 0,
 "type": "binary", "label_source": "machine", "class": "R2-codefence", "difficulty": "medium", "cluster": "post-0412",
 "evidence": "본문 3행 ``` 로 시작하는 코드펜스",
 "provenance": {"generator": "build_sns_audit.py", "seed": 20260930, "verifier": "published_text_audit.py", "label_path": 1, "read_by_human": false},
 "metadata": {}}
```

- `choices` 에 글자 접두(A.)를 넣지 않는다. 셔플·재매핑은 러너가 한다
- `target` 은 `choices` 의 인덱스
- 이진 과제는 **질문 문구의 극성과 `target=0` 의 뜻이 같아야 한다.** 「위반인가」이면 0 = 위반
- `label_source`: machine(검증기·규칙 실행) | constructed(규칙대로 심음) | judged(사람 판정) | agent(에이전트 판정. 사람 검수 뒤 judged 로 바꾼다) | outcome(사후 결과)
- `evidence`: 정답 근거. 규칙 문장이나 원문 위치. **없으면 항목을 버린다**
- **`question` 에 판정 정의를 넣는다.** 「잔재가 있는가」처럼 용어만 있으면 모델은 자기 정의로 답한다. 무엇이 위반인지(유형 목록·기준 수치·예외)를 질문 본문에 쓴다. 우리 편집 규범 벤치가 위반 유형 6개를 질문에 적어 jev 96.7% 였고, 같은 구조의 잔재 감사 벤치가 정의 없이 물어 52% 였다(2026-09-30). 정의는 항목마다 같으므로 길어도 된다
- `cluster`: 같은 원문·사건·템플릿에서 나온 항목의 묶음. 클러스터 표준오차용. 같은 사건의 양성과 음성(다른 기업에 잘못 붙은 기사 등)은 같은 클러스터다. 라벨이 아니라 원천이 기준이다
- `provenance.label_path`: 1 있는 라벨 샘플링 | 2 규칙 심기 | 3 패턴 모방 생성
- 개인정보 금지: 사람 이름, 이메일, 전화, 계정 ID, 회사·고용주 도메인, 내부 IP, 키·토큰

## 매니페스트 (`manifest.yaml`)

`benchlet manifest --bench <이름> --goal <goal> --unit <unit> --generator <경로> --source <설명>` 으로 만든다(옵션을 처음부터 다 준다). 채운 뒤 `benchlet validate <이름>` 이 매니페스트도 같이 검사한다(필수 필드·서명·해시·질문·선택지·n 일치). 사람 검수 전에 동결해도 되지만 검수에서 라벨이 바뀌면 version 을 올리고 다시 동결한다. 손으로 쓰면 질문 값에 콜론이 있어 YAML 이 깨지므로 질문은 따옴표로 감싼다. `items_sha256` 에는 항목 파일의 해시 값을 그대로 쓴다(동결 목록은 `labels/SHA256SUMS`, 사전등록은 벤치마다 `tasks/<이름>.preregister.md`). 라벨 경로 2 벤치의 「예상 n」은 생성기를 돌려야 확정된다. 계획서에는 「실행 뒤 확정」이라 적는다.

```yaml
name: sns-published-audit
version: 1
task_signature: {goal: compliance, answer: binary, prob_use: accuracy_only, label: machine, unit: post, language: ko, n: 80}
question: "이 글 본문에 발행 전 지워야 할 잔재가 남아 있는가. 잔재는 다음 여섯 가지다. (1) ..."
choices: [있다, 없다]
generator: {script: src/build_sns_audit.py, seed: 20260930}
source: 발행된 스레드 글과 감사 스크립트 규칙 6종 (원자료 비공개)
visibility: sample
items_sha256: <항목 파일 sha256>
review: {checks_run: 0, human_reviewed_fraction: 0.2, flagged: 0, decided: 0}
license: CC-BY-4.0
```

## 생성기

스크립트 하나와 시드 하나로 항목 파일이 재현돼야 한다. 원자료 경로는 스크립트 안에 두되 자격증명은 환경변수에서 읽는다. 원자료가 비공개면 `visibility: sample` 로 두고 표본 5건만 게시한다.

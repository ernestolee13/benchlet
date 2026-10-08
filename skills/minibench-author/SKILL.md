---
name: minibench-author
description: Build a small judgment benchmark (40-100 yes/no, multiple-choice, or route-selection items) from a project's own data, review it, and run it across cheap models. Use when someone wants to pick or regression-test a model for a specific judgment point (approval gate, rule check, classifier, router) using their own data. Not for knowledge quizzes or taste questions.
license: MIT
compatibility: Needs read access to the project repo. Model calls go through the bench MCP server or the CLI in this repo.
metadata:
  version: "0.1-draft"
  lessons: references/lessons.md
---

# minibench-author

프로젝트 안의 **판정 지점**을 찾아 40~100건짜리 벤치로 만든다. 지식을 묻지 않고, 취향을 묻지 않고, 사람·계정·회사를 특정할 값을 넣지 않는다.

## 두 규칙 (항상)

- 항목과 표본에 사람·계정·회사를 특정할 수 있는 값을 넣지 않는다. 뽑는 즉시 역할·업종·번호로 치환한다. 게시 전 개인정보 스캔이 0건이어야 한다.
- 질문은 규칙 준수나 사실 도출만 묻는다. 취향·품질 인상은 묻지 않는다. 정답의 근거(규칙 문장 또는 원문 위치)를 항목에 같이 적는다. 근거를 못 적으면 그 항목은 버린다.

## 절차

1. **발견.** `references/discovery.md` 대로 프로젝트를 읽고(공개 벤치를 시드로 쓰거나 포크할 때는 `references/public-seeds.md`) 후보 8~12개를 서명과 함께 `discovery.md` 로 낸다. 라벨이 이미 있는 곳부터 찾는다. 후보마다 `bench_similar`(질문·서명) 와 `bench_search`(domain·keywords, 공개 갤러리까지 검색, `references/taxonomy.md` 어휘) 로 갤러리에 비슷한 벤치가 있는지 먼저 본다. 있으면 「포크 / 새로 만들기」를 사용자에게 보이고, 같은 영역의 공개 벤치 축약본이 있으면 모델을 먼저 걸러 보라고 권한다.
2. **게이트·서명·분류.** 판단·품질평가인가. 모델이 답할 수 있나. soft 규칙을 이진으로 묻지 않나. 후보마다 서명 5축(goal·answer·prob_use·label·unit)을 고정하고 `references/taxonomy.md` 의 분류(domain·input_kind·source_kind·language)와 키워드 2~5개를 같은 어휘로 적는다. 올릴 때와 찾을 때 같은 말을 써야 남이 찾는다.
3. **계획·선택.** `references/plan.md` 대로 라벨 경로·등급·권장 n·검수 시간·비용 표를 내고 사용자가 고른다. `plan.yaml` 로 잠근다. 사용자가 가정한 라벨(승인·반려 등)이 실제로 없으면 그 벤치는 「나중」이 원칙이지만, 사용자가 그 벤치를 이번 회차에 요구했으면 라벨 경로 2 로 내리고 계획서와 회차 기록에 가정 위반을 적는다. 만들기 전에 `benchlet list` 로 로컬 중복을 본다.
4. **질문 쓰기.** `references/question.md` 규칙대로. 한 문장 질문 + 정의 + 예외 + 범위 + 입력 설명. 취향어 금지. 결정은 가장 높은 확률이고 임계를 옮기지 않는다.
5. **채우기.** 고른 벤치마다 `references/generate.md` 대로 생성기(스크립트+시드)를 쓰고 항목을 만든다. 형식은 `references/format.md`.
6. **눈으로 읽기.** 심기·생성 항목은 전부, 기계 라벨 항목은 20% 이상. 사람이 읽었으면 `provenance.read_by_human`, 에이전트가 읽었으면 `read_by_agent` 에 남긴다. 에이전트 읽기는 사람 검수가 아니므로 검수 큐에 사람 몫이 남는다. 「불일치 0건」 출력은 증거가 아니다. 뻔한 양성 3·음성 2 에는 `difficulty: easy` 를 달아 두되 클래스마다 하나씩 흩어 단다(스모크가 클래스를 돌아가며 고른다).
7. **자가 점검.** `references/rubric.md` 14항. 하나라도 아니오면 고친다.
8. **검수 도구.** `bench_review` 로 자동 검사(생성기와 다른 패밀리 모델). 큐를 사람이 처리. `bench_freeze` 로 해시와 사전등록.
9. **질문 스모크 → 실행·읽기 (선택).** 실행은 게시의 조건이 아니다. 키가 없으면 건너뛰고 게시한다. 레지스트리가 예시 모델 넷을 돌려 결과를 붙인다(확정된 기본값은 없다. 로그프롭을 주는 모델이면 입력이 싼 프런티어, 20~30B 급, Jev 류 판단 전용 모델 무엇이든 사용자가 고른다). 직접 돌리면 `references/run-guide.md` 의 요건 8개를 **네가 쓰는 게이트웨이에서 스스로 확인하고 맞춘다.** 그 뒤 뻔한 양성 3·음성 2로 전 팔 스모크. 스모크 결과의 `per_item` 으로 어느 항목을 틀렸는지 본다. 두 팔 이상이 같은 항목을 틀리면 질문 결함이고, 한 팔만 틀리면 팔 약점이다. 질문 결함이면 질문을 고치고 다시 스모크한다. 그다음 팔 2~4개 전량. 정확도(argmax)·Wilson 구간·클래스별 표·AUROC(진단). 큰 차이만 믿는다.
10. **공유 여부.** 생성기+표본 5건+결과. 게시하려면 `references/format.md` 의 형식을 그대로 따라야 하고 `bench_validate` 를 통과해야 한다. 게시 전에 AskUserQuestion 으로 **어디에 올릴지** 하나를 고르게 한다: 로컬 레지스트리만 / 내 GitHub 리포 비공개(`bench_publish target=github private=true`) / 내 GitHub 리포 공개(`private=false`, 갤러리에 모이려면 공개). 기본 추천은 비공개로 올려 본 뒤 공개다. 게시는 사용자 확인 뒤.
11. **작성자에게 감사.** 남의 벤치를 포크했거나 그 결과로 모델을 골랐으면, 끝날 때 한 번 「이 벤치가 쓸모 있었으면 작성자 리포에 스타를 남길까요」를 AskUserQuestion 으로 묻는다(gh 로그인이 있을 때만). 원하면 `bench_star bench_id confirm=true`. 스타는 갤러리 신뢰 점수와 유형별 추천 가중에 반영된다고 알려 준다. 묻지 않고 스타를 남기지 않는다.

## 도구 (이 판본: CLI. MCP `bench_*` 는 같은 검사기를 감싼 것이다)

MCP 서버가 없는 환경에서는 리포의 CLI 를 부른다. 리포 루트에서 `bench-core/bin/benchlet` 이다. 이름이 `bench_*` 인 툴은 아래 명령과 같은 일을 한다.

| 스킬이 부르는 것 | CLI |
|---|---|
| `bench_validate` | `benchlet validate <이름>` (항목 + 옆의 `.manifest.yaml` 을 같이 검사) |
| `bench_add_items` 의 개인정보 스캔·극성·중복 검사 | `benchlet validate` 에 포함 |
| `bench_review` · `bench_review_queue` | `benchlet review --bench <이름> [--results R] [--rules F] --out <경로.md>` |
| `bench_freeze` | `shasum -a 256 tasks/<이름>.jsonl >> labels/SHA256SUMS` + `tasks/<이름>.preregister.md` 에 예측·판정 규칙. 사람 검수 전이면 검수 뒤 라벨이 바뀔 때 version 을 올린다 |
| `bench_run` · `bench_status` · `bench_results` | `benchlet smoke --bench <이름> --arms qwen,jev` → `benchlet run --bench <이름> --arms qwen,jev` → `benchlet report <이름>` |
| `bench_export` | `benchlet export --bench <이름> --format inspect|lm-eval|hf` |
| `bench_publish` | `benchlet publish --bench <이름> --out <폴더>` (사용자 확인 뒤) |
| `bench_similar` · `bench_search` · `bench_fork` · `bench_taxonomy` | 로컬 레지스트리(`registry/benches`)와 공개 갤러리(benchlet.vibestash.app, 하루 캐시)를 같이 본다. 원격 결과는 path 가 `remote:` 로 시작하고 `bench_fork` 가 받아 온다. CLI 는 `benchlet list`, 어휘는 `registry/taxonomy.yaml` |
| `bench_star` | `benchlet star <bench_id> --yes` (사용자 확인 뒤) |

산출 위치는 `references/generate.md` 의 「산출」과 같다(`src/build_<bench>.py`, `tasks/<bench>.jsonl`, `tasks/<bench>.manifest.yaml`, `tasks/<bench>.dist.md`). 발견 보고는 `discovery/<프로젝트>-<날짜>.md`, 계획은 `discovery/<프로젝트>-<날짜>.plan.yaml`.

## 기본값과 재정의

아래 값은 기본값이다. 사용자가 호출할 때 문장으로 바꿀 수 있고(「n 은 100, 검수 30분, 팔은 qwen 과 jev 만」), 계획표에서 행 단위로도 바꿀 수 있다. 바뀐 값은 `plan.yaml` 에 그대로 남는다. 계획표에는 기본값과 바뀐 값을 나란히 보여 준다.

| 키 | 기본값 | 뜻 |
|---|---|---|
| `n` | 라벨 경로 1 은 80, 2·3 은 48 | 벤치당 항목 수. 클래스별 최소는 따로 |
| `class_min` | 8 | 클래스(위반 종류·분류 라벨)별 최소 항목 수 |
| `budget_min` | 60 | 첫 회차 사람 검수 시간(분). 넘으면 「나중」 등급부터 내린다 |
| `read_fraction` | 심기·생성 1.0, 기계 라벨 0.2 | 사람이 눈으로 읽는 비율 |
| `benches` | 권장 개수(핵심 + 라벨 있는 보조) | 만들 벤치 수. 목록에서 켜고 끈다 |
| `arms` | 검증 조합표의 최저가 로그확률 팔 1 + jev | 실행 팔. `prob_use` 가 threshold 이상이면 확률 팔 2개 이상 강제 |
| `label_path` | 자동(1 → 2 → 3) | 특정 벤치에 경로를 강제할 때 |
| `seed` | 오늘 날짜 YYYYMMDD | 생성기 시드 |
| `visibility` | sample | 게시 범위. generator · sample · full |
| `banned_terms` | 로컬 설정 파일 | 개인정보 스캔에 더하는 사용자 금지어 |
| `language` | 프로젝트 언어 | 항목 언어 |

바꿀 수 없는 것: 두 규칙(개인정보·객관성), 형식 계약, 「자기 검증은 증거가 아니다」.

## 하지 않는 것

- 자기가 만든 항목을 자기가 검증했다고 보고하지 않는다 (순환)
- 음성을 「값이 아예 없는 문장」처럼 자명하게 만들지 않는다. 양성과 같은 풀에서 뽑는다
- 심은 결함이 문법·태·주체·내용 모순으로 새게 만들지 않는다
- 선택지에 글자 접두(A.)를 넣지 않는다. 질문 극성과 label 0 의 뜻을 어긋나게 두지 않는다

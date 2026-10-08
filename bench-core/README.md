# benchlet bench-core

내 데이터로 만든 40~100건짜리 판정 미니벤치의 스키마 검증, 검수 검사, 실행, 통계, 내보내기, MCP 서버.

**실행은 선택이다. 키가 없으면 올리기만 해라.** `validate → review → publish` 가 기본 흐름(경로 0)이고, 레지스트리가 기준 팔을 돌려 결과를 붙인다. 직접 돌리려면 OpenAI 호환 게이트웨이 하나와 키 하나면 된다.

## 설치

Python 3.9 이상, pyyaml. 이 리포에서는 설치 없이 쓴다.

```
bench-core/bin/benchlet --version
# 또는
PYTHONPATH=bench-core python3 -m benchlet.cli --version
```

패키지로 설치하려면 `pip install -e bench-core` (setuptools 64 이상).

## 명령

```
benchlet validate <bench> [...]           최소 형식·확장 형식·구식 씨앗 스키마. 극성·글자 접두·중복 해시·개인정보 스캔
benchlet review  --bench X [--results R] [--rules F] [--checks 1,2,5]   검수 검사 v0 → 플래그 큐
benchlet publish --bench X [--out DIR]     게시 묶음 (manifest.yaml + samples.jsonl + results 또는 pending)
benchlet smoke   --bench X --arms qwen,jev 5건 스모크 · 3회 재현성 · 확률값 종류 수 (종료 코드 0 전부 사용 가능 / 2 일부 / 3 전부 불가)
benchlet run     --bench X --arms qwen,jev [--limit N]   전량 실행 (스모크 먼저. 못 쓰는 조합은 뺀다)
benchlet report  <bench> [...]             정확도·Wilson·클래스별·AUROC(진단)·Brier·McNemar·표면 특징 최선
benchlet export  --bench X --format inspect|lm-eval|hf
```

`<bench>` 는 이름(`tasks/<이름>.jsonl`, `tasks/retired/`, `tasks/parked/` 순으로 찾는다), `.jsonl` 경로, 또는 `bench.yaml` 이 있는 폴더다.

## 형식

- 최소 형식: `bench.yaml`(name, guide, choices, items 또는 items.jsonl). 항목은 input, target, 권장 evidence, class
- 확장 형식: `.jsonl` 한 줄에 id, input, question, choices, target, type, label_source, class, difficulty, cluster, evidence, provenance, metadata. 같은 이름의 `.manifest.yaml` 을 읽는다
- 구식 씨앗 스키마(state, options, label)는 파일을 바꾸지 않고 로더가 메모리에서 확장 형식으로 바꾼다. 프롬프트는 `src/run.py` 와 글자 단위로 같다(`tests/test_runner_offline.py`)

세부는 `skill/minibench-author/references/format.md`.

## 검수 검사 v0

PRD 6절의 1(교차 패밀리 불일치) 2(오답 쏠림, 클래스 전멸·만점) 5(순환) 7(음성 자명성, 단일 표면 특징 최선 정확도) 8(유일해, 규칙 매처) 9(극성, 어간 대조 휴리스틱) 10(분포, 출처 필드 상관) 11(채점기 표본 20건 덤프). 1·2 는 실행 결과 파일이 있어야 돈다. 자동 검사는 플래그만 하고 판정은 사람이 한다. 결함 12개 소급 재현률은 `docs/REVIEW_RECALL.md`.

## 팔과 실행

러너는 OpenAI 호환 chat completions 한 종류만 말한다. `base_url`, `api_key`, `model`, `extra_body` 넷으로 추상화되고 OpenRouter 는 그 위의 프리셋이다(`benchlet/runner/arms.py`). 게이트웨이별 분기 코드는 없다. 요건은 `skill/minibench-author/references/run-guide.md`.

```
qwen, glm, deepseek, jev, ds-low, ds-high, gemma, nemotron    OpenRouter 프리셋 (검증 조합표 data/or_verified.json)
qwen/qwen3.8-27b@parasail                                      OpenRouter 모델@provider 핀
custom:<model>                                                 임의의 OpenAI 호환 엔드포인트. BENCHLET_BASE_URL, BENCHLET_API_KEY, 선택 BENCHLET_EXTRA_BODY(JSON)
```

키는 환경변수 또는 `~/.config/benchlet/env`(`BENCHLET_ENV_FILE` 로 바꿀 수 있다)의 `OPENROUTER_API_KEY` 만 읽고 값을 어디에도 쓰지 않는다. 로그확률이 안 오면 생성 팔로 강등하고 결과의 `arms.<key>.prob_source` 에 `none` 으로 남긴다. 스모크 결과는 결과 파일 `arms.<key>.smoke` 에 남아 갤러리가 모은다.

정직하게: 우리가 확인한 조합은 OpenRouter 뿐이다(2026-09-30). Vercel AI Gateway, LiteLLM, 사내 게이트웨이는 위 요건을 사용자의 에이전트가 확인한다.

## 결정 규칙

이진 0.5, 다지 argmax. 임계 이동·온도 보정으로 점수를 올리지 않는다. AUROC 는 진단용이다.

## 테스트

```
python3 -m pytest tests -q
python3 tests/fixtures/build_fixtures.py      # 결함 픽스처 재생성 (원자료가 있는 머신에서만)
python3 -m benchlet.review.recall --out docs/REVIEW_RECALL.md
```

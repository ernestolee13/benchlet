# 6단계 산출 (2026-10-04, 판단·라우팅 벤치 추가, 2차 원천, 커뮤니티 검증, 소개)

사용자 지시: Jev 용도(단순 판단·라우팅)에 맞는 사례를 더 만들고, 사용자 욕구에 기능이 맞는지 점검하고, 초기 시드를 더 확보하고, 사용 흐름 소개 문서를 만든다.

## 1. 사용자 욕구 대 기능 점검

| 욕구 | 지금 되는 것 | 빠진 것 / 다음 |
|---|---|---|
| 새 모델이 나올 때마다 점수를 못 믿겠다. 작아도 나만의 벤치를 만들어 관리하고 싶다 | 스킬(발견→계획→생성→검수), 최소 형식, validate·review, 경로 0 게시, GitHub 리포가 저장소, 판본은 커밋 이력 | 판본 비교 뷰(v1 대 v2 결과 나란히)는 갤러리에 없다. 매니페스트에 version 만 있다 |
| 나와 비슷한 일을 하는 사람은 어떤 벤치를 관리하고 어느 모델을 선호하나 | 갤러리 서명·작성자 필터, 유형별 추천(같은 서명 벤치 합산, 근거 수), bench_search·similar·fork | 작성자 페이지(그 사람의 벤치 묶음과 모델 선호 요약)가 없다. 추천은 n·검수 신뢰로 가중하지 않는다 |
| 괜찮은 벤치에 새 모델을 돌려 점수를 공개하고, 남의 점수는 몇 개 쌓여야 믿겠다 | **이번에 구현**. `benchlet submit` / `bench_submit_result`: 같은 판본 해시 필수, 항목별 응답 전문 동봉, 제출자 리포 `community/<slug>/` 에 쌓임, sync 가 수집(리포 주인 = 제출자만 인정), 서로 다른 제출자 3건 이상이 5pp 안이면 「검증됨」, 공식 점수 = 중앙값, 작성자 본인 제출 제외 | 실제 제출 0건. 제출자 평판(제출 이력·검증 통과율)과 악의적 제출 방어는 없다. 새 벤치가 올라오면 알림이 없다(리포 watch 로 대신) |
| 공개 벤치 점수는 외운 것 같다. 공신력 있는 축약 시드가 있으면 좋겠다 | 시드 7개(ARC·TruthfulQA·WinoGrande·HellaSwag·MMLU·OpenBookQA·MMLU-Pro), 검증 모델 집단 셋(metabench 800, HELM 31, OpenEval 121) | GSM8K 류 단답 생성형은 생성 팔 채점기가 없어 못 넣는다. 한국어 공개 벤치는 모델별 응답이 없어 축약 검증 불가 |
| 실생활 판정 사례가 더 있으면 좋겠다 | 샘플 12개(도구 선택, 문의 분류, 클릭 대상, 커밋 규칙, 확인 게이트, JSON 스키마 + 에스컬레이션 라우팅, RAG 근거 선별, 환각 게이트, SQL 자동 실행 게이트, 중복 이슈, 메일 우선순위) | 대부분 싼 팔도 90% 이상이라 격차를 못 보여 준다. 경계 사례(hard)를 더해야 한다 |

## 2. 새 판단·라우팅 벤치 6개 (`src/build_samples2.py`)

| 벤치 | 유형 | n | 묻는 것 | glm | qwen | deepseek | jev | 검수 플래그(medium 이상) |
|---|---|---|---|---|---|---|---|---|
| support-escalation-route | 4분류 | 28 | 고객 메시지를 봇·1선·2선·보안 중 어디로 | 89% | 96% | 100% | 100% | 없음 |
| rag-passage-relevance | 이진 | 24 | 문단이 질의에 답하는 근거가 되는가 | 100% | 100% | 100% | 100% | 검사 2: 전 팔 만점 (너무 쉽다) |
| answer-grounded-check | 이진 | 24 | 답변의 모든 사실이 근거 문단에서 도출되는가 | 88% | 92% | 96% | 96% | 검사 5 자기 검증 |
| sql-autorun-gate | 이진 | 28 | SQL 문을 확인 없이 자동 실행해도 되는가 | 82% | 100% | 96% | 100% | 검사 7 길이만으로 79%, 검사 2 세 클래스 전 팔 만점 |
| duplicate-issue-pair | 이진 | 24 | 두 이슈가 같은 문제를 보고하는가 | 75% | 96% | 96% | 100% | 검사 7 길이만으로 79% |
| email-triage-priority | 4분류 | 28 | 메일을 지금·오늘·이번 주·보관 중 언제 처리하나 | 79% | 100% | 93% | 93% | 없음 |

팔은 5단계와 같다(glm = z-ai/glm-4.7-flash provider cloudflare, qwen = qwen/qwen3.8-27b provider parasail, deepseek = deepseek/deepseek-v4-flash provider digitalocean. 셋 다 OpenRouter 로그프롭 팔, 추론 끔, 제공자 고정, fallback 금지. jev = typesafe/jev-1.13 typed 팔). 각 벤치의 정확한 슬러그·제공자·호출 템플릿은 `results/<bench>-run.json` 과 갤러리 상세의 「실험 방식」에 있다.

첫 실행에서 answer-grounded-check 와 sql-autorun-gate 는 전 팔이 0~20% 였다. 생성기가 target 을 반대로 적어 둔 것(「도출된다」와 「도출되지 않는다」, 「자동 실행 가능」과 「확인 필요」가 바뀜)을 검사 1(교차 패밀리 불일치)과 검사 2(오답 쏠림)가 잡았고, 생성기를 고쳐 다시 돌린 수치가 위 표다. 이 사고로 스모크에 「전 팔이 자명한 항목을 다 틀리면 본 실행을 중단」하는 극성 의심 가드를 넣었다(`--force-polarity` 로만 통과, `docs/REVIEW_RECALL.md` 현장 기록).

남은 약점: rag-passage-relevance 는 네 팔 모두 만점이라 격차를 못 보여 주고, sql-autorun-gate 와 duplicate-issue-pair 는 긴 입력이 「확인 필요」「같은 문제」 쪽으로 쏠려 길이 하나로 79% 가 나온다. 둘 다 경계 사례(짧은 위험 SQL, 긴 안전 SELECT, 길지만 다른 문제인 이슈 쌍)를 더해야 한다. 열두 샘플 전부 생성기가 곧 검증기라 검사 5 가 자기 검증을 경고한다. 사람이 읽은 항목(read_by_human)은 0 이다.

## 3. 2차 원천 시드

| 시드 | 원천 | 검증 모델 | 검증 MAE / τ |
|---|---|---|---|
| openbookqa-mini (100/500) | HELM Lite v1.0.0 commonsense | 31개 중 10개 (GPT-4, Claude 2, Llama 2 등) | 2.54pp / 1.000 (10개라 τ 는 참고) |
| mmlu-pro-mini (100/998) | OpenEval MMLU-Pro 공통 부분집합 | 121개 중 37개 (GPT-5.x, Claude 3.5, Qwen 3, Grok 3 등) | 2.14pp / 0.948 |

네 팔 실측(100건):

| 시드 | glm | qwen | deepseek | jev |
|---|---|---|---|---|
| openbookqa-mini | 72% | 95% | 71% | 98% |
| mmlu-pro-mini | 42% | 62% | 57% | 87% |

OpenBookQA 는 원천 모델 집단(2023년 HELM Lite)보다 요즘 팔이 쉽게 푼다. deepseek 71% 는 qwen 95% 와 격차가 커서 제공자 비결정성 재실행 비교 대상으로 남긴다. MMLU-Pro 는 선택지가 열 개라 로그프롭 팔의 첫 토큰 분포가 흩어진다. 둘 다 원천 라이선스(HELM Apache-2.0 결과 + OpenBookQA Apache-2.0, OpenEval CC-BY-NC-4.0 + MMLU-Pro MIT)와 attribution 을 매니페스트에 적었다. MMLU-Pro 축약본은 NC 조건을 그대로 승계한다.

## 4. 소개 아티팩트

사용 흐름 다섯 가지(만들기, 돌리기, 올리기, 찾기, 서로 검증하기)와 각 흐름의 구현 상태를 적은 페이지. `site/intro.html`, 아티팩트 https://claude.ai/artifact/3gz7imdm1zUSm2VtckvN5R

## 5. 분류 체계와 키워드 (추가 지시)

`registry/taxonomy.yaml` 에 축 다섯(goal, domain 18종, input_kind, source_kind, language)과 키워드 정규형·동의어를 두고, 33개 벤치 전부에 `registry/taxonomy_labels.yaml` 로 라벨을 붙였다. `benchlet taxonomy apply` 가 매니페스트에 써 넣고 `benchlet taxonomy check` 와 validate 가 어긋난 값(없는 domain, 동의어로만 적은 키워드)을 경고한다. 갤러리는 축별 필터와 동의어 확장 검색(예: 「환각」으로 grounding 벤치가 잡힘)을 하고, MCP 는 `bench_taxonomy`(어휘 조회), `bench_search(domain, keywords)`, `bench_create(taxonomy_domain, keywords)` 로 같은 어휘를 강제한다. 스킬 참조 `skill/minibench-author/references/taxonomy.md` 에 축의 뜻과 고르는 요령을 적어 에이전트가 새 벤치를 만들 때나 비슷한 벤치를 찾을 때 같은 말을 쓰게 했다.

## 6. 이번 단계에서 못 한 것

- 작성자 페이지(한 사람의 벤치 묶음과 모델 선호 요약), 추천의 n·검수 신뢰 가중, 판본 비교 뷰.
- 커뮤니티 제출 실데이터 0건. 제출자 평판·악의 제출 방어 없음.
- GSM8K 류 단답 생성형 시드(생성 팔 채점기 필요), 한국어 공개 시드(모델별 응답 원천 없음).
- 샘플 벤치의 사람 검수(read_by_human) 와 경계 사례 보강.
- 네이버 서치어드바이저 소유확인은 사용자 로그인(캡차) 뒤 사이트맵 제출만 남았다.

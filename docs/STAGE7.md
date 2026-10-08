# 7단계 산출 (2026-10-05, 판단형 공개 벤치로 선택 풀 넓히기)

사용자 지시: 선택형·단답형이면서 지식보다 판단을 묻는 공개 벤치를 이름과 주요 모델 점수부터 모으고, 맞는 것만 원본을 직접 받아 축약한다. 너무 비슷한 것은 더 최신이고 신뢰도가 있고 SOTA 모델 결과가 있는 벤치로 교체하고, 아니면 추가해서 선택 풀을 훨씬 넓힌다. 순차 진행.

조사 정본은 `docs/RESEARCH_judgment_candidates.md`(후보 60여 개)와 `docs/RESEARCH_recent_sources.md`(원천별 항목 결과 공개 여부, 현재 팔 전체 대 축약 실측).

## 1. 토대 두 가지

- **축약 방법 자동 선택.** 모델이 100개 이상이면 층화 + 교환 탐색, 미만이면 층화 무작위. 실측 근거: HELM 67~91개 모델에서는 교환 탐색이 과적합해 무작위보다 0.2~0.7pp 나빴고, BFCL 109개·metabench 800개에서는 교환이 0.4~1.7pp 좋았다. 두 방법의 검증 수치를 항상 나란히 보고한다(`distill.alt`).
- **항목 병렬 실행.** `benchlet run --concurrency`(기본 6). 순서 보존, 집계 동일(테스트). ARC 1,170건 4팔이 순차로 약 70분 걸렸으므로 병렬 6 이면 그 1/5 안팎이 기대값이다(실측은 아래 실행에서).

## 2. 행렬 있는 시드 8개 (원천 모델 집단으로 축약 검증)

| 벤치 | 묻는 것 | 형식 | 원천 / 라이선스 | 검증 모델 집단 | 100건 검증 MAE / 최대 / τ |
|---|---|---|---|---|---|
| tool-call-gate-mini | 이 요청에 주어진 도구를 불러야 하나 | 이진 50/50 | BFCL live_simple + live_irrelevance / Apache-2.0 | BFCL-Result 109개 (Claude 4.5, GPT-5.2, o3, Gemini 3 Pro, Qwen3, DeepSeek V3.2, Llama 4) | 호출 2.69 / 7.22 / 0.909, 무관 3.23 / 10.34 / 0.826 |
| tool-pick-mini | 어느 함수를 불러야 하나 | 2~10지 | BFCL multiple + live_multiple / Apache-2.0 | 같음 | 1.62 / 5.44 / 0.941 |
| judge-pair-mini | 두 응답 중 객관적으로 맞는 쪽 | 이진 | JudgeBench GPT-4o split 350 / MIT | 심판 37개 (o3-mini, DeepSeek-R1, GPT-4o, Claude 3.5, Gemini 1.5, Llama 3.1, 보상 모델) | 2.36 / 4.39 / 0.970 |
| best-of-4-mini | 네 응답 중 가장 나은 것 | 4지 | RewardBench 2 (Ties 제외) / ODC-BY | 188개 (Claude Opus 4, Sonnet 4, 3.7, Gemini 2.5 Pro/Flash, GPT-4.1, GPT-4o + 보상 모델) | 2.32 / 7.96 / 0.875 |
| bbq-mini | 편향 QA 3지 (근거 없으면 「모름」) | 3지 | BBQ via HELM safety v1.17.0 / CC-BY-4.0 | 81개 (GPT-5.1, Claude Sonnet 4.5, Gemini 3 Pro, Grok 4) | 1.89 / 6.21 / 0.959 |
| legal-lobbying-mini | 법안이 이 회사와 관련 있나 | 이진 | LegalBench corporate_lobbying via HELM / CC-BY-4.0 | 91개 | 2.51 / 6.73 / 0.843 |
| mmlu-pro-mini (v2, 교체) | 시험 문제 최대 10지 | 다지 | MMLU-Pro via HELM capabilities v1.15.0 / MIT | 67개 (GPT-5.1, GPT-5, o3, Claude Sonnet 4.5, Gemini 3 Pro, Grok 4) | 2.48 / 6.22 / 0.904 |
| openbookqa-mini (v2, 교체) | 초등 과학 상식 4지 | 4지 | OpenBookQA via HELM lite v1.13.0 / Apache-2.0 | 91개 | 2.63 / 5.80 / 0.781 |

교체 이유. mmlu-pro-mini v1 은 OpenEval(CC-BY-NC) 행렬 121개 모델이었고 v2 는 HELM(Apache-2.0) 행렬에 2025~2026 모델이 들어간다. openbookqa-mini v1 은 HELM v1.0.0 의 31개 모델(2023)이었고 v2 는 v1.13.0 의 91개 모델이다.

주의할 점.
- BFCL 의 정오는 「올바른 인자로 올바른 함수를 호출했나」라 우리 질문(부를 도구가 있나, 어느 함수인가)보다 엄격하다. 검증 집단의 정확도는 우리 팔 점수와 직접 비교하지 않는다. 같은 모델도 FC 모드와 Prompt 모드 점수가 10pp 이상 다르다.
- JudgeBench 정오는 「두 제시 순서에서 모두 라벨과 일치」(논문의 position-consistent accuracy)로 재구성했고, o3-mini-high 79.7, GPT-4o 50.3 으로 논문 수치(80.9, 56.6)와 맞는다. 우리 항목은 쌍마다 결정론적으로 순서를 뒤집어 위치 편향을 상쇄한다.
- RewardBench 2 응답은 길어서 보기마다 1,800자에서 잘랐다. 잘린 항목은 「… [잘림]」 표시가 있다.

4팔 실행 결과(정확도 %, 성공 항목 기준. deepseek 의 실패는 라벨 질량이 아니라 제공자 속도 제한 HTTP 429 였다. 러너에 지수 대기 재시도를 넣고 `--merge` 로 deepseek 팔만 다시 돌려 합쳤다. 괄호는 성공 수):

| 벤치 | glm | qwen | deepseek (성공) | jev | 읽는 법 |
|---|---|---|---|---|---|
| tool-call-gate-mini | 81 | 81 | 89 (90) | 81 | 호출 쪽은 45~49/50 인데 「도구 없음」 쪽은 32~36/50. 세 팔이 똑같이 19개를 틀리고 그 대부분이 도구 없음 항목이라, 작은 모델이 도구를 과하게 부르는 경향이 그대로 보인다. BFCL 리더보드에서도 irrelevance 가 73~93 으로 가장 갈리는 열이다 |
| tool-pick-mini | 99 | 99 | 97 (99) | 99 | 함수 이름 고르기는 거의 포화. 변별은 gate 쪽에서 난다 |
| judge-pair-mini | 48 | 79 | 51 (99) | 47 | 어렵다(JudgeBench 는 GPT-4o 57, Gemini 1.5 Pro 47). glm 과 jev 는 99%, 92% 를 「응답 A」로 답해 위치 편향이 그대로 드러났고, qwen 만 79 다 |
| best-of-4-mini | 59 | 84 | 62 (84) | 82 | RewardBench 2 의 LM 심판(Claude Opus 4 77, GPT-4.1 72)과 같은 범위. 글자 접두·핸들이 든 응답을 걸러 다시 뽑은 뒤 수치 |
| bbq-mini | 80 | 96 | 76 (99) | 95 | |
| legal-lobbying-mini | 81 | 82 | 79 (100) | 81 | 세 팔이 같은 19건을 틀린다. 긴 법안 요약(평균 6천 자)에서 회사 관련성을 놓치는 항목이 같다 |
| mmlu-pro-mini v2 | 38 | 62 | 62 (91) | 85 | v1(42/62/59/87)과 같은 범위. 검증 집단만 2025~2026 모델로 바뀌었다 |
| openbookqa-mini v2 | 76 | 95 | 79 (33) | 96 | v1(72/95/71/98)과 같은 범위 |

빠진 것. legal-citizenship-mini 는 만들어 돌려 본 뒤 뺐다. 국적법 지식 문제라 판단형이 아니고, 네 팔 모두 「예」로 쏠려(85%) 다수결 67% 보다 낮은 46% 가 나왔다. 검사 1 이 46건을 strong 으로 올렸다. 라벨이 틀린 게 아니라 벤치가 우리 목적과 안 맞는 경우다.

검수 플래그. tool-call-gate-mini 는 검사 7 이 「줄 수 < 6 이면 도구 없음」 표면 특징으로 74% 를 낸다고 경고했다. live_simple 항목이 도구 하나만 주는 구조 탓이고, 다음 판에서 도구 여러 개짜리 호출 항목(live_multiple 의 정답 하나짜리)을 양성에 섞어 깬다. judge-pair-mini 는 검사 1 이 18건을 strong 으로 올렸는데 모두 「세 팔이 A 로 답한」 항목이라 라벨 문제가 아니라 팔의 위치 편향이다.

## 3. 행렬 없는 시드 8개 (우리 팔의 전체 대 축약 비교로 검증)

| 벤치 | 묻는 것 | 형식 | 원천 / 라이선스 | 전체 | 공개된 주요 모델 점수 |
|---|---|---|---|---|---|
| xstest-refusal-mini | 이 요청을 거절해야 하나 (과잉 거절 대조) | 이진 | XSTest / CC-BY-4.0 | 450 | 오거절률 Claude 3.5 Sonnet 1.7%, Claude 3 Opus 8.3% |
| aegis-prompt-safety-mini | 이 프롬프트는 안전하지 않은가 | 이진 | Aegis 2.0 test, 사람 라벨만 / CC-BY-4.0 | 1,912 | GPT-4 F1 84.4(1.0), Llama Guard 3 76.4 |
| musr-murder-mini | 범인은 둘 중 누구인가 | 이진 | MuSR / MIT | 250 | GPT-4 80.4, GPT-3.5 61.6 |
| musr-objects-mini | 물건을 어디서 찾겠나 | 2~5지 | MuSR / MIT | 256 | GPT-4 60.9, GPT-3.5 46.9 |
| bbh-judgment-mini | 인과 판단, 경로 복귀, 스포츠 상식 예·아니오 | 이진 | BBH 3개 소집합 / MIT | 687 | causal GPT-4o 67.0, Claude 3.5 Sonnet 69.0 |
| jbb-jailbreak-judge-mini | 이 응답은 유해 목표를 수행했나 | 이진 | JailbreakBench judge-comparison, 사람 3명 다수결 / MIT | 300 | 항목별 심판 열(GPT-4, Llama Guard 2, Llama 3, HarmBench) 동봉 |
| halueval-qa-mini | 이 답변은 근거에 비추어 환각인가 | 이진 | HaluEval QA 표본 1,000 / MIT | 1,000 | ChatGPT 62.6, Claude 2 69.8 |
| ethics-commonsense-mini | 이 행동은 도덕적으로 잘못됐나 | 이진 | ETHICS commonsense 표본 1,000 / MIT | 1,000 | GPT-4 95 (short) / 78 (long) |

축약은 클래스(원천 라벨, 소집합) 층화 무작위이고 팔 정보는 쓰지 않는다. 검증은 `src/compare_full_vs_mini.py` 가 전체 실행 대 축약본 실행의 팔별 정확도 차이와 순위 보존을 매니페스트 `distill.own_arms` 에 적는다.

전체 대 축약 비교(정확도 %, 전체 → 100건. deepseek 은 전체 세트에서 429 실패가 70% 를 넘어 비교에서 뺐다):

| 벤치 | glm | qwen | jev | 팔 평균 차이 | 최대 차이 | 순위 보존 |
|---|---|---|---|---|---|---|
| xstest-refusal-mini | 90 → 89 | 94 → 94 | 94 → 93 | 0.8pp | 1.4pp | qwen·jev 동점이라 순서만 바뀜 |
| aegis-prompt-safety-mini | 78 → 78 | 82 → 80 | 84 → 83 | 0.8pp | 1.6pp | 보존 |
| musr-murder-mini | 59 → 52 | 71 → 74 | 50 → 47 | 3.7pp | 7.2pp | 보존 |
| musr-objects-mini | 52 → 49 | 50 → 49 | 56 → 59 | 2.4pp | 3.0pp | 보존 |
| bbh-judgment-mini | 49 → 46 | 69 → 67 | 85 → 82 | 2.8pp | 3.4pp | 보존 |
| jbb-jailbreak-judge-mini | 60 → 67 | 67 → 68 | 70 → 74 | 3.9pp | 7.3pp | 보존 |
| halueval-qa-mini | 61 → 60 | 91 → 95 | 84 → 86 | 2.6pp | 4.4pp | 보존 |
| ethics-commonsense-mini | 68 → 68 | 87 → 84 | 84 → 80 | 2.2pp | 3.7pp | 보존 |

읽는 법. 정확도 80% 근처에서 100건의 이항 표준오차가 4pp 이므로 2~4pp 차이는 표본 잡음이다. Aegis 는 첫 표본(라벨만 층화)에서 네 팔이 모두 6~9pp 높게 나와 표본이 쉬운 쪽으로 쏠린 것이 보였고, 라벨 × 위반 범주로 층을 잘게 나눠 다시 뽑자 0.8pp 로 내려왔다. MuSR murder 와 JBB 는 전체가 250~300건뿐이라 7pp 최대 차이가 나온다.

결과에서 보이는 것.
- 작은 모델이 가장 못 하는 판단은 「두 응답 중 맞는 쪽」(judge-pair 47~79), 「범인 추론」(musr-murder 47~74), 「물건 위치」(musr-objects 47~59), 「인과·경로」(bbh 46~82)다. 지식 시험보다 이쪽이 팔 간 격차를 더 크게 벌린다.
- 안전 판정은 쉬운 편이다(xstest 89~94, aegis 78~87). 탈옥 성공 판정(jbb 67~74)과 도덕 판단(ethics 68~84)은 중간이다.
- jev(typed 팔)는 bbh 82, best-of-4 86, mmlu-pro 85 로 추론·선택형에서 가장 좋지만 judge-pair 47, musr-murder 47 로 긴 쌍 비교에서는 「응답 A」로 쏠린다.

## 4. 제외하거나 미룬 것

- Mind2Web(요소 선택): 테스트 분할이 OpenRAIL 멀티모달 판에만 있고 후보 요소의 HTML 조각이 길어 러너 입력 설계가 따로 필요하다. 다음 판.
- Banking77(77분류): 첫 토큰 로그프롭으로는 77지가 안 된다. 8지(정답 + 무작위 7)로 바꾸는 설계가 필요하고 HELM 행렬(22개 모델, 2024)은 그 변형과 맞지 않는다. 다음 판.
- WildGuardTest, OLL v2 details: HF 토큰 게이트.
- LLM-AggreFact(ND), HaluBench·ToxicChat·SciFact(NC), SORRY-Bench(재호스팅 금지), RewardMATH(NC-ND): 라이선스.
- ClearFacts, R-Judge: 라이선스 미기재. 저자 확인 전엔 재게시 안 함.
- SQL 자동실행, 티켓 우선순위, 이슈 중복: 공개 세트 없음. 우리 샘플 벤치가 유일.

## 5. 산출과 다음

갤러리는 33개에서 47개가 됐다(새 벤치 14개, 교체 2개, 만들었다 뺀 것 1개). 영역별로 agent-tools 2, 심판 2, content-moderation 5, legal 1, retrieval-rag 1, commonsense 추론 3 이 늘었다. 모든 새 벤치는 taxonomy 라벨이 붙었고, 매니페스트에 원천·라이선스·검증 집단·검증 수치가 있다. 스킬 참조 `references/public-seeds.md` 에 두 경로와 시드 지도를 적었다.

다음.
- tool-call-gate 의 표면 특징(도구 수) 깨기, judge-pair 의 위치 편향을 줄이는 쌍 비교 템플릿(두 순서 평균).
- Mind2Web 요소 선택, Banking77 8지 변형, WiCE 하위주장, SummaC, TofuEval.
- HF 토큰이 생기면 WildGuardTest, OLL v2 details(MuSR·BBH 의 오픈 모델 행렬).
- 선택지 10개 이상용 번호 라벨 템플릿, 제공자별 동시성 한도(deepseek 은 2 이하).

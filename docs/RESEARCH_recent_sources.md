# 최신 모델의 항목별 결과가 열린 공개 원천 조사 (2026-10-05)

사용자 지적: 5단계 시드의 검증 집단(metabench, Open LLM Leaderboard v1 의 2023~2024 오픈 모델)은 벤치도 모델도 오래됐다. 지금 쓰는 4팔이나 Claude, OpenAI 최신 모델에서 축약이 유지되는지는 다른 얘기다. 그래서 「2025~2026 모델의 항목별 정오가 공개된 원천」을 다시 찾았다.

찾는 조건은 셋이다. (1) 모델마다 항목 단위 정오 또는 응답이 내려받아진다. (2) 2025년 이후 모델이 여럿 있다. (3) 선택형이나 분류형이라 우리 러너(첫 토큰 로그프롭, typed)로 돌릴 수 있다.

## 1. 결론

항목별 결과를 최신 모델까지 공개하는 곳은 사실상 **HELM(스탠퍼드 CRFM) 공개 버킷** 하나다. 리더보드 사이트 대부분(Artificial Analysis, Vals, LM Council, Epoch 허브, Scale SEAL, OpenEvals)은 모델별 총점만 내고 항목별 출력은 내지 않는다. Open LLM Leaderboard v2 는 항목별 결과가 있지만 2025년 3월에 멈췄고 HF 토큰이 있어야 받는다.

HELM 은 모든 모델을 같은 프롬프트로 돌리고 `display_predictions.json` 과 `per_instance_stats.json` 에 항목별 정오를 남긴다. 결과는 Apache-2.0 이고 버킷은 인증 없이 열려 있다. 리더보드별 최신 릴리스와 모델 수는 아래와 같다.

| HELM 리더보드 | 릴리스 | 모델 수 | 2025년 이후 모델(예) | 우리가 쓸 수 있는 시나리오 |
|---|---|---|---|---|
| capabilities | v1.15.0 | 68 | GPT-5.1, GPT-5, o3, o4-mini, Claude Sonnet 4.5, Claude Opus 4, Gemini 3 Pro preview, Gemini 2.5 Pro, Grok 4, Qwen3-235B, DeepSeek R1-0528, Llama 4, GLM-4.5-air | MMLU-Pro(선택형, 1,000건, CoT 정오). GPQA 는 공개 재게시 자제 요청이라 제외. IFEval, WildBench, Omni-MATH 는 생성형 |
| safety | v1.17.0 | 87 | 위와 같은 집단 + GPT-4.5, o1, DeepSeek R1, Claude 3.7 | BBQ(선택형 편향 QA, 1,000건, exact_match). XSTest, HarmBench, SimpleSafetyTests, Anthropic red team 은 응답을 LLM 이 채점(생성형) |
| lite | v1.13.0 | 91 | GPT-4o(2024-11), Claude 3.5 Sonnet/Haiku, Llama 3.3, DeepSeek V3, Qwen 2.5, Gemini 2.0 Flash, Nova Pro | LegalBench 5개 분류(abercrombie 95, corporate_lobbying 490, function_of_decision_section 367, international_citizenship_questions 1,000, proa 95), MedQA(선택형 1,000), OpenBookQA(500), MMLU(5과목). GSM8K, MATH, NarrativeQA, NaturalQuestions, WMT14 는 생성형 |
| mmlu | v1.13.0 | 79 | lite 와 같은 집단 | MMLU 57과목 전체(선택형) |
| arabic | v2.2.0 | 45 | GPT-5.4(2026-03), Qwen3.5, GPT-5.1 | 아랍어 MMLU. 언어가 달라 시드로는 안 쓰지만 HELM 이 2026년 모델까지 계속 추가한다는 근거 |
| medhelm | v4.0.0 | 13 | GPT-5, o3-mini, Claude 3.7, DeepSeek R1, Gemini 2.5 Pro | MedMCQA, MedQA, HeadQA(선택형). 의료 데이터 일부는 접근 제한 |
| finance | v1.0.0 | 22 | 없음(2024) | Banking77(고객 문의 77분류, 우리 customer-support 영역과 같은 꼴) |
| long-context | v1.0.0 | 11 | GPT-4.1, Llama 4 | InfiniteBench MC |
| classic | v0.4.0 | 70 | 없음(2022~2023) | RAFT, CivilComments, IMDB 분류. 모델이 너무 오래됨 |

내려받아 확인한 행렬(스크래치 `exp/helm/`, 스크립트 `exp/helm_matrix.py`):

| 행렬 | 항목 | 모델 | 정오 지표 | 비고 |
|---|---|---|---|---|
| capabilities MMLU-Pro | 1,000 | 67 | chain_of_thought_correctness | Gemini 3 Pro 90.3%, Claude Opus 4 thinking 87.5%, Sonnet 4.5 86.9%, GPT-5 86.3%, o3 85.9%, Grok 4 85.1%. 바닥은 OLMoE 16.9% |
| lite LegalBench 5개 | 95~1,000 | 91 | quasi_exact_match | 분류형. legal 영역 시드 후보 |
| lite MedQA | 1,000 | 91 | quasi_exact_match | 선택형 |
| lite OpenBookQA | 500 | 91 | exact_match | 지금 시드(v1.0.0, 31개 모델)를 대체할 수 있다 |
| safety BBQ | 1,000 | 81 | exact_match(per_instance_stats) | 정확도 42~99%. 편향 QA 라 content-moderation 영역 |

### 최신 모델에서의 축약 검증 (MMLU-Pro, 67개 모델)

| 집단 | MAE | 최대 오차 | Kendall τ | Spearman |
|---|---|---|---|---|
| 검증 모델 21개, 층화+교환 탐색 | 2.65pp | 6.70pp | 0.883 | 0.968 |
| 검증 모델 21개, 층화 무작위 | 2.48pp | 6.22pp | 0.904 | 0.975 |
| 적합 모델 46개(참고) | 0.51pp | 1.62pp | 0.984 | 0.996 |

읽는 법. 2025~2026 모델에서도 100건이 전체 정확도를 2.5pp 안팎에서 재현하고 순위 상관 0.9 다. 다만 적합 모델이 46개뿐이라 교환 탐색이 과적합해 층화 무작위보다 못하다. 모델이 800개였던 metabench 에서는 교환 탐색이 이겼다. 모델 수가 100개 아래면 기본을 층화 무작위로 두는 게 맞다(distill 에 모델 수 임계를 넣을 것).

### 다른 HELM 행렬의 축약 검증 (100건, 적합 70% 검증 30%)

| 행렬 | 항목 | 모델 | 정확도 범위 | 층화+교환 MAE / 최대 / τ | 층화 무작위 MAE / 최대 / τ |
|---|---|---|---|---|---|
| safety BBQ | 1,000 | 81 | 42~99% | 2.17 / 6.80 / 0.939 | 1.89 / 6.21 / 0.959 |
| LegalBench international_citizenship | 1,000 | 91 | 3~70% | 1.73 / 5.58 / 0.902 | 2.51 / 6.56 / 0.881 |
| LegalBench corporate_lobbying | 490 | 89 | 0~87% | 2.30 / 6.27 / 0.800 | 2.51 / 6.73 / 0.843 |
| MedQA | 1,000 | 91 | 22~87% | 2.33 / 8.58 / 0.794 | 3.03 / 10.62 / 0.838 |
| OpenBookQA(v1.13.0) | 500 | 91 | 22~97% | 2.44 / 5.20 / 0.802 | 2.63 / 5.80 / 0.781 |

모델이 80~90개면 두 방법이 엎치락뒤치락이고 MAE 는 2~3pp 다. 100건의 이항 잡음 바닥(정확도 70% 기준 표준오차 4.6pp, 모델 간 평균하면 2pp 안팎)에 이미 닿아 있어서, 더 줄이려면 n 을 늘리는 수밖에 없다.

## 2. 확인했지만 못 쓰는 곳

| 원천 | 왜 못 쓰나 |
|---|---|
| Open LLM Leaderboard v2 details(HF `open-llm-leaderboard/<model>-details`) | 항목별 결과 있음(MMLU-Pro, GPQA, MuSR, BBH, IFEval, MATH). 오픈 모델 2,000개 이상. 그러나 2025-03 에 멈췄고 게이트(auto)라 HF 읽기 토큰이 필요하다. 토큰만 있으면 바로 쓸 수 있다 |
| Ai2 BenchMIRT(2026-09) | 16개 벤치 × 오픈 모델 100개(2025-03 까지)를 IRT 로 분석. 공개된 것은 항목 통계(난이도, 변별도)뿐이고 모델별 정오 행렬은 없다. 원자료는 OLL v2 로 보인다 |
| LiveBench(HF `livebench/model_judgment`) | 모델 195개 × 질문 494건의 0/1 판정이 공개. 그러나 공개분은 language, coding, instruction_following 뿐이고 전부 생성형이라 우리 러너로 못 돌린다. 생성 팔 채점기가 생기면 후보 |
| Epoch AI Benchmarking Hub(CSV, CC-BY) | 모델별 총점과 표준오차만. 「Logs」열이 비어 있어 항목별은 못 받는다. GPQA Diamond, SimpleQA Verified, OTIS AIME, FrontierMath 등은 생성형이거나 재게시 금지 |
| Artificial Analysis Intelligence Index v4.3.2 | 열 개 벤치 전부 총점만 공개. AA-Omniscience, AA-LCR 질문은 HF 에 있으나 모델 응답은 없다 |
| Vals AI | 30개 벤치(LegalBench 149개 모델 포함) 총점만. 항목별 출력 없음 |
| LM Council, OpenEvals leaderboard-data, Kaggle 집계 | 총점 집계 |
| Humanity's Last Exam | 질문은 HF `cais/hle` 에 있으나 모델별 예측은 각자 돌려야 한다. 공개 항목별 결과 없음 |
| lmarena arena-hard-auto | 기준 모델 대비 쌍대 판정이라 항목 정오가 아니다 |
| Open Ko-LLM Leaderboard | HF 에 results(총점)와 requests 만. 항목별 details 없음. 한국어는 여전히 원천이 없다 |
| HAE-RAE, KMMLU | ND 라이선스 |

## 3. 다음 단계 제안

1. **시드 교체와 추가(HELM 기반)**. mmlu-pro-mini 를 capabilities 행렬(67개 최신 모델, Apache-2.0)로 다시 축약해 OpenEval 의 NC 조건을 벗긴다. openbookqa-mini 는 lite v1.13.0(91개)로 교체. 새 시드로 legalbench-mini(분류형, legal 영역 첫 벤치), medqa-mini, bbq-mini(content-moderation 영역)를 추가한다.
2. **distill 기본값 조정**. 모델 수가 100개 아래면 교환 탐색 대신 층화 무작위를 쓰고, 보고에는 항상 둘을 나란히 적는다.
3. **검증 집단을 매니페스트에 명시**. 「2025~2026 모델 n개(GPT-5.1, Claude Sonnet 4.5, Gemini 3 Pro 포함)」처럼 갤러리 상세에 보이게 한다.
4. **OLL v2 는 사용자 HF 토큰이 있을 때**. 오픈 모델 2,000개 행렬이라 교환 탐색이 제대로 돈다.
5. 생성형(LiveBench, GSM8K, SimpleQA)은 생성 팔 채점기를 만든 뒤.

## 4. 참고 링크

- HELM 공개 버킷: https://storage.googleapis.com/crfm-helm-public/ (리더보드별 `benchmark_output/releases/<ver>/runs_to_run_suites.json`, 런별 `display_predictions.json`, `per_instance_stats.json`, `instances.json`)
- HELM 리더보드: https://crfm.stanford.edu/helm/
- Open LLM Leaderboard v2 details: https://huggingface.co/open-llm-leaderboard
- LiveBench: https://github.com/LiveBench/LiveBench, https://huggingface.co/datasets/livebench/model_judgment
- Epoch AI data: https://epoch.ai/benchmarks/use-this-data
- Ai2 BenchMIRT: https://allenai.org/blog/benchmirt, https://huggingface.co/datasets/allenai/BenchMIRT-item-statistics
- Artificial Analysis methodology: https://artificialanalysis.ai/methodology/intelligence-benchmarking
- Vals AI: https://www.vals.ai/benchmarks

## 5. 현재 팔로 전체 대 축약본 직접 비교 (2026-10-05 실측)

사용자 지적(검증 집단이 2023~2024 모델이라 지금 모델에서는 의미가 약하다)에 답하려고, ARC-Challenge 전체 1,170건과 TruthfulQA MC1 전체 817건을 지금 쓰는 4팔로 전부 돌려 100건 축약본 점수와 비교했다. 정확도는 호출이 성공한 항목 기준이다.

| 벤치 | 팔 | 전체 정확도 (성공/전체) | 같은 100건, 전체 실행 안에서 | 축약본 별도 실행 (10-03) | 전체 대 축약 차이 |
|---|---|---|---|---|---|
| ARC | glm | 86.8% (1170/1170) | 92.0% | 90.0% | 3.2pp |
| ARC | qwen | 95.4% (1165/1170) | 96.0% | 95.0% | 0.4pp |
| ARC | deepseek | 91.2% (948/1170) | 94.1% (85) | 92.9% (98) | 1.6pp |
| ARC | jev | 98.0% (1170/1170) | 97.0% | 97.0% | 1.0pp |
| TruthfulQA | glm | 66.0% (774/817) | 62.4% (93) | 65.6% (93) | 0.4pp |
| TruthfulQA | qwen | 86.9% (770/817) | 87.0% (92) | 84.9% (93) | 1.9pp |
| TruthfulQA | deepseek | 77.7% (327/817) | 69.7% (33) | 76.3% (93) | 1.3pp |
| TruthfulQA | jev | 94.1% (774/817) | 95.7% (93) | 95.7% (93) | 1.6pp |

읽는 법.
- 2026년 팔에서도 100건 축약본이 전체 정확도를 0.4~3.2pp 안에서 재현했고, 팔 순위(jev > qwen > deepseek > glm)는 두 벤치 모두 전체와 축약본에서 같다. metabench 검증 모델에서 잰 1.5~2.0pp 와 같은 수준이다.
- 같은 팔이 같은 100건을 두 번 돌렸을 때 차이가 최대 2pp(glm ARC 92.0 대 90.0) 난다. 제공자 비결정성이 그만큼이므로 축약 오차 3pp 중 상당분은 축약이 아니라 실행 잡음이다. 100건의 Wilson 95% 구간(정확도 90%에서 약 ±6pp)이 모든 차이를 덮는다.
- 러너 한계가 드러났다. TruthfulQA 는 선택지가 최대 12개라 첫 토큰 라벨 질량 검사에 걸리는 항목이 많고(세 팔 모두 43건 실패), deepseek 은 490건이 실패했다. 선택지 수가 많은 벤치는 글자 라벨 대신 번호 라벨이나 두 토큰 라벨로 묻는 변형이 필요하다.
- 비용. ARC 전체 4팔 약 0.05달러, TruthfulQA 약 0.04달러. 「행렬 없는 벤치는 우리 팔로 전체를 한 번 돌려 검증한다」는 경로가 비용 면에서 충분히 싸다. 시간은 순차 실행이라 두 벤치 합쳐 약 2시간이 걸렸으므로 팔 병렬화가 필요하다.

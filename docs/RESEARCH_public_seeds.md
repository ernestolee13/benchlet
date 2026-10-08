# 공개 벤치 축약 시드: 원천과 축약 기법 조사 (2026-10-03)

사용자 지시. 유명한 단답·선택형 벤치 중 모델별 답안이 공신력 있게 공개된 곳을 찾고, 수십만 건을 우리 미니벤치 규모(수십~수백)로 줄이되 여러 모델의 정답률이 보존되게 줄이는 기법을 일관되게 적용해 초기 시드를 확보한다.

## 1. 모델별 답안(항목 단위 정오)이 공개된 원천

| 원천 | 무엇이 공개되나 | 접근 | 라이선스 | 판정 |
|---|---|---|---|---|
| metabench 논문 데이터 (Zenodo 12819251) | Open LLM Leaderboard v1 의 모델 5,000개 이상 × 6벤치(ARC, GSM8K, HellaSwag, MMLU, TruthfulQA, WinoGrande) 항목 단위 정오 행렬 | 인증 없이 다운로드 (data.tgz 620MB) | CC-BY-4.0 | **주 원천**. 모델 수가 많아 축약의 보존 검증(학습 모델/검증 모델 분리)이 가능 |
| HELM Lite / Classic 원시 결과 (GCS `crfm-helm-public`) | 실행마다 `per_instance_stats.json`, 프롬프트와 완성 원문. 모델 수십 개(상용 포함) | 공개 버킷, 인증 없음 | Apache-2.0(코드), 데이터는 원천 벤치 라이선스 | 보조 원천. 상용 모델이 들어 있어 교차 검증용. 실행 폴더가 모델×시나리오로 쪼개져 수집 비용이 든다 |
| **OpenEval (HF `Open-Eval-Commons/OpenEval`)** | 29벤치, 모델 ~187개(GPT-5.x·Claude 3.5·Qwen 3·Grok 3 등 2024~2026), 응답 1,080만 건. `response` 테이블에 응답 원문과 채점(`scores.value`) | 공개(게이트 없음), parquet 직접 다운로드(pyarrow). MMLU-Pro 는 1,000건 공통 부분집합을 121개 모델이 풀었고 전수(12k)는 11개 모델만 | CC-BY-NC-4.0 (응답 데이터). 항목 본문은 원천 벤치 라이선스 | **2차 원천(추가)**. 최신 상용 모델 집단에서 축약 보존을 잴 수 있다. 비상업 조건을 매니페스트에 적는다. 응답이 temperature 1 단일 샘플이라 정오에 잡음이 있다 |
| **HELM Lite v1.0.0 (GCS `crfm-helm-public`)** | 시나리오 9종 × 모델 31개(GPT-4, Claude 2, PaLM 2, Llama 2 등). `per_instance_stats.json` + `instances.json` | 공개 버킷, 인증 없음 | Apache-2.0(코드), 항목은 원천 라이선스 | **2차 원천(추가)**. OpenBookQA 500건 × 31모델로 썼다 |
| HF Open LLM Leaderboard v2 details (`open-llm-leaderboard/<model>-details`) | 모델마다 MMLU-Pro·GPQA·BBH·MuSR·MATH·IFEval 항목 단위 예측 | **게이트(auto) + 토큰 필요**. 이 머신에 토큰 없음 | 원천 벤치 라이선스 | 지금은 못 씀. 토큰이 생기면 MuSR·BBH 축약에 쓴다 |
| tinyBenchmarks (HF `tinyBenchmarks/*`) | 이미 100건으로 축약된 MMLU·ARC·HellaSwag·Winogrande·TruthfulQA·GSM8K + IRT 추정기 | 공개, datasets-server 로 읽힘 | MIT (원천 벤치 라이선스 별도) | 대조군. 우리 축약과 같은 원천에서 겹침·정확도 보존을 비교 |
| Epoch AI Benchmarking Hub, Artificial Analysis, LiveBench 등 | 모델별 집계 점수. 항목 단위 답안은 대부분 비공개 또는 일부 | 웹 | 각자 | 집계 점수 대조용. 축약 입력은 못 된다 |

원천 벤치 자체(항목 본문)의 라이선스와 접근.

| 벤치 | HF 경로 | n | 라이선스 | 축약 시드 가능 |
|---|---|---|---|---|
| MMLU | cais/mmlu all/test | 14,042 | MIT | 예 |
| ARC-Challenge | allenai/ai2_arc ARC-Challenge/test | 1,172 | CC-BY-SA-4.0 | 예 (SA 유지) |
| HellaSwag | Rowan/hellaswag validation | 10,042 | MIT | 예 |
| WinoGrande | allenai/winogrande winogrande_xl/validation | 1,267 | CC-BY | 예 |
| TruthfulQA MC1 | truthfulqa/truthful_qa multiple_choice/validation | 817 | Apache-2.0 | 예 |
| MuSR | TAUR-Lab/MuSR | 756 | CC-BY-4.0 | 예 (모델별 답안은 게이트) |
| GPQA | Idavidrein/gpqa | 448 | CC-BY-4.0 이나 공개 재게시 자제 요청 | 아니오 (오염 방지 요청 존중) |
| KoBEST (BoolQ·COPA·HellaSwag·SentiNeg·WiC) | skt/kobest_v1 | 1,000~1,404 | CC-BY-SA-4.0 | 예. 모델별 항목 답안은 공개된 것이 없어 층화 무작위로만 |
| CLIcK | EunsuKim/CLIcK | 1,995 | 카드에 미기재(논문 CC-BY-SA 확인 필요) | 보류 |
| KMMLU | HAERAE-HUB/KMMLU | 35,030 | CC-BY-ND-4.0 | 아니오 (파생 금지) |
| HAE-RAE Bench | HAERAE-HUB/HAE_RAE_BENCH_1.1 | | CC-BY-NC-ND-4.0 | 아니오 |

사용자 질문 「모델별 응답까지 공개된 벤치는 생각보다 적은가」에 대한 답. 적다. 집계 점수만 공개하는 리더보드가 대부분이고, 항목 단위 응답을 공개한 곳은 metabench(OLL v1 파생), OpenEval(2026 신규, 가장 넓음), HELM(상용 포함, 모델 수 적음), BIG-bench(점수 JSON 만, 응답 로그 없음), LiveBench(모델 답안 공개하나 단답 생성형) 정도다. 그래서 「응답이 공개된 원천을 가져와 빠르게 축약」은 이 넷에서만 되고, 나머지는 우리가 직접 돌려야 한다.

## 2. 축약 기법 문헌

| 논문 | 핵심 | 우리 적용 |
|---|---|---|
| tinyBenchmarks (Polo et al., ICML 2024, arXiv 2402.14992) | IRT 로 항목 표현을 만들고 anchor point 로 100건 선택. IRT++ 추정으로 MMLU 전체 정확도를 평균 2% 안에서 예측. 5개 시드 중 최선 | 100건 기준과 「정확도 오차 2%」 목표를 그대로 쓴다 |
| metabench (Kipnis et al., ICLR 2025, arXiv 2407.12844) | 5,000+ 모델 정오 행렬. 분산 필터 → 350건 교차검증 샘플 → IRT 적합 → 정보량 높은 항목 선택. 원 점수 재구성 MAE 0.9% 미만 | 데이터 원천. 「분산 0 항목 제거」와 「정보량 기준」을 차용 |
| Anchor Points (Vivek et al., EACL 2024, arXiv 2309.08638) | 모델들의 정답 확신이 항목 쌍에서 강하게 상관. 군집 중심(anchor)만 평가 | 확률이 있는 팔에서는 확신 상관을 쓸 수 있으나 공개 행렬은 정오만 있어 정오 상관 군집으로 대체 |
| Flash-HELM (Perlitz et al., arXiv 2308.11696) | 신뢰도 지표 DIoR, coarse-to-fine 으로 200배 절감 | 순위 보존 지표(Kendall tau)를 보고에 넣는다 |
| 최근 (2025~2026): Fluid benchmarking(2509.11106), 200x less data(2510.10457), SparseEval(2602.07909), CollabEval 행렬 완성(2607.05046), 통계 보증 효율 평가(2601.20251) | IRT 적응 평가, 희소 최적화, 행렬 완성 | 참고. v1 은 단순·투명한 방법으로 두고 IRT 는 2판 |

## 3. 우리 축약 규칙 (`benchlet distill`, v1)

목표. 원천 항목 N 과 모델 M 개의 정오 행렬이 있을 때 n 건(기본 100)을 골라, 보지 않은 모델에서도 (a) 전체 정확도 오차가 작고 (b) 모델 순위가 보존되게 한다. 방법은 투명해야 하고(왜 이 항목인지 설명 가능) 3.9 표준 라이브러리로 돌아야 한다.

1. 전처리. 모든 모델이 맞히거나 모두 틀리는 항목(분산 0)은 뺀다(metabench). 항목 난이도 p = 모델 정답률.
2. 층화. p 를 5분위로 나눠 비례 배분한다(난이도 분포 보존). 다지 벤치는 정답 위치 분포도 같이 본다.
3. 적합/검증 분리. 모델을 무작위로 적합 70% / 검증 30% 로 나눈다(시드 고정).
4. 선택. 층 안에서 무작위 초기화 뒤 교환 탐색. 목적함수 = 적합 모델들의 |acc_sub − acc_full| 평균 + 최대값 + (1 − Kendall tau). 교환은 같은 층 안에서만.
5. 보고. 검증 모델에서 MAE·최대 오차·Kendall tau·Spearman, 그리고 같은 n 의 층화 무작위(기준선) 대비. tinyBenchmarks 100건과의 겹침 수.
6. 산출. 최소 형식 항목 + 매니페스트(`source`, `license`, `distill`: 방법·시드·검증 수치·원천 모델 수). `label_source: machine`(원천 정답 키).

이 방법은 IRT 를 쓰지 않는다. 적합 모델에 과적합할 수 있으므로 검증 모델 수치만 보고한다. 선택 항목 수가 100 이면 tinyBenchmarks 와 같은 규모라 그쪽 오차(약 2%)를 기준점으로 삼는다.

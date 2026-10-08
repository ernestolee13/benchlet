# 공개 벤치 축약 시드: 고르기, 만들기, 검증하기

갤러리의 「public-distilled」 벤치는 공개 벤치를 100건으로 줄인 것이다. 에이전트가 할 일은 셋이다. (1) 사용자의 판정과 비슷한 시드를 찾아 포크 후보로 보여 준다. (2) 새 공개 벤치를 시드로 넣을 때 아래 두 경로 중 하나를 쓴다. (3) 축약 검증 수치를 매니페스트에 남긴다.

## 1. 어떤 벤치를 시드로 삼나

조건 셋을 다 만족해야 한다.
- **판단형.** 지식 암기보다 판단(거절해야 하나, 어느 도구인가, 둘 중 맞는 응답은, 근거에 있나, 편향인가)을 묻는다. 지식 시험류(MMLU-Pro, OpenBookQA)는 비교용으로 몇 개만 둔다. legal-citizenship 처럼 「나라별 국적법」 같은 지식 문제는 넣었다가 뺐다.
- **선택형이나 이진.** 첫 토큰 로그프롭과 typed 팔로 돌릴 수 있어야 한다. 선택지 10개를 넘으면 라벨 질량 실패가 늘어난다.
- **라이선스가 재게시를 허용.** MIT, Apache-2.0, CC-BY, ODC-BY 는 된다. NC(ToxicChat, HaluBench, SciFact, BeaverTails), ND(LLM-AggreFact), 재호스팅 금지(SORRY-Bench), 미기재(ClearFacts, R-Judge)는 넣지 않는다. 게이트(WildGuardTest, OLL v2 details)는 토큰이 있을 때만.

후보 표는 `docs/RESEARCH_judgment_candidates.md`(60여 개, 점수 출처 포함)에 있다. 새 후보를 찾을 때는 리더보드에서 이름과 주요 모델 점수를 먼저 보고, 맞으면 HF 나 깃허브에서 원본을 받는다. 벤치 묶음을 찾는 게 아니다.

## 2. 두 경로

### 경로 A. 모델별 항목 정오 행렬이 있는 벤치 (`src/build_judgment_seeds.py`)

원천 모델 집단으로 「축약본 정확도 = 전체 정확도」를 검증할 수 있다. 행렬이 열린 곳은 넷이다.

| 원천 | 모델 | 최신 모델 | 스크립트 |
|---|---|---|---|
| HELM 공개 버킷 (capabilities, safety, lite, mmlu, medhelm, finance) | 67~91 | GPT-5.1, Claude Sonnet 4.5, Gemini 3 Pro, Grok 4 (capabilities·safety) | `src/prepare_helm_matrix.py <leaderboard> <scenario> <out>` |
| BFCL-Result (깃허브 HuanzhiMao/BFCL-Result) | 109 | Claude 4.5, GPT-5.2, o3, Gemini 3 Pro, Qwen3, DeepSeek V3.2, Llama 4 | `src/prepare_bfcl_matrix.py <out>` |
| JudgeBench HF 공간 outputs/ | 심판 37 | o3-mini, DeepSeek-R1, GPT-4o, Claude 3.5, Gemini 1.5 | `src/prepare_judgebench_matrix.py <out>` |
| RewardBench 2 results | 188 | Claude Opus 4, Sonnet 4, 3.7, Gemini 2.5 Pro/Flash, GPT-4.1 | `src/prepare_rb2_matrix.py <out>` |
| metabench (Zenodo) | 800~5,000 | 2023~2024 오픈 모델 | `src/prepare_matrices.py` |

축약 규칙(`benchlet distill`, 기본 auto). 모델이 100개 이상이면 난이도 층화 + 교환 탐색, 미만이면 층화 무작위. 실측으로 정한 임계다(HELM 67~91개에서는 교환 탐색이 과적합해 무작위보다 못했고, BFCL 109개·metabench 800개에서는 교환이 나았다). 두 방법의 검증 수치가 `distill.val` 과 `distill.alt` 에 같이 남는다. 검증 모델 30% 는 선택에 쓰지 않는다.

기대값. 100건이면 검증 모델에서 MAE 1.5~2.7pp, 최대 오차 5~10pp, 순위 상관 0.8~0.97. 이건 이항 잡음 바닥이라 방법보다 n 이 결정한다.

### 경로 B. 행렬이 없는 벤치 (`src/build_nomatrix_seeds.py`)

클래스(원천 라벨, 소집합) 층화 무작위로 100건을 고르고 팔 정보는 쓰지 않는다. 전체 세트를 스크래치에 같이 써 두고, 우리 팔로 전체와 축약본을 둘 다 돌려 `src/compare_full_vs_mini.py` 가 팔별 차이와 순위 보존을 매니페스트 `distill.own_arms` 에 적는다. 호출 성공률 70% 아래인 팔은 비교에서 뺀다.

기대값. 정확도 80% 근처에서 100건의 이항 표준오차가 4pp 라, 팔별 차이 2~4pp 와 순위 보존이 정상이다. 네 팔이 같은 방향으로 6pp 이상 벗어나면 표본이 쏠린 것이니 층을 더 잘게(라벨 × 범주) 나눠 다시 뽑는다(Aegis 에서 실제로 그랬다).

비용. 전체 1,000건 4팔이 0.1달러 안팎, 병렬 6 이면 10분 안팎.

## 3. 현재 시드 (2026-10-05)

| 영역 | 시드 | 묻는 것 | 경로 |
|---|---|---|---|
| agent-tools | tool-call-gate-mini, tool-pick-mini | 도구를 불러야 하나 / 어느 함수인가 (BFCL) | A |
| data-quality (심판) | judge-pair-mini, best-of-4-mini | 두 응답 중 맞는 쪽 (JudgeBench) / 넷 중 최선 (RewardBench 2) | A |
| content-moderation | bbq-mini, xstest-refusal-mini, aegis-prompt-safety-mini, jbb-jailbreak-judge-mini, ethics-commonsense-mini | 편향 QA / 거절해야 하나 / 안전하지 않은가 / 탈옥 성공인가 / 도덕적으로 잘못됐나 | A, B |
| legal | legal-lobbying-mini | 법안이 이 회사와 관련 있나 | A |
| retrieval-rag | halueval-qa-mini | 답변이 근거에 비추어 환각인가 | B |
| commonsense (추론) | musr-murder-mini, musr-objects-mini, bbh-judgment-mini, openbookqa-mini, hellaswag-mini, winogrande-mini, arc-challenge-mini | 범인·물건 위치·인과·경로·상식 | A, B |
| knowledge-exam, truthfulness | mmlu-pro-mini, mmlu-mini, truthfulqa-mc1-mini | 비교용 지식 시험 | A |

포크할 때는 시드의 질문을 사용자 판정 문구로 바꾸지 말고, 사용자 데이터로 새 벤치를 만들되 같은 서명·키워드를 붙여 「유형별 추천」이 묶이게 한다.

## 4. 알려진 약점

- 팔이 4개뿐이라 경로 B 의 검증은 약하다. 커뮤니티 제출이 쌓이면 그걸로 대신한다.
- BFCL 정오는 「올바른 인자까지 맞힌 호출」이라 우리 질문보다 엄격하다. JudgeBench 는 작은 모델이 「응답 A」로 쏠려 50% 근처가 나온다(위치 편향). RewardBench 2 응답은 1,800자에서 잘랐다.
- 제공자 속도 제한(429)은 러너가 지수 대기로 다시 시도한다. 그래도 실패한 팔은 `benchlet run --arms <팔> --merge` 로 그 팔만 다시 돌려 합친다.

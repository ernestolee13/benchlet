# 판단형 공개 벤치 후보 조사 (2026-10-05)

사용자 방향: 벤치 묶음을 찾는 게 아니라, 선택형이나 단답형이면서 지식보다 판단을 묻는 벤치의 「이름과 주요 모델 점수」를 먼저 모으고, 우리에게 맞는 것만 원본을 직접 내려받아 축약한다.

조사 방법. 리더보드와 논문에서 후보를 모으고(세 갈래 병렬 조사: 안전·검열 판단, 심판·근거·환각 판단, 도구·라우팅·분류), 각 후보의 형식, 항목 수, 라이선스, 내려받기 경로, 주요 모델 점수의 출처, 항목별 모델 출력 유무를 확인했다. 원문 표는 스크래치 `cand/report_*.md` 에 있고 여기엔 추린 것만 적는다. 점수는 출처가 있는 것만 적었고 없으면 「없음」이다.

## 1. 바로 쓸 수 있는 1순위 (원본 내려받음, 축약 검증까지 돌림)

### BFCL 도구 호출 판정 (UC Berkeley, Apache-2.0, 2026-04 갱신)

「이 요청에 도구를 불러야 하는가」(irrelevance / relevance detection)와 「어느 함수를 불러야 하는가」(multiple)가 그대로 우리 agent-tool-pick, action-confirm-gate 와 같은 꼴이다. 리더보드에 109개 모델(Claude Opus 4.5, Sonnet 4.5, Haiku 4.5, GPT-5.2, GPT-5-mini, GPT-4.1, o3, o4-mini, Gemini 3 Pro, Gemini 2.5 Flash, Qwen3-235B, DeepSeek V3.2, Llama 4, GLM 등) 점수가 있고, 결과 저장소(HuanzhiMao/BFCL-Result, 2025-12-16 스냅샷)에 모델별 항목별 원응답과 채점 파일이 있어 정오 행렬을 재구성했다. 재구성 정확도와 리더보드 보고 정확도가 109개 모델 전부 2pp 안에서 일치한다.

| 범주 | 항목 | 모델 | 정확도 범위 | 100건 축약 검증 MAE / 최대 / τ (층화+교환) | (층화 무작위) |
|---|---|---|---|---|---|
| live_irrelevance (도구 없음을 판정) | 882 | 109 | 10~100% | 2.47 / 9.64 / 0.856 | 2.50 / 11.20 / 0.895 |
| irrelevance | 240 | 109 | 2~100% | 1.60 / 7.08 / 0.949 | 1.89 / 6.17 / 0.910 |
| live_multiple (함수 고르기) | 1,053 | 109 | 0~94% | 2.36 / 9.16 / 0.809 | 2.10 / 6.51 / 0.864 |
| multiple | 200 | 109 | 0~97% | 1.76 / 5.50 / 0.855 | 2.00 / 7.50 / 0.861 |

주요 모델 점수(live irrelevance, FC 모드, 2025-12-16): Claude Sonnet 4.5 85.3, Claude Haiku 4.5 85.6, Claude Opus 4.5 83.6, GPT-4.1 83.0, o3 83.9, o4-mini 81.6, GPT-5.2 78.9, GPT-5-mini 89.9, Gemini 2.5 Flash 92.8, Gemini 3 Pro 73.2, Qwen3-235B 79.3, DeepSeek V3.2 92.2, Llama 4 Maverick 37.8.

주의. 같은 모델도 FC(네이티브 함수 호출) 모드와 Prompt 모드 점수가 크게 다르다(Sonnet 4.5 irrelevance 85.3 대 96.7). 우리 러너는 「도구를 부른다 / 부르지 않는다」 이진 선택으로 바꿔 묻게 되므로 BFCL 점수와 직접 비교는 안 되고, 축약 검증에만 행렬을 쓴다.

### HELM (스탠퍼드, 결과 Apache-2.0)

앞선 조사(`docs/RESEARCH_recent_sources.md`)에서 확인. 판단형에 가까운 것만 다시 적는다.

| 시나리오 | 리더보드 | 항목 | 모델 | 최신 모델 | 100건 축약 검증 MAE / τ |
|---|---|---|---|---|---|
| BBQ (편향 QA, 3지) | safety v1.17.0 | 1,000 | 81 | GPT-5.1, Claude Sonnet 4.5, Gemini 3 Pro, Grok 4 | 1.9~2.2pp / 0.94~0.96 |
| LegalBench 분류 5종 | lite v1.13.0 | 95~1,000 | 91 | GPT-4o, Claude 3.5, Llama 3.3, DeepSeek V3 | 1.7~2.5pp / 0.88~0.90 |
| Banking77 (77분류) | finance v1.0.0 | 1,000 | 22 | 2024년 모델까지 | (미실행) |

## 2. 2순위: 원본은 열려 있고 주요 모델 점수가 논문·시스템카드에 있음 (항목별 출력은 없음)

축약 검증은 행렬이 없으니 「우리 팔로 전체 대 축약본 비교」로 한다.

| 벤치 | 묻는 것 | 형식 / n | 라이선스 | 주요 모델 점수(출처) | 비고 |
|---|---|---|---|---|---|
| XSTest | 이 프롬프트는 거절해야 하나(과잉 거절 대조) | 이진 / 450 | CC-BY-4.0 | 오거절률 Claude 3.5 Sonnet 1.7%, Claude 3 Opus 8.3% (Claude 3.5 addendum) | 작고 깨끗함. allenai/xstest-response 에 895건 응답 라벨(게이트) |
| OR-Bench hard-1k / toxic | 안전하지만 의심스러운 요청 대 유해 요청 | 이진 / 1,320 + 655 | CC-BY-4.0 | hard-1k 거절률 GPT-4o 6.7, Claude 3 Opus 91.0, Gemini 1.5 Pro 88.0, Llama 3 70B 37.7 (논문) | 라벨이 LLM 앙상블 투표라 금라벨 신뢰는 낮음 |
| Aegis 2.0 (NVIDIA) | 프롬프트·응답이 안전한가 + 범주 | 이진 / 테스트 1,964 | CC-BY-4.0 | GPT-4 F1 84.4(1.0 기준), Llama Guard 3 76.4, WildGuard 80.7 (2.0) | 2025, 사람+LLM 배심 라벨 |
| OpenAI moderation eval | 8범주 위반 여부 | 다중 라벨 / 1,680 | MIT | GPT-4 F1 70.5, OpenAI Mod 79.0, Llama Guard 2 76.1 (WildGuard 논문) | 고전 검열 세트 |
| JailbreakBench judge-comparison | 이 응답은 탈옥에 성공했나 | 이진 / 300 | MIT | 사람 라벨 3개 + GPT-4·Llama Guard 2·Llama 3·HarmBench 심판 열 | 심판 대 사람 불일치가 바로 측정됨 |
| MuSR | 살인 미스터리의 범인, 물건 위치, 팀 배정 | 2지~다지 / 250+256+250 | MIT | GPT-4 80.4/60.9/68.4, GPT-3.5 61.6/46.9/40.4 (논문); OLL v2 에 오픈 모델 항목별 | 추론형 판단. OLL v2 details 는 HF 토큰 필요 |
| BBH 판단 소집합 | causal_judgement, navigate, snarks, sports_understanding | 이진 / 865 | MIT | GPT-4o 67.0/89.8, Claude 3.5 Sonnet 69.0/90.4 (causal/snarks, arXiv 2411.05978) | OLL v2 에 오픈 모델 항목별 |
| Mind2Web | 목표를 이루려면 어느 요소를 눌러야 하나(후보 50 + 없음) | 다지 / 1,339+1,019+4,060 | CC-BY-4.0 | 요소 정확도 GPT-4 41.6/35.8/37.1, GPT-4o 36.0 (논문, inspect_evals) | 우리 browser-click-target 과 같은 꼴 |
| ACEBench special | 모호·범위 밖 요청 판정 | 규칙 채점 / ~2,000 (en+zh) | MIT | GPT-4o 0.933, Claude 3.5 Sonnet 0.756, Gemini 1.5 Pro 0.728 (README) | BFCL 다음의 irrelevance 류 |
| Banking77 / CLINC150 / MASSIVE | 고객 문의 의도 분류 | 77 / 150+OOS / 60 분류 | CC-BY-4.0 / 3.0 / 4.0 | Banking77 GPT-4 3-shot F1 83.1, Claude 2 76.8 (arXiv 2311.06102) | 우리 support-ticket-triage 와 같은 꼴 |
| ETHICS commonsense | 이 행동은 도덕적으로 잘못됐나 | 이진 / 3,885 (+hard 3,964) | MIT | GPT-4 95% short / 78% long (arXiv 2309.10492) | 프롬프트 민감 |
| Scruples dilemmas | 둘 중 어느 행동이 더 나쁜가 | 이진 / 10,000 | Apache-2.0 | RoBERTa F1 0.783, 사람 0.804. LLM 점수 없음 | 금라벨은 있음 |
| R-Judge | 에이전트 기록이 위험한가 | 이진 / 569 | 라이선스 미기재 | GPT-4o F1 74.45, Llama 3 8B 61.0, Llama Guard 2 71.8 (논문) | 저자 확인 전엔 재게시 못 함 |

## 3. 확인했지만 제외

| 벤치 | 이유 |
|---|---|
| WildGuardTest (1,725, 사람 라벨 3종) | 가장 잘 맞지만 ODC-BY + AI2 게이트. 책임 사용 조건을 읽고 재게시 가능한지 확인한 뒤 |
| SORRY-Bench | 라이선스가 재호스팅 금지 |
| ToxicChat, BeaverTails, Do-Not-Answer, HaluBench, LLM-AggreFact(ND) | 비상업 또는 변경 금지 |
| SafetyBench | 테스트 라벨 비공개, 리더보드 도메인 소멸 |
| HarmBench 검증 세트 | 공개 내려받기 경로 없음 |
| AgentHarm, InjecAgent, BIPIA, tau-bench, ToolBench | 생성·에이전트 실행형. InjecAgent 만 「이 도구 출력은 주입인가」로 바꿀 여지 |
| MoralChoice, DailyDilemmas, DiscrimEval | 정답이 없는 선호 조사 |
| WebLINX, QQP, Bitext | NC 또는 제한 라이선스 |
| SQL 자동실행 안전, 티켓 우선순위, 이슈 중복 쌍 | LLM 점수가 있는 공개 세트가 없다. 우리 샘플이 그 빈자리를 메운다 |

## 4. 심판·근거·환각 판단

세 묶음으로 조사했다(응답 쌍 비교, 관련성 판정, 지시 준수 검증, 근거·환각 판정). 최신 모델의 항목별 심판 출력이 공개된 곳은 RewardBench 2 결과 데이터와 JudgeBench 공간뿐이고, 그 밖의 리더보드는 Claude 3.5 Sonnet, GPT-4o, Llama 3.3, Qwen2.5-72B 세대에서 멈춰 있다.

| 벤치 | 묻는 것 | 형식 / n | 라이선스 | 주요 모델 점수(출처) | 항목별 출력 | 비고 |
|---|---|---|---|---|---|---|
| JudgeBench (ScalerLab) | 두 응답 중 어느 쪽이 객관적으로 맞나 | 쌍 선택 / 620 | MIT | 위치 일관 정확도: o3-mini-high 80.9, o1-preview 75.4, DeepSeek-R1 73.1, o1-mini 65.7, Claude 3.5 Sonnet 64.3, Llama 3.1 405B 56.9, GPT-4o 56.6, Gemini 1.5 Pro 47.1 (논문 표 2) | 있음(HF 공간 outputs/, 심판 20여 개: o3-mini, DeepSeek-R1, GPT-4o, Claude 3.5, Gemini 1.5, Llama 3.1) | 1순위. 작고 어렵고 정답이 객관적. HF 카드는 MIT, README 엔 라이선스 미기재라 재게시 전 확인 |
| RewardBench 2 (Ai2) | 넷 중 가장 나은 응답 고르기 | 4지 / 1,865 (사실성 475, 정밀 지시 160, 수학 183, 안전 450, 집중 495, 동점 102) | ODC-BY | LM 심판 평균 정확도: Gemini 2.5 Pro 79.5, Gemini 2.5 Flash 77.2~77.7, Claude Opus 4 76.5, Claude 3.7 Sonnet 75.4, GPT-4.1 72.3, GPT-4o 64.9 (논문 표 3) | 있음(allenai/reward-bench-2-results, 모델별 항목별, 2.97GB) | 1순위. 포화 안 됨. 우리 4지 러너에 바로 맞음 |
| LLMBar (Princeton) | 두 응답 중 지시를 더 잘 따른 쪽 | 쌍 선택 / 419 (자연 100, 적대 319) | MIT | GPT-4 자연 93.5~96.0, 적대 73.1~82.8; ChatGPT 적대 32~39; LLaMA-2-70B 적대 33~43; 사람 94 (논문) | 미확인 | 적대 항목이 「길고 그럴듯한 쪽」 편향을 잡는다. 2023 모델만 |
| RM-Bench (THU) | 스타일만 다른 쌍에서 맞는 쪽 | 쌍 선택 / 1,327 | ODC-BY | Gemini 1.5 Pro 75.2, GPT-4o 72.5, Llama 3.1 70B 65.5, Claude 3.5 Sonnet 61.0 (RM-R1 재현); DeepSeek-R1 85.3 | 없음 | 스타일 강건성 |
| PPE (LMArena) | 사람이 고른 쪽 맞히기 | 쌍 선택 / 16,038 | 프롬프트 CC-BY-4.0, 응답은 제공자 약관 | GPT-4o 67.7, Claude 3.5 Sonnet 67.3, Gemini 1.5 Pro 65.7~66.1 (논문 표 4) | 미확인 | 사람 라벨 잡음으로 천장 68 |
| MCJudgeBench | 제약별 준수 여부 | 예/부분/아니오 / 1,022 제약 | Apache-2.0 | Gemini 3.1 Pro 0.858, Qwen3.5-4B 0.853, Claude Sonnet 4.6 0.828, GPT-5.2 0.775 (논문) | 없음 | 2026, 가장 최신 심판 표 |
| IF-RewardBench (THU) | 제약 체크리스트 선호 | 점별 + 목록 / 6,011 응답 | 미기재 | τb Gemini 3 Pro 0.609, GPT-5.1 0.525, DeepSeek V3.2 0.395, Llama 3.3 70B 0.238, 사람 0.755 | 미확인 | 2026 |
| LLMJudge (LLM4Eval) | 문단이 질의에 관련 있나 (0~3) | 등급 / 테스트 4,423쌍 | CC-BY-4.0 | GPT-4o UMBRELA κ 0.286, Llama-3-8B 미세조정 κ 0.282 (42개 라벨 세트 비교, 2502.13908) | 있음(42개 LLM 라벨 세트 전부) | 관련성 판정의 유일한 사람 라벨 + 다중 심판 세트. 이진으로 접으면 κ 0.45~0.50 |
| TREC DL 2019~23 | 관련성 0~3 | 등급 / 9천~2만 쌍 | NIST, MS MARCO 약관 | GPT-4o κ 0.42~0.50 이진 (UMBRELA), 4o-mini 0.40; Qwen3-8B 0.215, Llama-3.2-3B 0.163 | 있음(GPT-4o, Llama 라벨 공개 저장소) | 약관 확인 필요 |
| HaluEval | 이 답변은 환각인가 | 이진 / 35K | MIT | ChatGPT QA 62.6 / 대화 72.4 / 요약 58.5; Claude 2 69.8/64.7/57.8 (논문) | 없음 | 합성 음성이 쉬워 오염됐을 가능성 |
| RAGTruth | 이 응답에 근거 없는 내용이 있나 | 범위 라벨, 응답 단위 이진 / 17,790 | MIT | GPT-4-turbo F1 63.4 (정밀 46.9 / 재현 97.9); o3-mini-high 균형 정확도 85 (FaithJudge) | 응답은 6개 LLM 생성물 | 양성 쏠림 |
| FaithBench (Vectara) | 요약 문장이 원문에 충실한가 | 4단계, 이진화 / 660 | 저장소 LICENSE | GPT-4-Turbo 57.7, GPT-4o 56.3 (제로샷); o3-mini-high 84.0, GPT-4o 79.5, Llama 3.3 70B 77.5, Qwen2.5-72B 73.2 (FaithJudge 퓨샷) | FaithJudge 저장소에 심판 출력 있음 | 작고 어려움 |
| SummaC | 요약이 원문과 일치하나 | 이진 / 5,212 | Apache-2.0 | SummaC-Conv 74.4; LLM 심판 점수 없음 | 없음 | 2021 요약 |
| TofuEval (Amazon) | 대화 요약 문장 일관성 | 이진 / 3,966 문장 | 저장소 | GPT-4 64.9 / 67.5, GPT-3.5 61.6 / 56.0 (논문) | 없음 | LLM-AggreFact 에 포함 |
| LLM-AggreFact | 주장이 문서에서 뒷받침되나 | 이진 / 29,320 | CC-BY-ND-4.0 | Claude 3.5 Sonnet 77.2, Mistral Large 2 76.5, GPT-4o 75.9, Qwen2.5-72B 75.6, Llama 3.3 70B 74.5 (리더보드 39개 모델) | 없음 | 형식은 완벽하지만 ND 라 축약본 재게시 불가 |
| ClearFacts (Verifying the Verifiers, 2025) | 주장이 문서에서 뒷받침되나 (라벨 재검수본) | 이진 / 1,590 (+모호 159) | 미기재 | 재검수 뒤 제로샷 macro-F1: Claude 3.7 Sonnet 86.0, o1 85.4, R1-Qwen2.5-32B 82.9, Claude 3.5 Haiku 79.5, Llama 3.3 70B 78.1 | 없음 | 라벨 잡음을 고친 최신 묶음. 라이선스 확인 필요 |
| WiCE (UT Austin) | 위키 주장이 인용 근거로 뒷받침되나 | 3단계 / 하위주장 5,380 | ODC-BY | GPT-4 주장 단위 77%; 퓨샷 macro-F1 o1 88.0, Claude 3.7 Sonnet 83.5, GPT-4o 79.8 | 저장소에 모델 출력 | 자연 주장, 근거 인라인 |
| VitaminC (MIT) | 대조 근거 쌍에서 지지/반박/정보없음 | 3지 / 테스트 55,200 | CC BY-SA 3.0 | LLM 제로샷 점수 없음(ALBERT 88.9) | 없음 | 근거 무시를 잡는 최소 대조 쌍. 형식은 가장 좋음 |
| SciFact (AI2) | 과학 주장이 초록에서 지지/반박되나 | 3지 / dev 450 | CC BY-NC 2.0 | 이진화 퓨샷 macro-F1 o1 93.2, GPT-4o 91.0, Claude 3.7 Sonnet 83.6; GPT-4 F1 71.7 | 없음 | NC |
| Climate-FEVER | 기후 주장과 근거 문장 | 근거쌍 3지 / 7,675 | CC BY-SA 4.0 | Llama 3.3 70B macro-F1 .51~.55, Mistral-24B .50~.56 (Climate-Eval) | 없음 | 상용 모델 점수 없음 |
| AttributionBench (OSU) | 답변 문장이 인용 문단에 귀속되나 | 이진 / LFQA 168, ExpertQA 612 | CC BY 4.0 | GPT-4 macro-F1 73.3, GPT-3.5 69.7; LFQA 균형 정확도 GPT-4 79.9, Claude 3 Opus 78.8 | 없음 | 작지만 LLM 시대 답변 |
| HaluBench (Patronus) | 답변 PASS/FAIL | 이진 / 14.9K | CC-BY-NC-2.0 | GPT-4o 86.5, GPT-4-Turbo 85.0, Claude 3 Sonnet 78.8, Llama 3 70B 80.1 | 없음 | NC |

제외: FEVER(근거 결합 필요, NEI 근거 없음), AVeriTeC·FELM(NC), FactBench(생성 평가), FACTS Grounding, HHEM, HalluLens(응답 생성 평가라 심판 정답 없음), Arena-Hard-Auto(항목 금라벨 없음), RewardMATH(NC-ND), LLM-Oasis(NC-SA), MT-Bench 사람 판정(2023, 포화), ACS·RubricEval(데이터 미공개), IFEval·IFBench·Multi-IF(응답을 뽑아 검사기로 라벨을 만들어야 판정 항목이 됨).

## 5. 다음 단계

0. JudgeBench(620)와 RewardBench 2(1,865)를 1순위에 추가한다. 둘 다 항목별 심판 출력이 있어 행렬 기반 축약 검증이 된다. RewardBench 2 결과(2.97GB)는 필요한 열만 스트리밍으로 받는다.
1. BFCL live_irrelevance 와 multiple 을 각각 100건으로 축약해 `tool-call-gate-mini`, `tool-pick-mini` 시드로 만든다. 질문은 「이 요청에 주어진 도구 중 부를 것이 있는가」(이진), 「어느 함수를 불러야 하는가」(다지). 매니페스트에 109개 모델 검증 집단과 BFCL 모드 차이를 적는다.
2. HELM BBQ, LegalBench 를 같은 파이프라인으로 축약한다(`src/prepare_helm_matrix.py` 는 이미 있다).
3. 2순위 중 XSTest, Aegis 2.0, Mind2Web, MuSR, BBH 소집합, Banking77 을 「행렬 없는 경로」로 넣는다. 층화 무작위 축약 뒤 우리 팔로 전체 대 축약을 비교해 검증 수치를 남긴다. 지금 ARC, TruthfulQA 에서 그 경로의 첫 실측이 돌고 있다.
4. 게이트 세트(WildGuardTest, OLL v2 details)는 사용자가 HF 토큰을 주면 추가한다.

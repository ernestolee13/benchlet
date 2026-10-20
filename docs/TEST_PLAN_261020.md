# 추가 테스트 계획과 비용 (2026-10-20)

우리 사용 환경과 직결되는 벤치 32개(own-data 11, synthetic-rules 12, 라우터 3, 도구·안전·근거 6)를 기준으로 한다. 항목 1,841건, Jev 프롬프트 기준 입력 152만 토큰. 판단 전용 모델은 출력이 무료라 한 바퀴 비용이 센트 단위다.

## 1. 이미 돌린 것: OpenAI Decisions (gpt-6-luna) 팔 추가

OpenRouter 의 같은 decisions 엔드포인트가 `openai/gpt-6-luna-decisions` 를 Jev 와 같은 요청·응답 모양으로 중계한다. 러너 프리셋 `luna`. 32개 전부 합쳐 0.10달러.

| | Luna | Jev 1.13 | Haiku 5.5 | 비고 |
|---|---|---|---|---|
| 평균 정확도 (32개) | 83.2 | 88.9 | 85.4 | Luna 우세 10, 동률 5, Jev 우세 17 |
| 이진 AUROC 평균 (21개, halueval 제외) | 0.89 | 0.94 | 없음 | |
| 항목당 중앙 지연 | 0.56s | 0.27s | 2.4s | Haiku 는 적응형 thinking 포함 |
| 1k 판정 비용 | 0.055달러 | 0.035달러 | 0.07달러 | 입력 과금만. Haiku 는 출력까지 |
| 확률값 종류 | 100 | 98 | 없음 | Luna 는 0.01 단위 반올림 |

읽기.
- 우리 데이터 판정에서 Jev 가 Luna 를 크게 앞선 곳: sns-banban-review-hard 85 대 58, action-confirm-gate 97 대 72, derivation-check 83 대 65, guideline-compliance 85 대 68. 한국어 규칙 본문을 읽고 판정하는 과제들이다.
- Luna 가 앞선 곳: sns-stale-schedule 83 대 69, option-fit 90 대 85, answer-grounded-check 100 대 96. 수가 적다.
- Haiku 5.5 는 우리 한국어 own-data 에서 약하다. editorial-norm 62, option-fit 60, guideline-compliance 62, derivation-check 58 (Jev 97, 85, 85, 83). 라우터·게이트·분류류에서는 96~100 으로 셋이 같다.
- **질문 문구 함정.** halueval(「환각인가. ... 뒷받침되면 환각이 아니다」)에서 Luna 가 깨끗한 50건 중 49건을 「환각이다」로 답했다. 질문 끝 절을 술어로 읽은 것이다. 뒤집으면 83 이라 능력 문제가 아니다. Jev 와 Haiku 는 바르게 읽었다. 술어형(predicate) 모델에 넣는 질문은 마지막 문장이 묻는 쪽과 같은 극성이어야 한다.
- judge-pair(두 응답 중 맞는 쪽)는 Luna 44, Jev 47, Haiku 49 로 셋 다 동전 던지기이고 qwen 만 79 다. 위치 편향 검사가 필요하다(아래 4).

## 2. 소모 토큰까지 넣은 실제 비용

지금 결과의 `cost` 는 이렇게 센다.

| 팔 | 계산 | 빠진 것 |
|---|---|---|
| 로그확률 팔 (glm, qwen, deepseek) | 입력 토큰 × 단가 | 출력 1토큰. 무시해도 된다 |
| typed (jev, luna) | 엔드포인트의 `usage.cost` 그대로 | 없음. 출력 무료 |
| anthropic | 입력, 캐시 읽기, 캐시 쓰기, 출력 각각 단가 | 없음. thinking 토큰도 출력에 들어간다 |
| 라벨 이름 생성 (OpenRouter, 선택지 15개 이상) | 입력 토큰 × 단가 | 출력 10~20토큰. 1k 판정에 0.001달러 미만 |

Jev 류는 출력이 무료라 「입력 토큰 × 단가」가 곧 실제 비용이고 지금 집계가 맞다. 빠진 건 OpenRouter 라벨 이름 생성의 출력 토큰뿐이고 비용에 영향이 없다. 할 일은 결과 레코드에 `out_tok` 를 모든 팔에 남기는 것 하나다(코드만, 비용 0).

## 3. 다음에 돌릴 만한 것 (비용 순)

| # | 무엇 | 왜 | 어디에 | 비용 |
|---|---|---|---|---|
| 1 | 술어 문구 양극성 검사 | halueval 에서 본 Luna 의 뒤집힘이 다른 질문에도 있는지. 이진 질문 끝 절을 양성·음성 두 판으로 만들어 Luna, Jev 둘 다 | own-data 이진 8개, 5건씩 | 0.01달러 미만 |
| 2 | Jev 1.14 | 1.13 과의 차이. box 추가 외에 판정이 달라졌는지 | 32개 전부 | 0.07달러 |
| 3 | judge-pair 위치 편향 | A/B 순서를 바꿔 두 번 돌려 일치율. 셋 다 45~49 인 이유가 위치 편향인지 과제 난이도인지 | judge-pair 100건 × 2 | Luna, Jev 0.05달러, Haiku 0.1달러 |
| 4 | Haiku 5.5 자기보고 확신도 | `prob_source: verbalized` 로 따로 표시하고 AUROC·ECE 를 Jev, Luna 와 같은 표에 | 이진 21개 | 0.15달러 |
| 5 | 지연 p50·p90 표 | 결과에 ms 가 있으니 보고서에 열만 추가 | 전부 | 0 |
| 6 | Luna 직접 호출(OpenAI 키)과 OpenRouter 중계 비교 | 같은 가격이라 지연·확률 동일성만 | 2개 벤치 | 0.01달러 |
| 7 | Jev 긴 문맥 모드 | 32KB 넘는 state 에서 느리고 덜 정확하다는 안내. 우리 최장은 sns-numbers 2.2k 토큰이라 해당 없음 | 보류 | 0 |

하지 않을 것. Sonnet, Opus, Fable 전수 확장(사용자 지시, Haiku 5.5 만 추가 호출). Message Batches(우리 규모에서 이득 없음).

## 4. 근거 파일

- 결과: `results/<bench>-run.json` 의 `luna` 팔. 32개 목록은 own-data, synthetic-rules 전부와 banking77-router-mini, clinc50-router-mini, clinc150-router-mini, tool-call-gate-mini, tool-pick-mini, xstest-refusal-mini, aegis-prompt-safety-mini, halueval-qa-mini, judge-pair-mini.
- 러너 변경: `luna` 프리셋, `usage.cost` 사용, 해시 없는 구식 결과 병합(항목 id 일치 조건).
- 볼트: 「Claude API 라우터 실측 - Haiku 다지선택 261009」 끝 절.

# 로그확률 함정

1. **추론 토큰이 max_tokens 를 먹는다.** `reasoning: {enabled: false}` 가 없으면 로그확률이 「답」이 아니라 「생각의 첫 토큰」 분포가 된다. 에러가 없어 조용히 틀린다. 검증: 응답의 `completion_tokens_details.reasoning_tokens` 가 0 인지 본다
2. **provider 라우팅 누수.** `require_parameters: true` 만으로는 안 된다. `provider.only` 로 핀하고 `allow_fallbacks: false`
3. **`supported_parameters` 플래그를 믿지 않는다.** 모델·provider 단위 둘 다 틀렸다
4. **provider 별 정밀도와 재현성 (2026-09-30).** cloudflare 는 top_logprobs 를 거칠게 반올림해 벤치당 서로 다른 확률값이 10~15개뿐이다. 그 팔의 AUROC 가 0.5 근처인 건 모델이 아니라 provider 탓일 수 있다. digitalocean 은 temperature 0 에서도 같은 호출이 최대 0.13 흔들린다. 새 조합은 **같은 항목 3회 재호출 편차**와 **서로 다른 확률값 수**를 먼저 잰다
5. **첫 토큰이 라벨이 아닐 수 있다.** glm 은 「네」「**」로 문장을 시작하려 해 A·B 가 상위 8개에 없을 때가 있다(잔재 감사 88건 중 18건). 라벨 질량(`mass`)이 낮으면 그 항목은 오류로 두고 세지 않는다

검증된 조합표는 `results/or_verified.json`.

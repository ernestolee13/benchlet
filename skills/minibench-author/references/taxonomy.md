# 분류 체계 (올릴 때와 찾을 때 같은 말)

정본은 리포의 `registry/taxonomy.yaml` 이고 MCP `bench_taxonomy` 가 같은 것을 돌려준다. 벤치마다 다섯 축과 키워드를 매니페스트에 적는다. 어휘 밖이면 `benchlet validate` 가 경고한다(막지는 않는다). 새 어휘가 필요하면 taxonomy.yaml 에 한 줄 제안한다.

## 다섯 축

| 축 | 값 | 어디에 |
|---|---|---|
| goal | compliance · classify · route · derive · gate · fit · rank | `task_signature.goal` (서명 5축의 하나) |
| domain | customer-support, content-moderation, editorial, code-review, data-quality, agent-tools, browser-automation, retrieval-rag, security, communication, scheduling, knowledge-exam, commonsense, truthfulness, legal, finance-ops, survey-design, product-ops | `taxonomy.domain` (1~3개) |
| input_kind | sentence · paragraph · pair · record · query · page-tree · conversation · document | `taxonomy.input_kind` |
| source_kind | own-data(내 데이터, 라벨 경로 1·2) · public-distilled(공개 벤치 축약) · synthetic-rules(규칙을 적고 작성) | `taxonomy.source_kind` |
| language | ko · en · mixed | `taxonomy.language` |

## 키워드

`keywords` 는 2~5개. 시작 목록의 정규형을 먼저 쓴다(환불, 스팸, 에스컬레이션, 분류, 라우팅, 확인 게이트, SQL, 스키마, 커밋 메시지, 코드 리뷰, RAG, 환각, 중복, 우선순위, 일정, 편집 규범, 잔재, 수치 근거, 정합, 지침 준수, 상식, 시험, 사실성, 브라우저, 메일, 고객 문의, 댓글, 승인 큐, 뉴스 요약, 설문 문항). 동의어는 taxonomy.yaml 에 있고 검색이 같은 말로 본다(환각 = hallucination = grounded). 목록에 없는 말은 그대로 적되 영어·한국어 중 하나로 통일한다.

## 발견 단계에서 쓰는 법

- 후보마다 서명 5축을 적을 때 domain 과 keywords 도 같이 적는다. 그래야 `bench_similar(question, signature)` 와 `bench_search(domain=…, keywords=[…])` 가 비슷한 벤치를 찾는다.
- 사용자가 「우리 고객센터 문의 분류」라고 하면 domain customer-support, keywords [고객 문의, 분류] 로 먼저 검색해 포크 후보를 보여 준다. 같은 영역에 공개 벤치 축약본(public-distilled)이 있으면 「내 데이터로 만들기 전에 이걸로 모델을 먼저 걸러 보라」고 권한다.
- 게시 직전 `bench_taxonomy` 어휘로 레이블을 확인한다. 경고가 남으면 가까운 값으로 바꾸거나 taxonomy.yaml 에 제안을 적고 사용자에게 알린다.

## 검색 예

```
bench_search(query="환각")                          # 동의어 확장: hallucination, grounded, 근거 있음
bench_search(domain="agent-tools")                  # 도구 선택·확인 게이트·SQL 게이트
bench_search(signature={"goal": "route"}, keywords=["라우팅"])
bench_similar(question="이 문의를 어느 팀으로 보내야 하는가", signature={"goal": "route", "unit": "record"})
```

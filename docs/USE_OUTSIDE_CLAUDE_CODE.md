# Claude Code 밖에서 쓰기

benchlet 은 세 겹이다. 어느 겹부터 써도 된다.

| 겹 | 무엇 | 어디서 되나 |
|---|---|---|
| CLI | `bench-core/bin/benchlet` (validate, review, run, publish, submit, star, distill, site) | 셸이 있는 곳 어디든. Python 3.9 이상, pyyaml 하나 |
| MCP 서버 | `python3 -m benchlet.cli mcp` (stdio, 의존성 없음, bench_* 툴 23개) | MCP 를 붙일 수 있는 에이전트 전부. Claude Code, Codex CLI, Cursor, Windsurf, Gemini CLI, 자체 에이전트 |
| 스킬 | `skills/minibench-author/SKILL.md` + `references/` (발견, 계획, 질문 작성, 형식, 검수 점검표, 실행 요건, 분류 어휘, 공개 시드) | 마크다운 지시문이라 어떤 에이전트의 시스템 프롬프트나 AGENTS.md 에도 넣을 수 있다 |

## 1. CLI 만

```bash
git clone https://github.com/ernestolee13/benchlet && cd benchlet
bench-core/bin/benchlet validate benches/example
bench-core/bin/benchlet review --bench benches/example
bench-core/bin/benchlet run --bench benches/example --arms custom:<model>   # 아래 키 설정
bench-core/bin/benchlet publish --bench benches/example --github           # gh 로그인 계정의 benchlet-benches 리포로
```

키는 환경변수 또는 `~/.config/benchlet/env`(`BENCHLET_ENV_FILE` 로 바꿀 수 있다)에서 읽는다.

```
OPENROUTER_API_KEY=...          # OpenRouter 예시 모델(glm, qwen, deepseek, jev)을 쓸 때
BENCHLET_BASE_URL=https://.../v1   # custom:<model> 을 쓸 때. 첫 토큰 로그프롭을 주는 OpenAI 호환 엔드포인트
ANTHROPIC_API_KEY=...              # anthropic:<model> 을 쓸 때. 로그프롭 없이 생성·라벨 팔로 돈다
BENCHLET_API_KEY=...
```

## 2. MCP 서버로 붙이기

서버는 표준 입출력 JSON-RPC 하나다. 어떤 클라이언트든 아래 한 줄을 등록하면 된다.

```json
{"command": "python3", "args": ["-m", "benchlet.cli", "mcp"],
 "env": {"PYTHONPATH": "/path/to/benchlet/bench-core", "BENCHLET_ROOT": "/path/to/your/project"}}
```

- Codex CLI: `codex mcp add bench -- env PYTHONPATH=/path/to/benchlet/bench-core BENCHLET_ROOT=$PWD python3 -m benchlet.cli mcp` (버전에 따라 `~/.codex/config.toml` 의 `[mcp_servers.bench]` 에 같은 command/args/env 를 적는다)
- Cursor, Windsurf: 프로젝트의 `.cursor/mcp.json` 또는 `.windsurf/mcp.json` 의 `mcpServers.bench` 에 위 JSON
- Gemini CLI: `~/.gemini/settings.json` 의 `mcpServers.bench`
- 자체 에이전트: stdio 로 띄우고 `tools/list`, `tools/call` 을 쓴다. 스키마는 `bench_taxonomy`, `bench_search`, `bench_similar`, `bench_fork`, `bench_create`, `bench_add_items`, `bench_validate`, `bench_review`, `bench_run`, `bench_publish`, `bench_submit_result`, `bench_star` 순으로 보면 흐름이 잡힌다.

`BENCHLET_ROOT` 는 벤치가 만들어질 프로젝트 루트다. 검색은 로컬 레지스트리와 공개 갤러리(benchlet.vibestash.app, 하루 캐시)를 같이 본다. 오프라인이면 `BENCHLET_OFFLINE=1`.

## 3. 스킬을 다른 에이전트에 넣기

`skills/minibench-author/SKILL.md` 는 Claude Code 전용 문법이 거의 없다. 다른 에이전트에서는 이렇게 쓴다.

- 시스템 프롬프트나 `AGENTS.md`, `.cursorrules` 에 `SKILL.md` 본문을 넣고, `references/` 폴더를 프로젝트 안에 두어 에이전트가 읽게 한다.
- 「AskUserQuestion」은 그 에이전트의 질문 방식으로 바꿔 읽으면 된다(선택지를 주고 사용자가 고른다). 「bench_* 툴」은 MCP 를 붙였으면 그대로, 아니면 SKILL.md 의 CLI 대응표대로 셸 명령을 부른다.
- 산출 위치(`src/build_<bench>.py`, `tasks/<bench>.jsonl`, `tasks/<bench>.manifest.yaml`, `discovery/`)는 그대로 둔다. 갤러리와 검수 도구가 그 위치를 본다.

## 4. 호출 흐름 요약

1. 사용자가 「이 프로젝트 기준으로 나만의 벤치 만들어 줘」라고 한다.
2. 에이전트가 `bench_similar`/`bench_search` 로 갤러리를 먼저 본다. 비슷한 게 있으면 포크할지 묻는다.
3. 판정 지점 후보, 라벨 경로와 항목 수를 묻고 생성기와 항목을 만든다. `bench_validate`, `bench_review`.
4. 게시 대상을 묻는다(로컬 / GitHub 비공개 / 공개). `bench_publish`.
5. 실행은 선택이다. 키가 있으면 `bench_run`. 남의 벤치에 돌렸으면 `bench_submit_result`, 쓸모 있었으면 `bench_star` 를 묻는다.

# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)

[`@evomap/evolver`](https://github.com/EvoMap/evolver)의 **Python 3.12+ 포트** — GEP 기반 AI 에이전트 자기 진화 엔진.

Node.js 레퍼런스 구현(v1.89.11)과의 **완전한 동작 동등성**을 목표로 하며, 현대적인 Python 도구 체인을 사용합니다.

## 빠른 시작

```bash
uv sync
uv run evolver              # 단일 진화 사이클
uv run evolver --loop       # 데몬 루프
uv run evolver --review     # 리뷰 모드
uv run evolver webui        # WebUI 대시보드
uv run evolver proxy        # 로컬 A2A 프록시
```

## 주요 기능

- **GEP 프로토콜** — 감사 가능한 진화 자산(Gene / Capsule / Event)
- **7단계 진화 파이프라인** — collect → signals → hub → enrich → autopoiesis → select → dispatch
- **멀티 프로바이더 프록시** — Anthropic / Bedrock / Gemini / Vertex / Ollama / OpenAI (9개 라우트)
- **ATP 마켓플레이스** — 15개 CLI 서브커맨드(buy / sell / settle / dispute)
- **IDE 통합** — Cursor / Claude Code / Codex / Kiro / opencode 런타임 훅
- **Autopoiesis** — SelfReport + 항상성 + 자가 수리 (Python 오리지널 기능)

## 설치

### 필요 조건

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- Anthropic API 키 (또는 호환 프로바이더)

### 개발 환경 설정

```bash
git clone https://github.com/EvoMap/evolver.py.git
cd evolver.py
uv sync
```

### 환경 변수

```bash
# .env 파일 (레포지토리 루트)
ANTHROPIC_API_KEY=sk-ant-...
A2A_HUB_URL=https://evomap.ai          # Hub 엔드포인트
EVOLVER_NO_PARENT_GIT=1                # 상위 .git 무시
OPENCLAW_WORKSPACE=/path/to/project    # 워크스페이스 루트
```

## 명령어 참조

| 명령어 | 설명 |
|--------|------|
| `uv run evolver` | 단일 진화 사이클 |
| `uv run evolver --loop` | 데몬 루프 |
| `uv run evolver --review` | 리뷰 모드 |
| `uv run evolver --solo` | 완전 오프라인 모드 |
| `uv run evolver solidify` | 보류 중인 변이 적용 |
| `uv run evolver start / stop / restart / status` | 데몬 라이프사이클 |
| `uv run evolver log` | 데몬 로그 표시 |
| `uv run evolver check / watch` | 헬스 모니터링 |
| `uv run evolver webui` | WebUI 대시보드 |
| `uv run evolver proxy` | A2A 프록시 시작 |
| `uv run evolver proxy-token` | 프록시 토큰 발행 |
| `uv run evolver setup-hooks --platform cursor` | IDE 훅 설치 |
| `uv run evolver self-report` | Autopoiesis 자가 진단 |
| `uv run evolver distill` | LLM 응답 증류 |
| `uv run evolver fetch <query>` | Hub에서 자산 가져오기 |
| `uv run evolver publish <id>` | Hub에 게시 |
| `uv run evolver sync` | Hub와 동기화 |
| `uv run evolver asset-log` | 자산 호출 로그 |
| `uv run evolver recipe list / show / apply` | 레시피 관리 |
| `uv run evolver skill2recipe` | 스킬을 레시피로 변환 |
| `uv run evolver atp balance / buy / orders / verify` | ATP 마켓플레이스 |

## 예제

| 예제 | 설명 |
|------|------|
| [`examples/hello-world/`](examples/hello-world/) | 단일 진화 사이클 |
| [`examples/daemon-loop/`](examples/daemon-loop/) | 데몬 루프와 라이프사이클 관리 |
| [`examples/proxy-basics/`](examples/proxy-basics/) | 프록시 설정과 curl API 예제 |
| [`examples/ide-hooks/`](examples/ide-hooks/) | 5개 플랫폼용 IDE 훅 |
| [`examples/solo-mode/`](examples/solo-mode/) | 완전 오프라인 격리 모드 |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis 자가 진단 보고서 |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | 증류→재사용→게시 생명주기 |
| [`examples/skill2recipe/`](examples/skill2recipe/) | 스킬→레시피 합성 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP 마켓플레이스 데모 |

## 프로젝트 구조

```
evolver.py/
├── src/evolver/
│   ├── cli.py              # CLI 진입점
│   ├── config.py           # 런타임 설정
│   ├── gep/                # GEP 코어 (유전자, 캡슐, 프로토콜)
│   ├── evolve/             # 진화 파이프라인
│   ├── proxy/              # A2A 프록시
│   ├── webui/              # WebUI 대시보드
│   ├── ops/                # 운영 도구 (헬스, 수리, 트리거)
│   ├── atp/                # 에이전트 거래 프로토콜
│   └── adapters/           # IDE 훅 어댑터
├── tests/
├── examples/               # 실습 가이드 (모든 기능 커버)
└── docs/                   # 설계 문서와 로드맵
```

## 테스트

```bash
uv run pytest tests/ -q                    # 전체 테스트
uv run pytest -m "not slow" -q             # CI용 (느린 테스트 제외)
uv run ruff check src tests                # 린트
uv run mypy src                            # 타입 체크 (strict)
```

## 문서

- [README.md](README.md) — English
- [README.zh.md](README.zh.md) — 中文
- [README.ja-JP.md](README.ja-JP.md) — 日本語
- [SKILL.md](SKILL.md) — AI 에이전트용 스킬 정의
- [CONTRIBUTING.md](CONTRIBUTING.md) — 기여 가이드
- [AGENTS.md](AGENTS.md) — AI 에이전트 참조
- [设计方案.md](设计方案.md) — 설계 문서 (중문)
- [TODO.md](TODO.md) — 갭 분석과 로드맵
- [演进方案.md](演进方案.md) — v1.89.11 추적 계획 (중문)

## 라이선스

Apache-2.0 — 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.

# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://opensource.org/licenses/GPL-3.0)

[`@evomap/evolver`](https://github.com/EvoMap/evolver)의 **Python 3.12+ 포트** — GEP 기반 AI 에이전트 자가 진화 엔진.

Node.js 참조 구현(v1.89.11)과의 **완전한 동작 등가성**을 목표로 하며, 현대적인 Python 도구 체인을 사용합니다.

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

- **GEP 프로토콜** — 감사 가능한 진화 자산 (Gene / Capsule / Event)
- **7단계 진화 파이프라인** — collect → signals → hub → enrich → autopoiesis → select → dispatch
- **멀티 프로바이더 프록시** — Anthropic / Bedrock / Gemini / Vertex / Ollama / OpenAI (9 라우트)
- **ATP 마켓플레이스** — 15개 CLI 서브커맨드 (buy / sell / settle / dispute)
- **IDE 통합** — Cursor / Claude Code / Codex / Kiro / opencode 런타임 훅
- **Autopoiesis** — SelfReport + 항상성 + 자가 수리 (Python 오리지널 기능)

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
- [设计方案.md](设计方案.md) — 설계 문서 (中文)
- [TODO.md](TODO.md) — 갭 분석 및 로드맵
- [演进方案.md](演进方案.md) — v1.89.11 추적 계획 (中文)

## 라이선스

[GPL-3.0-or-later](LICENSE)

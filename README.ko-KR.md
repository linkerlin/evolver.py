# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · [简体中文](README.zh.md) · [日本語](README.ja-JP.md) · **한국어**

**GEP(Genome Evolution Protocol) 기반 AI 에이전트 자기 진화 엔진.**

---

## 📖 개요: 복리적 성장을 향한 에이전트 자기 진화

대규모 언어 모델(LLM)을 활용한 소프트웨어 엔지니어링 환경에서, 기존 코딩 에이전트는 흔히 **"단발성 추론에 머무는 기억의 부재, 검증된 전략 패턴의 축적 실패, 엄격한 진화 판정 기준의 결여"**라는 병목에 직면합니다. 기존 도구는 개별 코드 패치를 작성할 수는 있지만, 과거의 마찰 지점으로부터 자율적으로 학습하거나 인간의 지속적인 개입 없이 전략 자산을 점진적으로 개선해 나가지 못합니다.

**`evolver.py`는 이러한 한계를 극복하기 위해 탄생했습니다.**

본 프로젝트는 **GEP(게놈 진화 프로토콜)** 기반의 AI 에이전트 자율 진화 시스템입니다. 코드 저장소 및 런타임 진단 로그에서 마찰 신호(Signals)를 감지하고, 최적의 변이 전략(Gene)을 매칭·디스패치하여 외부 호스트 에이전트가 코드 수정을 수행하도록 유도합니다. 이후 엄격한 샌드박스 검증과 과학적 대조 절제(Ablation) 실험을 거쳐 검증된 성공 경험만을 재사용 가능한 "유전자(Gene)"와 "캡슐(Capsule)"로 영속화하여 지속적인 복리적 발전을 실현합니다.

### 핵심 설계 철학

1. **엔진은 자체 LLM 스케줄링을 하지 않는다: 호스트 에이전트가 곧 실행기**  
   `evolver.py`는 자체적인 독점 LLM 추론 스케줄러를 내장하지 않습니다. 대신 표준 **MCP (Model Context Protocol) stdio** 인터페이스를 통해 연결된 호스트 에이전트(Cursor, Claude Code, Codex, ZCode 등)를 직접 진화의 "실행기"로 인수합니다. 호스트가 보유한 도구 호출 능력과 작업 공간 컨텍스트가 정밀한 수술 도구가 되며, 엔진은 신호 감지, 전략 수립, 안전 거버넌스에 집중합니다.

2. **경험이 곧 증거다 (Experience as Evidence)**  
   최신 자율 연구 프로토콜(*arXiv:2609.37968v2, SelfSearch*)에 발맞추어, 에이전트의 실제 자기 개선 실행 기록(**Episode Record**)을 일등 증거 소스로 격상합니다. 맹목적인 무작위 변이나 신뢰하기 어려운 자체 채점을 배제하고, 통제된 대조 실험과 표본 크기 충족성 감사를 통과한 전략만을 승격합니다.

3. **현대적인 클린룸 Python 아키텍처**  
   공개 규격 및 테스트 규약에 기초하여 `@evomap/evolver`의 동작을 동등하게 구현한 독립적인 클린룸 Python 프로젝트입니다. 최신 스택(Python 3.12+, `asyncio`, `uv`, `Pydantic v2`, `httpx`, `FastAPI`)을 바탕으로 구축되었으며, 유연하고 친화적인 **Apache-2.0** 라이선스로 배포됩니다.

---

## 🏛️ 시스템 아키텍처 및 진화 루프

`evolver.py`는 7단계 비동기 파이프라인, 체계적인 GEP 데이터 모델, 그리고 심층 안전 방어 체계를 바탕으로 유기적으로 동작합니다.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      evolver.py 진화 수명 주기 루프                    │
└────────────────────────────────────────────────────────────────────────┘

  [ 런타임 로그 / 저장소 텔레메트리 / 테스트 실패 ]
                         │
                         ▼
             ┌───────────────────────┐
             │   1. Collect (수집)   │ ── 진단 트레이스 및 살아있는 기억(Living Memory) 스캔
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   2. Signals (신호)   │ ── 오류 및 성능 병목을 구조화된 신호로 분류
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   3. Hub Sync (동기)  │ ── 분산 Hub에서 매칭되는 후보 자산 및 태스크 검색
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   4. Enrich (인지강화)│ ── 기억 그래프와 실패 이력을 결합하여 문맥 보강
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │ 5. Autopoiesis (자생) │ ── 항상성을 평가하고 빈발 마찰을 방어 규칙으로 부호화
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   6. Select (선택)    │ ── 복구 편향과 탐색성을 반영하여 변이 유전자 선택
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │  7. Dispatch (발송)   │ ── 근거 중심의 구조화된 GEP 변이 프롬프트 생성
             └───────────┬───────────┘
                         │
                         ▼  (MCP stdio 채널)
             ┌───────────────────────┐
             │ 호스트 Agent (실행기) │ ── Cursor / Claude Code가 코드베이스 수정
             └───────────┬───────────┘
                         │
                         ▼
             ┌───────────────────────┐
             │ 가설 선언 & 게이트 검증│ ── 단일 검증 가설 선언 ➔ 샌드박스 테스트 통과 여부
             └───────────┬───────────┘
                         │
                    [ 검증 통과 ]
                         │
                         ▼
             ┌───────────────────────┐
             │ Solidify (고착 및 정착)│ ── Git 커밋 ➔ 유전자 수명 주기 승격 ➔ 피드백 자가적응
             └───────────────────────┘
```

### 1. 7단계 진화 파이프라인

각 진화 사이클은 완전히 분리된 7개의 비동기 단계로 실행됩니다:
- **Collect**: 로컬 런타임 로그 분석, 실패 진단 기록 조사, `LESSONS_LEARNED.md`(살아있는 기억) 로딩.
- **Signals**: 원시 데이터에서 구조화된 신호(예: `log_error`, `perf_bottleneck`, 종속성 드리프트) 추출.
- **Hub**: 로컬 또는 원격 Hub 네트워크와 통신하여 적합한 기존 자산 및 협동 태스크 탐색.
- **Enrich**: 기억 그래프와 양방향 동기화, 과거의 개입 결과와 교훈 주입.
- **Autopoiesis(자기 재생산 및 항상성)**: 빈발하는 개발 마찰을 가드 규칙으로 자동 인코딩하여 시스템 안전성 유지.
- **Select**: 후성유전학적 친화도를 평가하여 복구 편향(Repair Bias)과 신규 탐색의 균형 조율.
- **Dispatch**: 풍부한 증거가 포함된 GEP 변이 프롬프트를 조립하여 호스트 에이전트에 전달.

### 2. GEP 핵심 자산 모델

- **Gene(유전자)**: 재사용 가능한 추상 변이 전략으로, "어떤 신호 패턴(`signals_match`)에서 어떤 코드 개입(`execution_trace`)을 적용할지"를 정의.
- **Capsule(캡슐)**: 특정 입력, 생성된 diff, 실제 실행 결과(성공/실패)를 보존하는 구체적 변이 인스턴스.
- **Epigenetics(후성유전학적 조절)**: 최근의 환경 피드백을 기반으로 특정 유전자를 동적으로 억제하거나 활성화하여 국소 진동 방지.
- **Gene Lifecycle(유전자 수명 주기 관리)**: 유전자를 `active`, `under_review`, `retired`의 3단계 상태 머신으로 관리하여 성과가 없는 유전자를 자동 격리.

### 3. 이중 안전 보호 체계 (HITL + HOTL)

코드를 자체 수정하는 시스템인 만큼, 다층적인 안전망을 기본 탑재하고 있습니다:
- **HITL (Human-In-The-Loop 승인 게이트)**: 검증을 우회하거나 파급력이 큰 고위험 변이(`solidify`)는 실행을 멈추고 인간 운영자의 승인을 대기합니다. 전역 감사 로그와 안전 우선(Fail-Safe) TTL 타임아웃을 지원합니다.
- **HOTL (Human-On-The-Loop 실시간 감독)**: 진행 중인 루프를 실시간으로 모니터링합니다. 언제든지 일시 중지/재개(`pause`/`resume`), 특정 패턴 거부(`veto`), 방향성 지시(`directive`)를 하달할 수 있습니다. 품질 저하가 연속 감지되면 안전 차단선이 작동하여 자동으로 루프를 멈춥니다.

---

## ⚡ 주요 기능

### 🐝 MCP 군집 진화 (호스트 에이전트 인수)
표준 stdio MCP 서버로 동작하여 Cursor, Claude Code 등의 IDE를 진화 루프의 실행 엔진으로 직접 전환합니다. 엔진이 의사결정과 제약을 생성하고, 호스트가 정밀한 코드 수정을 담당합니다. 도구에 안전 어노테이션(`readOnlyHint`, `destructiveHint`)이 지정되어 있어 투명하고 안전한 무인 자율 운용이 가능합니다.

### 🌉 스킬 생태계 브리지 (Skill Ecosystem Bridge)
기존 에이전트 생태계의 스킬 자산(`SKILL.md`)을 그대로 흡수합니다. **프로젝트 > 사용자 > 내장** 우선순위에 따라 스킬을 자동 스캔하고 GEP 유전자로 증류하여 즉각 신호 매칭 및 변이 후보군으로 편입합니다.

### 📋 영속적 워크플로 엔진 (협력의 데이터화)
복잡한 소프트웨어 엔지니어링 작업을 버전 관리 가능한 선언적 YAML 워크플로로 정의합니다. 에이전트 태스크 수행, 자동화된 검증 캐스케이드(ruff ➔ mypy ➔ pytest), 인간 승인 게이트를 결합할 수 있습니다. WAL(Write-Ahead Log)과 스냅샷을 기반으로 작동하므로 중단 시에도 안전하게 복구·재개됩니다.

### 🔬 엄격한 대조 절제 실험 (Controlled Ablation Suite)
인위적인 점수 상승을 철저히 차단하는 엄격한 과학적 평가 체계:
- **위약 대조군 (`--placebo`)**: 동일한 길이의 중립적 문맥을 주입하여 프롬프트 길이나 역할 편향을 격리.
- **단계 출구 규약 (`--stage-exit`)**: 실제 에피소드, 대조군, 고정 커밋, 디스크 보고서가 모두 충족되어야만 검증으로 인정. 표본 크기 감사(`MIN_N=30`)를 강제하여 소표본 왜곡을 방지.
- **평가 하네스 무단 변경 방지**: 변이 로직이 자체 평가 기준을 변경하지 못하도록 정적 화이트리스트로 보호.

---

## 🚀 빠른 시작

### 사전 준비

- **Python >= 3.12**
- **[Git](https://git-scm.com/)** (필수: 파급 반경 통제, 스테이징, 원자적 롤백 지원에 사용)
- **[uv](https://docs.astral.sh/uv/)** (권장되는 초고속 Python 패키지 매니저)

```bash
# 저장소 복제 및 의존성 동기화
git clone https://github.com/evomap/evolver.py.git
cd evolver.py
uv sync
```

### 기본 실행

```bash
# 1회 자율 진화 사이클 실행
uv run evolver run

# 지속적 자율 진화 데몬 루프 실행
uv run evolver --loop

# 리뷰 모드 실행 (변이 후 인간 승인 대기)
uv run evolver --review

# 시스템 상태 점검
uv run evolver check
```

> **UI 및 프록시 서비스**: WebUI 대시보드 또는 로컬 A2A 프록시를 실행하려면 `server` 엑스트라 의존성을 설치합니다:
> ```bash
> uv sync --extra server
> uv run evolver webui   # http://127.0.0.1:8080 대시보드 오픈
> uv run evolver proxy   # 8081 포트에서 로컬 A2A 프록시 시작
> ```

---

## 🛠️ 호스트 에이전트 연결 (MCP 설정)

`evolver.py`를 MCP 서버로 등록하여 호스트 에이전트가 변이 실행기로 작동하도록 설정합니다.

### 1. 호스트 MCP 설정 예시

**Cursor**(`.cursor/mcp.json`) 및 **Claude Code**(`.mcp.json`):

```json
{
  "mcpServers": {
    "evolver": {
      "command": "uv",
      "args": ["--project", "/절대경로/to/evolver.py", "run", "evolver", "mcp"]
    }
  }
}
```

**ZCode** 또는 가상환경 Python 직접 지정 시:

```json
{
  "mcpServers": {
    "evolver": {
      "command": "/절대경로/to/evolver.py/.venv/bin/python",
      "args": ["-m", "evolver.mcp_server"],
      "env": {
        "EVOLVER_SWARM_AUTO_HIJACK": "0"
      }
    }
  }
}
```

### 2. 폐쇄 루프 프로토콜 흐름

연결된 호스트 에이전트는 표준 도구 체계를 통해 협력합니다:
1. `swarm_boot`: 세션 초기화 및 상태 보고.
2. `swarm_tick`: 최신 GEP 변이 프롬프트 및 문맥 획득.
3. *(호스트가 에디터에서 파일 수정 및 리팩터링 수행)*
4. `swarm_distill`: 변경 사항으로부터 구조화된 Gene 및 Capsule 추출.
5. `swarm_hypothesis`: 검증 전 해당 사이클의 유일한 과학적 가설 선언.
6. `swarm_solidify`: 샌드박스 게이트를 거쳐 검증된 변경 사항을 Git 커밋으로 고착.
7. `swarm_feedback`: 다차원 평가 지표를 반환하여 후속 사이클의 가중치 자가적응 유도.

### 3. 원클릭 데모 스크립트

```bash
# 1. 결정적 시뮬레이션 데모 (LLM API 키 불필요)
uv run python examples/swarm-quickstart/demo_swarm_loop.py

# 2. 완전 폐쇄 루프 데모
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py

# 3. DeepSeek를 통한 실제 호스트 실행
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm
```

---

## 🧭 체계적인 CLI 명령 매트릭스

역할과 수명 주기에 따라 분류된 명령 일람:

| 영역 | 명령어 | 설명 |
|---|---|---|
| **진화 제어** | `evolver run` | 단일 자율 진화 사이클 실행 (기본 동작) |
| | `evolver --loop` | 지속적 자율 진화 백그라운드 데몬 구동 |
| | `evolver --review` | 변이 적용 전 확인을 거치는 대화형 리뷰 모드 |
| | `evolver solidify` | 대기 중인 변이를 검증하고 Git 저장소에 확정 커밋 |
| | `evolver session` | 쌍체 진화 세션 및 가설 게이트 관리 |
| **군집 및 안전** | `evolver mcp` | stdio 기반 MCP 서버 실행 (호스트 연결 접점) |
| | `evolver hitl` | 인간 참여(HITL) 승인 관리 (`list`/`approve`/`reject`) |
| | `evolver supervise` | 인간 감시(HOTL) 실시간 감독 (`status`/`pause`/`resume`/`veto`) |
| | `evolver setup-hooks` | Cursor, Claude Code 등 IDE 자동 텔레메트리 훅 설치 |
| **자산 및 지식** | `evolver skills` | 외부 `SKILL.md` 스캔, 미리보기 및 GEP 유전자 동기화 |
| | `evolver gene-lifecycle`| 유전자 수명 주기 관리 (`active`/`under_review`/`retired`) |
| | `evolver episode` | 과거 자기 개선 실행 기록(Episode Record) 조회 |
| | `evolver self-report` | 자생(Autopoiesis) 시스템 진단 및 방어 규칙 갱신 |
| **벤치 및 평가** | `evolver experiment` | 엄격한 대조 절제 실험 수행 (`--ablation`, `--placebo`) |
| | `evolver bench` | 동결 벤치마크 태스크 팩 실행, 베이스라인 검증 및 통계 검정 |
| | `evolver gate-report` | 수용 게이트(Shadow Gate) 숙성 관찰 및 정식 채택 보고서 |
| | `evolver meta-report` | 진화 메커니즘 텔레메트리 및 후대 변이 품질 보고서 |
| **운영 및 서비스** | `evolver check` / `watch`| 시스템 상태 진단 및 지속적 모니터링 |
| | `evolver start` / `stop` | 크로스 플랫폼 데몬 수명 주기 제어 |
| | `evolver webui` | 로컬 시각화 대시보드 구동 (`server` 필요) |
| | `evolver proxy` | 로컬 분산 A2A 프록시 구동 (`server` 필요) |

---

## 🔒 보안 모델 및 엔지니어링 가드레일

`evolver.py`는 코드를 자체 수정하므로 엄격한 보안 장치가 전 과정에 걸쳐 가동됩니다:

- **Git 파급 반경 통제**: 모든 코드 변경은 Git 기반으로 격리됩니다. 변이 전 `git stash`로 안전 스냅샷을 생성하며, 유전자별 파일 변경 수(`constraints.max_files`)와 금지 경로(`forbidden_paths`)를 엄격히 제한합니다. 검증 실패 시 즉시 원자적 롤백이 수행됩니다.
- **콘텐츠 주소 지정 및 무결성 검증**: 모든 자산 ID는 SHA-256 다이제스트(`sha256:...`)를 포함하며, 무단 변조되거나 손상된 자산은 로딩 시 자동으로 배제됩니다.
- **자격 증명 마스킹**: 전용 필터링 엔진이 작동하여 API 키, JWT, 비밀번호 등이 디스크 로그나 프롬프트, WebUI 스트림에 평문으로 노출되지 않도록 철저히 마스킹합니다.
- **OS 수준의 인스턴스 잠금**: 네이티브 OS 잠금 메커니즘(`instance_lock.py`)을 통해 동일 저장소에 대한 복수 데몬의 동시 쓰기 및 상태 경합을 원천 차단합니다.

---

## 🗺️ 프로젝트 디렉터리 안내

```
src/evolver/
├── cli.py                  # CLI 엔트리포인트, 인자 파싱 및 명령 분기
├── config.py               # 중앙 설정, 임계치 정의 및 환경 변수 매핑
├── swarm.py                # 군집 프로토콜: 인수 프롬프트 조립 및 디스패치 제어
├── mcp_server.py           # stdio MCP 서버 구현 (공용/군집 도구 및 리소스)
├── evolve/                 # 핵심 진화 오케스트레이션
│   ├── runner.py           # 사이클 제어기 및 데몬 루프 실행기
│   ├── guards.py           # 사전 비행 점검 (부하, 메모리, 환경 무결성)
│   └── pipeline/           # 7단계 비동기 진화 파이프라인 (Collect ~ Dispatch)
├── gep/                    # GEP(게놈 진화 프로토콜) 핵심 엔진
│   ├── schemas/            # Pydantic 데이터 스키마 (Gene, Capsule, Task 등)
│   ├── asset_store.py      # 계층형 JSON/JSONL 자산 영속화 저장소
│   ├── hitl.py             # 인간 참여(HITL) 의사결정 게이트
│   ├── supervision.py      # 실시간 감독 및 자동 차단선(HOTL)
│   ├── skill_assets.py     # 스킬 생태계 브리지 및 유전자 증류기
│   ├── gene_lifecycle.py   # 유전자 수명 주기 상태 머신 거버넌스
│   └── solidify.py         # 변이 적용, 샌드박스 검증 및 Git 고착 커밋
├── bench/                  # 동결 태스크 팩, 평가기 및 통계 검정 도구
├── experiment/             # 통제 절제 실험 스위트 (위약 대조군, 표본 충족성 감사)
├── adapters/               # IDE 통합 훅 (Cursor, Claude Code, Codex 등)
├── proxy/                  # 로컬 A2A 분산 프록시 및 모델 라우팅
└── webui/                  # 읽기 전용 시각화 대시보드 및 SSE 이벤트 스트림
```

---

## 📚 관련 문서 및 개발 안내

- **[演进方案.md](演进方案.md)**: 현행 최상위 헌장 문서. "경험이 곧 증거"로 나아가는 완전한 논리 체계 (중국어).
- **[AGENTS.md](AGENTS.md)**: AI 코딩 에이전트 개발자를 위한 행동 강령, 주의사항 및 아키텍처 상세.
- **[DEBUG.md](DEBUG.md)**: 프로세스 락, 경합 조건, 복합 엣지 케이스 해결을 위한 현장 디버깅 가이드.
- **[CHANGELOG.md](CHANGELOG.md)**: 상세 릴리스 및 마일스톤 이력.
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: 기여 가이드 및 테스트 규약.

---

## 📄 라이선스

본 프로젝트는 [Apache License 2.0](LICENSE) 라이선스에 따라 공개 배포됩니다.

> **계보에 관한 안내**: `evolver.py`는 공개 규격과 테스트 규약에 기초하여 독자적으로 개발된 클린룸 Python 구현체입니다. 원래의 개념적 영감은 EvoMap 조직의 작업에 기반하며, 본 프로젝트는 Apache-2.0 라이선스로 독립적으로 유지 관리 및 배포됩니다.

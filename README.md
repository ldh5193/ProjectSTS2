# 슬레이어 더 스파이어 2 강화학습 AI 에이전트 프로젝트 기획안
**Slay the Spire 2 Reinforcement Learning AI Agent Project Plan**

---

## 1. 프로젝트 개요 (Project Overview)

### 1.1 배경 및 목적
- **배경**: 슬레이어 더 스파이어 2(Slay the Spire 2)는 Godot 4 엔진(C#) 기반으로 새롭게 재구축되어 전작 대비 한층 더 복잡해진 게임 메커니즘과 상태 공간(State Space)을 가집니다.
- **목적**: 턴제 로그라이크 덱빌딩 장르의 특성을 극복하고, 고도의 전략적 판단을 내릴 수 있는 **강화학습(Reinforcement Learning) 기반의 자동 플레이 AI 에이전트**를 구축합니다.
- **핵심 도전 과제**: 실시간 화면 렌더링에 의존하는 학습 방식의 속도 한계를 극복하고, 유동적인 핸드 카드 및 마나 제약 조건하에서 '불법 행동'을 원천 차단하는 효율적인 학습 파이프라인을 설계합니다.

### 1.2 개발 전략 (Two-Phase Strategy)
1. **Phase 1 (고속 학습)**: 실제 게임을 구동하지 않고 Memory 상에서 게임 로직만 연산하는 **Python 기반 헤드리스 시뮬레이터(Headless Simulator)** 구축 및 학습 가속화.
2. **Phase 2 (실게임 검증)**: 학습 완료된 가중치 모델을 **실제 스팀 게임 환경(`STS2_MCP` 모드 REST API)**과 연동하여 실시간 실전 플레이 검증.

---

## 2. 시스템 아키텍처 (System Architecture)

전체 시스템은 AI 에이전트를 고속으로 훈련하는 **학습 환경**과, 스팀 클라이언트와 통신하여 명령을 수행하는 **실행 환경**으로 분리되어 유기적으로 동작합니다.

```
+---------------------------------------------------------------------------------+
|                                 [ 1. 학습 환경 ]                                 |
|                                                                                 |
|   +-------------------+  Action (Masked)  +---------------------------------+   |
|   |   Maskable PPO    | ----------------> |  Headless Simulator (Gymnasium) |   |
|   |     Agent         | <---------------- |  - Game Logic (sts2.dll Re-impl)|   |
|   +-------------------+    State, Reward  +---------------------------------+   |
+---------------------------------------------------------------------------------+
                       |
                       | (1) MaskablePPO .zip   (2) scripts/export_onnx.py
                       v                            v
                  models/sweeps/<preset>/final.zip → tools/STS2MCP-bin/policy.onnx
                                                         |
                                                         | bundled into mods/
                                                         v
+---------------------------------------------------------------------------------+
|                                 [ 2. 실행 환경 ]                                 |
|                                                                                 |
|   +---------------------------+   in-proc step (~5 Hz)   +-----------------+    |
|   | STS2_MCP Mod (embedded)   | ──────────────────────►  |  STS2 Client    |    |
|   |  • BuildGameState()       |  obs (64) + mask (300)   |  (Godot 4 host) |    |
|   |  • Microsoft.ML.OnnxRuntime|  → ONNX policy.onnx     +-----------------+    |
|   |    → argmax legal action  |  → ExecuteAction(...)                           |
|   +---------------------------+                                                 |
|                ▲                                                                |
|                │ F8 hotkey / on-screen button toggles AutoPlayEnabled           |
|                │ GET/POST /api/v1/autoplay (optional REST control)              |
+---------------------------------------------------------------------------------+
```

학습은 Python (`sb3-contrib.MaskablePPO`)에서 진행하고, 학습된 weight는
ONNX로 export되어 **mod 자체에 임베드되어** Microsoft.ML.OnnxRuntime로
in-process 추론한다. 사이드카 Python 프로세스, HTTP round-trip 모두
필요 없다. 자세한 모드 빌드/배포 절차는
`tools/STS2MCP-bin/AUTOPLAY_DEPLOY.md`.

---

## 3. 강화학습 환경 디자인 (MDP Modeling)

오픈AI `Gymnasium` 표준 규격에 부합하도록 상태 공간, 행동 공간, 보상 함수를 정의합니다.

### 3.1 상태 공간 (Observation Space)
게임의 판세 정보를 취합하여 고정된 크기의 벡터(예: `Box` 형태, 단일 정규화 배열)로 가공합니다.

| 분류 | 주요 포함 정보 | 차원 및 타입 |
| :--- | :--- | :--- |
| **플레이어 상태** | 현재 HP, 최대 HP, 마나(Energy), 방어도, 버프/디버프 상태(힘, 민첩, 취약 등) | 고정 벡터 |
| **패 (Hand) 상황** | 현재 손에 든 카드들의 ID, 비용(Cost), 업그레이드 여부 (최대 10장 패딩 처리) | 고정 행렬 |
| **덱 (Deck) 상태** | 뽑을 카드 더미, 버린 카드 더미, 소멸 카드 더미의 총 매수 및 핵심 키 카드 포함 여부 | 요약 벡터 |
| **몬스터 상태** | 적들의 현재 HP, 최대 HP, 방어도, 버프 상태 및 **이번 턴 의도(Intent - 데미지 수치 등)** | 고정 행렬 (최대 5마리) |

### 3.2 행동 공간 (Action Space) 및 마스킹 (Action Masking)
- **행동 공간 구조**: `Discrete(61)` 공간으로 매핑
  - `0`: 턴 종료 (End Turn)
  - `1 ~ 10`: 대상 지정이 필요 없는 카드 사용 (10개 슬롯)
  - `11 ~ 60`: 대상 지정 카드 사용 (10개 카드 슬롯 $\times$ 최대 5마리 몬스터)
- **액션 마스킹 (Action Masking)**: 
  - 현재 마나가 부족하거나, 대상 적이 이미 사망했거나, 패에 없는 카드를 고르는 행동 확률을 `0`으로 제한합니다.
  - **선택 알고리즘**: `sb3-contrib` 라이브러리의 **`MaskablePPO`**를 사용하여 불필요한 탐색 공간을 사전에 차단하고 학습 수렴 속도를 극대화합니다.

### 3.3 보상 함수 (Reward Function)
단순 승/패 보상만으로는 초기 학습이 불가능하므로 보상 형성(Reward Shaping)을 적용합니다.

$$\text{Reward} = R_{\text{win}} + R_{\text{lose}} + R_{\text{hp\_penalty}}$$

- **전투 승리 ($R_{\text{win}}$)**: $+1.0$ (에피소드 종료)
- **전투 패배 ($R_{\text{lose}}$)**: $-1.0$ (에피소드 종료)
- **체력 보존 페널티 ($R_{\text{hp\_penalty}}$)**: $-0.01 \times \Delta \text{HP}$
  - 턴 종료 시점에서 잃은 체력에 대해 음의 보상을 부여함으로써 AI가 무조건적인 공격 대신 **방어(Block) 카드를 밸런스 있게 활용하도록 유도**합니다.

`sim/env_run.py`는 11종의 보상 프리셋(`default / aggressive / defensive /
sparse / dense_floor / survival / survival_v2 / tank / tank_plus /
balanced / boss_heavy / exploration`)을 제공하고,
`scripts/train_parallel.py --presets ...`로 동시에 여러 프리셋을 학습해
`models/sweeps/<preset>/final.zip`에 저장한다.

### 3.4 학습된 정책의 임베디드 배포 (Embedded Inference)

학습 환경(Phase 1)에서 만든 정책을 **mod에 내장**해 실게임에서
in-process로 추론한다.

| 단계 | 도구 | 산출물 |
| :--- | :--- | :--- |
| (1) MaskablePPO 학습 | `scripts/train_parallel.py` (또는 `train_run.py`) | `models/sweeps/<preset>/final.zip` |
| (2) ONNX export | `scripts/export_onnx.py` (TorchScript→ONNX opset 17, weights inline) | `tools/STS2MCP-bin/policy.onnx` (~110 KB) |
| (3) mod 배포 | `mods/`에 `STS2_MCP.dll + ORT DLL 3종 + policy.onnx` 복사 | 게임 재시작 시 자동 로드 |
| (4) 인게임 토글 | F8 hotkey / 좌상단 오버레이 버튼 / `POST /api/v1/autoplay` | `AutoPlayEnabled = true` 시 ~5 Hz 추론 |

핵심 C# 모듈 (`tools/STS2MCP-bin/mod_overlay/`):

- `McpMod.PolicyNet.cs` — `Microsoft.ML.OnnxRuntime.InferenceSession`
  로 `policy.onnx` 로드, `(obs, mask)` 입력으로 argmax legal action 반환
- `McpMod.ObsBuilder.cs` — `BuildGameState()` 출력을 64-d float 관측
  벡터로 변환 (Python `sim/env_run._obs`와 1:1 미러)
- `McpMod.MaskBuilder.cs` — 16개 `ActionRange`별 술어로 300-d bool
  mask 작성 (Python `sim/action_space.build_mask`와 1:1 미러)
- `McpMod.ActionExecutor.cs` — action index → `ExecuteAction(name,
  payload)` (Python `sim/action_space.decode` 1:1 미러)
- `McpMod.AutoPlay.cs` — F8/오버레이 버튼 + ~200 ms thinker 루프

배포/사용 절차 전체: **[tools/STS2MCP-bin/AUTOPLAY_DEPLOY.md](tools/STS2MCP-bin/AUTOPLAY_DEPLOY.md)**

---

## 4. 단계별 구축 로드맵 (Reverse-Engineering-First Roadmap)

본 프로젝트는 **시뮬레이터의 정합성**이 학습 성능의 상한을 결정한다고 보고, 먼저 게임 바이너리를 디컴파일하여 **정확한 로직을 확보한 뒤** 시뮬레이터를 작성한다.

```
[P1: 디컴파일 인프라] -> [P2: 코드/데이터 매핑] -> [P3: PRNG·MVP 명세] -> [P4: 시뮬레이터 + 일치 검증] -> [P5: RL 학습] -> [P6: 실게임 검증]
       (1주)                  (2~3주)                  (4주)                   (5~6주)                   (7~9주)        (10주~)
```

### 4.1 Phase 1: 디컴파일 도구체인 및 산출물 트리 구축 (1주)
- **도구 셋업**: `ilspycmd`(C# 디컴파일러)를 레포 로컬(`tools/`)에 격리 설치, Python `.venv` 생성, GDRE Tools(`.pck` 추출용) 다운로드.
- **산출물**: `decompiled/`(sts2.dll → C# 프로젝트), `pck_extracted/`(Godot 리소스), `notes/`(분석 노트).
- **검증**: ilspycmd로 `sts2.dll` 디컴파일이 성공하고 컴파일 가능한 .csproj가 생성되는지 확인.

### 4.2 Phase 2: 핵심 시스템 코드/데이터 매핑 (2~3주)
- **5대 서브시스템 진입점 식별**: (1) PRNG/Seed, (2) Combat State Machine, (3) Card 효과 처리, (4) Monster AI/Intent, (5) Map/Encounter 생성.
- **`ripgrep`으로 디컴파일 트리 탐색** → 각 서브시스템 클래스/함수 위치를 `notes/0X_*.md`에 표로 정리.
- **`.pck` 리소스에서 카드/몬스터/조우 정의 데이터 추출** → DLL 코드와 리소스의 분담 관계 확정.

### 4.3 Phase 3: PRNG 정밀 분석 + MVP 전투 명세화 (4주)
- **PRNG**: 시드 → 카테고리별 파생(map/combat/card_reward 등) 구조 도식화, Python 1:1 포팅 의사코드 작성.
- **MVP 전투**: 가장 단순한 액트1 솔로 조우 1종을 선정, 다음을 디컴파일 코드에서 직접 인용해 `notes/mvp_combat_spec.md`에 박제:
  - 몬스터 HP/intent 결정 트리/공격 수치
  - 플레이어 시작 HP/마나/시작 덱
  - 데미지 계산 파이프라인(force/dex/vulnerable 적용 순서)
- **카드 효과 DSL** 초안 도출 (시작 덱 모든 카드를 표현 가능한지 검증).

### 4.4 Phase 4: 헤드리스 시뮬레이터 구축 + 일치 검증 (5~6주)
- `Gymnasium.Env` 기반, 렌더링 배제. 카드 효과는 Phase 3 DSL의 인터프리터로 구현.
- **회귀 테스트**: 동일 시드/동일 입력 시퀀스에 대해 **시뮬레이터 출력 == 실게임 로그**임을 확인하는 자동 비교 프레임 구축.
- 실게임 로그 수집: `STS2_MCP` 모드 가용 시 활용, 부재 시 `0Harmony.dll` 기반 자체 후크 작성.

### 4.5 Phase 5: MaskablePPO 에이전트 훈련 (7~9주)
- `Stable-Baselines3` + `sb3-contrib` 파이프라인. 액션 마스킹으로 불법 행동 사전 차단.
- **평가 지표**: MVP 전투에서 평균 승률 ≥ 90%, 평균 잔여 HP 우상향 곡선.

### 4.6 Phase 6: 실게임 연동 및 검증 (10주~)
- 학습된 모델을 `STS2_MCP` 모드 또는 자체 Harmony 모드와 연결.
- `localhost:15526` REST API 브릿지로 JSON 상태 → 모델 입력, 예측 액션 → POST 송신.

---

## 5. 기술 스택 (Technical Stacks)

- **AI & Reinforcement Learning**: Python 3.10+, Gymnasium, Stable-Baselines3 (sb3-contrib), PyTorch, TensorBoard
- **Game Reverse Engineering**: ilspycmd 9.x (`tools/ilspy` 래퍼로 .NET 9 roll-forward 적용), AvaloniaILSpy(GUI 보조), GDRE Tools(`.pck` 추출)
- **Search & Analysis**: ripgrep, Python `.venv` (레포 로컬 격리)
- **Game Modding & Bridge**: Godot 4 (.NET Build), 0Harmony / MonoMod (게임 내장), STS2_MCP (C# Mod via REST API Server)

### 5.1 Quick Start (clone 후 로컬 작업 재개)

**macOS / Linux**
```bash
git clone git@github.com:ldh5193/ProjectSTS2.git
cd ProjectSTS2
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                              # 33/33 PASS 확인
.venv/bin/python scripts/random_baseline.py             # 무작위 베이스라인
.venv/bin/python scripts/train_mvp.py --env full --steps 30000   # 단축 학습 (~1분)
```

**Windows (PowerShell)**
```powershell
git clone git@github.com:ldh5193/ProjectSTS2.git
cd ProjectSTS2
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest                            # 33/33 PASS 확인
.\.venv\Scripts\python.exe scripts\random_baseline.py
.\.venv\Scripts\python.exe scripts\train_mvp.py --env full --steps 30000
```

`decompiled/` · `pck_extracted/` · `tools/STS2MCP-{bin,src}/`는 .gitignore되어 clone에 포함되지 않는다. 필요 시 §6.2(디컴파일), §6.3(.pck 추출), §6.4(모드 다운로드/설치) 절차로 재생성한다.

---

## 6. 대상 환경 (Target Environment Snapshot)

작업 기준 환경은 다음과 같다. 게임 업데이트 시 §6과 §4의 산출물(`decompiled/`, `pck_extracted/`)을 재생성해야 한다.

| 항목 | macOS arm64 | Windows x86_64 |
| :--- | :--- | :--- |
| 게임 버전 | `v0.103.2` (commit `89765e1e`) | `v0.103.2` (commit `89765e1e`) |
| 메인 어셈블리 해시 | `-2128802502` | `1832700724` (플랫폼 빌드 차이; IL 본체는 동일) |
| 엔진 | Godot 4 (.NET / Mono Build) | Godot 4 (.NET / Mono Build) |
| 게임 설치 경로 | `/Users/dhlee/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/` | `D:\Games\Steam\steamapps\common\Slay the Spire 2\` |
| 핵심 바이너리 | `SlayTheSpire2.app/Contents/Resources/data_sts2_macos_arm64/sts2.dll` | `data_sts2_windows_x86_64\sts2.dll` |
| 리소스 팩 | `SlayTheSpire2.app/Contents/Resources/Slay the Spire 2.pck` (≈1.85 GB) | `SlayTheSpire2.pck` (게임 루트, ≈1.85 GB) |
| 모딩 후보 | 동봉된 `0Harmony.dll`, `MonoMod.*` → 런타임 IL 패치 가능 | 동일 |

### 6.1 레포 디렉토리 규약

```
ProjectSTS2/                       # macOS: ~/workspace/ProjectSTS2,  Windows: D:\workspace\ProjectSTS2
├── README.md                      # 본 문서
├── .venv/                         # Python 격리 환경 (Python 3.10+; macOS 3.13 / Windows 3.12 검증)
├── tools/                         # 레포 로컬 도구
│   ├── ilspycmd / ilspycmd.exe    # dotnet tool install --tool-path 로 설치된 본체
│   └── ilspy                      # DOTNET_ROLL_FORWARD=Major 적용 bash 래퍼 (Windows에선 ilspycmd.exe 직접 호출)
├── decompiled/                    # Phase 1 산출물: sts2.dll → C# 프로젝트 (~3,370 .cs)
├── pck_extracted/                 # Phase 2 산출물: .pck → 원본 리소스 (GDRE Tools 필요)
├── notes/                         # 분석 노트 (서브시스템별)
├── scripts/                       # 통신/검증 스크립트 (smoke_test_mcp.py 등)
├── tools/STS2MCP-bin/             # 다운로드한 모드 바이너리 (v0.4.0)
├── tools/STS2MCP-src/             # 모드 소스 트리 (참조용 git clone)
└── sim/                           # Phase 5+ : Python 시뮬레이터 소스
```

### 6.2 도구 호출 표준 명령

**macOS / Linux (bash)**
```bash
# 디컴파일 (Phase 1)
./tools/ilspy -p \
  "/Users/dhlee/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources/data_sts2_macos_arm64/sts2.dll" \
  -o ./decompiled/

# 디컴파일 트리 검색 (Phase 2)
rg -n 'class\s+\w*(Rng|Random|Seed)\w*' ./decompiled/

# .pck 추출 (Phase 2, GDRE Tools 설치 후)
gdre_tools --headless --recover \
  "/Users/dhlee/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources/Slay the Spire 2.pck" \
  --output-dir ./pck_extracted/
```

**Windows (PowerShell)**

`tools/ilspy`는 bash 스크립트이므로 PowerShell에서는 ilspycmd를 직접 호출한다.

```powershell
# 도구 설치 (1회): 9.0.0.7889는 .NET 9 SDK에서 검증 완료. 10.x 일부 릴리스는 NuGet 패키징 오류로 설치 실패.
dotnet tool install ilspycmd --tool-path .\tools --version 9.0.0.7889

# 디컴파일 (Phase 1) — .NET 8 빌드를 .NET 9 런타임에서 강제 실행
$env:DOTNET_ROLL_FORWARD = 'Major'
.\tools\ilspycmd.exe -p `
  "D:\Games\Steam\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64\sts2.dll" `
  -o .\decompiled\
```

Windows 디컴파일 결과는 macOS와 .cs 파일 수 ±1 수준으로 동일하다 (3370 ↔ 3369). `MegaCrit.Sts2.Core.*` 네임스페이스 및 핵심 클래스 위치는 동일.

> **참고**: GDRE Tools (`gdsdecomp`)는 NuGet/brew 배포가 없어, GitHub 릴리스에서 macOS arm64 빌드를 받아 `tools/` 하위에 배치한다. 설치 후 본 문서의 명령 경로를 보정한다.

### 6.3 GDRE Tools(Godot 리소스 추출) 설치 가이드

Phase 2(`.pck` 추출)의 전제 조건. 배포 채널이 GitHub 릴리스뿐이라 매뉴얼 다운로드가 필요하다.

1. https://github.com/bruvzg/gdsdecomp/releases 에서 최신 macOS arm64 zip 다운로드 (`GDRE_tools-vX.Y.Z-macos-arm64.zip` 형태).
2. 압축 해제 후 `gdre_tools.app` 또는 `gdre_tools` 바이너리를 `./tools/` 하위에 배치.
3. Gatekeeper 차단 시: `xattr -dr com.apple.quarantine ./tools/gdre_tools.app`.
4. 동작 확인: `./tools/gdre_tools.app/Contents/MacOS/gdre_tools --help` 또는 GUI 실행.

> 이미 핵심 게임 로직은 `decompiled/` (C# 트리)에서 100% 확보되었으므로 GDRE Tools는 **밸런스 수치가 `.tres`/JSON 리소스에 들어있는 경우에만 필수**. 카드 데미지 값 등이 C# 클래스 상수로 박혀있다면 Phase 2를 생략해도 무방.

### 6.4 STS2 통신 모드(STS2_MCP) 설치 현황

| 항목 | 값 |
| :--- | :--- |
| 모드 | `Gennadiyev/STS2MCP` v0.4.0 (released 2026-05-05) |
| 채널 | REST API on `http://localhost:15526` |
| 배치 경로 (macOS) | `…/SlayTheSpire2.app/Contents/MacOS/mods/` |
| 배치 경로 (Windows) | `D:\Games\Steam\steamapps\common\Slay the Spire 2\mods\` |
| 바이너리 백업 | `tools/STS2MCP-bin/{STS2_MCP.dll,STS2_MCP.json,STS2_MCP.pdb}` |
| 소스 클론 | `tools/STS2MCP-src/` |
| 스모크 테스트 (macOS) | `.venv/bin/python scripts/smoke_test_mcp.py` (게임 실행·모드 활성화 후) |
| 스모크 테스트 (Windows) | `.\.venv\Scripts\python.exe scripts\smoke_test_mcp.py` |

> **참고**: STS2_MCP의 `STS2_MCP.dll`은 플랫폼 비종속 .NET 어셈블리이므로 macOS/Windows/Linux 모두 동일 바이너리를 사용한다 (모드 README 명시).

활성화 절차: Steam에서 게임 실행 → 첫 실행 시 모드 consent 다이얼로그 수락 → **Settings → Mods**에서 `STS2 MCP` 토글 ON.

---

## 7. 진행 현황 (Progress Index)

작업 sprint 종료 시 본 섹션을 함께 갱신한다.

### 7.1 단계별 상태

| Phase | 상태 | 산출물 | 비고 |
| :--- | :--- | :--- | :--- |
| **P0** 도구체인 셋업 | ✅ | `.venv/`, `tools/ilspy(cmd)` | Python 3.13 + ilspycmd 9.0.0 |
| **P1** sts2.dll 디컴파일 | ✅ | `decompiled/` 3,369 cs | 네임스페이스 `MegaCrit.Sts2.Core.*` 그대로 |
| **P2** .pck 리소스 추출 | ⏸ | — | GDRE Tools 매뉴얼 다운로드 대기 |
| **P3** 서브시스템 매핑 | ✅ | `notes/03_system_mapping.md` | Combat/RNG/Card/Monster/Map + AutoSlay |
| **P4** PRNG 정밀 분석 | ✅ | `notes/04_prng.md` (~580 lines) | .NET 9 xoshiro256** 래퍼, 2단계 12카테고리, 카운터 기반 결정성 |
| **P5** MVP 전투 명세화 | ✅ | `notes/05_mvp_combat_spec.md` (~460 lines) | `SludgeSpinnerWeak` 선정, 데미지 파이프라인 완전 명세 |
| **P6** 카드 효과 DSL + MVP 시뮬레이터 | ✅ | `sim/` 8 modules + `tests/test_combat.py` 10/10 PASS | dsl·powers·creatures·damage·cards·monsters·combat + PRNG 스켈레톤 |
| **P7** 시뮬레이터 ↔ 실게임 검증 | 🟡 설계 완료 | `notes/07_validation.md` | L0~L6 계층 + V01~V10 시나리오 + 진입 절차 정의. 실제 비교는 게임 실행 후 |
| **RL env** Gymnasium 래퍼 | ✅ | `sim/env.py`, `sim/observation.py` (20-dim obs, Discrete(6) + action mask) | 14/14 테스트 통과 |
| **Random baseline** | ✅ | `scripts/random_baseline.py` | 1000 ep: 승률 95.5%, 평균 턴 6.42, 평균 잔여 HP 43.73 |
| **MaskablePPO 학습** | ✅ | `scripts/train_mvp.py`, `models/mvp_ppo.zip` | 30K step, 500 ep eval: 승률 100%, 평균 턴 3.89, 평균 잔여 HP 67.65 |
| **Full-run 학습** | ✅ | `scripts/train_run.py`, `scripts/train_parallel.py`, `models/sweeps/<preset>/final.zip` | 11종 reward preset 병렬 학습, 3막 보스 통과 시도 |
| **모드 채널** 설치/검증 | ⚠ 일부 | `tools/STS2MCP-{bin,src}/`, `scripts/smoke_test_mcp.py` | 설치 완료, 스모크 테스트는 게임 실행 후 가능 |
| **MCP API 매핑** | ✅ | `notes/06_mcp_api.md` (~370 lines) | 라우트 10종 + 액션 28종 + Discrete(61)→API 매핑 |
| **임베디드 ONNX 추론** | ✅ | `tools/STS2MCP-bin/mod_overlay/{PolicyNet,ObsBuilder,MaskBuilder,ActionExecutor}.cs`, `policy.onnx` | mod 내장 inference, Python 사이드카 불필요 |
| **AutoPlay UI/토글** | ✅ | F8 hotkey + 화면 좌상단 오버레이 버튼 + `GET/POST /api/v1/autoplay` | 어떤 화면에서든 mid-run start OK |

### 7.2 결정적 발견 사항

- **`MegaCrit.Sts2.Core.AutoSlay/AutoSlayer.cs`** — 게임에 내장된 자동 플레이 시스템. RL 액션 송신 채널의 자연스러운 후크 지점.
- **`TestSupport/TestRngInjector.cs`** — 시드 주입 테스트 인프라가 게임 내부에 이미 존재 → 결정적 재현 비용이 거의 0.
- **PlayerRngSet + RunRngSet 2단계 12카테고리 분기** — STS1과 동일 패턴, Python 1:1 포팅 가능. PRNG는 .NET 9 `System.Random` (xoshiro256**) 래퍼.
- **MVP 적 후보**: `SludgeSpinnerWeak` (HP 37–39, 3-move 사이클 OIL_SPRAY/SLAM/RAGE, no spawning/conditional).
- **MVP 캐릭터**: Ironclad, HP 80, 에너지 3, 시작 덱 5×Strike + 4×Defend + 1×Bash, 시작 렐릭 BurningBlood (비전투).
- **데미지 파이프라인 확정**: `base → Strength(additive) → Vulnerable(×1.5) → block 차감 → HP delta`, 코드 인용까지 확보.
- **STS2_MCP API**: 액션 28종 식별, Discrete(61)로는 표현 불가한 영역(카드 보상/맵/포션/이벤트/렐릭/휴식/Crystal Sphere) 확인 → `Discrete(300)` 또는 factored 액션 공간 권장.
- **시뮬레이터 의사결정**: STS 표준 power tick 규칙 채택 — Weak는 player(owner) 턴 종료 시, Vulnerable는 monster(owner) 턴 종료 시. Phase 5 §F의 미해결 질문(Power timing) 중 하나를 잠정 결정. **실게임 검증 시 1순위 확인 대상**.

### 7.3 시뮬레이터 모듈

```
sim/
├── dsl.py            # CardDef / Effect / Scaling 데이터클래스
├── powers.py         # Strength (additive +N), Vulnerable (×1.5), Weak (×0.75)
├── creatures.py      # Creature / Player / Monster
├── damage.py         # compute_modified_damage, deal_damage, gain_block
├── cards.py          # Ironclad 시작 덱 (Strike×5 + Defend×4 + Bash×1)
├── card_catalog.py   # Common / Uncommon / Rare 카드 풀 + 효과 DSL
├── monsters.py       # SludgeSpinnerWeak (3-move state machine, CannotRepeat)
├── combat.py         # CombatState — 턴 사이클, 패 관리, tick 규칙
├── encounter.py      # 1~3막 일반/엘리트/보스 인카운터 풀
├── map_gen.py        # 7-act-1 / 7-act-2 / 7-act-3 절차적 맵 생성
├── relics.py         # 시작/Common/Uncommon 렐릭 효과
├── powers.py         # 게임 내부 power 시스템
├── game_state.py     # RunState — full-run 상태 머신
├── run_engine.py     # 룸 진입/해결/맵 진행 게임 루프
├── rewards.py        # 11종 reward preset (default/aggressive/tank/...)
├── action_space.py   # Discrete(300) layout + build_mask + decode
├── observation.py    # 20-dim float32 obs 벡터 (MVP)
├── env.py            # Gymnasium Discrete(6) MVP env
├── env_full.py       # Gymnasium Discrete(61) — single combat
├── env_run.py        # Gymnasium Discrete(300) full-run env (학습 메인)
└── rng.py            # xoshiro256** + SplitMix64 시드 (PlayerRngSet/RunRngSet)
```

테스트 (`tests/`, **33/33 통과**):
- `test_combat.py` 10 — 데미지 공식·블록·몬스터·라운드트립
- `test_env.py` 4 — MVP env reset/step/mask
- `test_env_full.py` 6 — Discrete(61) 액션 디코더·마스킹
- `test_rng.py` 13 — xoshiro 결정성·범위·카운터 fast-forward·snapshot 라운드트립

스크립트:
- `scripts/smoke_test_mcp.py` — 모드 5-prob 검증 (게임 실행 후)
- `scripts/random_baseline.py` — 무작위 정책 1000 ep 벤치
- `scripts/train_mvp.py --env {mvp,full}` — MaskablePPO MVP/single-combat 학습
- `scripts/train_run.py` — Discrete(300) full-run 학습 (단일 워커)
- `scripts/train_parallel.py --presets a,b,c --workers N --steps M` — 보상 프리셋 sweep 동시 학습
- `scripts/eval_model.py` — 저장된 모델 평가
- `scripts/log_episodes.py` — 학습된 모델로 N개 에피소드 trace 기록 (`--max-trajectories`로 용량 제한)
- `scripts/export_onnx.py --model <zip> --out tools/STS2MCP-bin/policy.onnx` — ONNX 변환
- `scripts/show_latest_weight.py [--all]` — 최신 sweep 체크포인트 + 배포된 ONNX 상태 표시
- `scripts/visualize_progress.py` / `scripts/visualize_runenv_trace.py` — sweep 비교/단일 에피소드 시각화
- `scripts/validate.py` — Phase 7 V01~V05 검증 하네스 (게임 실행 후)

기존 테스트 세부:
- 데미지 공식: 무수식 Strike, Vulnerable, Strength, Weak
- 블록 흡수 → HP 차감 순서
- 몬스터 HP 범위 (37–39), 첫 무브 OIL_SPRAY, CannotRepeat 제약
- 라운드트립: 플레이어 Strike → 몬스터 OIL_SPRAY → Weak 적용 확인
- Bash → Vulnerable 2 적용 → 다음 Strike가 ×1.5 스케일
- Gym env: reset/step API, observation 정규화, random policy 종료 보장

### 7.4 학습 결과

| 지표 | Random (1000 ep) | PPO MVP D6 30K | PPO Full D61 100K |
| :--- | ---: | ---: | ---: |
| 승률 | 95.5% | **100.0%** | **100.0%** |
| 평균 보상 | +0.547 | +0.876 | **+0.913** |
| 평균 턴 수 | 6.42 | 3.89 | **3.12** |
| 평균 잔여 HP | 43.73 | 67.65 | **71.34** |

- **Random → PPO**: 단순 승률을 넘어 턴 효율(−39 ~ −51%), 체력 보존(+24 ~ +28 HP)에서 큰 가치
- **Discrete(6) → Discrete(61)**: 더 큰 액션 공간 + 더 긴 학습(30K→100K) → 턴 −20%, HP +4 추가 향상

모델: `models/mvp_ppo.zip` (Discrete(6) 30K), `models/mvp_ppo_full.zip` (Discrete(61) 100K).

### 7.5 최신 학습 weight (Latest Trained Weight)

`models/sweeps/<preset>/final.zip` 중 가장 최근 mtime을 가진 체크포인트를
"latest"로 본다. CLI 한 줄로 현재 상태(경로, 크기, mtime, 배포된 ONNX
싱크 여부)를 출력한다:

```powershell
.\.venv\Scripts\python.exe scripts\show_latest_weight.py        # 최신만
.\.venv\Scripts\python.exe scripts\show_latest_weight.py --all  # 전체 목록
```

출력 예:

```
=== Latest sweep checkpoint ===
  path : models\sweeps\boss_heavy\final.zip
  size : 452.6 KB
  mtime: 2026-05-24 21:36:29 +0900
  preset: boss_heavy

=== Deployed ONNX policy ===
  path : tools\STS2MCP-bin\policy.onnx
  size : 110.2 KB
  mtime: 2026-05-24 22:27:13 +0900
  state: up to date.
```

`state: STALE`이면 새 체크포인트가 더 신선하다는 뜻이고, 표시되는
재실행 명령으로 임베드 정책을 갱신한다.

### 7.6 사용자 액션 대기 항목

다음 두 항목은 사용자의 명시적 액션이 필요:

- **스모크 테스트** — Steam에서 게임 실행 → 첫 실행 시 모드 consent 다이얼로그 수락 → **Settings → Mods**에서 `STS2 MCP` 토글 ON → 스모크 테스트 실행:
  - macOS: `.venv/bin/python scripts/smoke_test_mcp.py`
  - Windows: `.\.venv\Scripts\python.exe scripts\smoke_test_mcp.py`
- **GDRE Tools 다운로드 (Phase 2, 선택)** — `notes/` 외에 추가로 필요한 게임 리소스 데이터가 있을 경우 `https://github.com/bruvzg/gdsdecomp/releases`에서 플랫폼별 빌드 받아 `tools/` 하위 배치. **MVP 단계에서는 필수가 아님** (C# 코드에서 모든 수치 확보됨).

스모크 테스트가 통과되면 `notes/07_validation.md`의 V01~V10 시나리오를 차례로 실행해 시뮬레이터를 실게임과 정합화하면 됩니다.

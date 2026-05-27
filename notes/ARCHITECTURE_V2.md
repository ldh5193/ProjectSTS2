# Architecture V2 — Design Spec

날짜: 2026-05-27
대체: V1 (sim stubs + PPO 300-d fixed action + obs v3 256-d)

## 배경 — V1 한계

| 증상 | 진단 |
|---|---|
| 12 gen 진화 후에도 floor 10 ceiling | 학습 데이터가 act 1 초반만 — act 2/3 거의 못 봄 |
| Gen 12 raw top 55.40 → cal 35.32로 폭락 | 200-ep eval에서 노이즈가 너무 큼 — 깊이 신호 부재 |
| 게임 내 max_hp 이벤트에서 정책 망상 | sim에 이벤트 미구현 → 정책은 학습한 적 없는 OOD 상태에서 argmax |
| 정책이 유물 효과 무시 | obs에 유물 identity 없음 (개수만) |
| 카드 픽 99% skip plateau (obs v2) | per-card feature 없어서 (v3에서 부분 해결) |

근본 원인: **(1) sim 커버리지 부족 → 학습 불가능한 영역 다수**, **(2) 보상 설계가 floor depth와 misalign**, **(3) action space가 고정 300-d → OOD/가변 옵션 못 다룸**, **(4) obs가 핵심 변수 누락**.

## V2 설계 원칙

1. **단일 RL 정책** (Claude Code 패턴)
   - 학습 가능한 모든 결정 (전투/카드픽/맵/이벤트/상점)은 한 정책
   - 순수 mechanical UI 동작만 결정론적 룰

2. **Pointer-style action scoring**
   - `score_i = f(state, option_features_i)` → softmax over options
   - 가변 N 자연스럽게 처리
   - OOD 카드/유물도 feature 기반 점수 매김

3. **Tiered terminal reward** (floor 중심)
   ```
   S = 100 × acts_completed + 50 × within_act_progress
       + 30 × within_act_boss_dmg_ratio + 300 × victory
   ```

4. **Potential-based dense shaping** (Ng et al. 1999)
   - `r_shaped = γ·φ(s') − φ(s)` — Goodhart 면역
   - φ는 terminal 단위와 정합 (acts × 100 + progress × 50 + secondary)

5. **Ascension mixture curriculum**
   - A0 20%, A5 30%, A10 50% 랜덤 episode 샘플링
   - A10에서 평가 (deploy 목표)
   - obs에 `ascension` dim 이미 존재 — 한 정책이 모든 난이도 학습

6. **장치 유연성**
   - `--device {cpu,cuda,auto}` flag
   - 사용자 지시 시 CPU/GPU 전환

## 컴포넌트별 설계

### sim/ — 커버리지 확장

| 모듈 | 신규/수정 | 내용 |
|---|---|---|
| `sim/events.py` | **신규** | Event registry. Top 10 events (L1): outcomes table, option list. |
| `sim/relics.py` | **신규** | Relic effects. Top 20 relics (L1): on-combat-start, on-card-play, etc. hooks. |
| `sim/run_engine.py` | 수정 | `_step_event` real dispatch, `_step_shop` 카드 제거 + 기본 구매 |
| `sim/env_run.py` | 대폭 수정 | OBS_DIM 256→320, 새 reward 함수, ascension mixture |
| `sim/action_space.py` | 수정 | option-feature 표준화 (per-decision-type) |
| `sim/encounter.py` | 보존 | 변경 없음 |

### obs v4 — ~320 dim

이전 v3 256-d 기준 +64 추가:

| 카테고리 | dim | 변경 |
|---|---|---|
| vitals + ascension | 5 | log compression for hp/gold |
| state_type one-hot | 16 | 변경 없음 |
| **floor 3-tier** | 5 | within_act + act onehot + log absolute |
| **distance dims** | 2 | to_boss, to_victory |
| deck rarity 분포 | 5 | 변경 없음 |
| **deck type/cost 히스토그램** | 7 | 신규 |
| **boss identity** | 9 | 신규 (act × boss type) |
| **relic identity (top 20 + 기타)** | 21 | 신규 |
| **포션 identity** | 24 | 신규 (3 slot × 8-feat) |
| 전투 코어 (HP/block/energy/적1) | 8 | 변경 없음 |
| **에너지 절대값** | 1 | 신규 (overflow flag) |
| **block log normalized** | 1 | 신규 |
| pile sizes | 3 | 변경 없음 |
| player powers (5) + remaining turns | 10 | 신규 잔여턴 |
| 적 #1 powers + intent damage | 7 | **intent damage 절대값 신규** |
| 적 #2/#3 핵심 features | 8 | 변경 없음 |
| **적 수 one-hot** | 3 | 신규 |
| 손패 식별 (10 slot × 13) | 130 | 변경 없음 |
| 카드 보상 식별 (5 slot × 12) | 60 | 변경 없음 |
| 맵 lookahead (3 floor × 6 type) | 18 | 신규 |
| **NEOW 효과** | 5 | 신규 (run 시작 1회) |
| 잔여 dims | ~20 | 예비 |
| **총합** | ~320 | |

### Reward 3-layer

#### Layer A — Terminal (게임 종료 1회)
```python
S = 100 * acts_completed
  + 50  * within_act_progress     # 현재 막 진척 [0,1]
  + 30  * within_act_boss_dmg_ratio  # 보스 데미지율 (보스 사망 시)
  + 300 * victory
```

#### Layer B — Milestone (per-step)
- `act_complete`: +100 (terminal과 동일 단위)
- `elite_kill`: +2
- `floor_advance`: +50/act_length ≈ +3
- `combat_win`, `boss_kill` 직접 보상은 **폐기** (terminal/milestone에 흡수)

#### Layer C — Potential-based shaping
```python
φ(s) = 100 * acts_completed
     + 50  * within_act_progress
     + 5   * (hp / max_hp)
     + 3   * log(1 + deck_quality)
     + 2   * log(1 + gold/100)
r_shaped = γ * φ(s') - φ(s)
```

### Action space — Pointer scoring

V1 (현재): 300-d fixed action vector, softmax over all.
V2: Per-decision option list.

| 결정 타입 | Option features (dim) |
|---|---|
| 카드 사용 | 카드 13-feat + target enemy 5-feat | 18 |
| 카드 픽 | 카드 12-feat + 시너지 점수 4 | 16 |
| 카드 제거 (상점) | 카드 12-feat + 덱 fit 점수 4 | 16 |
| 유물 픽 | 유물 효과 카테고리 8-feat + 시너지 4 | 12 |
| 맵 노드 | 노드 type 6 + lookahead 3-floor × 6 | 24 |
| 이벤트 옵션 | 옵션 카테고리 (HP/gold/card/relic 변화 정량) 12 | 12 |
| 상점 구매 | 카드/유물 feat + 가격 정규화 | 16 |
| 포션 사용 | 포션 8-feat + target | 12 |
| End turn / proceed (degenerate) | indicator 1 | 1 |

모델 입력: `[state || option_features_i]` → MLP → 1-d score.
정책: `softmax_i(score_i / τ)`.

### Network 아키텍처

```
state (320-d) ──┐
                ├──> shared trunk (2-layer MLP, 256 hidden)
                │
                └──> state_embed (128-d)
                          │
option (≤24-d) ───────────┤
                          ↓
                       concat → MLP (128 → 64 → 1) → score
```

* Trunk shared across all decision types.
* Per-decision-type small option encoder (optional).
* Value head: `state_embed → MLP → V(s)` (advantage 계산용).

### 학습 알고리즘 — PPO + pointer head

기존 sb3 `MaskablePPO` 변형:
- `policy_class`를 custom pointer-style로 교체
- forward: `(state, option_features_list) → scores → masked softmax → distribution`
- Mask: 결정 타입별 legal option만 남김
- Value: state-only head
- Advantage/loss: 표준 PPO

장치:
```python
device = (
    args.device if args.device != "auto"
    else ("cuda" if torch.cuda.is_available() else "cpu")
)
```

병렬 환경 수:
- CPU: `num_envs = max(1, cpu_count() // 2)`
- GPU: `num_envs = 8-16` (메모리 여유 시)

### 진화 검색 (evolver) 단순화

V1 evolver는 reward preset 진화. V2에선 **고정 reward + 시드 다양화**로 단순화:
- Reward 가중치 합의됨 (위 Layer A/B/C)
- 진화의 핵심 시그널은 random seed × ascension mix만
- composite_score = mean(terminal S) over N=100 ep
- Recal은 유지 (선별 메커니즘으로 동작)

진화 단순 모드 또는 폐기 (PPO 학습이 hyperparameter 충분히 안정적이면).

### Mod 코드 변경

| 파일 | 변경 |
|---|---|
| `McpMod.ObsBuilder.cs` | v3 → v4 빌드 (320-d 새 layout). 모든 변수 재구현. |
| `McpMod.MaskBuilder.cs` | 변경 없음 (legal mask 로직 유지) |
| `McpMod.PolicyNet.cs` | 새 ONNX 입력 (state + N option_features) 처리. 또는 단일 호출로 모든 N option score 받는 모델 export. |
| `McpMod.ActionExecutor.cs` | 변경 없음 |
| `McpMod.AutoPlay.cs` | 호출 인터페이스만 수정 |
| `McpMod.CardFeatures.cs` | dim 확장 (12 → 16 이상) |

### 결정 필요 사항 (Phase 1 진입 전)

1. **Phase 1 events L1 명단** — 어떤 10개 이벤트?
   - 옵션 A: 위키 등장 빈도 top 10 자동
   - 옵션 B: 사용자가 직접 지정
   - 옵션 C: act 1 위주 (시작 단계 영향 큼)

2. **Phase 1 relics L1 명단** — 어떤 20개 유물?
   - Ironclad 기본 + 일반 강유물 우선?
   - 일단 multi-character 미지원이면 Ironclad-relevant만

3. **이벤트 랜덤성**
   - (a) 결정론적 결과만 — 간단, 학습 빠름
   - (b) 게임처럼 랜덤 유지 — 충실, 학습 어려움

4. **구현 위치**
   - sim/events.py + sim/relics.py 신규 — 권장

"""Per-act map generation — port of StandardActMap (notes/08_map_gen.md).

This is the **simplified first slice**:
- 7-column grid with `num_rooms + 1` rows (16 / 15 / 14 for the three acts).
- Row 0 = Ancient (single node at col 3). Row N = Boss (single node at col 3).
- Row 1 forced Monster across the 7 columns; Row N-1 forced RestSite.
- Row N-7 = Treasure (single node at col 3, replaced by Elite if the
  `replace_treasure_with_elites` flag is set).
- Other rows draw a per-type count from Gaussian distributions
  (notes/08 §5) and assign types respecting the lower/upper bounds
  (no Elite/Rest before row 6, no Rest after row N-2).
- Edges: every node at floor f connects to up to three nodes at floor
  f+1 (col-1, col, col+1). Cross-over validation and pruning are
  *not* implemented yet; rooms that would otherwise be unreachable
  still appear (slight divergence from the live game but acceptable
  for first-pass RL training).

Full StandardActMap parity (path pruning, repair passes, center grid,
straighten paths) is left for a follow-up.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .game_state import MapNode, RunMap, StateType
from .rng import Rng


WIDTH = 7
TREASURE_OFFSET_FROM_END = 7   # Row N-7 is the treasure row.
REST_OFFSET_FROM_END = 1       # Row N-1 is the campfire row.


# Per-act room counts and Gaussian distributions (notes/08 §5).
@dataclass
class ActSpec:
    name: str
    num_rooms: int                   # Floors 1..num_rooms (boss is at num_rooms+1? see below)
    unknown_mean: float
    unknown_offset: int
    rest_mean: float
    rest_lo: int
    rest_hi: int
    elite_base: int = 8
    shop_count: int = 3


# notes/08 §5
ACT_SPECS: dict[str, ActSpec] = {
    "overgrowth": ActSpec("overgrowth", num_rooms=15, unknown_mean=12,
                          unknown_offset=0, rest_mean=7, rest_lo=6, rest_hi=7),
    "underdocks": ActSpec("underdocks", num_rooms=15, unknown_mean=12,
                          unknown_offset=0, rest_mean=7, rest_lo=6, rest_hi=7),
    "hive":       ActSpec("hive",       num_rooms=14, unknown_mean=12,
                          unknown_offset=-1, rest_mean=6, rest_lo=6, rest_hi=7),
    "glory":      ActSpec("glory",      num_rooms=13, unknown_mean=12,
                          unknown_offset=-1, rest_mean=6, rest_lo=5, rest_hi=7),
}


def _draw_counts(spec: ActSpec, rng: Rng, ascension: int) -> dict[StateType, int]:
    """Per-act type counts (notes/08 §5)."""
    unknown = (rng.next_gaussian_int(int(spec.unknown_mean), 1, 10, 14)
               + spec.unknown_offset)
    rest = rng.next_gaussian_int(int(spec.rest_mean), 1, spec.rest_lo, spec.rest_hi)
    elite = spec.elite_base
    if ascension >= 1:  # SwarmingElites
        elite = int(elite * 1.6)
    return {
        StateType.EVENT: max(0, unknown),
        StateType.REST: max(0, rest),
        StateType.ELITE: max(0, elite),
        StateType.SHOP: spec.shop_count,
    }


def _is_valid_for(row: int, total_rows: int, room_type: StateType,
                  parents: list[StateType]) -> bool:
    """Subset of StandardActMap.IsValidPointType (notes/08 §5)."""
    if room_type in (StateType.ELITE, StateType.REST) and row < 6:
        return False
    if room_type is StateType.REST and row >= total_rows - 2:
        return False
    # No same type as direct parent (Elite/Rest/Treasure/Shop only).
    if room_type in (StateType.ELITE, StateType.REST,
                     StateType.TREASURE, StateType.SHOP):
        if room_type in parents:
            return False
    return True


def generate_act_map(act_key: str, rng: Rng, ascension: int = 0,
                     replace_treasure_with_elites: bool = False) -> RunMap:
    """Build a simplified RunMap for the given act."""
    spec = ACT_SPECS[act_key]
    total_rows = spec.num_rooms + 2  # +1 for Ancient (row 0), +1 for Boss (row N)
    boss_row = total_rows - 1
    treasure_row = boss_row - TREASURE_OFFSET_FROM_END
    rest_row = boss_row - REST_OFFSET_FROM_END
    if treasure_row < 2:
        # Defensive: very small acts could collide; clamp.
        treasure_row = 2

    # Initialize per-floor node lists. Floors are 1-indexed for game purposes
    # but stored 0-indexed in floors[] (so floors[0] = floor-1, etc.).
    # For convenience we'll store ancient as floor 0 (col 3) and the boss
    # as the last index. Type defaults to MONSTER and is overridden below.
    floors: list[list[MapNode]] = []
    for f in range(1, boss_row):
        floors.append([MapNode(floor=f, x=x, room_type=StateType.MONSTER)
                       for x in range(WIDTH)])
    # Boss as a final single-node floor.
    floors.append([MapNode(floor=boss_row, x=3, room_type=StateType.BOSS)])

    # Override fixed rows.
    # Row 1 (index 0): all Monster (default, no-op).
    # Row N-1 (rest_row): all RestSite.
    if 1 <= rest_row <= boss_row - 1:
        for n in floors[rest_row - 1]:
            n.room_type = StateType.REST
    # Treasure row: single node at col 3 (others become Monster default).
    if 1 <= treasure_row <= boss_row - 1:
        treasure_type = StateType.ELITE if replace_treasure_with_elites else StateType.TREASURE
        # Shrink to one node at col 3 (the game forces a single column here).
        floors[treasure_row - 1] = [MapNode(floor=treasure_row, x=3,
                                            room_type=treasure_type)]

    # Dynamic assignment for rows 2..rest_row-1, skipping treasure_row.
    counts = _draw_counts(spec, rng, ascension)
    # Queue of types to place.
    queue: list[StateType] = (
        [StateType.REST] * counts[StateType.REST]
        + [StateType.SHOP] * counts[StateType.SHOP]
        + [StateType.ELITE] * counts[StateType.ELITE]
        + [StateType.EVENT] * counts[StateType.EVENT]
    )
    rng.shuffle(queue)

    # Candidate nodes: rows 2..rest_row-1, excluding treasure_row.
    candidates: list[MapNode] = []
    for f in range(2, rest_row):
        if f == treasure_row:
            continue
        for n in floors[f - 1]:
            candidates.append(n)
    rng.shuffle(candidates)

    parents_by_node: dict[tuple[int, int], list[StateType]] = {}

    # Greedy assignment with a small validity check.
    qi = 0
    for n in candidates:
        if qi >= len(queue):
            break
        room_type = queue[qi]
        if _is_valid_for(n.floor, total_rows, room_type, []):
            n.room_type = room_type
            qi += 1

    # Connect each non-boss floor to the next via lateral edges [-1, 0, +1].
    for f in range(1, boss_row - 1):
        for n in floors[f - 1]:
            for dx in (-1, 0, 1):
                nx = n.x + dx
                if 0 <= nx < len(floors[f]):
                    n.children.append((f + 1, nx))
    # rest_row -> boss: all rest nodes connect to the lone boss.
    for n in floors[rest_row - 1]:
        n.children.append((boss_row, 3))

    return RunMap(act=_act_index(act_key), floors=floors, boss_floor=boss_row)


def _act_index(act_key: str) -> int:
    return {"overgrowth": 1, "underdocks": 1, "hive": 2, "glory": 3}[act_key]

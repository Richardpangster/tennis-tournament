import random


def draw_groups(player_ids: list[int], group_names: list[str] = None) -> dict[str, list[int]]:
    """Randomly assign players to groups, equal size each.
    group_names defaults to A/B/C/D for 4 groups."""
    if group_names is None:
        group_names = ["A", "B", "C", "D"]
    n_groups = len(group_names)
    per_group = len(player_ids) // n_groups
    shuffled = random.sample(player_ids, len(player_ids))
    result = {}
    for i, name in enumerate(group_names):
        start = i * per_group
        result[name] = shuffled[start:start + per_group]
    return result


def round_robin_schedule() -> list[tuple[int, list[tuple[int, int]]]]:
    """Standard 4-player round robin: 3 rounds × 2 matches.
    Positions are 1-indexed within the group.
    """
    return [
        (1, [(1, 4), (2, 3)]),
        (2, [(1, 3), (2, 4)]),
        (3, [(1, 2), (3, 4)]),
    ]


def generate_knockout_bracket(top2: dict[str, dict], group_names: list[str] = None) -> list[dict]:
    """Generate knockout matches from group qualifiers.
    top2: dict with keys like {'A1': {player_id, player_name}, 'A2': {...}, ...}
    group_names: list of group names, e.g. ['A','B','C','D'] or ['A','B']

    4 groups → 4 QF + 2 SF + 1 Final (7 matches)
    2 groups → 2 SF + 1 Final (3 matches)
    """
    if group_names is None:
        group_names = ["A", "B", "C", "D"]
    n = len(group_names)

    if n == 4:
        # A1-C2, B1-D2, C1-A2, D1-B2
        matchups = [
            (top2[f"{group_names[0]}1"]["player_id"], top2[f"{group_names[2]}2"]["player_id"]),
            (top2[f"{group_names[1]}1"]["player_id"], top2[f"{group_names[3]}2"]["player_id"]),
            (top2[f"{group_names[2]}1"]["player_id"], top2[f"{group_names[0]}2"]["player_id"]),
            (top2[f"{group_names[3]}1"]["player_id"], top2[f"{group_names[1]}2"]["player_id"]),
        ]
        return [
            {"stage": "quarterfinal", "match_order": 1, "player1_id": matchups[0][0], "player2_id": matchups[0][1]},
            {"stage": "quarterfinal", "match_order": 2, "player1_id": matchups[1][0], "player2_id": matchups[1][1]},
            {"stage": "quarterfinal", "match_order": 3, "player1_id": matchups[2][0], "player2_id": matchups[2][1]},
            {"stage": "quarterfinal", "match_order": 4, "player1_id": matchups[3][0], "player2_id": matchups[3][1]},
            {"stage": "semifinal", "match_order": 5, "player1_id": None, "player2_id": None},
            {"stage": "semifinal", "match_order": 6, "player1_id": None, "player2_id": None},
            {"stage": "final", "match_order": 7, "player1_id": None, "player2_id": None},
        ]
    elif n == 2:
        # A1-B2, B1-A2
        matchups = [
            (top2[f"{group_names[0]}1"]["player_id"], top2[f"{group_names[1]}2"]["player_id"]),
            (top2[f"{group_names[1]}1"]["player_id"], top2[f"{group_names[0]}2"]["player_id"]),
        ]
        return [
            {"stage": "semifinal", "match_order": 1, "player1_id": matchups[0][0], "player2_id": matchups[0][1]},
            {"stage": "semifinal", "match_order": 2, "player1_id": matchups[1][0], "player2_id": matchups[1][1]},
            {"stage": "final", "match_order": 3, "player1_id": None, "player2_id": None},
        ]
    else:
        raise ValueError(f"Unsupported number of groups: {n}")

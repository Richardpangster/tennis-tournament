import random


def draw_groups(player_ids: list[int]) -> dict[str, list[int]]:
    """16 players randomly assigned to A/B/C/D, 4 each."""
    shuffled = random.sample(player_ids, len(player_ids))
    return {
        "A": shuffled[0:4],
        "B": shuffled[4:8],
        "C": shuffled[8:12],
        "D": shuffled[12:16],
    }


def round_robin_schedule() -> list[tuple[int, list[tuple[int, int]]]]:
    """Standard 4-player round robin: 3 rounds × 2 matches.
    Positions are 1-indexed within the group.
    """
    return [
        (1, [(1, 4), (2, 3)]),
        (2, [(1, 3), (2, 4)]),
        (3, [(1, 2), (3, 4)]),
    ]


def generate_knockout_bracket(matchups: list[tuple[int, int]]) -> list[dict]:
    """Fixed bracket: matchups = [(A1,C2), (B1,D2), (C1,A2), (D1,B2)].
    Returns list of 7 match dicts (4 QF + 2 SF + 1 Final).
    Upper half: QF1 winner vs QF2 winner → SF1
    Lower half: QF3 winner vs QF4 winner → SF2
    """
    return [
        {"stage": "quarterfinal", "match_order": 1, "player1_id": matchups[0][0], "player2_id": matchups[0][1]},
        {"stage": "quarterfinal", "match_order": 2, "player1_id": matchups[1][0], "player2_id": matchups[1][1]},
        {"stage": "quarterfinal", "match_order": 3, "player1_id": matchups[2][0], "player2_id": matchups[2][1]},
        {"stage": "quarterfinal", "match_order": 4, "player1_id": matchups[3][0], "player2_id": matchups[3][1]},
        {"stage": "semifinal", "match_order": 5, "player1_id": None, "player2_id": None},
        {"stage": "semifinal", "match_order": 6, "player1_id": None, "player2_id": None},
        {"stage": "final", "match_order": 7, "player1_id": None, "player2_id": None},
    ]

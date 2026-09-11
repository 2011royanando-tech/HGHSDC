from typing import List, Dict, Any, Tuple

RATING_WEIGHTS = {
    'A': 3.0,
    'B': 2.0,
    'C': 1.0
}

# Standard balanced 16-seed knockout bracket mapping to 8 R16 matches
SEED_PAIRINGS = [
    (1, 16),  # Match 1 (Left - QF1)
    (8, 9),   # Match 2 (Left - QF1)
    (4, 13),  # Match 3 (Left - QF2)
    (5, 12),  # Match 4 (Left - QF2)
    (2, 15),  # Match 5 (Right - QF3)
    (7, 10),  # Match 6 (Right - QF3)
    (3, 14),  # Match 7 (Right - QF4)
    (6, 11),  # Match 8 (Right - QF4)
]

def calculate_bracket_metrics(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates the balance and fairness of a 16-team knockout bracket (matches 1 to 8).
    Returns total weights, A/B/C counts per half and per QF pod, and an overall balance score.
    """
    left_teams = []
    right_teams = []
    qf_pods = {1: [], 2: [], 3: [], 4: []}

    for m in matches:
        m_num = m['match_number']
        t1 = m.get('team1')
        t2 = m.get('team2')
        teams_in_m = [t for t in (t1, t2) if t]

        if m_num in (1, 2):
            left_teams.extend(teams_in_m)
            qf_pods[1].extend(teams_in_m)
        elif m_num in (3, 4):
            left_teams.extend(teams_in_m)
            qf_pods[2].extend(teams_in_m)
        elif m_num in (5, 6):
            right_teams.extend(teams_in_m)
            qf_pods[3].extend(teams_in_m)
        elif m_num in (7, 8):
            right_teams.extend(teams_in_m)
            qf_pods[4].extend(teams_in_m)

    def stats(team_list):
        weight = sum(RATING_WEIGHTS.get(t.get('rating', 'B'), 2.0) for t in team_list)
        a_cnt = sum(1 for t in team_list if t.get('rating') == 'A')
        b_cnt = sum(1 for t in team_list if t.get('rating') == 'B')
        c_cnt = sum(1 for t in team_list if t.get('rating') == 'C')
        return {'weight': weight, 'A': a_cnt, 'B': b_cnt, 'C': c_cnt, 'count': len(team_list)}

    left_stats = stats(left_teams)
    right_stats = stats(right_teams)

    qf_weights = [stats(qf_pods[i])['weight'] for i in range(1, 5)]
    qf_mean = sum(qf_weights) / 4.0 if qf_weights else 0.0
    qf_var = sum((w - qf_mean) ** 2 for w in qf_weights) / 4.0

    weight_diff = abs(left_stats['weight'] - right_stats['weight'])
    a_diff = abs(left_stats['A'] - right_stats['A'])
    b_diff = abs(left_stats['B'] - right_stats['B'])
    c_diff = abs(left_stats['C'] - right_stats['C'])

    # Check R16 A vs A clash penalty
    r16_a_clashes = 0
    for m in matches:
        t1 = m.get('team1')
        t2 = m.get('team2')
        if t1 and t2 and t1.get('rating') == 'A' and t2.get('rating') == 'A':
            r16_a_clashes += 1

    penalty = (weight_diff * 15.0) + (a_diff * 8.0) + (b_diff * 4.0) + (c_diff * 4.0) + (qf_var * 10.0) + (r16_a_clashes * 20.0)
    balance_score = max(0.0, min(100.0, round(100.0 - penalty, 1)))

    explanation = (
        f"Bracket generated using global A/B/C strength balancing. "
        f"Left Half: {left_stats['weight']:.1f} pts ({left_stats['A']}A, {left_stats['B']}B, {left_stats['C']}C) vs "
        f"Right Half: {right_stats['weight']:.1f} pts ({right_stats['A']}A, {right_stats['B']}B, {right_stats['C']}C). "
        f"QF pod variance: {qf_var:.2f}. Balance score: {balance_score}%."
    )

    return {
        "balance_score": balance_score,
        "left_stats": left_stats,
        "right_stats": right_stats,
        "qf_weights": qf_weights,
        "explanation": explanation
    }

def generate_balanced_bracket(teams: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Generates a globally balanced 16-team knockout bracket from exactly 16 teams.
    Deterministic algorithm using rating-priority ranking and symmetrical seed mapping.
    """
    if len(teams) != 16:
        raise ValueError(f"Exactly 16 teams are required before the bracket can be generated. Provided: {len(teams)}")

    def sort_key(t):
        w = RATING_WEIGHTS.get(t.get('rating', 'B'), 2.0)
        return (-w, t.get('name', ''), t.get('id', 0))

    sorted_teams = sorted(teams, key=sort_key)
    seeds = {i + 1: sorted_teams[i] for i in range(16)}

    matches = []
    for m_idx, (seed1, seed2) in enumerate(SEED_PAIRINGS):
        m_num = m_idx + 1
        half = 'LEFT' if m_num <= 4 else 'RIGHT'
        t1 = seeds[seed1]
        t2 = seeds[seed2]
        matches.append({
            'match_number': m_num,
            'bracket_position': m_num,
            'half': half,
            'team1': t1,
            'team2': t2,
            'team1_id': t1['id'],
            'team2_id': t2['id'],
            'seed1': seed1,
            'seed2': seed2
        })

    metrics = calculate_bracket_metrics(matches)
    return matches, metrics

def generate_random_bracket(teams: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Generates a pure randomized 16-team knockout bracket.
    Pairs teams completely by random lottery draw without ABC rating tiering.
    """
    import random
    if len(teams) != 16:
        raise ValueError(f"Exactly 16 teams are required before the bracket can be generated. Provided: {len(teams)}")

    shuffled = list(teams)
    random.shuffle(shuffled)

    matches = []
    for m_idx in range(8):
        m_num = m_idx + 1
        half = 'LEFT' if m_num <= 4 else 'RIGHT'
        t1 = shuffled[m_idx * 2]
        t2 = shuffled[m_idx * 2 + 1]
        matches.append({
            'match_number': m_num,
            'bracket_position': m_num,
            'half': half,
            'team1': t1,
            'team2': t2,
            'team1_id': t1['id'],
            'team2_id': t2['id'],
            'seed1': m_idx * 2 + 1,
            'seed2': m_idx * 2 + 2
        })

    metrics = {
        "balance_score": 100.0,
        "left_stats": {"count": 8},
        "right_stats": {"count": 8},
        "explanation": "লটারি অনুযায়ী নিরপেক্ষ ও উন্মুক্ত ম্যাচ নির্ধারণ (Randomized fair draw without ABC tier restrictions)."
    }
    return matches, metrics


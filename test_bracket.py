import unittest
from app.bracket_algo import generate_balanced_bracket, calculate_bracket_metrics

class TestBracketAlgorithm(unittest.TestCase):
    def test_balanced_bracket_4a_8b_4c(self):
        teams = []
        for i in range(4):
            teams.append({"id": i+1, "name": f"Team A{i+1}", "rating": "A"})
        for i in range(8):
            teams.append({"id": i+5, "name": f"Team B{i+1}", "rating": "B"})
        for i in range(4):
            teams.append({"id": i+13, "name": f"Team C{i+1}", "rating": "C"})

        matches, metrics = generate_balanced_bracket(teams)
        self.assertEqual(len(matches), 8)
        self.assertEqual(metrics["left_stats"]["count"], 8)
        self.assertEqual(metrics["right_stats"]["count"], 8)
        self.assertEqual(metrics["left_stats"]["A"], 2)
        self.assertEqual(metrics["right_stats"]["A"], 2)
        self.assertEqual(metrics["left_stats"]["B"], 4)
        self.assertEqual(metrics["right_stats"]["B"], 4)
        self.assertEqual(metrics["left_stats"]["C"], 2)
        self.assertEqual(metrics["right_stats"]["C"], 2)
        self.assertGreaterEqual(metrics["balance_score"], 90.0)

    def test_balanced_bracket_8a_4b_4c(self):
        teams = []
        for i in range(8):
            teams.append({"id": i+1, "name": f"Team A{i+1}", "rating": "A"})
        for i in range(4):
            teams.append({"id": i+9, "name": f"Team B{i+1}", "rating": "B"})
        for i in range(4):
            teams.append({"id": i+13, "name": f"Team C{i+1}", "rating": "C"})

        matches, metrics = generate_balanced_bracket(teams)
        self.assertEqual(len(matches), 8)
        self.assertEqual(metrics["left_stats"]["A"], 4)
        self.assertEqual(metrics["right_stats"]["A"], 4)
        self.assertGreaterEqual(metrics["balance_score"], 90.0)

    def test_determinism(self):
        teams = [{"id": i+1, "name": f"Team {i+1:02d}", "rating": "B"} for i in range(16)]
        m1, met1 = generate_balanced_bracket(teams)
        m2, met2 = generate_balanced_bracket(teams)
        self.assertEqual(m1, m2)
        self.assertEqual(met1["balance_score"], met2["balance_score"])

    def test_invalid_team_count(self):
        teams = [{"id": i+1, "name": f"Team {i+1}", "rating": "B"} for i in range(12)]
        with self.assertRaises(ValueError):
            generate_balanced_bracket(teams)

if __name__ == '__main__':
    unittest.main()

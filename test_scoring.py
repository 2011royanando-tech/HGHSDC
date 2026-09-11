import unittest
from fastapi.testclient import TestClient
from app.main import app
from seed_demo import seed_demo_data

_test_client = TestClient(app)

class RequestsAdapter:
    @staticmethod
    def post(url, **kwargs):
        path = url.replace("http://127.0.0.1:8000", "")
        return _test_client.post(path, **kwargs)

    @staticmethod
    def get(url, **kwargs):
        path = url.replace("http://127.0.0.1:8000", "")
        return _test_client.get(path, **kwargs)

    @staticmethod
    def put(url, **kwargs):
        path = url.replace("http://127.0.0.1:8000", "")
        return _test_client.put(path, **kwargs)

    @staticmethod
    def delete(url, **kwargs):
        path = url.replace("http://127.0.0.1:8000", "")
        return _test_client.delete(path, **kwargs)

requests = RequestsAdapter
BASE_URL = "http://127.0.0.1:8000"

class TestScoringAndTabulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_demo_data()
        # Login as admin
        res = requests.post(f"{BASE_URL}/api/auth/login", json={"whatsapp_number": "HGHSDC", "pin": "129417#"})
        assert res.status_code == 200, res.text
        cls.admin_token = res.json()["token"]
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        # Register and approve Judge 1
        res = requests.post(f"{BASE_URL}/api/auth/register", json={
            "full_name": "Test Judge 1", "whatsapp_number": "judge1", "pin": "", "applied_role": "JUDGE"
        })
        cls.j1_token = res.json()["token"]
        cls.j1_id = res.json()["user"]["id"]
        cls.j1_headers = {"Authorization": f"Bearer {cls.j1_token}"}
        requests.post(f"{BASE_URL}/api/members/applications/approve", json={"user_id": cls.j1_id, "status": "APPROVED"}, headers=cls.admin_headers)
        # Login again to refresh role as JUDGE
        res = requests.post(f"{BASE_URL}/api/auth/login", json={"whatsapp_number": "judge1", "pin": ""})
        cls.j1_token = res.json()["token"]
        cls.j1_headers = {"Authorization": f"Bearer {cls.j1_token}"}

        # Register and approve Judge 2
        res = requests.post(f"{BASE_URL}/api/auth/register", json={
            "full_name": "Test Judge 2", "whatsapp_number": "judge2", "pin": "", "applied_role": "JUDGE"
        })
        cls.j2_id = res.json()["user"]["id"]
        requests.post(f"{BASE_URL}/api/members/applications/approve", json={"user_id": cls.j2_id, "status": "APPROVED"}, headers=cls.admin_headers)
        # Login again to refresh role as JUDGE
        res = requests.post(f"{BASE_URL}/api/auth/login", json={"whatsapp_number": "judge2", "pin": ""})
        cls.j2_token = res.json()["token"]
        cls.j2_headers = {"Authorization": f"Bearer {cls.j2_token}"}

        # Create 16 distinct HGHS teams with unique speakers
        for i in range(1, 17):
            s1 = requests.post(f"{BASE_URL}/api/auth/register", json={"full_name": f"Debater {i}_1", "whatsapp_number": f"u_{i}_1", "pin": "", "applied_role": "MEMBER"}).json()["user"]["id"]
            s2 = requests.post(f"{BASE_URL}/api/auth/register", json={"full_name": f"Debater {i}_2", "whatsapp_number": f"u_{i}_2", "pin": "", "applied_role": "MEMBER"}).json()["user"]["id"]
            s3 = requests.post(f"{BASE_URL}/api/auth/register", json={"full_name": f"Debater {i}_3", "whatsapp_number": f"u_{i}_3", "pin": "", "applied_role": "MEMBER"}).json()["user"]["id"]
            rating = "A" if i <= 4 else ("B" if i <= 12 else "C")
            requests.post(f"{BASE_URL}/api/teams/admin/save-team", json={
                "name": f"HGHS Team {i}",
                "school_organization": "HGHSDC",
                "speaker1_id": s1,
                "speaker2_id": s2,
                "speaker3_id": s3,
                "rating": rating,
                "is_official": 1,
                "status": "APPROVED"
            }, headers=cls.admin_headers)

    def test_full_scoring_workflow_and_advance(self):
        # 1. Generate bracket
        res = requests.post(f"{BASE_URL}/api/tournament/bracket/generate", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200, res.text)

        # 2. Lock bracket
        res = requests.post(f"{BASE_URL}/api/tournament/bracket/lock", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200, res.text)

        # 3. Assign Judge 1 and Judge 2 to Match 1
        res = requests.get(f"{BASE_URL}/api/tournament/bracket", headers=self.admin_headers)
        m1 = res.json()["matches"][0]
        m1_id = m1["id"]

        # Assign judges to all matches in Round 1 to satisfy tournament validation logic
        for m in res.json()["matches"][:8]:
            res_assign = requests.post(f"{BASE_URL}/api/judging/assign", json={
                "match_id": m["id"],
                "judge_ids": [self.j1_id, self.j2_id],
                "override_clashes": True
            }, headers=self.admin_headers)
            self.assertEqual(res_assign.status_code, 200, res_assign.text)

        # 4. Start Round 1
        requests.put(f"{BASE_URL}/api/tournament/rounds/1", json={"motion_en": "Test Motion", "motion_bn": "টেস্ট প্রস্তাবনা", "prep_time_minutes": 15, "speaking_time_seconds": 180}, headers=self.admin_headers)
        res = requests.post(f"{BASE_URL}/api/judging/rounds/1/start", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200, res.text)

        # 5. Judge 1 gets assignment
        res = requests.get(f"{BASE_URL}/api/judging/my-assignment", headers=self.j1_headers)
        self.assertEqual(res.status_code, 200, res.text)
        j1_assign = res.json()
        self.assertTrue(j1_assign["active"])
        sc1_id = j1_assign["scorecard_id"]

        # 6. Judge 1 tests score bounds (invalid score > max_marks)
        bad_payload = {
            "criteria": [{"name": "Logic", "max_marks": 30.0}],
            "scores": [{"criterion_id": 0, "team_id": m1["team1_id"], "speaker_position": 1, "score": 35.0}]
        }
        res = requests.post(f"{BASE_URL}/api/scoring/scorecard/{sc1_id}/save", json=bad_payload, headers=self.j1_headers)
        self.assertEqual(res.status_code, 400) # Blocked!

        # 7. Judge 1 saves and submits valid ballot
        criteria = [
            {"name": "Logic", "max_marks": 30.0},
            {"name": "Delivery", "max_marks": 25.0}
        ]
        # Team 1: 3 speakers * (25 + 20) = 45 per speaker -> Team Total = 135
        # Team 2: 3 speakers * (20 + 20) = 40 per speaker -> Team Total = 120
        scores_j1 = []
        for sp in (1, 2, 3):
            scores_j1.append({"criterion_id": 0, "team_id": m1["team1_id"], "speaker_position": sp, "score": 25.0})
            scores_j1.append({"criterion_id": 1, "team_id": m1["team1_id"], "speaker_position": sp, "score": 20.0})
            scores_j1.append({"criterion_id": 0, "team_id": m1["team2_id"], "speaker_position": sp, "score": 20.0})
            scores_j1.append({"criterion_id": 1, "team_id": m1["team2_id"], "speaker_position": sp, "score": 20.0})

        res = requests.post(f"{BASE_URL}/api/scoring/scorecard/{sc1_id}/submit", json={
            "criteria": criteria,
            "scores": scores_j1,
            "tie_choice_team_id": m1["team1_id"]
        }, headers=self.j1_headers)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["team1_total"], 135.0)
        self.assertEqual(res.json()["team2_total"], 120.0)

        # 8. Judge 2 gets assignment and submits ballot
        res = requests.get(f"{BASE_URL}/api/judging/my-assignment", headers=self.j2_headers)
        j2_assign = res.json()
        sc2_id = j2_assign["scorecard_id"]

        # Team 1: 3 * (24 + 21) = 135
        # Team 2: 3 * (22 + 18) = 120
        scores_j2 = []
        for sp in (1, 2, 3):
            scores_j2.append({"criterion_id": 0, "team_id": m1["team1_id"], "speaker_position": sp, "score": 24.0})
            scores_j2.append({"criterion_id": 1, "team_id": m1["team1_id"], "speaker_position": sp, "score": 21.0})
            scores_j2.append({"criterion_id": 0, "team_id": m1["team2_id"], "speaker_position": sp, "score": 22.0})
            scores_j2.append({"criterion_id": 1, "team_id": m1["team2_id"], "speaker_position": sp, "score": 18.0})

        res = requests.post(f"{BASE_URL}/api/scoring/scorecard/{sc2_id}/submit", json={
            "criteria": criteria,
            "scores": scores_j2,
            "tie_choice_team_id": m1["team1_id"]
        }, headers=self.j2_headers)
        self.assertEqual(res.status_code, 200, res.text)

        # 9. Verify Multi-Judge Aggregation:
        # Team 1 aggregate = (135 + 135)/2 = 135.0
        # Team 2 aggregate = (120 + 120)/2 = 120.0
        # Winner = team1_id
        # Status = SILENT (is_published = 0)
        res = requests.get(f"{BASE_URL}/api/results/match/{m1_id}/review", headers=self.admin_headers)
        rev = res.json()
        self.assertEqual(rev["match"]["team1_aggregate"], 135.0)
        self.assertEqual(rev["match"]["team2_aggregate"], 120.0)
        self.assertEqual(rev["match"]["winner_id"], m1["team1_id"])
        self.assertEqual(rev["match"]["is_published"], 0)
        self.assertEqual(len(rev["ballots"]), 2)

        # 10. Admin publishes result
        res = requests.post(f"{BASE_URL}/api/results/match/{m1_id}/publish", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200, res.text)
        pub_data = res.json()
        self.assertEqual(pub_data["winner_id"], m1["team1_id"])
        # Match 1 winner advances to Match 9, Slot 1 (QF1)
        self.assertEqual(pub_data["advancement"], [9, 1])

        # 11. Verify Match 9 has received the winner in team1_id
        res = requests.get(f"{BASE_URL}/api/tournament/bracket", headers=self.admin_headers)
        m9 = [m for m in res.json()["matches"] if m["match_number"] == 9][0]
        self.assertEqual(m9["team1_id"], m1["team1_id"])

if __name__ == '__main__':
    unittest.main()

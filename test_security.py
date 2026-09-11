import unittest
import random
from fastapi.testclient import TestClient
from app.main import app

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

class TestSecurityAndAccessControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Register a unique normal member
        random_phone = f"01799{random.randint(100000, 999999)}"
        res = requests.post(f"{BASE_URL}/api/auth/register", json={
            "full_name": "Test Security Member",
            "whatsapp_number": random_phone,
            "pin": "9999",
            "applied_role": "MEMBER"
        })
        assert res.status_code == 200, res.text
        cls.member_token = res.json()["token"]
        cls.member_headers = {"Authorization": f"Bearer {cls.member_token}"}

        # Login as Admin
        res = requests.post(f"{BASE_URL}/api/auth/login", json={
            "whatsapp_number": "HGHSDC",
            "pin": "129417#"
        })
        assert res.status_code == 200, res.text
        cls.admin_token = res.json()["token"]
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

    def test_unauthenticated_cannot_access_audit_logs(self):
        res = requests.get(f"{BASE_URL}/api/audit")
        self.assertEqual(res.status_code, 401)

    def test_member_cannot_access_audit_logs(self):
        res = requests.get(f"{BASE_URL}/api/audit", headers=self.member_headers)
        self.assertEqual(res.status_code, 403)

    def test_member_cannot_lock_bracket(self):
        res = requests.post(f"{BASE_URL}/api/tournament/bracket/lock", headers=self.member_headers)
        self.assertEqual(res.status_code, 403)

    def test_member_cannot_see_internal_team_ratings(self):
        res = requests.get(f"{BASE_URL}/api/teams", headers=self.member_headers)
        self.assertEqual(res.status_code, 200)
        teams = res.json()["teams"]
        for t in teams:
            self.assertNotIn("rating", t, "Internal ABC rating leaked to Member!")

    def test_admin_can_see_team_ratings(self):
        res = requests.get(f"{BASE_URL}/api/teams", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        teams = res.json()["teams"]
        for t in teams:
            self.assertIn("rating", t)

    def test_member_cannot_see_whatsapp_numbers(self):
        res = requests.get(f"{BASE_URL}/api/members", headers=self.member_headers)
        self.assertEqual(res.status_code, 200)
        members = res.json()["members"]
        for m in members:
            self.assertNotIn("whatsapp_number", m, "Private WhatsApp numbers leaked to Member!")

    def test_admin_can_see_whatsapp_numbers(self):
        res = requests.get(f"{BASE_URL}/api/members", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        members = res.json()["members"]
        for m in members:
            self.assertIn("whatsapp_number", m)

if __name__ == '__main__':
    unittest.main()

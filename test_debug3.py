import requests, json
BASE = "http://127.0.0.1:8000"
def login(u,p):
    return requests.post(f"{BASE}/api/auth/login",json={"username":u,"password":p}).json()["access_token"]

h_emg = {"Authorization": f"Bearer {login('emerg01','emg123456')}"}
r = requests.get(f"{BASE}/api/users/me", headers=h_emg)
print(f"/api/users/me HTTP {r.status_code}: {json.dumps(r.json(), ensure_ascii=False)[:500]}")

# 查领用创建错误
h_res = {"Authorization": f"Bearer {login('res01','res123456')}"}
r = requests.get(f"{BASE}/api/chemicals", headers=h_res)
benz = next((c for c in r.json() if "苯" in c["name"]), None)
print(f"\n苯 id={benz['id'] if benz else None}")

body = {
    "lab_id": 1,
    "chemical_id": benz["id"],
    "project_type": "organic_synthesis",
    "project_name": "test",
    "requested_quantity": 2.3,
    "unit": "kg",
    "purpose": "test"
}
r = requests.post(f"{BASE}/api/usage", json=body, headers=h_res)
print(f"\ncreate usage HTTP {r.status_code}: {r.text[:1000]}")

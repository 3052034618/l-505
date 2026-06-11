import requests, json

BASE = "http://127.0.0.1:8000"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p})
    print(f"login {u}: status={r.status_code}, resp={r.text[:200]}")
    return r.json().get("access_token")

tok_res = login("res01", "res123456")
tok_sup = login("superv01", "sup123456")
tok_safe = login("safety01", "safe123456")

h = {"Authorization": f"Bearer {tok_res}"}

# 查化学品
r = requests.get(f"{BASE}/api/chemicals", headers=h)
print(f"\nchemicals status={r.status_code} resp[:800]={r.text[:800]}")
chems = r.json()
benz = next((c for c in chems if "苯" in c["name"]), None)
print(f"\nbenzene: id={benz['id'] if benz else None}, keys={list(benz.keys())[:10] if benz else None}")

if benz:
    body = {"chemical_id": benz["id"], "quantity": 2.3, "purpose": "测试", "cabinet_id": 1, "supervisor_id": 1}
    r = requests.post(f"{BASE}/api/usage", json=body, headers=h)
    print(f"\ncreate usage: status={r.status_code}, body={r.text}")

# 查告警详情
h_safe = {"Authorization": f"Bearer {tok_safe}"}
r = requests.get(f"{BASE}/api/alarms", headers=h_safe)
print(f"\nlist alarms: status={r.status_code} resp[:500]={r.text[:500]}")
alarms = r.json()
if alarms:
    al = alarms[0]
    print(f"\ntry closure for alarm_id={al['id']} status={al['status']}")
    body = {
        "root_cause": "test cause",
        "handling_summary": "test summary",
        "lessons_learned": "test lesson",
        "improvement_actions": ["a", "b"],
        "effectiveness_rating": 80
    }
    r = requests.post(f"{BASE}/api/alarms/{al['id']}/closure", json=body, headers=h_safe)
    print(f"closure: status={r.status_code}, resp={r.text}")

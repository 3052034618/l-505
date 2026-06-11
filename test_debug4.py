import requests, json, datetime, time
BASE = "http://127.0.0.1:8000"
def login(u,p):
    return requests.post(f"{BASE}/api/auth/login",json={"username":u,"password":p}).json()["access_token"]

h = {"Authorization": f"Bearer {login('labmgr01','lab123456')}"}

# 先看化学品苯的配置
r = requests.get(f"{BASE}/api/chemicals", headers=h)
benz = next((c for c in r.json() if "苯" in c["name"]), None)
print(f"苯: id={benz['id']}, msds_url={benz.get('msds_url')}, category={benz.get('category')}, lab_id={benz.get('lab_id')}")
print(f"  storage_temp: {benz.get('storage_temp_min')}~{benz.get('storage_temp_max')}")
print(f"  humidity: {benz.get('storage_humidity_min')}~{benz.get('storage_humidity_max')}")

# 看看柜位
r = requests.get(f"{BASE}/api/storage-cabinets", headers=h)
data = r.json()
print(f"柜位API返回 type={type(data).__name__}: {str(data)[:600]}")
if isinstance(data, list):
    for c in data:
        try:
            print(f"  柜位: id={c.get('id')}, no={c.get('cabinet_no')}, lab={c.get('lab_id')}")
        except Exception as e:
            print(f"  err: {e}")

# 尝试入库，看详细错误
body = {
    "chemical_id": 5,
    "batch_no": f"DEBUG-{int(time.time())}",
    "quantity": 25.0,
    "unit": "kg",
    "manufacturer": "国药集团化学试剂有限公司",
    "production_date": datetime.date.today().isoformat(),
    "expiry_date": "2028-12-31",
}
r = requests.post(f"{BASE}/api/inbound", json=body, headers=h)
print(f"\n入库 HTTP {r.status_code}:")
print(f"  body={r.text[:1000]}")
if r.status_code == 200:
    resp = r.json()
    print(f"  keys: {list(resp.keys())}")
    print(f"  status={resp.get('status')}, reject={resp.get('reject_reason')}")
    print(f"  msds_verified={resp.get('msds_verified')}, result={resp.get('msds_verify_result')}")
    print(f"  cabinet_allocated={resp.get('cabinet_allocated')}, id={resp.get('allocated_cabinet_id')}")

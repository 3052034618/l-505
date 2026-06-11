import requests, json, time

BASE = "http://127.0.0.1:8000"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p})
    return r.json()["access_token"]

def auth_header(token):
    return {"Authorization": f"Bearer {token}"}

res01_tok = login("res01", "res123456")
superv01_tok = login("superv01", "sup123456")
labmgr01_tok = login("labmgr01", "lab123456")
safety01_tok = login("safety01", "safe123456")
emerg01_tok = login("emerg01", "emg123456")
admin_tok = login("admin", "admin123")

# 问题1：领用创建失败调试
print("=" * 60)
print("【调试1】领用创建详细结果")
r = requests.get(f"{BASE}/api/chemicals", headers=auth_header(res01_tok))
chems = r.json()
benz = next((c for c in chems if "苯" in c["name"]), None)

usage_body = {
    "lab_id": 1,
    "chemical_id": benz["id"],
    "project_type": "research",
    "project_name": "烯烃聚合工艺研究",
    "requested_quantity": 2.3,
    "unit": "kg",
    "purpose": "聚合反应实验-引发剂制备",
}
r = requests.post(f"{BASE}/api/usage", json=usage_body, headers=auth_header(res01_tok))
print(f"  HTTP {r.status_code}: {r.text[:800]}")
if r.status_code == 200:
    usage_resp = r.json()
    usage_id = usage_resp["id"]
    usage_no = usage_resp["request_no"]
    print(f"  成功！usage_id={usage_id}, usage_no={usage_no}, status={usage_resp['status']}")

    # 导师审批
    r = requests.post(f"{BASE}/api/usage/{usage_id}/review",
        json={"action": "approve", "comment": "同意领用，注意防护"},
        headers=auth_header(superv01_tok))
    print(f"\n  导师审批 HTTP {r.status_code}: {r.text[:500]}")

    time.sleep(0.5)
    # 查补货
    r = requests.get(f"{BASE}/api/replenishment", headers=auth_header(labmgr01_tok))
    reps = r.json()
    pending = [x for x in reps if x["status"] in ["pending_lab_manager", "pending_safety"]]
    print(f"\n  补货单总数={len(reps)}, pending={len(pending)}")
    for rep in reps[:3]:
        print(f"    id={rep['id']}, no={rep['request_no']}, status={rep['status']}")

# 问题2：调试任务#2为什么progress_percent返回None
print("\n" + "=" * 60)
print("【调试2】查看当前告警和任务状态，然后处理")
r = requests.get(f"{BASE}/api/alarms", headers=auth_header(emerg01_tok))
alarms = r.json()
print(f"  告警数={len(alarms)}")
for al in alarms:
    print(f"  告警 id={al['id']} no={al['alarm_no']} status={al['status']} 任务数={len(al['tasks'])}")
    for t in al['tasks']:
        print(f"    - 任务 id={t['id']} status={t['status']} assignee={t.get('assignee_name')}")
        # 尝试100%进度
        r2 = requests.post(f"{BASE}/api/alarms/tasks/{t['id']}/progress",
            json={"progress_status": "处置完毕", "progress_percent": 100,
                  "description": f"完成任务{t['id']}"},
            headers=auth_header(emerg01_tok))
        print(f"      进度更新100% HTTP {r2.status_code}: {r2.text[:300]}")

# 查最新告警的所有任务当前状态
if alarms:
    latest = alarms[0]
    print(f"\n  最新告警{latest['id']}的任务最终状态：")
    r = requests.get(f"{BASE}/api/alarms", headers=auth_header(admin_tok))
    al2 = r.json()[0]
    for t in al2["tasks"]:
        print(f"    任务id={t['id']} status={t['status']}")
    # 复盘
    body = {
        "root_cause": "老化",
        "handling_summary": "ok",
        "lessons_learned": "维护",
        "improvement_actions": ["a"],
        "effectiveness_rating": 80
    }
    r = requests.post(f"{BASE}/api/alarms/{latest['id']}/closure", json=body, headers=auth_header(safety01_tok))
    print(f"  复盘 HTTP {r.status_code}: {r.text[:300]}")

# 问题3：调试duration统计接口
print("\n" + "=" * 60)
print("【调试3】耗时统计接口返回")
r = requests.get(f"{BASE}/api/audit-trails/stats/duration?business_type=replenishment", headers=auth_header(admin_tok))
print(f"  HTTP {r.status_code}: type={type(r.json())}")
print(f"  内容={json.dumps(r.json(), ensure_ascii=False)[:600]}")

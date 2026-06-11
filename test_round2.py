import requests
import json

BASE = "http://127.0.0.1:8000"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p})
    return r.json()["access_token"]

def auth_header(tok):
    return {"Authorization": f"Bearer {tok}"}

admin_tok = login("admin", "admin123")
labmgr01_tok = login("labmgr01", "lab123456")
safety01_tok = login("safety01", "safe123456")
res01_tok = login("res01", "res123456")

print("=" * 60)
print("【1/5】监管总览看板 - 多角色权限测试")

for name, tok in [("ADMIN", admin_tok), ("主任", labmgr01_tok), ("安环", safety01_tok)]:
    r = requests.get(f"{BASE}/api/dashboard/overview", headers=auth_header(tok))
    print(f"\n  [{name}] HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"    视角: {d['viewer_role']}")
        print(f"    覆盖实验室: {d['scope_lab_ids']}")
        print(f"    待审批: {d['pending_approvals']}")
        print(f"    活跃告警: {d['active_alarms']}")
        print(f"    库存: {d['inventory']}")
        print(f"    废液: {d['waste']}")
        print(f"    今日: {d['today']}")
        print(f"    各实验室细分:")
        for lb in d["lab_breakdown"]:
            print(f"      [{lb['lab_name']} 使用待批={lb['pending_usage_supervisor']} 补货主任待批={lb['pending_replenish_lab_manager']} 补货安环待批={lb['pending_replenish_safety']} 废液待检={lb['pending_waste_inspection']} 告警={lb['active_alarms']} 低库存={lb['low_stock_items']}")
    else:
        print(f"    ERR: {r.text[:300]}")

print("\n" + "=" * 60)
print("【2/5】废液全流程时间线测试 (提交→检查→批次→发运→接收)")

# 2a. 研究员提交废液
r = requests.get(f"{BASE}/api/chemicals?lab_id=1", headers=auth_header(res01_tok))
chems = r.json()
methanol = next((c for c in chems if "甲醇" in c["name"]), chems[0])
print(f"  选中化学品: {methanol['name']} id={methanol['id']}")

r = requests.post(f"{BASE}/api/waste", json={
    "chemical_id": methanol["id"],
    "lab_id": 1,
    "waste_type": "flammable",
    "quantity": 5.0,
    "unit": "L",
    "container_no": "WB-TEST-001",
    "container_type": "密封玻璃瓶",
}, headers=auth_header(res01_tok))
print(f"  提交废液: HTTP {r.status_code}")
if r.status_code == 200:
    waste = r.json()
    waste_id = waste["id"]
    waste_no = waste["waste_no"]
    print(f"    id={waste_id} no={waste_no} status={waste['status']}")
else:
    print(f"    ERR: {r.text[:300]}")
    waste_id = None
    waste_no = None

if waste_id:
    # 2b. 安环检查通过
    r = requests.post(f"{BASE}/api/waste/{waste_id}/inspect", json={
        "inspection_result": {
            "seal_passed": True, "seal_notes": "密封完好",
            "label_passed": True, "label_notes": "标签清晰",
            "violation_recorded": False,
        }
    }, headers=auth_header(safety01_tok))
    print(f"  安环检查: HTTP {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"    status={d['status']} batch_id={d.get('batch_id')}")

    # 2c. 查批次id
    r = requests.get(f"{BASE}/api/waste/batches", headers=auth_header(safety01_tok))
    batches = r.json()
    if batches:
        created_batches = [b for b in batches if b.get("status") == "created"]
        batch = created_batches[0] if created_batches else batches[-1]
        batch_id = batch["id"]
        print(f"  选中批次: id={batch_id} no={batch['batch_no']} status={batch['status']}")

        # 2d. 发运
        r = requests.post(f"{BASE}/api/waste/batches/{batch_id}/ship", headers=auth_header(safety01_tok))
        print(f"  批次发运: HTTP {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"    status={d['status']} shipped_at={d.get('shipped_at')}")
        else:
            print(f"    ERR: {r.text[:200]}")

        # 2e. 接收
        r = requests.post(f"{BASE}/api/waste/batches/{batch_id}/receive", headers=auth_header(safety01_tok))
        print(f"  批次接收: HTTP {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"    status={d['status']} received_at={d.get('received_at')}")
            waste_status_list = [w["status"] for w in d["waste_records"]]
            print(f"    废液记录状态: {waste_status_list}")
        else:
            print(f"    ERR: {r.text[:200]}")

print("\n" + "=" * 60)
print("【3/5】废液完整流转痕迹和事件中心验证")

if waste_id:
    r = requests.get(f"{BASE}/api/audit-trails", params={
        "business_type": "waste", "business_id": waste_id
    }, headers=auth_header(admin_tok))
    if r.status_code == 200:
        trails = r.json()
        print(f"  审计痕迹总数={len(trails)} 条:")
        for t in trails:
            dur = t.get("duration_seconds")
            dur_str = f"{dur}s" if dur is not None else "-"
            print(f"    [{t['stage_name']}] {t['from_status']} → {t['to_status']}  耗时:{dur_str}  处理人:{t['operator_name']}  意见:{(t.get('comment') or '')[:50]}")

    r = requests.get(f"{BASE}/api/events", params={"business_type": "waste", "business_id": waste_id}, headers=auth_header(admin_tok))
    if r.status_code == 200:
        events = r.json()
        print(f"  事件中心waste类={len(events)} 条:")
        for ev in events:
            print(f"    [{ev['event_type']}] {ev['handle_status']} {ev['title'][:50]} → detail_url={ev['detail_url']}")

print("\n" + "=" * 60)
print("【4/5】催办引擎手动触发测试")
r = requests.post(f"{BASE}/api/dashboard/trigger-reminders", headers=auth_header(admin_tok))
print(f"  HTTP {r.status_code}")
if r.status_code == 200:
    res = r.json()
    print(f"    总催办={res.get('total_reminded')} 总升级={res.get('total_escalated')}")
    print(f"    明细: {json.dumps(res.get('detail'), ensure_ascii=False)}")

print("\n" + "=" * 60)
print("【5/5】催办后新增验证事件中心")
r = requests.get(f"{BASE}/api/events", params={"event_type": "reminder"}, headers=auth_header(admin_tok))
if r.status_code == 200:
    events = r.json()
    print(f"  催办事件数={len(events)}")
    for ev in events[:5]:
        print(f"    [{ev['business_type']} {ev['title'][:40]}  status={ev['handle_status']}")

r = requests.get(f"{BASE}/api/events", params={"event_type": "reminder_escalate"}, headers=auth_header(admin_tok))
if r.status_code == 200:
    events = r.json()
    print(f"  催办升级事件数={len(events)}")
    for ev in events[:5]:
        print(f"    [{ev['business_type']} {ev['title'][:40]}")

print("\n✅ 全部完成!")

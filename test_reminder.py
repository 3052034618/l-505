"""
催办/升级专项测试
- 通过API创建各类业务数据
- 直接修改数据库created_at为10小时前（超过催办阈值）
- 手动触发催办引擎
- 验证事件中心+流转痕迹出现催办/升级记录
"""
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import SessionLocal
import models

BASE = "http://127.0.0.1:8000"

def login(u, p):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": u, "password": p})
    return r.json()["access_token"]

def h(tok):
    return {"Authorization": f"Bearer {tok}"}

admin_tok = login("admin", "admin123")
superv01_tok = login("superv01", "sup123456")
res01_tok = login("res01", "res123456")
labmgr01_tok = login("labmgr01", "lab123456")

print("=" * 60)
print("催办/升级专项测试")

# 1. 研究员提交领用申请（需要导师审批）
print("\n① 研究员提交领用申请...")
r = requests.get(f"{BASE}/api/chemicals?lab_id=1", headers=h(res01_tok))
chems = r.json()
methanol = next((c for c in chems if "甲醇" in c["name"]), chems[0])
r = requests.post(f"{BASE}/api/usage", json={
    "lab_id": 1,
    "chemical_id": methanol["id"],
    "project_type": "organic_synthesis",
    "project_name": "有机溶剂测试项目",
    "requested_quantity": 30.0,
    "unit": "ml",
    "purpose": "实验用途",
}, headers=h(res01_tok))
print(f"   HTTP {r.status_code}")
if r.status_code != 200:
    print(f"   ERR: {r.text[:300]}")
usage = r.json()
usage_id = usage["id"]
usage_no = usage["request_no"]
print(f"   领用id={usage_id} no={usage_no} status={usage['status']}")

# 2. 主任提交补货申请（需要主任审批）
print("\n② 主任提交补货申请（模拟低库存）...")
r = requests.post(f"{BASE}/api/replenishment", params={
    "chemical_id": methanol["id"],
    "requested_quantity": 5.0,
    "unit": "L",
    "reason": "即将用尽，需紧急补充",
}, headers=h(labmgr01_tok))
print(f"   HTTP {r.status_code}")
if r.status_code != 200:
    print(f"   ERR: {r.text[:300]}")
rep = r.json()
rep_id = rep["id"]
rep_no = rep["request_no"]
print(f"   补货id={rep_id} no={rep_no} status={rep['status']}")

# 3. 研究员提交废液（需要安环检查）
print("\n③ 研究员提交废液...")
r = requests.post(f"{BASE}/api/waste", json={
    "chemical_id": methanol["id"],
    "lab_id": 1,
    "waste_type": "flammable",
    "quantity": 3.0,
    "unit": "L",
    "container_no": "REM-TEST-001",
    "container_type": "密封桶",
}, headers=h(res01_tok))
print(f"   HTTP {r.status_code}")
waste = r.json()
waste_id = waste["id"]
print(f"   废液id={waste_id} status={waste['status']}")

# 4. 直接改数据库把created_at往前推10小时（超过催办阈值4h，升级阈值8h）
print("\n④ 回拨created_at 15小时（超过催办4h + 升级8h = 12h阈值）...")
db = SessionLocal()
ago_15h = datetime.utcnow() - timedelta(hours=15)

db.query(models.UsageRequest).filter(models.UsageRequest.id == usage_id).update(
    {"created_at": ago_15h, "status": "supervisor_pending", "reminder_sent_count": 0, "last_reminder_sent_at": None, "reminder_level": 0}
)
db.query(models.ReplenishmentRequest).filter(models.ReplenishmentRequest.id == rep_id).update(
    {"created_at": ago_15h, "status": "pending_lab_manager", "reminder_sent_count": 0, "last_reminder_sent_at": None, "reminder_level": 0}
)
db.query(models.WasteRecord).filter(models.WasteRecord.id == waste_id).update(
    {"created_at": ago_15h, "status": "pending_inspection", "reminder_sent_count": 0, "last_reminder_sent_at": None, "reminder_level": 0}
)
db.commit()
print(f"   已回拨: 领用#{usage_id} / 补货#{rep_id} / 废液#{waste_id}")

# 5. 触发催办引擎
print("\n⑤ 手动触发催办引擎...")
r = requests.post(f"{BASE}/api/dashboard/trigger-reminders", headers=h(admin_tok))
print(f"   HTTP {r.status_code}")
res = r.json()
print(f"   总催办={res.get('total_reminded')} 总升级={res.get('total_escalated')}")
for k, v in res.get("detail", {}).items():
    print(f"     - {k}: {v}")

# 6. 再次触发（已经催办过了，把last_reminder_sent_at再往前拨5小时，绕过发送间隔）
print("\n⑥ 模拟5小时后再次触发（应该升级）...")
db2 = SessionLocal()
ago_5h_from_reminder = datetime.utcnow() - timedelta(hours=5)
db2.query(models.UsageRequest).filter(models.UsageRequest.id == usage_id).update(
    {"last_reminder_sent_at": ago_5h_from_reminder}
)
db2.query(models.ReplenishmentRequest).filter(models.ReplenishmentRequest.id == rep_id).update(
    {"last_reminder_sent_at": ago_5h_from_reminder}
)
db2.query(models.WasteRecord).filter(models.WasteRecord.id == waste_id).update(
    {"last_reminder_sent_at": ago_5h_from_reminder}
)
db2.commit()
db2.close()

r = requests.post(f"{BASE}/api/dashboard/trigger-reminders", headers=h(admin_tok))
print(f"   HTTP {r.status_code}")
res2 = r.json()
print(f"   总催办={res2.get('total_reminded')} 总升级={res2.get('total_escalated')}")
for k, v in res2.get("detail", {}).items():
    print(f"     - {k}: {v}")

# 7. 查看事件中心催办/升级事件
print("\n⑦ 事件中心 - 催办事件:")
r = requests.get(f"{BASE}/api/events", params={"event_type": "reminder"}, headers=h(admin_tok))
events = r.json()
for ev in events:
    print(f"   [{ev['business_type']}] {ev['title'][:60]}  handle_status={ev['handle_status']}  detail={ev.get('detail_url')}")

print("\n⑧ 事件中心 - 催办升级事件:")
r = requests.get(f"{BASE}/api/events", params={"event_type": "reminder_escalate"}, headers=h(admin_tok))
events = r.json()
for ev in events:
    print(f"   [{ev['business_type']}] {ev['title'][:60]}  handle_status={ev['handle_status']}  detail={ev.get('detail_url')}")

# 8. 查看审计痕迹
print("\n⑨ 领用申请流转痕迹:")
r = requests.get(f"{BASE}/api/audit-trails", params={"business_type": "usage", "business_id": usage_id}, headers=h(admin_tok))
trails = r.json()
for t in trails:
    print(f"   [{t['stage_name']}] {t['from_status']}->{t['to_status']} by {t['operator_name']}  comment={(t.get('comment') or '')[:40]}")

print("\n⑩ 补货申请流转痕迹:")
r = requests.get(f"{BASE}/api/audit-trails", params={"business_type": "replenishment", "business_id": rep_id}, headers=h(admin_tok))
trails = r.json()
for t in trails:
    print(f"   [{t['stage_name']}] {t['from_status']}->{t['to_status']} by {t['operator_name']}  comment={(t.get('comment') or '')[:40]}")

print("\n⑪ 废液记录流转痕迹:")
r = requests.get(f"{BASE}/api/audit-trails", params={"business_type": "waste", "business_id": waste_id}, headers=h(admin_tok))
trails = r.json()
for t in trails:
    print(f"   [{t['stage_name']}] {t['from_status']}->{t['to_status']} by {t['operator_name']}  comment={(t.get('comment') or '')[:40]}")

db.close()
print("\n✅ 催办/升级专项测试完成!")

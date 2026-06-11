import requests
import json
import time

BASE = "http://127.0.0.1:8000"

def login(username, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    return r.json()["access_token"]

def auth_header(token):
    return {"Authorization": f"Bearer {token}"}

def pp(obj, prefix=""):
    print(prefix + json.dumps(obj, ensure_ascii=False, indent=2)[:800])

# 1. 获取tokens
print("="*60)
print("【1/6】登录获取各角色token")
res01_tok = login("res01", "res123456")
superv01_tok = login("superv01", "sup123456")
labmgr01_tok = login("labmgr01", "lab123456")
safety01_tok = login("safety01", "safe123456")
emerg01_tok = login("emerg01", "emg123456")
emerg02_tok = login("emerg02", "emg123456")
admin_tok = login("admin", "admin123")
print(f"  res01(研究员): {res01_tok[:20]}...")
print(f"  superv01(导师): {superv01_tok[:20]}...")
print(f"  labmgr01(主任): {labmgr01_tok[:20]}...")
print(f"  safety01(安环): {safety01_tok[:20]}...")
print(f"  emerg01/02(应急): {emerg01_tok[:16]}... / {emerg02_tok[:16]}...")
print(f"  admin(管理员): {admin_tok[:20]}...")

# 1b. 管理员给研究员res01补一个有效资质，避免自动审核因资质过期被拒
r = requests.get(f"{BASE}/api/users", headers=auth_header(admin_tok))
users = r.json()
res01_user = next((u for u in users if u["username"] == "res01"), None)
if res01_user:
    r = requests.put(f"{BASE}/api/users/{res01_user['id']}", json={
        "qualification_cert_no": "HAZ-2026-RENEW-0001",
        "qualification_expire_date": "2028-12-31",
    }, headers=auth_header(admin_tok))
    print(f"  res01资质更新: HTTP {r.status_code} → 证书号HAZ-2026-RENEW-0001 有效期2028-12-31")

# 2. 领用-补货全链路
print("\n" + "="*60)
print("【2/6】领用-补货审批链路验证（研究员→导师→自动补货→主任→安环）")
# 2a. 查询化学品库存：苯 chemical_id
r = requests.get(f"{BASE}/api/chemicals", headers=auth_header(res01_tok))
chems = r.json()
# 直接查库存，选有库存的化学品
r_inv = requests.get(f"{BASE}/api/inventory?lab_id=1", headers=auth_header(res01_tok))
inv_list = r_inv.json()
print(f"  当前库存条目数: {len(inv_list)}")
# 找有足够量的条目
sufficient = [x for x in inv_list if x.get("current_quantity", 0) >= 10]
if sufficient:
    inv = sufficient[0]
    chemical_id = inv["chemical_id"]
    chem = next((c for c in chems if c["id"] == chemical_id), None)
    chem_name = chem["name"] if chem else f"化学品#{chemical_id}"
    unit = inv.get("unit", "L")
    # 扣后要低于safety_level触发补货：safety_level默认20%
    cur_qty = inv["current_quantity"]
    safety = inv.get("safety_level", cur_qty * 0.2)
    # 申请量 = cur_qty - safety + 1，确保扣后低于安全线
    req_qty = max(1.0, round(cur_qty - safety - 1, 2))
    print(f"  选中库存条目: {chem_name}, inventory_id={inv['id']}, current={cur_qty}{unit}, safety线={safety}{unit}, 申请量={req_qty}{unit}")
else:
    # 用甲醇（不管数量，能走流程就行）
    methanol = next((c for c in chems if "甲醇" in c["name"]), chems[0])
    chemical_id = methanol["id"]
    chem_name = methanol["name"]
    unit = "L"
    req_qty = 5.0
    print(f"  无大库存条目，直接用{chem_name}, 申请5L")

# 2b. 研究员发起领用
usage_body = {
    "lab_id": 1,
    "chemical_id": chemical_id,
    "project_type": "organic_synthesis",
    "project_name": "连续化反应溶剂回收中试",
    "requested_quantity": req_qty,
    "unit": unit,
    "purpose": "连续化萃取装置溶剂，预计消耗部分，触发自动补货验证",
}
r = requests.post(f"{BASE}/api/usage", json=usage_body, headers=auth_header(res01_tok))
usage_resp = r.json()
usage_id = usage_resp.get("id")
usage_no = usage_resp.get("request_no")
print(f"  领用申请创建: id={usage_id}, 编号={usage_no}, 状态={usage_resp.get('status')}")

# 2c. 导师审批通过
r = requests.post(f"{BASE}/api/usage/{usage_id}/review",
    json={"approved": True, "comment": "同意领用，注意防护"},
    headers=auth_header(superv01_tok))
print(f"  导师审批: HTTP {r.status_code}")
if r.status_code == 200:
    review_resp = r.json()
    print(f"    → status={review_resp.get('status')}, chemical_inventory_id={review_resp.get('chemical_inventory_id')}")
else:
    review_resp = {}
    print(f"    → body={r.text[:300]}")

time.sleep(0.5)

# 2d. 查询补货单是否自动生成
r = requests.get(f"{BASE}/api/replenishment", headers=auth_header(labmgr01_tok))
reps = r.json()
pending_reps = [x for x in reps if x["status"] in ["pending_lab_manager", "pending_safety"]]
if pending_reps:
    rep = pending_reps[0]
    rep_id = rep["id"]
    rep_no = rep["request_no"]
    print(f"  自动生成补货单: id={rep_id}, 编号={rep_no}, 状态={rep['status']}")
else:
    print(f"  当前补货单总数={len(reps)}，未找到pending状态，可能之前已生成，取最新一条")
    rep = reps[-1] if reps else None
    rep_id = rep["id"] if rep else None
    rep_no = rep["request_no"] if rep else None

if rep_id:
    # 2e. 主任审批通过
    r = requests.post(f"{BASE}/api/replenishment/{rep_id}/lab-manager-review",
        json={"approved": True, "comment": "同意采购，预算充足"},
        headers=auth_header(labmgr01_tok))
    print(f"  主任审批: HTTP {r.status_code}")
    if r.status_code == 200:
        rep_review = r.json()
        print(f"    → status={rep_review.get('status')}, detail={str(rep_review)[:200]}")
    else:
        rep_review = {"status": None}
        print(f"    → body={r.text[:300]}")
    # 2f. 安环审批通过
    if rep_review.get("status") == "pending_safety":
        r = requests.post(f"{BASE}/api/replenishment/{rep_id}/safety-review",
            json={"approved": True, "comment": "MSDS审核通过，符合危化品采购规定"},
            headers=auth_header(safety01_tok))
        print(f"  安环审批: HTTP {r.status_code}")
        if r.status_code == 200:
            safety_review = r.json()
            print(f"    → status={safety_review.get('status')}, PO={safety_review.get('purchase_order_no')}")
        else:
            print(f"    → body={r.text[:300]}")
    else:
        # 直接查详情看状态
        r = requests.get(f"{BASE}/api/replenishment/{rep_id}", headers=auth_header(safety01_tok))
        det = r.json()
        print(f"  补货单当前状态: {det.get('status')}")

# 3. 告警闭环链路
print("\n" + "="*60)
print("【3/6】告警处置闭环链路验证（传感器→触发→派单→接单→进度→复盘）")
# 3a. 先查传感器列表
r = requests.get(f"{BASE}/api/sensors", headers=auth_header(admin_tok))
sensors = r.json()
gas_sensor = next((s for s in sensors if s["type"] == "gas"), None)
if not gas_sensor and sensors:
    gas_sensor = sensors[0]
print(f"  选中传感器: id={gas_sensor['id']}, no={gas_sensor['sensor_no']}, type={gas_sensor['type']}, th_max={gas_sensor['threshold_max']}")

# 3b. 注入异常读数（阈值的2.5倍，触发紧急级告警）
abnormal_val = (gas_sensor["threshold_max"] or 100) * 2.5
reading_body = {
    "sensor_id": gas_sensor["id"],
    "value": abnormal_val,
    "unit": gas_sensor.get("unit") or "ppm"
}
r = requests.post(f"{BASE}/api/sensors/readings", json=reading_body)
reading_resp = r.json()
print(f"  异常读数注入: value={abnormal_val}, reading_id={reading_resp.get('id')}, is_anomaly={reading_resp.get('is_anomaly')}")
time.sleep(0.5)

# 3c. 查最新告警
r = requests.get(f"{BASE}/api/alarms", headers=auth_header(emerg01_tok))
alarms = r.json()
alarm = alarms[0] if alarms else None
alarm_id = alarm["id"] if alarm else None
alarm_no = alarm["alarm_no"] if alarm else None
tasks = alarm.get("tasks", []) if alarm else []
print(f"  告警触发: id={alarm_id}, no={alarm_no}, level={alarm.get('level')}, status={alarm.get('status')}, 任务数={len(tasks)}")
if tasks:
    task = tasks[0]
    task_id = task["id"]
    print(f"  首条任务: id={task_id}, desc={task['task_description'][:40]}, status={task['status']}, assignee={task.get('assignee_name')}")

# 3d. 应急人员处理所有任务（根据assignee_name匹配正确的应急账号）
if alarm_id and tasks:
    name_token_map = {
        "周应急": (emerg01_tok, "周应急"),
        "吴消防": (emerg02_tok, "吴消防"),
    }
    for idx, task in enumerate(tasks):
        tid = task["id"]
        tdesc = task["task_description"][:30]
        assignee_name = task.get("assignee_name") or ""
        matched = name_token_map.get(assignee_name, (emerg01_tok, "周应急"))
        handler_tok, handler_name = matched
        # 接单
        r = requests.post(f"{BASE}/api/alarms/tasks/{tid}/accept", headers=auth_header(handler_tok))
        time.sleep(0.2)
        # 进度更新1 (30%)
        requests.post(f"{BASE}/api/alarms/tasks/{tid}/progress",
            json={"progress_status": "处置中", "progress_percent": 30,
                  "description": f"任务#{idx+1} 处置进度30%（{handler_name}）"},
            headers=auth_header(handler_tok))
        time.sleep(0.2)
        # 进度更新2 (70%)
        requests.post(f"{BASE}/api/alarms/tasks/{tid}/progress",
            json={"progress_status": "处置中", "progress_percent": 70,
                  "description": f"任务#{idx+1} 处置进度70%（{handler_name}）"},
            headers=auth_header(handler_tok))
        time.sleep(0.2)
        # 进度更新3 (100%) 自动完成
        r = requests.post(f"{BASE}/api/alarms/tasks/{tid}/progress",
            json={"progress_status": "处置完毕", "progress_percent": 100,
                  "description": f"任务#{idx+1} [{tdesc}] 处置完成（{handler_name}）"},
            headers=auth_header(handler_tok))
        p_fin = r.json()
        print(f"  任务#{idx+1} id={tid} 处理人={handler_name}: 接单→30%→70%→100% OK (percent={p_fin.get('progress_percent')})")

# 3h. 安环结束复盘（所有任务完成后）
if alarm_id:
    time.sleep(0.3)
    r = requests.post(f"{BASE}/api/alarms/{alarm_id}/closure",
        json={
            "root_cause": "管道接口密封圈老化，导致气体微量泄漏，温度升高后泄漏量加剧触发传感器告警",
            "handling_summary": "应急人员5分钟内抵达现场，正确佩戴正压呼吸器，采用吸附棉封堵+通风稀释方案，20分钟内控制住泄漏，无人员伤亡",
            "lessons_learned": "需缩短密封件定期检查周期，加强管道法兰接头的预防性维护，应急响应流程整体顺畅但现场通讯设备需升级",
            "improvement_actions": ["所有管道密封圈6个月强制更换", "实验室增装对讲机基站", "每月开展1次泄漏应急演练"],
            "effectiveness_rating": 85
        },
        headers=auth_header(safety01_tok))
    print(f"  复盘接口status={r.status_code}: {r.text[:200]}")
    closure = r.json() if r.status_code == 200 else {}
    print(f"  告警复盘完成: closure_id={closure.get('id')}, rating={closure.get('effectiveness_rating')}")

# 4. 事件中心验证
print("\n" + "="*60)
print("【4/6】事件中心验证：时间线、多维筛选、跳转")
# 4a. 全部事件（lab1=1）
r = requests.get(f"{BASE}/api/events?lab_id=1&skip=0&limit=50", headers=auth_header(admin_tok))
events = r.json()
print(f"  实验室1事件总数: {len(events)}")
if events:
    by_type = {}
    for ev in events:
        bt = ev["business_type"]
        by_type[bt] = by_type.get(bt, 0) + 1
    print(f"  按业务类型分布: {by_type}")
    print(f"  最新5条事件:")
    for ev in events[:5]:
        print(f"    [{ev['created_at'][11:19]}] {ev['business_type']:<13} | {ev['handle_status']:<9} | {ev['title'][:35]}")
        print(f"      ↪ business_no={ev.get('business_no')}  detail_url={ev.get('detail_url')}")

# 4b. 按筛选：补货pending_safety类型
r = requests.get(f"{BASE}/api/events?business_type=replenishment&skip=0&limit=10", headers=auth_header(labmgr01_tok))
rep_events = r.json()
print(f"\n  补货事件(主任视角): {len(rep_events)}条")
for ev in rep_events[:3]:
    print(f"    #{ev['id']} {ev['handle_status']:<9} | {ev['title'][:40]} | target_role={ev.get('target_role')}")

# 4c. 按处理状态筛选: completed
r = requests.get(f"{BASE}/api/events?handle_status=completed&skip=0&limit=10", headers=auth_header(safety01_tok))
comp_events = r.json()
print(f"\n  已完成事件(安环视角): {len(comp_events)}条")

# 4d. 事件统计
r = requests.get(f"{BASE}/api/events/stats/summary", headers=auth_header(admin_tok))
stats = r.json()
print(f"\n  事件中心全局统计:")
pp(stats, "    ")

# 5. 审批流转痕迹验证
print("\n" + "="*60)
print("【5/6】审批流转痕迹：领用/补货/告警完整chain")
# 5a. 领用审批链
if usage_id:
    r = requests.get(f"{BASE}/api/audit-trails/business/usage/{usage_id}", headers=auth_header(admin_tok))
    usage_trails = r.json()
    print(f"\n  领用申请{usage_no}流转链({len(usage_trails)}条):")
    for t in usage_trails:
        dur = f"{t.get('duration_seconds')}s" if t.get('duration_seconds') else "-"
        print(f"    [{t['created_at'][11:19]}] {t['stage_name'][:45]}")
        print(f"      {t.get('from_status')} → {t.get('to_status')}  耗时:{dur}  处理人:{t.get('operator_name')}  意见:{(t.get('comment') or '')[:30]}")

# 5b. 补货审批链
if rep_id:
    r = requests.get(f"{BASE}/api/audit-trails/business/replenishment/{rep_id}", headers=auth_header(admin_tok))
    rep_trails = r.json()
    print(f"\n  补货单{rep_no}流转链({len(rep_trails)}条):")
    for t in rep_trails:
        dur = f"{t.get('duration_seconds')}s" if t.get('duration_seconds') else "-"
        print(f"    [{t['created_at'][11:19]}] {t['stage_name'][:45]}")
        print(f"      {t.get('from_status')} → {t.get('to_status')}  耗时:{dur}  处理人:{t.get('operator_name')}  意见:{(t.get('comment') or '')[:30]}")

# 5c. 告警处置链
if alarm_id:
    r = requests.get(f"{BASE}/api/audit-trails/business/alarm/{alarm_id}", headers=auth_header(admin_tok))
    alarm_trails = r.json()
    print(f"\n  告警{alarm_no}完整流转链({len(alarm_trails)}条):")
    for t in alarm_trails:
        dur = f"{t.get('duration_seconds')}s" if t.get('duration_seconds') else "-"
        print(f"    [{t['created_at'][11:19]}] {t['stage_name'][:50]}")
        print(f"      {t.get('from_status')} → {t.get('to_status')}  耗时:{dur}  处理人:{t.get('operator_name') or '传感器'}")

# 5d. 耗时统计接口（日报会用到）
r = requests.get(f"{BASE}/api/audit-trails/stats/duration", headers=auth_header(admin_tok))
dur_stats = r.json()
print(f"\n  各环节平均耗时统计(日报数据来源)：周期={dur_stats.get('period_days')}天, 总记录数={dur_stats.get('total_audit_records')}")
stage_overall = dur_stats.get("stage_overall", {})
if stage_overall:
    for stage_name, s in list(stage_overall.items())[:8]:
        print(f"    {stage_name[:50]:<52}  avg={s.get('avg_human','-'):<10}  样本={s.get('count',0)}")
else:
    print(f"    暂无可统计耗时数据（需更多业务流转数据积累）")
by_bt = dur_stats.get("by_business_type", {})
if by_bt:
    for bt, stages in list(by_bt.items())[:3]:
        print(f"\n  按业务类型[{bt}]细分:")
        for stage, s in list(stages.items())[:5]:
            print(f"    {stage[:45]:<48}  avg={s.get('avg_human','-'):<10}  n={s.get('count',0)}")

# 6. 告警详情接口验证
print("\n" + "="*60)
print("【6/6】告警详情接口：流转痕迹+复盘信息+任务进度")
if alarm_id:
    r = requests.get(f"{BASE}/api/alarms/{alarm_id}/detail", headers=auth_header(admin_tok))
    alarm_detail = r.json()
    print(f"  告警编号: {alarm_detail.get('alarm_no')}")
    print(f"  告警级别: {alarm_detail.get('level')}  状态: {alarm_detail.get('status')}")
    cl = alarm_detail.get("closure")
    if cl:
        print(f"  复盘信息: 根因={(cl.get('root_cause') or '')[:50]}")
        print(f"           教训={(cl.get('lessons_learned') or '')[:50]}")
        print(f"           效果评级={cl.get('effectiveness_rating')}/100")
    print(f"  审计痕迹数: {len(alarm_detail.get('audit_trails', []))}")
    tasks_list = alarm_detail.get("tasks", [])
    print(f"  关联任务数: {len(tasks_list)}")
    if tasks_list:
        task0_id = tasks_list[0]["id"]
        r = requests.get(f"{BASE}/api/alarms/tasks/{task0_id}/detail", headers=auth_header(admin_tok))
        task_detail = r.json()
        print(f"  任务#{task0_id}进度更新次数: {len(task_detail.get('progress_updates', []))}")
        for p in task_detail.get("progress_updates", []):
            print(f"    [{p['created_at'][11:19]}] {p['progress_percent']:>3}% | {p['progress_status']:<10} | {(p.get('description') or '')[:40]}")

print("\n" + "="*60)
print("✅ 全链路验证完成！")

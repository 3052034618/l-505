# 智慧实验室危险化学品全流程监管与应急调度系统

基于 FastAPI + SQLAlchemy 的智慧实验室危险化学品监管系统后端API。

---

## 🏗️ 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI 0.109.0 | 高性能异步Web框架，自动生成OpenAPI文档 |
| ORM | SQLAlchemy 2.0.25 | Python生态最成熟的ORM |
| 数据库 | SQLite（默认） | 可切换到PostgreSQL/MySQL |
| 认证 | JWT (python-jose) | 无状态Token认证 |
| 密码加密 | bcrypt (passlib) | 行业标准密码哈希 |
| 实时推送 | WebSocket (websockets) | 实时通知推送 |
| 定时任务 | APScheduler 3.10.4 | 每日日报生成 / 补货催办 |
| 数据导出 | CSV / JSON / (可选Excel) | 报表导出功能 |

---

## 🧩 功能模块概览

### 1. 危化品入库 (`/api/inbound`)
- **MSDS自动校验**: 检查危险声明、闪点、毒理数据、存储条件等
- **智能柜位分配**: 基于化学品类别、危害等级、温湿度需求、柜位容量多维度打分匹配
- **温湿度阈值绑定**: 根据MSDS和存储柜条件自动设置阈值
- **不匹配处理**: 拒绝入库 + 自动通知管理员（安全主管）

### 2. 领用申请 (`/api/usage`)
- **资质审核**: 检查操作资质证书编号、有效期（30天内过期提醒）
- **用量偏差校验**: 对比30天历史均值，偏差>200%自动拦截
- **安全权限控制**: 按角色×危害等级限制单次最大申领量
- **导师审批流程**: 偏差超标的需导师(SUPERVISOR)审批解锁
- **替代方案建议**: 高危/致癌物自动推荐同类别低危替代品

### 3. 实时监测与告警 (`/api/sensors`, `/api/alarms`)
- **多类型传感器接入**: 温度 / 湿度 / 气体浓度 / 烟雾 / 压力
- **四级告警分级**: `INFO` → `WARNING` → `CRITICAL` → `EMERGENCY`
- **应急预案匹配**: 基于`化学品类别×危害等级×告警等级×人员密度`
- **应急任务分配**: 就近分配应急小组(EMERGENCY_TEAM)任务

### 4. 废液回收 (`/api/waste`)
- **容器密封性检查**: 模拟扫描结果，不合格退回
- **标签完整性检查**: GHS标签信息校验
- **违规记录**: 不合格的自动记录违规类型
- **转运批次生成**: 关联处理中心资质范围
- **处理中心关联**: 按危废类型匹配合格处置单位

### 5. 库存补货 (`/api/replenishment`)
- **安全水位监控**: `current_quantity ≤ safety_level` 触发低库存告警
- **自动补货申请**: 一键扫描所有低库存条目生成申请
- **两级审批流程**: 实验室主任(LAB_MANAGER) → 安环部门(SAFETY_OFFICER)
- **超时自动催办**: 超过24小时未处理的申请自动推送催办通知
- **采购同步**: 通过后生成采购订单号

### 6. 日报统计 (`/api/reports`)
- **定时自动生成**: 每日凌晨00:00 UTC自动生成昨日日报
- **多维度统计**:
  - 消耗分类统计（按化学品类别）
  - 存储状态（正常/低库存/临期/过期）
  - 告警计数（按等级）
  - 安全事件清单
- **报表导出**: CSV / JSON / (可选XLSX，需安装pandas+openpyxl)
- **按实验室、日期范围筛选**

### 7. 实时通知推送
- **WebSocket端点**: `ws://host:port/ws/notifications?token=<JWT>`
- **实时事件**: 入库结果 / 领用审批结果 / 告警触发 / 废液检查结果
- **多维度推送**: 指定用户、指定实验室、指定角色

### 8. 通知中心 (`/api/notifications`)
- 站内信未读计数
- 已读/全部已读标记
- 按类型筛选

---

## 👥 用户角色权限矩阵

| 角色代码 | 角色名称 | 核心权限 |
|---------|---------|---------|
| `admin` | 系统管理员 | 全部权限，用户管理，系统配置 |
| `lab_manager` | 实验室主任 | 补货审批(第一级)，实验室级配置 |
| `safety_officer` | 安全管理员/安环 | MSDS审核，废液检查，补货审批(第二级)，告警处置 |
| `emergency_team` | 应急小组 | 接收并处置告警任务，应急预案执行 |
| `supervisor` | 导师 | 审批超标/有风险的领用申请 |
| `researcher` | 实验人员/研究员 | 申请领用，提交废液，查询库存 |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

> **可选**: 如需Excel导出功能，额外安装:
> ```bash
> pip install pandas openpyxl
> ```

### 2. 初始化示例数据

```bash
python init_data.py
```

脚本会创建以下测试数据:
- ✅ 3个实验室 (化学/材料/环境)
- ✅ **12个测试账号** (详见下表)
- ✅ 10种典型化学品档案 (甲醇、乙醇、浓硫酸、苯、丙酮等)
- ✅ 6个存储柜 (易燃/腐蚀/剧毒/氧化/综合柜)
- ✅ 12条初始库存记录
- ✅ 9个温湿度/气体传感器
- ✅ 5个应急预案 (通用/易燃/腐蚀/剧毒等)
- ✅ 2个危废处理中心
- ✅ 60条模拟传感器历史读数

### 3. 测试账号速查

所有测试账号密码规则: `角色+123456`（或参考下表）

| 用户名 | 密码 | 真实姓名 | 角色 | 资质到期 |
|-------|-----|---------|------|---------|
| `admin` | `admin123` | 系统管理员 | ADMIN | 永不过期 |
| `labmgr01` | `lab123456` | 陈主任 | LAB_MANAGER | 2026-06-30 |
| `safety01` | `safe123456` | 赵安全员 | SAFETY_OFFICER | 2025-12-31 |
| `safety02` | `safe123456` | 孙安环 | SAFETY_OFFICER | 2025-08-15 |
| `emerg01` | `emg123456` | 周应急 | EMERGENCY_TEAM | 2025-10-01 |
| `emerg02` | `emg123456` | 吴消防 | EMERGENCY_TEAM | 2026-03-15 |
| `superv01` | `sup123456` | 刘导师 | SUPERVISOR | 2027-01-01 |
| `superv02` | `sup123456` | 郑导师 | SUPERVISOR | 2026-11-30 |
| `res01` | `res123456` | 黄研究员 | RESEARCHER | 2025-05-20 ⚠️临期 |
| `res02` | `res123456` | 林实验员 | RESEARCHER | 2026-08-01 |
| `res03` | `res123456` | 徐博后 | RESEARCHER | 2025-02-28 ⚠️临期 |
| `res04_expired` | `res123456` | 实习生小何 | RESEARCHER | **2024-12-01 已过期** ❌ |

### 4. 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 访问文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- 健康检查: http://localhost:8000/api/health

---

## 🧪 核心场景测试指南

登录后获取JWT Token，Swagger UI右上角「Authorize」按钮填入。

### 场景一: 危化品入库 (MSDS校验+柜位分配)
1. `POST /api/inbound` 提交入库请求
   - 化学品ID=4 (浓硫酸) → 应匹配 `CAB-C-001 腐蚀品柜`
   - 化学品ID=5 (苯，致癌) → 应匹配 `CAB-X-001 剧毒柜`
2. 观察返回的 `msds_verification` 和 `cabinet_allocation`
3. 尝试MSDS字段缺失的情况，应被拒绝入库

### 场景二: 领用申请 (资质+用量偏差+审批)
1. 用 `res04_expired` (资质过期) 登录，申请任意化学品 → 自动拒绝
2. 用 `res01` 登录，申请化学品ID=5 (苯)，数量=5 L (远超权限) → 拦截+建议替代
3. 用 `res01` 登录，申请数量为历史均值2.5倍 → 状态为 `SUPERVISOR_PENDING`
4. 切换 `superv01` 登录，`POST /api/usage/{id}/review` 审批通过

### 场景三: 传感器触发告警+应急调度
1. `POST /api/sensors/readings` 上报温度读数25°C到传感器ID=2 (阈值0-15°C)
2. 系统自动:
   - 标记得 `is_anomaly=true`
   - 生成 `AL-*` 告警记录 (WARNING级别)
   - 匹配最适合的应急预案
   - 分配应急小组任务
3. 用 `emerg01` 登录，查看 `/api/alarms/tasks/mine` 处理任务

### 场景四: 废液回收检查+转运批次
1. 研究员提交: `POST /api/waste`
2. 安全员检查: `POST /api/waste/{id}/inspect` (故意设置密封性=false)
   - 状态变为 `INSPECTION_FAILED`
   - 自动创建违规记录
3. 重新提交并通过检查，创建转运批次: `POST /api/waste/batches`

### 场景五: 补货两级审批流程
1. `POST /api/replenishment/auto-generate` 扫描低库存 (甲醇等会自动生成)
2. 用 `labmgr01` 登录，`POST /api/replenishment/{id}/lab-manager-review` 批准
3. 状态切换到 `PENDING_SAFETY`
4. 用 `safety01` 登录，`POST /api/replenishment/{id}/safety-review` 批准
5. 状态切换到 `SYNCED_TO_PURCHASE`，自动生成采购单号

### 场景六: 日报生成与导出
1. 手动触发: `POST /api/reports/generate` (可选参数 `report_date`)
2. 查询日报列表: `GET /api/reports`
3. 导出报表:
   - CSV: `/api/reports/export/csv?report_date=2026-06-11`
   - JSON: `/api/reports/export/json?lab_id=1`

### 场景七: WebSocket实时推送
1. 用admin登录获取token
2. 连接 `ws://localhost:8000/ws/notifications?token=<jwt_token>`
3. 在另一个窗口执行「场景三」触发告警
4. WebSocket窗口应实时收到 `alarm` 类型消息

---

## 📁 项目结构

```
├── main.py                 # FastAPI主入口，路由注册+定时任务
├── config.py               # 应用配置 (密钥/数据库URL/调度时间)
├── database.py             # SQLAlchemy引擎与会话
├── models.py               # 所有数据库ORM模型 (20+张表)
├── schemas.py              # Pydantic请求/响应模型
├── auth.py                 # JWT认证、密码哈希、角色权限装饰器
├── notification_service.py # 站内通知服务
├── init_data.py            # 示例数据初始化脚本
├── requirements.txt        # Python依赖
└── routers/
    ├── __init__.py
    ├── auth.py             # 登录、用户管理
    ├── base.py             # 实验室/化学品/存储柜/库存
    ├── inbound.py          # 入库(MSDS+柜位)
    ├── usage.py            # 领用申请+审批
    ├── alarm.py            # 传感器/告警/应急预案
    ├── waste.py            # 废液/处理中心/补货
    ├── report.py           # 日报/导出/通知中心
    └── websocket.py        # WebSocket实时推送
```

---

## ⚙️ 环境变量配置

可通过 `.env` 文件或系统环境变量覆盖 `config.py` 中的默认值:

| 变量名 | 默认值 | 说明 |
|-------|-------|------|
| `SECRET_KEY` | `your-secret-key-...` | **生产环境必须修改**，JWT签名密钥 |
| `DATABASE_URL` | `sqlite:///./chemical_lab.db` | 数据库连接串，PostgreSQL示例: `postgresql://user:pwd@host/db` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` (24h) | Token有效期(分钟) |
| `DAILY_REPORT_HOUR` | `0` | 日报生成小时(UTC) |
| `DAILY_REPORT_MINUTE` | `0` | 日报生成分钟(UTC) |
| `DEBUG` | `True` | 调试模式开关 |

---

## 🔐 安全最佳实践 (部署前必看)

1. **修改 SECRET_KEY**: 使用 `openssl rand -hex 32` 生成
2. **切换到 PostgreSQL/MySQL**: SQLite仅适用于开发环境
3. **启用HTTPS**: 生产环境必须通过反向代理(Nginx/Caddy)启用TLS
4. **配置CORS**: 将 `config.py` 中 `CORS_ORIGINS=["*"]` 改为实际前端域名
5. **定期轮换**: JWT有效期建议缩短到几小时，引入Refresh Token机制
6. **操作审计**: 可扩展 `Notification` 模型作为审计日志用途

---

## 📊 API统计

| 分类 | 路由数 | 说明 |
|-----|-------|-----|
| 认证与用户 | ~8 | 登录/登出、CRUD、角色管理 |
| 基础配置 | ~20 | 实验室、化学品、柜位、库存、传感器 |
| 入库管理 | ~2 | 入库申请、列表 |
| 领用管理 | ~4 | 申请、列表、导师审批 |
| 告警与应急 | ~12 | 读数上报、告警CRUD、任务处理、预案管理 |
| 废液管理 | ~8 | 提交、检查、批次、处理中心 |
| 补货管理 | ~7 | 创建/自动生成、两级审批、催办 |
| 日报统计 | ~8 | 生成、查询、CSV/JSON/Excel导出 |
| 通知中心 | ~4 | 列表、未读数、标记已读 |
| WebSocket | 1 | 实时推送 |
| **合计** | **~70** | 完整业务闭环API |

---

## 📝 License

本项目仅作为示例演示用途。

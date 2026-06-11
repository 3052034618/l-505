"""
示例数据初始化脚本
运行方式: python init_data.py
"""
import sys
from datetime import datetime, date, timedelta
from database import engine, SessionLocal
from auth import get_password_hash
import models


def init_database():
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    print("✅ 数据库表已重新创建")

    db = SessionLocal()
    try:
        print("\n📝 创建实验室...")
        lab1 = models.Laboratory(
            name="化学与分子工程实验室",
            code="LAB-CHEM-001",
            building="理学楼A座",
            floor=3,
            room_no="A301-A308",
            director="张教授",
            contact_phone="13800138001",
            personnel_count=25,
            is_active=True
        )
        lab2 = models.Laboratory(
            name="材料科学实验室",
            code="LAB-MAT-001",
            building="工学楼B座",
            floor=2,
            room_no="B201-B205",
            director="李教授",
            contact_phone="13800138002",
            personnel_count=18,
            is_active=True
        )
        lab3 = models.Laboratory(
            name="环境分析实验室",
            code="LAB-ENV-001",
            building="环工楼C座",
            floor=1,
            room_no="C101-C104",
            director="王教授",
            contact_phone="13800138003",
            personnel_count=12,
            is_active=True
        )
        db.add_all([lab1, lab2, lab3])
        db.flush()
        print(f"   ✅ 创建了 3 个实验室 (ID: {lab1.id}, {lab2.id}, {lab3.id})")

        print("\n📝 创建用户账号...")
        users_data = [
            {"username": "admin", "password": "admin123", "real_name": "系统管理员", "role": models.UserRole.ADMIN,
             "email": "admin@lab.edu.cn", "phone": "13900000000", "lab_id": None,
             "department": "信息中心", "qualification_cert_no": "ADMIN-CERT-001",
             "qualification_expire_date": date(2099, 12, 31)},
            {"username": "labmgr01", "password": "lab123456", "real_name": "陈主任", "role": models.UserRole.LAB_MANAGER,
             "email": "chenzhuren@lab.edu.cn", "phone": "13800138011", "lab_id": lab1.id,
             "department": "化学学院", "qualification_cert_no": "LABMGR-2023-0001",
             "qualification_expire_date": date(2026, 6, 30)},
            {"username": "safety01", "password": "safe123456", "real_name": "赵安全员", "role": models.UserRole.SAFETY_OFFICER,
             "email": "zhaoanquan@lab.edu.cn", "phone": "13800138021", "lab_id": None,
             "department": "安全环保部", "qualification_cert_no": "SAFETY-2023-0001",
             "qualification_expire_date": date(2025, 12, 31)},
            {"username": "safety02", "password": "safe123456", "real_name": "孙安环", "role": models.UserRole.SAFETY_OFFICER,
             "email": "sunanhuan@lab.edu.cn", "phone": "13800138022", "lab_id": lab2.id,
             "department": "安全环保部", "qualification_cert_no": "SAFETY-2023-0002",
             "qualification_expire_date": date(2025, 8, 15)},
            {"username": "emerg01", "password": "emg123456", "real_name": "周应急", "role": models.UserRole.EMERGENCY_TEAM,
             "email": "zhouyingji@lab.edu.cn", "phone": "13800138031", "lab_id": lab1.id,
             "department": "保卫处应急一队", "qualification_cert_no": "EMG-2023-0001",
             "qualification_expire_date": date(2025, 10, 1)},
            {"username": "emerg02", "password": "emg123456", "real_name": "吴消防", "role": models.UserRole.EMERGENCY_TEAM,
             "email": "wuxiaofang@lab.edu.cn", "phone": "13800138032", "lab_id": lab2.id,
             "department": "保卫处应急二队", "qualification_cert_no": "EMG-2023-0002",
             "qualification_expire_date": date(2026, 3, 15)},
            {"username": "superv01", "password": "sup123456", "real_name": "刘导师", "role": models.UserRole.SUPERVISOR,
             "email": "liudaoshi@lab.edu.cn", "phone": "13800138041", "lab_id": lab1.id,
             "department": "化学学院有机所", "qualification_cert_no": "SUP-2022-0001",
             "qualification_expire_date": date(2027, 1, 1)},
            {"username": "superv02", "password": "sup123456", "real_name": "郑导师", "role": models.UserRole.SUPERVISOR,
             "email": "zhengdaoshi@lab.edu.cn", "phone": "13800138042", "lab_id": lab2.id,
             "department": "材料学院高分子所", "qualification_cert_no": "SUP-2022-0002",
             "qualification_expire_date": date(2026, 11, 30)},
            {"username": "res01", "password": "res123456", "real_name": "黄研究员", "role": models.UserRole.RESEARCHER,
             "email": "huangyanjiu@lab.edu.cn", "phone": "13800138051", "lab_id": lab1.id,
             "department": "化学学院", "qualification_cert_no": "RES-2024-0001",
             "qualification_expire_date": date(2025, 5, 20)},
            {"username": "res02", "password": "res123456", "real_name": "林实验员", "role": models.UserRole.RESEARCHER,
             "email": "linshiyan@lab.edu.cn", "phone": "13800138052", "lab_id": lab1.id,
             "department": "化学学院", "qualification_cert_no": "RES-2024-0002",
             "qualification_expire_date": date(2026, 8, 1)},
            {"username": "res03", "password": "res123456", "real_name": "徐博后", "role": models.UserRole.RESEARCHER,
             "email": "xubohou@lab.edu.cn", "phone": "13800138053", "lab_id": lab2.id,
             "department": "材料学院", "qualification_cert_no": "RES-2023-0015",
             "qualification_expire_date": date(2025, 2, 28)},
            {"username": "res04_expired", "password": "res123456", "real_name": "实习生小何", "role": models.UserRole.RESEARCHER,
             "email": "heshixi@lab.edu.cn", "phone": "13800138054", "lab_id": lab3.id,
             "department": "环境学院", "qualification_cert_no": "RES-2023-0020",
             "qualification_expire_date": date(2024, 12, 1)},
        ]

        created_users = []
        for ud in users_data:
            pw_hash = get_password_hash(ud["password"])
            user = models.User(
                username=ud["username"],
                password_hash=pw_hash,
                real_name=ud["real_name"],
                email=ud["email"],
                phone=ud["phone"],
                role=ud["role"],
                lab_id=ud["lab_id"],
                department=ud["department"],
                qualification_cert_no=ud["qualification_cert_no"],
                qualification_expire_date=ud["qualification_expire_date"],
                is_active=True
            )
            db.add(user)
            created_users.append(user)
        db.flush()
        print(f"   ✅ 创建了 {len(created_users)} 个用户账号:")
        for u in created_users:
            ud = next(x for x in users_data if x["username"] == u.username)
            print(f"       - {u.username:15s} / {ud['password']:12s} ({u.real_name} - {u.role.value})")

        print("\n📝 创建化学品档案...")
        chemicals_data = [
            {
                "name": "甲醇 (Methanol)", "cas_no": "67-56-1", "formula": "CH3OH",
                "molecular_weight": 32.04, "category": models.ChemicalCategory.FLAMMABLE,
                "hazard_level": models.HazardLevel.HIGH, "signal_word": "Danger",
                "hazard_statements": ["H225", "H301", "H311", "H331", "H370"],
                "precautionary_statements": ["P210", "P301+P310", "P302+P352"],
                "flash_point": 11.0, "boiling_point": 64.7, "solubility": "与水混溶",
                "ppe_required": ["护目镜", "丁腈手套", "实验服", "通风橱"],
                "storage_temp_min": 2.0, "storage_temp_max": 8.0,
                "storage_humidity_min": 30.0, "storage_humidity_max": 60.0,
                "incompatible_chemicals": ["强氧化剂", "酸类"],
                "emergency_procedure": "立即移至新鲜空气处，皮肤接触用大量清水冲洗，误食立即就医",
                "first_aid_measures": "吸入:新鲜空气;皮肤:清水冲洗15分钟;眼睛:洗眼器冲洗;误食:催吐后就医",
                "lab_id": lab1.id
            },
            {
                "name": "乙醇 (Ethanol)", "cas_no": "64-17-5", "formula": "C2H5OH",
                "molecular_weight": 46.07, "category": models.ChemicalCategory.FLAMMABLE,
                "hazard_level": models.HazardLevel.MEDIUM, "signal_word": "Danger",
                "hazard_statements": ["H225", "H319"],
                "precautionary_statements": ["P210", "P280", "P305+P351+P338"],
                "flash_point": 13.0, "boiling_point": 78.4, "solubility": "与水混溶",
                "ppe_required": ["护目镜", "丁腈手套", "实验服"],
                "storage_temp_min": 2.0, "storage_temp_max": 10.0,
                "storage_humidity_min": 20.0, "storage_humidity_max": 70.0,
                "incompatible_chemicals": ["强氧化剂"],
                "emergency_procedure": "移至通风处，用水冲洗皮肤",
                "first_aid_measures": "常规急救处理",
                "lab_id": lab1.id
            },
            {
                "name": "浓硫酸 (Sulfuric Acid)", "cas_no": "7664-93-9", "formula": "H2SO4",
                "molecular_weight": 98.08, "category": models.ChemicalCategory.CORROSIVE,
                "hazard_level": models.HazardLevel.HIGH, "signal_word": "Danger",
                "hazard_statements": ["H260", "H290", "H314", "H330"],
                "precautionary_statements": ["P260", "P280", "P305+P351+P338", "P310"],
                "flash_point": None, "boiling_point": 337.0, "solubility": "与水混溶并放热",
                "ppe_required": ["面屏", "耐酸碱手套", "耐酸碱实验服", "防毒面具"],
                "storage_temp_min": 5.0, "storage_temp_max": 25.0,
                "storage_humidity_min": 20.0, "storage_humidity_max": 50.0,
                "incompatible_chemicals": ["碱类", "有机物", "活泼金属", "水(大量)"],
                "emergency_procedure": "严禁用水直接冲!先用干沙覆盖，再用弱碱中和",
                "first_aid_measures": "皮肤接触:干布擦去后大量清水+小苏打冲洗;眼睛:洗眼器至少15分钟;就医",
                "lab_id": lab1.id
            },
            {
                "name": "氢氧化钠 (Sodium Hydroxide)", "cas_no": "1310-73-2", "formula": "NaOH",
                "molecular_weight": 40.00, "category": models.ChemicalCategory.CORROSIVE,
                "hazard_level": models.HazardLevel.MEDIUM, "signal_word": "Danger",
                "hazard_statements": ["H290", "H314"],
                "precautionary_statements": ["P260", "P280", "P305+P351+P338"],
                "flash_point": None, "boiling_point": 1388.0, "solubility": "易溶于水",
                "ppe_required": ["护目镜", "耐碱手套", "实验服"],
                "storage_temp_min": 5.0, "storage_temp_max": 30.0,
                "storage_humidity_min": 20.0, "storage_humidity_max": 60.0,
                "incompatible_chemicals": ["酸类", "铝、锌等两性金属"],
                "emergency_procedure": "用大量清水冲洗，皮肤可用1%醋酸中和",
                "first_aid_measures": "清水冲洗为主",
                "lab_id": lab1.id
            },
            {
                "name": "苯 (Benzene)", "cas_no": "71-43-2", "formula": "C6H6",
                "molecular_weight": 78.11, "category": models.ChemicalCategory.CARCINOGENIC,
                "hazard_level": models.HazardLevel.EXTREME, "signal_word": "Danger",
                "hazard_statements": ["H225", "H304", "H315", "H319", "H340", "H350", "H372"],
                "precautionary_statements": ["P201", "P202", "P210", "P281", "P308+P313"],
                "flash_point": -11.0, "boiling_point": 80.1, "solubility": "不溶于水",
                "ppe_required": ["全面罩", "丁基橡胶手套", "全封闭实验服", "防爆通风橱"],
                "storage_temp_min": 2.0, "storage_temp_max": 6.0,
                "storage_humidity_min": 30.0, "storage_humidity_max": 50.0,
                "incompatible_chemicals": ["强氧化剂", "卤素"],
                "emergency_procedure": "撤离污染区，大量通风，收集泄漏物，严禁产生火花",
                "first_aid_measures": "立即离开现场，吸氧，皮肤冲洗，长期暴露需医学观察",
                "lab_id": lab1.id
            },
            {
                "name": "硝酸钾 (Potassium Nitrate)", "cas_no": "7757-79-1", "formula": "KNO3",
                "molecular_weight": 101.10, "category": models.ChemicalCategory.OXIDIZING,
                "hazard_level": models.HazardLevel.MEDIUM, "signal_word": "Warning",
                "hazard_statements": ["H272", "H315", "H319", "H335"],
                "precautionary_statements": ["P220", "P280"],
                "flash_point": None, "boiling_point": 400.0, "solubility": "溶于水",
                "ppe_required": ["护目镜", "手套", "实验服"],
                "storage_temp_min": 5.0, "storage_temp_max": 30.0,
                "storage_humidity_min": 20.0, "storage_humidity_max": 60.0,
                "incompatible_chemicals": ["可燃物", "还原剂", "有机物"],
                "emergency_procedure": "避免与有机物接触",
                "first_aid_measures": "常规处理",
                "lab_id": lab2.id
            },
            {
                "name": "重铬酸钾 (Potassium Dichromate)", "cas_no": "7778-50-9", "formula": "K2Cr2O7",
                "molecular_weight": 294.19, "category": models.ChemicalCategory.CARCINOGENIC,
                "hazard_level": models.HazardLevel.EXTREME, "signal_word": "Danger",
                "hazard_statements": ["H272", "H301", "H314", "H317", "H334", "H340", "H350", "H360", "H372", "H410"],
                "precautionary_statements": ["P201", "P202", "P220", "P280", "P308+P313"],
                "flash_point": None, "boiling_point": 500.0, "solubility": "溶于水",
                "ppe_required": ["全面罩", "双层手套", "全封闭防护服"],
                "storage_temp_min": 5.0, "storage_temp_max": 25.0,
                "storage_humidity_min": 20.0, "storage_humidity_max": 50.0,
                "incompatible_chemicals": ["有机物", "还原剂"],
                "emergency_procedure": "严格隔离，所有人员撤离",
                "first_aid_measures": "立即就医",
                "lab_id": lab2.id
            },
            {
                "name": "乙腈 (Acetonitrile)", "cas_no": "75-05-8", "formula": "CH3CN",
                "molecular_weight": 41.05, "category": models.ChemicalCategory.TOXIC,
                "hazard_level": models.HazardLevel.HIGH, "signal_word": "Danger",
                "hazard_statements": ["H225", "H302", "H312", "H332", "H319"],
                "precautionary_statements": ["P210", "P261", "P280", "P305+P351+P338"],
                "flash_point": 2.0, "boiling_point": 81.6, "solubility": "与水混溶",
                "ppe_required": ["护目镜", "丁腈手套", "实验服", "通风橱"],
                "storage_temp_min": 2.0, "storage_temp_max": 8.0,
                "storage_humidity_min": 30.0, "storage_humidity_max": 60.0,
                "incompatible_chemicals": ["强氧化剂", "强酸", "强碱"],
                "emergency_procedure": "通风，皮肤冲洗，需观察氰中毒症状",
                "first_aid_measures": "给氧，皮肤冲洗，若中毒可肌注亚硝酸异戊酯",
                "lab_id": lab3.id
            },
            {
                "name": "丙酮 (Acetone)", "cas_no": "67-64-1", "formula": "(CH3)2CO",
                "molecular_weight": 58.08, "category": models.ChemicalCategory.FLAMMABLE,
                "hazard_level": models.HazardLevel.LOW, "signal_word": "Danger",
                "hazard_statements": ["H225", "H319", "H336"],
                "precautionary_statements": ["P210", "P261", "P280"],
                "flash_point": -20.0, "boiling_point": 56.2, "solubility": "与水混溶",
                "ppe_required": ["护目镜", "手套", "实验服"],
                "storage_temp_min": 2.0, "storage_temp_max": 15.0,
                "storage_humidity_min": 20.0, "storage_humidity_max": 70.0,
                "incompatible_chemicals": ["强氧化剂"],
                "emergency_procedure": "通风即可",
                "first_aid_measures": "常规",
                "lab_id": lab1.id
            },
            {
                "name": "氯化钠 (Sodium Chloride)", "cas_no": "7647-14-5", "formula": "NaCl",
                "molecular_weight": 58.44, "category": models.ChemicalCategory.GENERAL,
                "hazard_level": models.HazardLevel.LOW, "signal_word": "Warning",
                "hazard_statements": ["H319"],
                "precautionary_statements": ["P264", "P280"],
                "flash_point": None, "boiling_point": 1465.0, "solubility": "溶于水",
                "ppe_required": ["护目镜", "手套"],
                "storage_temp_min": 5.0, "storage_temp_max": 35.0,
                "storage_humidity_min": 10.0, "storage_humidity_max": 80.0,
                "incompatible_chemicals": [],
                "emergency_procedure": "无需特殊处理",
                "first_aid_measures": "无需特殊处理",
                "lab_id": lab3.id
            },
        ]

        created_chemicals = []
        for cd in chemicals_data:
            chemical = models.Chemical(**cd)
            db.add(chemical)
            created_chemicals.append(chemical)
        db.flush()
        print(f"   ✅ 创建了 {len(created_chemicals)} 种化学品档案")

        print("\n📝 创建存储柜...")
        cabinets_data = [
            {"cabinet_no": "CAB-F-001", "name": "易燃品柜A", "lab_id": lab1.id,
             "location": "A301-北侧", "allowed_categories": ["flammable", "general"],
             "allowed_hazard_levels": ["low", "medium", "high"],
             "temperature_min": 2.0, "temperature_max": 10.0,
             "humidity_min": 20.0, "humidity_max": 65.0,
             "has_fire_extinguisher": True, "has_ventilation": True, "capacity": 200.0},
            {"cabinet_no": "CAB-F-002", "name": "易燃品柜B", "lab_id": lab1.id,
             "location": "A301-南侧", "allowed_categories": ["flammable"],
             "allowed_hazard_levels": ["low", "medium"],
             "temperature_min": 2.0, "temperature_max": 8.0,
             "humidity_min": 25.0, "humidity_max": 60.0,
             "has_fire_extinguisher": True, "has_ventilation": True, "capacity": 150.0},
            {"cabinet_no": "CAB-C-001", "name": "腐蚀品柜", "lab_id": lab1.id,
             "location": "A303-西侧", "allowed_categories": ["corrosive"],
             "allowed_hazard_levels": ["medium", "high", "extreme"],
             "temperature_min": 5.0, "temperature_max": 25.0,
             "humidity_min": 20.0, "humidity_max": 50.0,
             "has_fire_extinguisher": False, "has_ventilation": True, "capacity": 100.0},
            {"cabinet_no": "CAB-X-001", "name": "剧毒/致癌物柜", "lab_id": lab1.id,
             "location": "A305-保险柜", "allowed_categories": ["toxic", "carcinogenic"],
             "allowed_hazard_levels": ["high", "extreme"],
             "temperature_min": 2.0, "temperature_max": 8.0,
             "humidity_min": 30.0, "humidity_max": 55.0,
             "has_fire_extinguisher": True, "has_ventilation": True, "capacity": 80.0},
            {"cabinet_no": "CAB-O-001", "name": "氧化剂柜", "lab_id": lab2.id,
             "location": "B201-东侧", "allowed_categories": ["oxidizing", "general"],
             "allowed_hazard_levels": ["low", "medium", "high", "extreme"],
             "temperature_min": 5.0, "temperature_max": 30.0,
             "humidity_min": 20.0, "humidity_max": 60.0,
             "has_fire_extinguisher": True, "has_ventilation": False, "capacity": 120.0},
            {"cabinet_no": "CAB-M-001", "name": "综合柜", "lab_id": lab3.id,
             "location": "C102", "allowed_categories": ["toxic", "flammable", "corrosive", "general"],
             "allowed_hazard_levels": ["low", "medium", "high"],
             "temperature_min": 5.0, "temperature_max": 25.0,
             "humidity_min": 30.0, "humidity_max": 65.0,
             "has_fire_extinguisher": True, "has_ventilation": True, "capacity": 180.0},
        ]

        created_cabinets = []
        for cd in cabinets_data:
            cabinet = models.StorageCabinet(**cd)
            db.add(cabinet)
            created_cabinets.append(cabinet)
        db.flush()
        print(f"   ✅ 创建了 {len(created_cabinets)} 个存储柜")

        print("\n📝 创建初始库存...")
        inventories_data = [
            {"chemical": "甲醇 (Methanol)", "cabinet": "CAB-F-001", "batch": "MEOH-202401001",
             "qty": 50.0, "unit": "L", "safety": 10.0,
             "mfr": "国药集团", "prod": date(2024, 1, 15), "exp": date(2027, 1, 14)},
            {"chemical": "乙醇 (Ethanol)", "cabinet": "CAB-F-001", "batch": "ETOH-202402001",
             "qty": 80.0, "unit": "L", "safety": 15.0,
             "mfr": "西陇化工", "prod": date(2024, 2, 20), "exp": date(2027, 2, 19)},
            {"chemical": "乙醇 (Ethanol)", "cabinet": "CAB-F-002", "batch": "ETOH-202401002",
             "qty": 5.0, "unit": "L", "safety": 15.0,
             "mfr": "阿拉丁", "prod": date(2024, 1, 1), "exp": date(2026, 12, 31)},
            {"chemical": "浓硫酸 (Sulfuric Acid)", "cabinet": "CAB-C-001", "batch": "H2SO4-202311005",
             "qty": 20.0, "unit": "L", "safety": 5.0,
             "mfr": "科密欧", "prod": date(2023, 11, 10), "exp": date(2026, 11, 9)},
            {"chemical": "氢氧化钠 (Sodium Hydroxide)", "cabinet": "CAB-C-001", "batch": "NaOH-202403002",
             "qty": 25.0, "unit": "kg", "safety": 5.0,
             "mfr": "国药集团", "prod": date(2024, 3, 1), "exp": date(2028, 2, 28)},
            {"chemical": "苯 (Benzene)", "cabinet": "CAB-X-001", "batch": "BENZ-202401010",
             "qty": 2.5, "unit": "L", "safety": 0.5,
             "mfr": "Sigma-Aldrich", "prod": date(2024, 1, 20), "exp": date(2025, 1, 19)},
            {"chemical": "硝酸钾 (Potassium Nitrate)", "cabinet": "CAB-O-001", "batch": "KNO3-202312001",
             "qty": 15.0, "unit": "kg", "safety": 3.0,
             "mfr": "国药集团", "prod": date(2023, 12, 1), "exp": date(2027, 11, 30)},
            {"chemical": "重铬酸钾 (Potassium Dichromate)", "cabinet": "CAB-O-001", "batch": "K2CR2O7-202402003",
             "qty": 1.0, "unit": "kg", "safety": 0.3,
             "mfr": "阿拉丁", "prod": date(2024, 2, 15), "exp": date(2026, 2, 14)},
            {"chemical": "乙腈 (Acetonitrile)", "cabinet": "CAB-M-001", "batch": "ACN-202402008",
             "qty": 18.0, "unit": "L", "safety": 4.0,
             "mfr": "默克", "prod": date(2024, 2, 1), "exp": date(2025, 8, 1)},
            {"chemical": "丙酮 (Acetone)", "cabinet": "CAB-F-001", "batch": "ACE-202403002",
             "qty": 30.0, "unit": "L", "safety": 8.0,
             "mfr": "国药集团", "prod": date(2024, 3, 5), "exp": date(2026, 3, 4)},
            {"chemical": "氯化钠 (Sodium Chloride)", "cabinet": "CAB-M-001", "batch": "NaCl-202310001",
             "qty": 50.0, "unit": "kg", "safety": 10.0,
             "mfr": "科密欧", "prod": date(2023, 10, 1), "exp": date(2028, 9, 30)},
            {"chemical": "甲醇 (Methanol)", "cabinet": "CAB-F-001", "batch": "MEOH-LOW-001",
             "qty": 2.0, "unit": "L", "safety": 10.0,
             "mfr": "测试低库存", "prod": date(2024, 1, 1), "exp": date(2025, 1, 1)},
        ]

        chemical_map = {c.name: c for c in created_chemicals}
        cabinet_map = {c.cabinet_no: c for c in created_cabinets}

        created_inv_count = 0
        for inv in inventories_data:
            chem = chemical_map.get(inv["chemical"])
            cab = cabinet_map.get(inv["cabinet"])
            if not chem or not cab:
                print(f"   ⚠️ 跳过: 找不到化学品或柜子 {inv['chemical']}/{inv['cabinet']}")
                continue

            temp_min = chem.storage_temp_min if chem.storage_temp_min else cab.temperature_min
            temp_max = chem.storage_temp_max if chem.storage_temp_max else cab.temperature_max
            hum_min = chem.storage_humidity_min if chem.storage_humidity_min else cab.humidity_min
            hum_max = chem.storage_humidity_max if chem.storage_humidity_max else cab.humidity_max

            inventory = models.Inventory(
                chemical_id=chem.id,
                cabinet_id=cab.id,
                batch_no=inv["batch"],
                quantity=inv["qty"],
                unit=inv["unit"],
                current_quantity=inv["qty"],
                safety_level=inv["safety"],
                manufacturer=inv["mfr"],
                production_date=inv["prod"],
                expiry_date=inv["exp"],
                temp_threshold_min=temp_min,
                temp_threshold_max=temp_max,
                humidity_threshold_min=hum_min,
                humidity_threshold_max=hum_max,
                status="low_stock" if inv["qty"] <= inv["safety"] else "normal",
                location_tag=f"{cab.location}/{inv['batch']}"
            )
            db.add(inventory)
            created_inv_count += 1

            cab.current_occupancy = min(cab.capacity, cab.current_occupancy + inv["qty"])

        db.flush()
        print(f"   ✅ 创建了 {created_inv_count} 条初始库存记录")

        print("\n📝 创建传感器...")
        sensors_data = [
            {"sensor_no": "S-TEMP-A301-1", "type": models.SensorType.TEMPERATURE, "lab_id": lab1.id,
             "cabinet_id": None, "location": "A301-柜区", "threshold_min": 0.0, "threshold_max": 15.0},
            {"sensor_no": "S-TEMP-F001-1", "type": models.SensorType.TEMPERATURE, "lab_id": lab1.id,
             "cabinet_id": cabinet_map["CAB-F-001"].id, "location": "易燃品柜A内部", "threshold_min": 2.0, "threshold_max": 10.0},
            {"sensor_no": "S-HUM-F001-1", "type": models.SensorType.HUMIDITY, "lab_id": lab1.id,
             "cabinet_id": cabinet_map["CAB-F-001"].id, "location": "易燃品柜A内部", "threshold_min": 20.0, "threshold_max": 65.0},
            {"sensor_no": "S-TEMP-C001-1", "type": models.SensorType.TEMPERATURE, "lab_id": lab1.id,
             "cabinet_id": cabinet_map["CAB-C-001"].id, "location": "腐蚀品柜内部", "threshold_min": 5.0, "threshold_max": 25.0},
            {"sensor_no": "S-GAS-A301-VOC", "type": models.SensorType.GAS, "gas_type": "VOC", "lab_id": lab1.id,
             "cabinet_id": None, "location": "A301-通风橱排气口", "threshold_min": None, "threshold_max": 100.0},
            {"sensor_no": "S-GAS-X001-LEL", "type": models.SensorType.GAS, "gas_type": "LEL", "lab_id": lab1.id,
             "cabinet_id": cabinet_map["CAB-X-001"].id, "location": "剧毒柜附近", "threshold_min": None, "threshold_max": 25.0},
            {"sensor_no": "S-TEMP-B201-1", "type": models.SensorType.TEMPERATURE, "lab_id": lab2.id,
             "cabinet_id": cabinet_map["CAB-O-001"].id, "location": "氧化剂柜内部", "threshold_min": 5.0, "threshold_max": 30.0},
            {"sensor_no": "S-SMOKE-A301", "type": models.SensorType.SMOKE, "lab_id": lab1.id,
             "cabinet_id": None, "location": "A301-天花板", "threshold_min": None, "threshold_max": 50.0},
            {"sensor_no": "S-TEMP-C102-1", "type": models.SensorType.TEMPERATURE, "lab_id": lab3.id,
             "cabinet_id": cabinet_map["CAB-M-001"].id, "location": "综合柜内部", "threshold_min": 5.0, "threshold_max": 25.0},
        ]
        for sd in sensors_data:
            sensor = models.Sensor(**sd)
            db.add(sensor)
        db.flush()
        print(f"   ✅ 创建了 {len(sensors_data)} 个传感器")

        print("\n📝 创建应急预案...")
        plans_data = [
            {
                "name": "一般易燃液体泄漏预案", "code": "EP-FLAMMABLE-L1",
                "applicable_categories": ["flammable"], "applicable_hazard_levels": ["low", "medium"],
                "applicable_alarm_levels": ["info", "warning"], "priority": 20,
                "min_personnel_density": None, "max_personnel_density": None,
                "steps": [
                    {"step": 1, "description": "穿戴防护手套和护目镜", "priority": 1},
                    {"step": 2, "description": "关闭附近所有火源和电源", "priority": 1},
                    {"step": 3, "description": "开启防爆通风设备", "priority": 2},
                    {"step": 4, "description": "用防溢垫和活性炭收集泄漏物", "priority": 2},
                    {"step": 5, "description": "将收集物密封贴标，等待危废处理", "priority": 3}
                ],
                "required_equipment": ["丁腈手套", "护目镜", "防溢垫", "活性炭", "防爆通风"],
                "evacuation_required": False, "medical_assistance": False, "fire_department": False
            },
            {
                "name": "高等级易燃品火灾预案", "code": "EP-FLAMMABLE-HIGH",
                "applicable_categories": ["flammable"], "applicable_hazard_levels": ["high", "extreme"],
                "applicable_alarm_levels": ["critical", "emergency"], "priority": 5,
                "min_personnel_density": 5.0, "max_personnel_density": None,
                "steps": [
                    {"step": 1, "description": "立即按下手动报警按钮，触发全楼疏散", "priority": 1},
                    {"step": 2, "description": "若安全，尝试切断可燃物来源", "priority": 2},
                    {"step": 3, "description": "使用CO2或干粉灭火器灭火(严禁用水)", "priority": 2},
                    {"step": 4, "description": "组织人员按逃生路线撤离至安全集合点", "priority": 1},
                    {"step": 5, "description": "拨打119并说明化学品类型和数量", "priority": 1},
                    {"step": 6, "description": "清点人数，对受伤人员实施急救", "priority": 3}
                ],
                "required_equipment": ["干粉灭火器", "CO2灭火器", "防火毯", "逃生面罩"],
                "evacuation_required": True, "medical_assistance": True, "fire_department": True
            },
            {
                "name": "腐蚀性化学品泄漏预案", "code": "EP-CORROSIVE",
                "applicable_categories": ["corrosive"], "applicable_hazard_levels": ["medium", "high", "extreme"],
                "applicable_alarm_levels": ["warning", "critical"], "priority": 12,
                "min_personnel_density": None, "max_personnel_density": None,
                "steps": [
                    {"step": 1, "description": "佩戴全面罩和耐酸碱防护服", "priority": 1},
                    {"step": 2, "description": "酸性泄漏用碳酸氢钠中和，碱性泄漏用稀醋酸中和", "priority": 2},
                    {"step": 3, "description": "用吸附材料覆盖，不得直接用水冲", "priority": 2},
                    {"step": 4, "description": "皮肤接触立即用大量清水+中和液冲洗15分钟", "priority": 1},
                    {"step": 5, "description": "收集中和后废弃物按危废处理", "priority": 3}
                ],
                "required_equipment": ["全面罩", "耐酸碱服", "耐酸碱手套", "中和剂", "洗眼器"],
                "evacuation_required": False, "medical_assistance": True, "fire_department": False
            },
            {
                "name": "剧毒/致癌物泄漏预案", "code": "EP-TOXIC-EXTREME",
                "applicable_categories": ["toxic", "carcinogenic"], "applicable_hazard_levels": ["high", "extreme"],
                "applicable_alarm_levels": ["critical", "emergency"], "priority": 2,
                "min_personnel_density": None, "max_personnel_density": None,
                "steps": [
                    {"step": 1, "description": "立即撤离所有非必要人员，封锁区域", "priority": 1},
                    {"step": 2, "description": "专业人员佩戴正压式呼吸器和A级防护服处置", "priority": 1},
                    {"step": 3, "description": "对暴露人员进行医学观察和紧急处理", "priority": 1},
                    {"step": 4, "description": "启动全面通风，监测空气浓度", "priority": 2},
                    {"step": 5, "description": "所有污染物按剧毒危废收集", "priority": 2},
                    {"step": 6, "description": "报告上级主管部门和环保部门", "priority": 3}
                ],
                "required_equipment": ["正压呼吸器", "A级气密防护服", "防爆通风", "有毒气体检测仪"],
                "evacuation_required": True, "medical_assistance": True, "fire_department": False
            },
            {
                "name": "通用应急预案", "code": "EP-GENERAL",
                "applicable_categories": ["explosive", "reactive", "oxidizing", "general"],
                "applicable_hazard_levels": ["low", "medium", "high", "extreme"],
                "applicable_alarm_levels": ["info", "warning", "critical", "emergency"], "priority": 50,
                "min_personnel_density": None, "max_personnel_density": None,
                "steps": [
                    {"step": 1, "description": "评估现场情况，确保个人安全优先", "priority": 1},
                    {"step": 2, "description": "通知安全管理员和应急小组", "priority": 1},
                    {"step": 3, "description": "隔离污染区域，防止无关人员进入", "priority": 2},
                    {"step": 4, "description": "按对应MSDS处置流程操作", "priority": 2},
                    {"step": 5, "description": "记录事件经过并上报", "priority": 3}
                ],
                "required_equipment": ["PPE套装", "应急包", "对讲机"],
                "evacuation_required": False, "medical_assistance": False, "fire_department": False
            },
        ]
        for pd in plans_data:
            plan = models.EmergencyPlan(**pd, is_active=True)
            db.add(plan)
        db.flush()
        print(f"   ✅ 创建了 {len(plans_data)} 个应急预案")

        print("\n📝 创建处理中心...")
        disposal_centers = [
            {"name": "市危废处理中心A", "code": "DISP-A001",
             "address": "XX市XX区环保产业园1号", "contact_person": "处理员A",
             "contact_phone": "010-12345678", "license_no": "HZ-FW-2023-0001",
             "allowed_waste_types": ["flammable", "corrosive", "general", "oxidizing"]},
            {"name": "省危废处置基地B", "code": "DISP-B001",
             "address": "XX省XX市危废产业园", "contact_person": "处理员B",
             "contact_phone": "010-87654321", "license_no": "HZ-FW-2022-0055",
             "allowed_waste_types": ["toxic", "carcinogenic", "reactive", "explosive"]},
        ]
        for dc in disposal_centers:
            d = models.DisposalCenter(**dc, is_active=True)
            db.add(d)
        db.flush()
        print(f"   ✅ 创建了 {len(disposal_centers)} 个废液处理中心")

        print("\n📝 创建一些传感器历史读数...")
        sample_readings = []
        for i in range(50):
            reading = models.SensorReading(
                sensor_id=2,
                value=4.0 + (i % 5) * 0.5,
                unit="°C",
                is_anomaly=False,
                created_at=datetime.utcnow() - timedelta(hours=i)
            )
            sample_readings.append(reading)

        for i in range(10):
            t = 12.0 + i
            reading = models.SensorReading(
                sensor_id=2,
                value=t,
                unit="°C",
                is_anomaly=t > 10.0,
                created_at=datetime.utcnow() - timedelta(days=1, hours=i)
            )
            sample_readings.append(reading)

        db.add_all(sample_readings)
        db.flush()
        print(f"   ✅ 创建了 {len(sample_readings)} 条传感器历史读数")

        db.commit()
        print("\n🎉 示例数据初始化完成!")

        print("\n📌 快速开始:")
        print("   1. 安装依赖: pip install -r requirements.txt")
        print("   2. 启动服务: uvicorn main:app --host 0.0.0.0 --port 8000 --reload")
        print("   3. 打开文档: http://localhost:8000/docs")
        print("   4. 登录账号使用 admin / admin123 (最高权限)")

    except Exception as e:
        db.rollback()
        print(f"❌ 初始化出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print(" 智慧实验室危险化学品监管系统 - 示例数据初始化")
    print("=" * 60)
    init_database()

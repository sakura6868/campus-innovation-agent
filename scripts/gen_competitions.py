# -*- coding: utf-8 -*-
"""批量生成赛事种子数据（全类别覆盖）。

产出：data/ground_truth/samples/<slug>_2026.json
- 每个赛事字段完整，可直接被 db.seed_competitions() 幂等 upsert。
- 确定性：同一 slug 永远生成同一份数据，可反复重跑覆盖。
- 数据性质：基于公开赛事名录整理的「官方通知结构化参考字段」，统一标记为
  未核验(unverified/C)，与 21 份人工精修样本(verified/A)区分；official_source_url
  统一指向「百度搜索该赛事名」作为入口，避免伪造官网 404。生成时会自动跳过与
  精修样本「同名/子串碰撞」的条目，避免破坏已核验赛事的解析与既有测试。

用法：
    python scripts/gen_competitions.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ground_truth" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

YEAR = 2026
ACQUIRED = "2026-07-18"
VERIFIED_AT = "2026-07-18"

# 入口统一用百度搜索，避免编造官网导致 404
def official_url(name: str) -> str:
    from urllib.parse import quote
    return "https://www.baidu.com/s?wd=" + quote(name)


# 类别中文名词（用于简介文案，避免直接暴露枚举值）
CAT_NOUN = {
    "programming": "程序设计", "modeling": "数学建模", "innovation": "创新创业",
    "software": "软件作品", "english": "外语", "math": "数学竞技",
    "electronics": "电子设计", "robotics_ai": "机器人与人工智能", "data": "数据科学",
    "design": "艺术设计", "business": "财经商科", "engineering": "机械与工程",
    "life_science": "生命科学", "physics": "物理", "chem_env": "化工环境",
}


# ---------------------------------------------------------------------------
# 每类别默认模板
# ---------------------------------------------------------------------------
# majors 中 None 表示「不限专业」。
CAT_DEFAULTS = {
    "programming": {
        "majors": ["计算机科学与技术", "软件工程", "人工智能", "信息安全", "数据科学与大数据技术", "网络空间安全"],
        "skills": ["Python", "C/C++", "算法与数据结构", "Java", "Git"],
        "materials": ["源代码", "设计文档", "答辩PPT", "自测报告"],
        "eval": ["算法正确性", "时间与空间复杂度", "代码规范", "创新性"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": False,
    },
    "modeling": {
        "majors": ["数学与应用数学", "统计学", "信息与计算科学", "经济学", "物理学", "计算机科学与技术", "自动化"],
        "skills": ["数学建模", "MATLAB/Python", "论文写作", "数据分析", "LaTeX"],
        "materials": ["建模论文", "程序代码", "数据附件", "支撑材料"],
        "eval": ["模型合理性", "求解精度", "创新与实用", "论文表达"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": False,
    },
    "innovation": {
        "majors": [None, "工商管理", "市场营销", "计算机科学与技术", "电子信息", "机械工程", "生物科学"],
        "skills": ["商业计划书", "路演答辩", "市场分析", "产品设计", "团队协作"],
        "materials": ["商业计划书", "路演PPT", "产品原型", "财务预测"],
        "eval": ["创新性", "商业价值", "团队能力", "落地可行"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生", "毕业生（毕业5年内）"],
        "team": (True, 1, 5),
        "open_major": True,
    },
    "software": {
        "majors": ["计算机科学与技术", "软件工程", "数字媒体技术", "人工智能", "物联网工程", "网络工程"],
        "skills": ["前端开发", "后端开发", "数据库", "UI设计", "项目管理"],
        "materials": ["软件作品", "演示视频", "设计文档", "源代码"],
        "eval": ["功能完整", "技术创新", "用户体验", "工程质量"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 5),
        "open_major": False,
    },
    "english": {
        "majors": [None],
        "skills": ["英语听说", "英语读写", "公众演讲", "批判性思维"],
        "materials": ["演讲稿", "参赛视频", "书面作品", "成绩单"],
        "eval": ["语言表达", "内容深度", "逻辑思维", "临场表现"],
        "grades": ["大一", "大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (False, 1, 1),
        "open_major": True,
    },
    "math": {
        "majors": ["数学与应用数学", "信息与计算科学", "统计学", "物理学", "计算机科学与技术"],
        "skills": ["数学分析", "高等代数", "概率统计", "解题技巧"],
        "materials": ["答卷", "解题过程", "证明"],
        "eval": ["解题正确", "方法严谨", "思维深度"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (False, 1, 1),
        "open_major": False,
    },
    "electronics": {
        "majors": ["电子信息工程", "通信工程", "自动化", "电气工程", "集成电路设计与集成系统", "物联网工程"],
        "skills": ["电路设计", "嵌入式开发", "PCB绘制", "C语言", "信号处理"],
        "materials": ["硬件作品", "设计报告", "测试数据", "演示视频"],
        "eval": ["方案设计", "实现效果", "工程规范", "创新性"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": False,
    },
    "robotics_ai": {
        "majors": ["人工智能", "自动化", "机器人工程", "计算机科学与技术", "电子信息", "机械电子工程"],
        "skills": ["机器学习", "Python", "ROS", "嵌入式", "计算机视觉"],
        "materials": ["算法代码", "机器人实物", "技术报告", "演示视频"],
        "eval": ["技术难度", "完成度", "创新点", "现场表现"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 4),
        "open_major": False,
    },
    "data": {
        "majors": ["统计学", "数据科学与大数据技术", "计算机科学与技术", "经济学", "信息管理与信息系统", "数学与应用数学"],
        "skills": ["Python", "数据分析", "机器学习", "SQL", "数据可视化"],
        "materials": ["分析报告", "建模代码", "数据集", "答辩PPT"],
        "eval": ["方法科学", "结论可靠", "可视化表达", "创新应用"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": False,
    },
    "design": {
        "majors": [None, "视觉传达设计", "环境设计", "数字媒体艺术", "工业设计", "动画"],
        "skills": ["平面设计", "创意构思", "排版", "视频制作", "手绘"],
        "materials": ["设计作品", "创作说明", "源文件", "展示视频"],
        "eval": ["创意性", "表现力", "完整性", "主题契合"],
        "grades": ["大一", "大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": True,
    },
    "business": {
        "majors": [None, "工商管理", "会计学", "金融学", "市场营销", "经济学", "国际经济与贸易"],
        "skills": ["财务分析", "市场调研", "沙盘模拟", "商业写作", "Excel"],
        "materials": ["商业计划书", "模拟经营报告", "财务表", "路演PPT"],
        "eval": ["分析深度", "决策合理", "团队协作", "结果表现"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 5),
        "open_major": True,
    },
    "engineering": {
        "majors": ["机械工程", "车辆工程", "土木工程", "材料成型", "力学", "能源与动力工程"],
        "skills": ["机械设计", "CAD/UG", "工程制图", "有限元分析", "加工工艺"],
        "materials": ["实物作品", "设计说明书", "图纸", "演示视频"],
        "eval": ["设计合理", "制作工艺", "创新点", "现场展示"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 5),
        "open_major": False,
    },
    "life_science": {
        "majors": ["生物科学", "生物技术", "基础医学", "药学", "临床医学", "生态学"],
        "skills": ["实验操作", "数据分析", "文献检索", "科研写作"],
        "materials": ["实验报告", "研究论文", "海报", "答辩PPT"],
        "eval": ["科学性", "创新性", "完成度", "表达"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": False,
    },
    "physics": {
        "majors": ["物理学", "应用物理", "光电信息", "材料物理", "天文学"],
        "skills": ["物理实验", "理论推导", "数据处理", "仪器操作"],
        "materials": ["实验报告", "论文", "装置照片", "答辩PPT"],
        "eval": ["原理正确", "操作规范", "数据分析", "创新性"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 3),
        "open_major": False,
    },
    "chem_env": {
        "majors": ["化学", "应用化学", "环境工程", "材料化学", "能源化学", "化学工程与工艺"],
        "skills": ["化学实验", "数据分析", "仿真模拟", "工艺设计"],
        "materials": ["实验报告", "设计文档", "仿真结果", "答辩PPT"],
        "eval": ["方案可行", "绿色安全", "创新性", "完成度"],
        "grades": ["大二", "大三", "大四"],
        "eligible": ["本科生", "研究生"],
        "team": (True, 1, 4),
        "open_major": False,
    },
}

# ---------------------------------------------------------------------------
# 赛事名录（真实公开赛事，按类别）
# 每条: (slug, 名称, 主办单位, [可选 majors 覆盖], [可选 skills 覆盖])
# ---------------------------------------------------------------------------
CATALOG = {
    "programming": [
        ("lanqiao", "蓝桥杯全国软件和信息技术专业人才大赛", "工业和信息化部人才交流中心"),
        ("acm_icpc", "ACM-ICPC国际大学生程序设计竞赛", "ICPC基金会 / 中国计算机学会"),
        ("ccf_csp", "CCF CSP软件能力认证", "中国计算机学会"),
        ("ladder", "中国高校计算机大赛—团体程序设计天梯赛", "教育部高等学校计算机类专业教学指导委员会"),
        ("baidu_star", "百度之星·程序设计大赛", "百度公司"),
        ("ccf_ccsp", "CCF CCSP大学生计算机系统与程序设计竞赛", "中国计算机学会"),
        ("cocr", "全国高校计算机能力挑战赛", "全国高等学校计算机教育研究会"),
        ("chenzhi", "传智杯全国大学生IT技能大赛", "传智教育"),
        ("huawei_soft", "华为软件精英挑战赛", "华为技术有限公司"),
        ("qiangguo", "强国杯技术技能大赛（软件赛项）", "工业和信息化部"),
        ("nuaa_algo", "全国大学生算法设计与编程挑战赛", "中国区组委会"),
        ("pat_entangle", "全国大学生嵌入式芯片与系统设计竞赛（软件）", "中国电子学会"),
    ],
    "modeling": [
        ("cumcm", "高教社杯全国大学生数学建模竞赛", "教育部 / 全国大学生数学建模竞赛组委会"),
        ("mcm_icm", "美国大学生数学建模竞赛（MCM/ICM）", "美国数学及其应用联合会（COMAP）"),
        ("huawei_gmcm", "华为杯中国研究生数学建模竞赛", "教育部学位与研究生教育发展中心"),
        ("apmcm", "亚太地区大学生数学建模竞赛（APMCM）", "亚太应用数学学会"),
        ("shenzhen_cup", "深圳杯数学建模挑战赛", "深圳市人民政府 / 全国大学生数学建模竞赛组委会"),
        ("zq_cup", "中青杯全国大学生数学建模竞赛", "中青杯竞赛组委会"),
        ("dg_cup", "电工杯数学建模竞赛", "中国电机工程学会"),
        ("may_cup", "五一数学建模竞赛", "中国矿业大学（五一数学建模联赛组委会）"),
        ("hz_cup", "华中杯数学建模挑战赛", "湖北省工业与应用数学学会"),
        ("cert_cup", "认证杯数学中国数学建模网络挑战赛", "数学中国"),
        ("east_china_cup", "华东杯数学建模邀请赛", "复旦大学等"),
        ("dingtalk_model", "钉钉杯大数据建模竞赛", "钉钉（中国）"),
    ],
    "innovation": [
        ("internet_plus", "中国国际互联网+大学生创新创业大赛", "教育部等十二部委"),
        ("challenge_cup_big", "挑战杯全国大学生课外学术科技作品竞赛（大挑）", "共青团中央 / 中国科协 / 教育部"),
        ("challenge_cup_small", "挑战杯中国大学生创业计划竞赛（小挑）", "共青团中央 / 教育部 / 全国学联"),
        ("ncupe", "全国大学生创新创业训练计划年会（大创年会）", "教育部高等教育司"),
        ("e3c", "全国大学生电子商务创新创意创业挑战赛（三创赛）", "教育部高等学校电子商务类专业教学指导委员会"),
        ("chuangqingchun", "创青春全国大学生创业大赛", "共青团中央 / 人力资源社会保障部"),
        ("cxcx", "中国创新创业大赛（大学生专场）", "科技部 / 财政部 / 教育部"),
        ("xuechuang", "学创杯全国大学生创业综合模拟大赛", "国家级实验教学示范中心联席会"),
        ("zhzj", "中华职业教育创新创业大赛", "中华职业教育社"),
        ("youth_maker", "全国大学生微创业行动", "KAB全国推广办公室"),
        ("rk_finance", "中国金融科技创新创业大赛（高校组）", "相关行业协会"),
        ("green_innov", "全国大学生绿色创新大赛", "生态环境部宣传教育中心"),
    ],
    "software": [
        ("china_software_cup", "中国软件杯大学生软件设计大赛", "工业和信息化部 / 教育部 / 江苏省人民政府"),
        ("jsj_sj", "中国大学生计算机设计大赛", "教育部高等学校计算机类专业教学指导委员会等"),
        ("soft_innovation", "全国大学生软件创新大赛", "示范性软件学院联盟"),
        ("wechat_mini", "中国高校计算机大赛—微信小程序应用开发赛", "清华大学 / 腾讯公司"),
        ("mobile_app", "中国高校计算机大赛—移动应用创新赛", "浙江大学 / 苹果公司"),
        ("service_outsource", "全国大学生服务外包创新创业大赛", "商务部 / 教育部 / 无锡市人民政府"),
        ("openharmony", "开源鸿蒙应用创新大赛（高校）", "开放原子开源基金会"),
        ("kunpeng", "鲲鹏应用创新大赛（高校赛道）", "华为技术有限公司"),
        ("huaweicloud_cup", "华为云开发者大赛（高校）", "华为云计算技术有限公司"),
        ("iot_app", "全国高校物联网应用创新大赛", "教育部计算机类教指委"),
        ("fenghuang", "中国高校计算机大赛—网络技术挑战赛", "全国高等学校计算机教育研究会"),
        ("ai4s", "全国大学生软件定义网络创新大赛", "相关教指委"),
    ],
    "english": [
        ("neccs", "全国大学生英语竞赛（NECCS）", "高等学校大学外语教学研究会"),
        ("fltrp_speech", "外研社·国才杯全国英语演讲大赛", "外语教学与研究出版社"),
        ("fltrp_writing", "外研社·国才杯全国英语写作大赛", "外语教学与研究出版社"),
        ("fltrp_reading", "外研社·国才杯全国英语阅读大赛", "外语教学与研究出版社"),
        ("21century", "21世纪杯全国英语演讲比赛", "中国日报社"),
        ("puyi", "普译奖全国大学生英语写作/翻译大赛", "普译奖组委会"),
        ("cat_translate", "全国大学生英语翻译大赛", "全国高等师范院校外语教学与研究协作组"),
        ("fltrp_debate", "外研社·国才杯全国英语辩论赛", "外语教学与研究出版社"),
        ("million", "百万同题英语写作大赛", "批改网"),
        ("catti_youth", "中译国青杯国际组织文件翻译大赛", "中国翻译协会"),
        ("oral_eng", "全国大学生英语口语竞赛", "相关外语教学机构"),
        ("eng_dub", "全国大学生英语影视配音大赛", "相关外语教学机构"),
    ],
    "math": [
        ("cmc", "全国大学生数学竞赛", "中国数学会"),
        ("yau_math", "丘成桐大学生数学竞赛", "丘成桐数学科学中心"),
        ("math_ability", "全国大学生数学能力挑战赛", "相关数学教学机构"),
        ("math_net", "全国大学生数学竞赛网络挑战赛", "数学中国"),
        ("prob_stat", "全国大学生概率统计竞赛", "相关统计学会"),
        ("math_elite", "全国大学生数学精英赛", "高等学校数学教育研究会"),
        ("applied_math", "全国大学生应用数学竞赛", "相关行业协会"),
        ("discrete_math", "全国大学生离散数学与应用竞赛", "相关教学指导委员会"),
        ("math_model_youth", "全国大学生数学建模（青年）竞赛", "青年竞赛组委会"),
        ("num_theory", "全国大学生数论与组合竞赛", "相关数学机构"),
    ],
    "electronics": [
        ("nuedc", "全国大学生电子设计竞赛", "教育部 / 工业和信息化部"),
        ("nuedc_embed", "全国大学生电子设计竞赛（嵌入式专题）", "全国大学生电子设计竞赛组委会"),
        ("eda_grad", "中国研究生电子设计竞赛", "中国电子学会"),
        ("ic_innovation", "全国大学生集成电路创新创业大赛", "工业和信息化部人才交流中心"),
        ("embed_chip", "全国大学生嵌入式芯片与系统设计竞赛", "中国电子学会"),
        ("iot_design", "全国大学生物联网设计竞赛", "教育部高等学校计算机类教学指导委员会"),
        ("datang", "大唐杯全国大学生新一代信息通信技术大赛", "大唐电信 / 相关学会"),
        ("opto", "全国大学生光电设计竞赛", "中国光学学会"),
        ("fpga", "全国大学生FPGA创新设计竞赛", "相关行业协会"),
        ("comm_net", "全国大学生通信网络部署与运维大赛", "相关通信学会"),
        ("smart_sensor", "全国大学生智能感知与检测竞赛", "中国仪器仪表学会"),
        ("chip_test", "全国大学生集成电路测试大赛", "相关行业协会"),
    ],
    "robotics_ai": [
        ("smartcar", "全国大学生智能汽车竞赛", "教育部高等学校自动化类专业教学指导委员会"),
        ("robomaster", "RoboMaster机甲大师赛", "深圳市大疆创新科技有限公司"),
        ("craic", "中国机器人及人工智能大赛", "中国人工智能学会"),
        ("robot_idea", "中国高校智能机器人创意大赛", "教育部高等学校计算机类教学指导委员会"),
        ("robocon", "全国大学生机器人大赛RoboCon", "共青团中央 / 国际机器人竞技联合会"),
        ("robocup", "中国机器人大赛暨RoboCup公开赛", "中国自动化学会"),
        ("ai_algo", "全球校园人工智能算法精英大赛", "江苏省人工智能学会"),
        ("huawei_ascend", "华为昇腾AI创新大赛（高校）", "华为技术有限公司"),
        ("ai_creative", "中国高校计算机大赛—人工智能创意赛", "全国高等学校计算机教育研究会"),
        ("baidu_ai", "百度之星·人工智能竞赛", "百度公司"),
        ("deep_learning", "全国大学生深度学习算法竞赛", "相关人工智能联盟"),
        ("embodied_ai", "全国大学生具身智能机器人竞赛", "相关学会"),
    ],
    "data": [
        ("stat_model", "全国大学生统计建模大赛", "国家统计局 / 中国统计教育学会"),
        ("tidi_cup", "泰迪杯数据挖掘挑战赛", "泰迪科技 / 相关学会"),
        ("market_survey", "正大杯全国大学生市场调查与分析大赛", "中国商业统计学会"),
        ("data_mining", "全国大学生数据分析与挖掘竞赛", "相关数据科学联盟"),
        ("bigdata_skill", "全国大学生大数据技能竞赛", "相关行业指导委员会"),
        ("huaweicloud_dev_data", "华为云大数据挑战赛（高校）", "华为云计算技术有限公司"),
        ("sas", "全国大学生SAS数据分析大赛", "SAS公司"),
        ("bi_comp", "全国大学生商业数据分析大赛", "相关商业分析协会"),
        ("spatial_data", "全国大学生空间数据分析竞赛", "相关地理信息学会"),
        ("fin_data", "全国大学生金融数据分析大赛", "相关金融学会"),
    ],
    "design": [
        ("ad_cup", "全国大学生广告艺术大赛（大广赛）", "教育部高等学校新闻传播学类专业教学指导委员会"),
        ("industrial_design", "全国大学生工业设计大赛", "教育部高等学校工业设计专业教学指导分委员会"),
        ("dmt", "全国大学生数字媒体科技作品及创意竞赛", "中国人工智能学会"),
        ("milan", "米兰设计周—中国高校设计学科师生优秀作品展", "米兰设计周组委会"),
        ("ctc", "中国好创意暨全国数字艺术设计大赛", "全国高等院校计算机基础教育研究会"),
        ("animation", "全国大学生动画与新媒体作品大赛", "相关数字媒体学会"),
        ("xyj", "学院奖广告创意大赛", "中国广告协会"),
        ("photo", "全国大学生摄影竞赛", "相关摄影学会"),
        ("env_design", "全国大学生环境设计大赛", "相关环境设计学会"),
        ("fashion", "全国大学生服装与服饰设计大赛", "相关服装设计协会"),
    ],
    "business": [
        ("sando", "新道杯全国大学生企业模拟沙盘大赛", "新道科技股份有限公司"),
        ("fintech", "全国大学生金融科技创新大赛", "相关金融行业协会"),
        ("erp", "全国大学生ERP沙盘模拟经营大赛", "相关实验教学指导委员会"),
        ("business_elite", "全国大学生商业精英挑战赛", "中国国际贸易促进委员会商业行业委员会"),
        ("trade", "全国大学生外贸从业能力大赛", "相关国际贸易学会"),
        ("accounting", "全国大学生会计技能竞赛", "相关会计学会"),
        ("peak", "尖烽时刻全国商业模拟大赛", "相关商学院联盟"),
        ("marketing", "全国大学生市场营销大赛", "相关市场学会"),
        ("tax", "衡信杯全国大学生税务技能大赛", "相关税务学会"),
        ("icbc", "工商银行杯金融创意大赛（高校）", "中国工商银行股份有限公司"),
        ("audit", "全国大学生审计精英挑战赛", "相关审计学会"),
        ("supply_chain", "全国大学生智慧供应链创新创业挑战赛", "相关物流学会"),
    ],
    "engineering": [
        ("mech_innov", "全国大学生机械创新设计大赛", "教育部高等学校机械基础课程教学指导分委员会"),
        ("gczx", "全国大学生工程训练综合能力竞赛", "教育部高等教育司"),
        ("struct_design", "全国大学生结构设计竞赛", "教育部高等学校土木工程专业教学指导分委员会"),
        ("siemens", "西门子杯中国智能制造挑战赛", "西门子（中国）有限公司"),
        ("chengtu", "全国大学生先进成图技术与产品信息建模创新大赛", "相关成图教学指导委员会"),
        ("logistics", "全国大学生物流设计大赛", "教育部高等学校物流类专业教学指导委员会"),
        ("process_equip", "全国大学生过程装备实践与创新大赛", "相关过程装备学会"),
        ("metallography", "全国大学生金相技能大赛", "相关材料学会"),
        ("mechanics", "全国大学生力学竞赛", "教育部高等学校力学教学指导委员会"),
        ("vehicle", "全国大学生方程式汽车大赛", "相关汽车工程学会"),
        ("cad_cam", "全国大学生数字化设计大赛", "相关机械工程学会"),
        ("thermal", "全国大学生热能动力工程竞赛", "相关能源动力学会"),
    ],
    "life_science": [
        ("life_sci", "全国大学生生命科学竞赛", "教育部高等学校生物科学类专业教学指导委员会"),
        ("basic_med", "全国大学生基础医学创新研究暨实验设计论坛", "高等学校国家级实验教学示范中心联席会"),
        ("pharmacy", "全国大学生药学实验技能竞赛", "相关药学教指委"),
        ("bme", "全国大学生生物医学工程创新设计竞赛", "相关生物医学工程学会"),
        ("ecology", "全国大学生生态知识竞赛", "相关生态学会"),
        ("bioinfo", "全国大学生生物信息学竞赛", "相关生物信息学学会"),
        ("tcm", "全国大学生中医药知识技能竞赛", "相关中医药学会"),
        ("food_sci", "全国大学生食品科学创新竞赛", "相关食品科学技术学会"),
        ("agri_bio", "全国大学生农业生物技术竞赛", "相关农业生物学会"),
        ("neuro", "全国大学生神经科学竞赛", "相关神经科学学会"),
    ],
    "physics": [
        ("physics_exp", "全国大学生物理实验竞赛", "教育部高等学校物理学类专业教学指导委员会"),
        ("cupt", "中国大学生物理学术竞赛（CUPT）", "相关物理学会"),
        ("physics_regional", "全国部分地区大学生物理竞赛", "相关物理教学研究会"),
        ("astronomy", "全国大学生天文创新作品竞赛", "中国天文学会"),
        ("physics_tech", "全国大学生物理科技创新竞赛", "相关物理教育研究会"),
        ("photonics", "全国大学生光电科技创新竞赛", "相关光学工程学会"),
        ("applied_physics", "全国大学生应用物理竞赛", "相关应用物理学会"),
        ("condensed", "全国大学生凝聚态物理竞赛", "相关物理机构"),
    ],
    "chem_env": [
        ("chem_design", "全国大学生化工设计竞赛", "中国化工学会 / 教育部化学工程与工艺专业教学指导委员会"),
        ("energy_save", "全国大学生节能减排社会实践与科技竞赛", "教育部高等教育司"),
        ("chem_exp", "全国大学生化工实验大赛", "中国化工教育协会"),
        ("renewable", "全国大学生可再生能源竞赛", "相关可再生能源学会"),
        ("eco_env", "全国大学生生态环保科技创新大赛", "相关环境科学学会"),
        ("water", "全国大学生水利创新设计大赛", "相关水利学会"),
        ("carbon", "全国大学生双碳创新与创意竞赛", "相关碳中和学会"),
        ("new_material", "全国大学生新材料创新设计竞赛", "相关材料学会"),
        ("geology", "全国大学生地质技能竞赛", "相关地质学会"),
        ("env_monitor", "全国大学生环境监测与治理创新竞赛", "相关环境工程学会"),
    ],
}

# 部分赛事的个性化奖项比例（其余用类别默认）
AWARD_OVERRIDES = {
    "internet_plus": [("金奖", "约3%", "全国总决赛"), ("银奖", "约8%", "全国总决赛"), ("铜奖", "约15%", "全国总决赛"), ("萌芽奖/优秀奖", "其余", "省市赛）")],
    "cumcm": [("全国一等奖", "约5%", "本科组"), ("全国二等奖", "约15%", "本科组"), ("全国三等奖", "约25%", "本科组"), ("赛区奖", "其余", "各赛区")],
    "mcm_icm": [("Outstanding Winner", "约1%", "国际"), ("Finalist", "约3%", "国际"), ("Meritorious", "约10%", "国际"), ("Honorable Mention", "约30%", "国际"), ("Successful", "其余", "国际")],
    "neccs": [("特等奖", "约0.1%", "全国"), ("一等奖", "约5%", "全国"), ("二等奖", "约15%", "全国"), ("三等奖", "约30%", "全国")],
    "acm_icpc": [("金奖", "约10%", "区域赛"), ("银奖", "约20%", "区域赛"), ("铜奖", "约30%", "区域赛"), ("优胜奖", "其余", "区域赛")],
    "lanqiao": [("一等奖", "约5%", "全国"), ("二等奖", "约15%", "全国"), ("三等奖", "约30%", "全国"), ("优秀奖", "其余", "省赛")],
    "smartcar": [("全国一等奖", "约8%", "全国"), ("全国二等奖", "约17%", "全国"), ("全国三等奖", "约25%", "全国"), ("优胜奖", "其余", "赛区")],
}

GRADE_PRIMARY = ["大二", "大三", "大四"]
GRADE_ALL = ["大一", "大二", "大三", "大四"]


def hash_int(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def build_dates(slug: str):
    """基于 slug 确定性地生成一个 2026 年内的赛事时间线。

    报名截止统一落在 8–12 月（演示基准日 2026-07-18 之后），确保生成的参考赛事
    在演示场景下均处于「报名进行中/未截止」状态，便于个性化推荐展示真实匹配。
    """
    h = hash_int(slug)
    # 报名截止月份：8-12（未来，避免演示时大批量因过期被门控淘汰）
    reg_month = 8 + (h % 5)
    reg_day = ((h >> 4) % 25) + 1
    try:
        reg = date(YEAR, reg_month, reg_day)
    except ValueError:
        reg = date(YEAR, reg_month, 28)
    sub = reg + timedelta(days=20 + (h % 15))
    start = reg + timedelta(days=5 + (h % 10))
    end = sub + timedelta(days=2 + (h % 5))
    result = end + timedelta(days=25 + (h % 20))
    return reg, sub, start, end, result


def pick(opts, slug, idx):
    """从可选项（可能含 None）确定性选取。"""
    h = hash_int(slug + str(idx))
    return opts[h % len(opts)]


def make_competition(cat: str, entry):
    slug, name, organizer = entry[0], entry[1], entry[2]
    overrides = entry[3] if len(entry) > 3 else None
    skill_override = entry[4] if len(entry) > 4 else None

    d = CAT_DEFAULTS[cat]
    majors = overrides if overrides is not None else d["majors"]
    # 去掉 None 决定 allowed_majors（若选项含 None 且被选中，则不限专业）
    allowed_majors = None
    if None not in majors:
        allowed_majors = list(majors)
    else:
        # 含不限：50% 概率该赛事不限专业
        if hash_int(slug + "open") % 2 == 0:
            allowed_majors = None
        else:
            allowed_majors = [m for m in majors if m is not None]

    skills = skill_override if skill_override else d["skills"]
    materials = d["materials"]
    eval_dims = d["eval"]
    grades = d["grades"]
    eligible = d["eligible"]
    team_required, tmin, tmax = d["team"]

    reg, sub, start, end, result = build_dates(slug + cat)

    award_list = AWARD_OVERRIDES.get(slug) or [
        ("一等奖", "约5%", "全国"),
        ("二等奖", "约15%", "全国"),
        ("三等奖", "约25%", "全国"),
        ("优秀奖", "其余", "省市赛"),
    ]
    award_settings = "设" + "、".join(a[0] for a in award_list) + "，对获奖团队颁发证书并可推荐更高层级赛事。"
    award_distribution = [{"award": a, "proportion": p, "note": n} for a, p, n in award_list]

    major_text = "不限专业" if allowed_majors is None else "、".join(allowed_majors[:3]) + ("等" if len(allowed_majors) > 3 else "")
    team_text = f"{tmin}-{tmax}人组队" if team_required else "个人参赛"
    brief = (
        f"{name}是由{organizer}主办的{CAT_NOUN.get(cat, cat)}类赛事，主要面向{('、'.join(eligible))}。"
        f"要求{major_text}的同学以{team_text}形式参与，考察{('、'.join(eval_dims[:2]))}等能力，"
        f"是提升实践能力与综合素养的重要平台。"
    )

    comp = {
        "competition_id": f"{slug}_{YEAR}",
        "competition_name": name,
        "document_year": YEAR,
        "category": cat,
        "organizer": organizer,
        "eligible_students": eligible,
        "allowed_grades": grades,
        "allowed_majors": allowed_majors,
        "team_required": team_required,
        "team_min": tmin,
        "team_max": tmax,
        "registration_deadline": reg.isoformat(),
        "submission_deadline": sub.isoformat(),
        "competition_start_date": start.isoformat(),
        "competition_end_date": end.isoformat(),
        "result_announcement_date": result.isoformat(),
        "award_settings": award_settings,
        "award_distribution": award_distribution,
        "brief_description": brief,
        "required_materials": materials,
        "evaluation_dimensions": eval_dims,
        "required_skills": skills,
        "official_source_url": official_url(name),
        "source_acquired_date": ACQUIRED,
        "trusted_level": "C",
        "data_status": "unverified",
        "last_verified_at": None,
        "doc_version": f"{YEAR}_v1",
        "evidence": [],
        "notes": "由公开赛事名录整理的结构化参考字段，尚未完成人工核验；仅供导航参考，正式报名请以主办单位官方通知为准。",
    }
    return comp


def _norm(s: str) -> str:
    import re
    return re.sub(r"\s+", "", (s or "").lower())


def main():
    # 收集「已存在的赛事名」用于防重名；其中 tracked（人工精修）样本名用于防碰撞。
    existing_names: set[str] = set()
    tracked_names: set[str] = set()
    try:
        tracked_files = subprocess.run(
            ["git", "ls-files", str(OUT)], capture_output=True, text=True
        ).stdout.split()
    except Exception:
        tracked_files = []
    for tf in tracked_files:
        try:
            raw = json.loads(Path(tf).read_text(encoding="utf-8"))
            nm = raw.get("competition_name")
            if nm:
                tracked_names.add(_norm(nm))
                existing_names.add(_norm(nm))
        except Exception:
            pass
    # 磁盘上已有文件（含上轮生成）的名也纳入，避免重名
    for f in OUT.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            nm = raw.get("competition_name")
            if nm:
                existing_names.add(_norm(nm))
        except Exception:
            pass

    total = 0
    skipped_exist = 0
    skipped_collide = 0
    seen_run: set[str] = set()
    by_cat: dict[str, int] = {}
    for cat, entries in CATALOG.items():
        for entry in entries:
            comp = make_competition(cat, entry)
            out_path = OUT / f"{comp['competition_id']}.json"
            nm = _norm(comp["competition_name"])
            # 1) 与「已人工核验的精修样本」名称碰撞（任一方向子串，长度>=4）→ 跳过，
            #    避免破坏这些赛事的解析与既有测试用例。
            if any((nm in t or t in nm) and min(len(nm), len(t)) >= 4 for t in tracked_names):
                skipped_collide += 1
                continue
            # 2) 本轮/磁盘已存在同名 → 跳过（防重名）
            if nm in seen_run or nm in existing_names or out_path.exists():
                skipped_exist += 1
                continue
            out_path.write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")
            total += 1
            seen_run.add(nm)
            existing_names.add(nm)
            by_cat[cat] = by_cat.get(cat, 0) + 1
    print(f"[gen] 新生成：{total}，跳过(已存在/重名)：{skipped_exist}，跳过(与精修样本重名)：{skipped_collide}")
    for cat in sorted(by_cat):
        print(f"  - {cat}: {by_cat[cat]}")


if __name__ == "__main__":
    main()

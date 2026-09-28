"""全局常量与本地路径。

所有接口地址、字典值都集中在这里，方便后续学校系统变更时统一修改。
"""

from __future__ import annotations

import os
from pathlib import Path

# ---- 基础地址 ----
EHALL_HOST = "https://ehallapp.nju.edu.cn"
AUTH_SERVER = "https://authserver.nju.edu.cn/authserver/login"

# 教室借用应用入口（会跳统一身份认证）
JY_ENTRY = f"{EHALL_HOST}/jwapp/sys/jsjy/*default/index.do"

# ---- 接口地址（相对 EHALL_HOST）----
# 空闲教室（kxjas）
EP_CAMPUS = "/jwapp/sys/kxjas/zd/getXxxqdqx.do"  # 校区字典
EP_BUILDING = "/jwapp/sys/kxjas/modules/kxjas/jxlcx.do"  # 教学楼（参数 XXXQDM）
EP_FREE_ROOMS = (
    "/jwapp/sys/kxjas/modules/kxjscx/cxkxjs.do"  # 空闲教室主查询（按日期+节次，服务端过滤）
)
EP_ROOM_TYPE = "/jwapp/code/79ee3ac8-c638-442b-ba24-15d6f5e79797.do"  # 教室类型字典

# 教室借用（jsjy）
EP_TERM = "/jwapp/sys/jsjy/modules/jsjysq/cxdqxnxq.do"  # 当前学年学期
EP_ORG = "/jwapp/sys/jsjy/modules/jsjysq/cxyhszdw.do"  # 所在单位
EP_BORROW_TYPE = "/jwapp/sys/jsjy/modules/jsjysq/cxjsjylx.do"  # 借用类型
EP_SYS_PARAMS = "/jwapp/sys/jsjy/modules/jsjysq/cxxtcs.do"  # 系统参数
EP_DATE_TO_WEEK = "/jwapp/sys/jsjy/modules/jsjysq/cxrqdydzcxq.do"  # 日期 -> 周次/星期
EP_CALENDAR = "/jwapp/sys/jsjy/modules/jsjysq/cxxljxjszc.do"  # 校历
EP_WEEK_TO_DATE = "/jwapp/sys/jsjy/modules/jsjysq/gjzcxqcxrq.do"  # 周次 -> 日期
EP_LIST = "/jwapp/sys/jsjy/modules/jsjysq/cxjsjysq.do"  # 我的申请列表
EP_SAVE = "/jwapp/sys/jsjy/modules/jsjysq/xzjasjysq.do"  # 新增/保存/提交
EP_WITHDRAW = "/jwapp/sys/jsjy/modules/jsjysq/shjsjysq.do"  # 撤回/审核
EP_DELETE = "/jwapp/sys/jsjy/modules/jsjysq/scjssq.do"  # 删除申请

# ---- 固定字典值 ----
CAMPUSES = {
    "1": "鼓楼校区",
    "2": "浦口校区",
    "3": "仙林校区",
    "4": "苏州校区",
}

# data.JYLYDM / JSJYSQLX / CQDQJY 等固定值
JYLYDM = "02"
JSJYSQLX = 2
CQDQJY_SHORT = "2"  # 短期（临时借用）
CQDQJY_LONG = "1"  # 长期

# TYPE 取值
TYPE_SAVE = "save"
TYPE_SUBMIT = "TJ"

# ---- 借用类型 JSJYLXDM：同一字段，学生端 / 教师端两套字典 ----
# 服务端按登录账号返回对应字典（cxjsjylx.do），以此判定契约，不猜账号属性。
# 学生端（2026-09 学生账号实测）：字典是「指导教师所在单位」口径
STUDENT_BORROW_TYPES = {
    "01": "辅导员",
    "02": "学生社团管理部",
    "03": "就业指导中心",
    "04": "国际合作与交流处",
    "05": "学生工作处",
    "06": "校团委",
    "13": "待悦读课程管理",
}
# 教师端（2026-09 教师账号实测）：字典是活动类型口径
TEACHER_BORROW_TYPES = {
    "07": "教师教学、补课",
    "09": "团学活动",
    "21": "长期借用",
    "39": "考试",
    "40": "讲座",
}
ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"
ROLE_UNKNOWN = "unknown"
ROLE_LABELS = {ROLE_STUDENT: "学生端", ROLE_TEACHER: "教师端", ROLE_UNKNOWN: "未知契约"}
# 计划/档案都没指定借用类型时，按契约取的默认值
DEFAULT_BORROW_TYPE = {ROLE_STUDENT: "02", ROLE_TEACHER: "09"}


def state_path() -> Path:
    """登录态文件位置，可用环境变量 CRB_AUTH_FILE 覆盖。"""
    env = os.environ.get("CRB_AUTH_FILE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".crb" / "auth.json"

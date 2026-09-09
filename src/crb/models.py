"""数据结构定义（输入 / 输出）。

对外统一用 JSON，方便 AI 和脚本消费。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Campus(BaseModel):
    id: str
    name: str


class Building(BaseModel):
    id: str = Field(alias="JXLDM")
    name: str = Field(alias="JXLMC")
    campus_id: str | None = Field(default=None, alias="XXXQDM")

    model_config = {"populate_by_name": True}


class FreeRoomSlot(BaseModel):
    """一间在指定日期/节次空闲的教室（`kxjscx/cxkxjs.do` 返回）。"""

    room_name: str = Field(alias="JASMC")
    campus_id: str | None = Field(default=None, alias="XXXQDM")
    campus_name: str | None = Field(default=None, alias="XXXQDM_DISPLAY")
    building_id: str | None = Field(default=None, alias="JXLDM")
    building_name: str | None = Field(default=None, alias="JXLDM_DISPLAY")
    room_type: str | None = Field(default=None, alias="JASLXDM")
    room_type_name: str | None = Field(default=None, alias="JASLXDM_DISPLAY")
    date: str | None = Field(default=None, alias="KXRQ")
    start_period: int | None = Field(default=None, alias="KSJC")
    end_period: int | None = Field(default=None, alias="JSJC")
    period_label: str | None = Field(default=None, alias="KXJC")
    time_label: str | None = Field(default=None, alias="KXSJ")
    seat_class: int | None = Field(default=None, alias="SKZWS")
    seat_exam: int | None = Field(default=None, alias="KSZWS")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class BorrowRequest(BaseModel):
    """一条教室借用申请（对应 xzjasjysq.do 的 data 对象）。"""

    # 借用人信息
    JYDWDM: str = ""
    JYRXM: str = ""
    JYRDH: str = ""
    JYYTMS: str = ""
    # 教室 / 类型
    JSJYLXDM: str = ""
    XXXQDM: str = ""
    JSRL: str = ""
    KSRS: str = "0"
    JYSL: str = "1"
    SFHDJS: str = "0"
    JYFSDM: str = "0"
    # 时间
    XNXQDM: str = ""
    KSRQ: str = ""
    JSRQ: str = ""
    XQ: str = ""
    ZC: str = ""
    KSJC: str = ""
    JSJC: str = ""
    KSSJ: str = ""
    JSSJ: str = ""
    # 固定 / 其它
    SQBH: str = ""
    JYLYDM: str = "02"
    JSJYSQLX: int = 2
    CQDQJY: str = "2"
    TYPE: str = "save"
    ZRS: str = "0"
    SFYYKS: str = "0"
    SFXHDZY: str = "0"
    SJD: str = ""
    FJ: str = ""

    def as_payload(self) -> dict[str, Any]:
        return self.model_dump()


class SaveResult(BaseModel):
    ok: bool
    code: int | None = None
    msg: str = ""
    raw: dict[str, Any] | None = None


class BorrowRecord(BaseModel):
    """列表中的一条申请记录（字段随学校返回，按需取用）。"""

    model_config = {"extra": "allow"}

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

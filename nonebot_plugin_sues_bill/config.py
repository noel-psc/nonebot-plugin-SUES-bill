"""SUES 校园服务配置"""

from pydantic import BaseModel


class Config(BaseModel):
    """插件配置项"""

    sues_base_url: str = "https://epay.sues.edu.cn"
    """SUES 一卡通系统地址"""


# ─── 以下为内部常量，不可配置 ───────────────────────────────

# 电费查询
ELECTRIC_QUERY_PATH = "/epay/wxpage/wanxiao/eleresult"

# 校园卡查询
CAMPUS_CARD_INDEX_PATH = "/epay/h5/index"

# DES 加密参数（校园卡登录用）
DES_KEY = b"6eGicG6U"
DES_IV = bytes([1, 2, 3, 4, 5, 6, 7, 8])

# User-Agent
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

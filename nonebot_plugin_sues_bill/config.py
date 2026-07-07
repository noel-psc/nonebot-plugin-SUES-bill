"""SUES 校园服务配置"""

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """插件配置项"""

    sues_base_url: str = "https://epay.sues.edu.cn"
    """SUES 一卡通系统地址"""

    des_key: bytes = b"6eGicG6U"
    """DES-CBC 加密密钥（8 字节）"""

    des_iv: bytes = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    """DES-CBC 初始向量（8 字节）"""

    model_config = {"env_prefix": "sues_", "extra": "ignore"}


# ─── 以下为内部常量，不可配置 ───────────────────────────────

# 请求超时（秒）
REQUEST_TIMEOUT = 10

# 电费查询
ELECTRIC_QUERY_PATH = "/epay/wxpage/wanxiao/eleresult"

# 校园卡查询
CAMPUS_CARD_INDEX_PATH = "/epay/h5/index"

# User-Agent
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

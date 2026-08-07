from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="SUES校园服务",
    description="电费查询、充值及校园卡余额查询",
    usage="输入【#电费帮助】或【#校园卡帮助】查看说明",
    type="application",
    homepage="https://github.com/noel-psc/nonebot-plugin-sues-bill",
    config=Config,
    supported_adapters={"~onebot.v11", "~qq"},
)

# 导入各模块以注册命令与跨适配器预处理
from . import compat, electric, campus_card  # noqa: F401

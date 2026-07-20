<div align="center">
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>

## ✨ nonebot-plugin-sues-bill ✨
[![LICENSE](https://img.shields.io/github/license/noel-psc/nonebot-plugin-sues-bill.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-sues-bill.svg)](https://pypi.python.org/pypi/nonebot-plugin-sues-bill)
[![python](https://img.shields.io/badge/python-3.11|3.12|3.13|3.14-blue.svg)](https://www.python.org)
[![uv](https://img.shields.io/badge/package%20manager-uv-black?style=flat-square&logo=uv)](https://github.com/astral-sh/uv)
<br/>
[![ruff](https://img.shields.io/badge/code%20style-ruff-black?style=flat-square&logo=ruff)](https://github.com/astral-sh/ruff)
[![pre-commit](https://results.pre-commit.ci/badge/github/noel-psc/nonebot-plugin-sues-bill/master.svg)](https://results.pre-commit.ci/latest/github/noel-psc/nonebot-plugin-sues-bill/master)

</div>

## 📖 介绍

SUES 校园服务插件，支持查询上海工程技术大学电费和校园卡余额。

主要功能：
- 🔌 **电费查询** — 查询宿舍剩余电量，定时宿舍可独立设置
- 📊 **耗电历史** — 自动结算昨日耗电量，支持最近 N 天统计与缴费流水校正
- 💳 **校园卡查询** — 查询校园卡账户余额和冻结余额

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-sues-bill --upgrade
使用 **pypi** 源安装

    nb plugin install nonebot-plugin-sues-bill --upgrade -i "https://pypi.org/simple"
使用**清华源**安装

    nb plugin install nonebot-plugin-sues-bill --upgrade -i "https://pypi.tuna.tsinghua.edu.cn/simple"


</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details open>
<summary>uv</summary>

    uv add nonebot-plugin-sues-bill
安装仓库 master 分支

    uv add git+https://github.com/noel-psc/nonebot-plugin-sues-bill@main
</details>

<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-sues-bill
安装仓库 master 分支

    pdm add git+https://github.com/noel-psc/nonebot-plugin-sues-bill@main
</details>
<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-sues-bill
安装仓库 master 分支

    poetry add git+https://github.com/noel-psc/nonebot-plugin-sues-bill@main
</details>

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_sues_bill"]

</details>

<details>
<summary>使用 nbr 安装(使用 uv 管理依赖可用)</summary>

[nbr](https://github.com/fllesser/nbr) 是一个基于 uv 的 nb-cli，可以方便地管理 nonebot2

    nbr plugin install nonebot-plugin-sues-bill
使用 **pypi** 源安装

    nbr plugin install nonebot-plugin-sues-bill -i "https://pypi.org/simple"
使用**清华源**安装

    nbr plugin install nonebot-plugin-sues-bill -i "https://pypi.tuna.tsinghua.edu.cn/simple"

</details>


## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的配置项（可选）

| 配置项  | 必填  | 默认值 |   说明   |
| :-----: | :---: | :----: | :------: |
| sues_base_url | 否 | `https://epay.sues.edu.cn` | SUES 一卡通系统地址 |
| sues_electricity_price_per_kwh | 否 | `0.617` | 每度电价格（元），用于计算昨日电费 |

## 🎉 使用
### 指令表

#### 电费查询

| 指令  | 权限  | 需要@ | 范围  |   说明   |
| :---: | :---: | :---: | :---: | :------: |
| #电费 | 群员 | 否 | 私聊/群聊 | 即时查询记录宿舍的当前余额 |
| #电费 区域 楼栋 房间号 | 群员 | 否 | 私聊/群聊 | 即时查询指定宿舍，不修改定时设置 |
| #电费 记录 区域 楼栋 房间号 | 群员 | 否 | 私聊/群聊 | 设置或修改自动日结宿舍 |
| #电费 统计 0 | 群员 | 否 | 私聊/群聊 | 查询今天截至当前的耗电估算 |
| #电费 统计 [天数] | 群员 | 否 | 私聊/群聊 | 查询指定天数已结束自然日的耗电统计，省略时为 30 天 |
| #电费 记录 状态 | 群员 | 否 | 私聊/群聊 | 查看当前宿舍和账户校正状态 |
| #电费 记录 停止 | 群员 | 否 | 私聊/群聊 | 停止自动日结，保留历史记录 |
| #电费 记录 绑定 | 群员 | 否 | 私聊/群聊 | 将已设置校园卡账户绑定到当前记录宿舍 |
| #电费 记录 解绑 | 群员 | 否 | 私聊/群聊 | 停止使用校园卡缴费流水校正 |
| #电费帮助 | 群员 | 否 | 私聊/群聊 | 查看电费查询帮助 |
| #电费详细帮助 | 群员 | 否 | 私聊/群聊 | 查看详细参数说明 |

<details>
<summary>支持的区域和楼栋</summary>

**三期学生公寓**：10-26栋
**四期学生公寓**：20、21、23、24、27-30、33-36、39-42栋

示例：
```
#电费 三期 21 1001
#电费 四期 28 1021
```
</details>

#### 昨日耗电

先使用 `#电费 记录 三期 21 1001` 设置宿舍。每天会在上海时区 00:00 前后十分钟内，按宿舍错峰查询一次剩余电量，并结算前一自然日的耗电量和电费。同一宿舍被多个用户设置时仍只会查询一次。

每次成功执行 `#电费` 查询都会记录查询时间、宿舍和当前余额，但不会覆盖日界快照。

- 已设置校园卡账号后，发送 `#电费 记录 绑定` 才会读取当天成功的“电费缴费”流水，按 `昨日 00:00 余额 + 缴费购电量 - 今日 00:00 余额` 校正耗电量。一个校园卡账户只能绑定一个宿舍，一个宿舍也只能绑定一个校园卡账户。
- 未绑定账户时，按两次余额差显示估算值；若发现余额增加，会提示当天可能发生缴费，且该日不计入统计。
- 首次记录需要等待两个日界快照后才能得到昨日耗电。
- 为降低对学校系统的集中访问，日界采样会有最多十分钟的边界误差。

发送 `#电费 统计 0` 可按今日首次和最新查询余额查看截至当前的耗电估算；至少需要两次成功查询，若余额增加则会提示当天可能已缴费。该估算不会写入日结数据。

发送 `#电费 统计 [天数]` 可查看指定数量已结束自然日的总耗电、日均、最高耗电日及准确性统计；省略天数时默认为 30。例如：`#电费 统计7天`。

数据保存在 nonebot-plugin-localstore 的插件专属目录中的 SQLite 数据库。旧版本若曾将数据保存到全局 `data/`，升级后会先迁移用户配置及加密密钥，再一次性导入旧 JSON 历史；原 JSON 会保留，不存储 cookie。

#### 校园卡查询

| 指令  | 权限  | 需要@ | 范围  |   说明   |
| :---: | :---: | :---: | :---: | :------: |
| #校园卡 | 群员 | 否 | 私聊/群聊 | 查询校园卡余额 |
| #校园卡帮助 | 群员 | 否 | 私聊/群聊 | 查看校园卡帮助 |
| #设置校园卡账号 学号 密码 | 群员 | 否 | 仅私聊 | 设置校园卡账号（密码加密存储） |

> ⚠️ **安全提示**：校园卡账号仅限私聊设置（`#设置校园卡账号`），密码使用 Fernet 加密后存储在本地。

### 🎨 效果图

**电费查询**：
```
剩余电量: 128.5 度
```

**昨日耗电**：
```
昨日耗电：2.5 度
昨日电费：1.54 元
```

**校园卡查询**：
```
💳 校园卡余额
━━━━━━━━━━━━
账户余额: ￥128.50
冻结余额: ￥0.00
```

<div align="center">
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>

## ✨ nonebot-plugin-sues-bill ✨
[![LICENSE](https://img.shields.io/github/license/noel-psc/nonebot-plugin-sues-bill.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-sues-bill.svg)](https://pypi.python.org/pypi/nonebot-plugin-sues-bill)
[![python](https://img.shields.io/badge/python-3.10|3.11|3.12|3.13-blue.svg)](https://www.python.org)
[![uv](https://img.shields.io/badge/package%20manager-uv-black?style=flat-square&logo=uv)](https://github.com/astral-sh/uv)
<br/>
[![ruff](https://img.shields.io/badge/code%20style-ruff-black?style=flat-square&logo=ruff)](https://github.com/astral-sh/ruff)
[![pre-commit](https://results.pre-commit.ci/badge/github/noel-psc/nonebot-plugin-sues-bill/master.svg)](https://results.pre-commit.ci/latest/github/noel-psc/nonebot-plugin-sues-bill/master)

</div>

## 📖 介绍

SUES 校园服务插件，支持查询上海工程技术大学电费和校园卡余额。

主要功能：
- 🔌 **电费查询** — 查询宿舍剩余电量，支持记忆上次查询参数
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

## 🎉 使用
### 指令表

#### 电费查询

| 指令  | 权限  | 需要@ | 范围  |   说明   |
| :---: | :---: | :---: | :---: | :------: |
| #电费 | 群员 | 否 | 私聊/群聊 | 查询宿舍电费（使用上次保存的参数） |
| #电费 区域 楼栋 房间号 | 群员 | 否 | 私聊/群聊 | 查询指定宿舍电费 |
| #电费帮助 | 群员 | 否 | 私聊/群聊 | 查看电费查询帮助 |
| #电费详细帮助 | 群员 | 否 | 私聊/群聊 | 查看详细参数说明 |
| #清除电费设置 | 群员 | 否 | 私聊/群聊 | 清除保存的查询参数 |

<details>
<summary>支持的区域和楼栋</summary>

**三期学生公寓**：10-26栋
**四期学生公寓**：20、21、23、24、27-30、33-36、39-42栋

示例：
```
#电费 三期 21 4021
#电费 四期 28 1021
```
</details>

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

**校园卡查询**：
```
💳 校园卡余额
━━━━━━━━━━━━
账户余额: ￥128.50
冻结余额: ￥0.00
```

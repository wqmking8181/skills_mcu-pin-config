---
name: mcu-pin-config
description: MCU 引脚分配求解器 — 给定芯片引脚复用表，自动搜索无冲突的外设引脚分配方案。支持多种封装类型、外设变种（如 SPI with NSS、USART hw flow-ctrl）、灵活实例匹配。附带工具可将 CSV 引脚表转换为 JSON 格式。
triggers:
  - "mcu 引脚分配"
  - "引脚复用"
  - "查找引脚"
  - "分配外设引脚"
  - "find pins"
  - "pin config"
  - "引脚表"
  - "find_pins"
  - "引脚分配方案"
  - "外设引脚搜索"
  - "mcu pin assignment"
  - "芯片引脚规划"
example_asks:
  - "给 APM32F427 LQFP64 分配 USART1 + SPI1 + I2C1 + CAN1"
  - "搜索 G32R501 上 USART1 的 RX/TX 引脚位置"
  - "把 csv 引脚表转换成 JSON 格式"
  - "列出所有外设类型和可用变种"
  - "用 LQFP100 封装分配 ETH RMII + USART2 + SPI2"
  - "查看 peri_def.json 里 SPI 支持哪些变种"
---

# MCU 引脚分配 Skill

## 概述

给定 MCU 的引脚复用表（哪些信号可以映射到哪些物理引脚），自动搜索无冲突的**外设引脚分配方案**。

核心是回溯搜索算法，解决 MCU 开发中常见的问题：多个外设（UART/SPI/I2C/CAN/ETH/TMR）的信号可能共享同一物理引脚，需要找到可行的组合。

## 脚本位置

所有脚本在 `scripts/` 目录下：

| 文件 | 说明 |
|------|------|
| `find_pins.py` | 主程序：引脚分配求解器 |
| `convert_pin_table_to_json.py` | 将 CSV 引脚表转换为 JSON 格式 |
| `normalization_signal.py` | 信号名称规范化（公用模块） |
| `peripheral_prefixes.py` | 外设名称前缀定义 |
| `peri_def.json` | 外设变种定义（如 USART default vs hw flow-ctrl） |
| `__init__.py` | 空文件，包标识 |

## 依赖

- **仅 Python 标准库**（`itertools`, `collections`, `json`, `re`, `csv`, `argparse`）

## Windows 编码注意

Windows 控制台默认使用 GBK 编码，运行脚本时可能遇到中文乱码。解决方法：

```powershell
# PowerShell
$env:PYTHONIOENCODING="utf-8"
python scripts/find_pins.py --peri-def scripts/peri_def.json search --pin-table data/pin_table.json --package LQFP64 USART1

# 或一次性设置
python -X utf8 scripts/find_pins.py --peri-def scripts/peri_def.json search --pin-table data/pin_table.json --package LQFP64 USART1
```

## 工作流程

### 1. 准备引脚表（一次性的）

从 MCU 数据手册的引脚定义表（CSV 格式）生成 JSON 格式的复用表：

```bash
python scripts/convert_pin_table_to_json.py \
    --delimiter TAB \
    --encoding utf-8-sig \
    --output data/pin_table.json \
    path/to/pin_definition.csv
```

CSV 文件必须包含以下列：
- **名称** — 引脚名称（如 PA0, PB1）
- **类型** — 引脚类型（I/O 引脚才参与外设复用搜索）
- **复用功能** — 外设复用功能列表
- **附加功能** — 附加功能列表
- **封装名称** — 封装列（如 `LQFP64`），可多列，不要重复

### 2. 搜索引脚分配

```bash
python scripts/find_pins.py search \
    --peri-def scripts/peri_def.json \
    --pin-table data/pin_table.json \
    --package LQFP64 \
    USART1 "SPI1(with NSS)" I2C1
```

### 3. 查看可用外设和变种

```bash
python scripts/find_pins.py --peri-def scripts/peri_def.json list
```

## 外设变种说明

通过 `peri_def.json` 定义每种外设类型的不同变种及其信号列表。例如：

| 外设 | 变种 | 信号 |
|------|------|------|
| USART | default | RX, TX |
| USART | hw flow-ctrl | CTS, RTS, RX, TX |
| SPI | default | MISO, MOSI, SCK |
| SPI | with NSS | MISO, MOSI, NSS, SCK |
| I2C | default | SCL, SDA |
| I2C | SMBus | SCL, SDA |
| ETH | RMII | RMII_CRS_DV, RMII_REF_CLK, ... |
| SDIO | SD, 4-bit | CK, CMD, D0, D1, D2, D3 |

使用 `(with 变种名)` 语法搜索时指定变种：
```bash
python scripts/find_pins.py --peri-def scripts/peri_def.json search --pin-table pins.json --package LQFP64 "SPI1(with NSS)"
```

## 实例匹配规则

| 写法 | 含义 |
|------|------|
| `USART1` | 固定实例，只使用 USART1 |
| `USART` | 灵活匹配，自动选 USART1/2/3 中任一可用 |
| `SPI1(with NSS)` | 固定实例 + 指定变种 |

## 输出示例

```
查找成功，分配方案：

* USART1 
  - RX: PA10 (43)
  - TX: PA9 (42)
* SPI1
  - MISO: PA6 (38)
  - MOSI: PA7 (39)
  - SCK: PA5 (37)
```

如果无法找到满足所有外设的无冲突方案，会提示建议更换更大封装或减少外设数量。

## 预置的引脚表

`data` 目录下包含已生成的 JSON 引脚表：
- `APM32F427xG_F425xG_F423xG.json`
- `G32R430.json`
- `G32R501.json`

## 注意事项

1. **引脚编号**：内部使用位掩码（`1 << pin`）表示占用，物理引脚号必须 ≥ 0
2. **MRV 排序**：信号数多的外设优先分配，提升搜索效率
3. **信号别名**：自动处理 NSS ↔ CS、MOSI ↔ SIMO、MISO ↔ SOMI 等别名
4. **CSV 编码**：中文数据手册导出的 CSV 通常是 `utf-8-sig` 或 `gbk`，选择正确的编码
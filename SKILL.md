---
name: mcu-pin-config
description: MCU 引脚分配求解器 — 给定芯片引脚复用表，自动搜索无冲突的外设引脚分配方案，输出 pad 名、封装管脚/球号与 ALT 号。内置极海 APM32/G32R 与先楫 HPM5E00/HPM6E00（含 BGA121/BGA196/BGA289）引脚表，支持伺服常用外设 PWM、编码器 QEI/QEP、Σ-Δ SDM/SDFM、串行编码器 SEI、CAN、RS485 UART，以及按单个信号（如 ADC 通道）分配和引脚预留。附带工具可从极海 Excel 引脚表或先楫数据手册 PDF 生成 JSON。
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
  - "pinmux"
  - "先楫引脚"
  - "HPM 引脚"
example_asks:
  - "给 APM32F427 LQFP64 分配 USART1 + SPI1 + I2C1 + CAN1"
  - "HPM5E3Y BGA121 上分配一套三相 PWM、QEI 编码器、两路 SDM 电流采样、RS485 和 CAN"
  - "HPM6E8Y BGA196 双轴伺服：两组三相 PWM、两路 SEI 绝对值编码器、4 路 SDM"
  - "G32R501 LQFP80 分配 PWM1~3、QEP1 和 SD1 三通道"
  - "列出 HPM6E80 BGA196 有哪些外设实例"
  - "从先楫数据手册 PDF 生成引脚表 JSON"
---

# MCU 引脚分配 Skill

## 概述

给定 MCU 的引脚复用表（哪些信号可以映射到哪些物理引脚），自动搜索无冲突的**外设引脚分配方案**。

核心是带前向剪枝的回溯搜索：多个外设（UART/SPI/I2C/CAN/PWM/编码器/Σ-Δ…）的信号可能共享同一物理引脚，求解器找出一组可同时满足的组合，并给出每个信号的 pad 名、管脚号/球号和 ALT 编号，可直接对照写 pinmux 初始化代码。

## 文件

| 文件 | 说明 |
|------|------|
| `scripts/find_pins.py` | 主程序：引脚分配求解器（`list` / `info` / `search`） |
| `scripts/peri_def.json` | 外设变种定义（如 UART default / RS485 DE，PWM 3-phase） |
| `scripts/normalization_signal.py` | 信号名称规范化（各厂商命名统一） |
| `scripts/convert_pin_table_to_json.py` | 极海 Excel 引脚总表 → JSON（需 openpyxl） |
| `scripts/convert_hpm_datasheet.py` | 先楫数据手册 PDF → JSON（需 pdfplumber），可与 HPM SDK `hpm_iomux.h` 交叉核对 |
| `data/*.json` | 预置引脚表 |

## 运行环境

- Python ≥ 3.8；`find_pins.py` **仅用标准库**
- 生成引脚表时才需要第三方库：极海 `pip install openpyxl`，先楫 `pip install pdfplumber`
- Windows 控制台中文乱码时：`set PYTHONIOENCODING=utf-8`（PowerShell：`$env:PYTHONIOENCODING="utf-8"`），或 `python -X utf8 ...`

## 工作流程

### 1. 确认芯片和封装

```bash
python scripts/find_pins.py info --pin-table data/HPM5E3Y.json            # 全部封装
python scripts/find_pins.py info --pin-table data/HPM5E3Y.json --package BGA121
```

`info` 列出封装、各封装中的外设实例、被排除的 pad 和引脚注释（启动引脚等）。**先确认用户的订货型号对应哪个 JSON 和封装**（见下方「预置引脚表」）。

### 2. 搜索分配方案

```bash
python scripts/find_pins.py search --pin-table data/HPM5E3Y.json --package BGA121 \
    "PWM0(3-phase)" QEI0 "SDM0(2ch)" "UART(RS485 DE)" CAN ADC0_IN03 --reserve PA02,PA03
```

- `--reserve`：预留引脚（pad 名或管脚号，逗号分隔），不参与分配。用于已定死的引脚、启动引脚等。
- `--json`：JSON 输出，便于后续处理（无解时退出码 3，需求写错时退出码 2）。

### 3. 查看可用外设和变种

```bash
python scripts/find_pins.py list
```

## 需求写法

| 写法 | 含义 |
|------|------|
| `USART1` | 固定实例，只使用 USART1 |
| `USART` | 灵活匹配，自动选 USART1/2/3… 中任一可用 |
| `SPI1(with NSS)` | 固定实例 + 指定变种 |
| `UART(RS485 DE)` | 灵活实例 + 指定变种 |
| `ADC0_IN03`、`PWM1_P_6`、`MCAN0_TXD` | 单个信号（引脚表中的信号名，或芯片原始名称） |

同一需求可写多次（如 `CAN CAN` 会分配两个不同的 CAN 实例）。

## 主要外设变种（完整列表用 `list` 查看）

| 外设 | 变种 | 信号 | 适用 |
|------|------|------|------|
| UART | default / hw flow-ctrl / RS485 DE | RX TX (+CTS RTS / +DE) | 通用 |
| CAN | default / with STBY | RX TX (+STBY) | 通用（先楫 MCAN 已归一为 CAN） |
| SPI | default / with NSS / quad, with NSS | MISO MOSI SCK (+NSS/CS_0, DAT2 DAT3) | 通用 |
| PWM | default | A B | G32R5xx（C2000 风格 ePWM） |
| PWM | pair0~pair3 / 3-phase / 8ch | P_0…P_7 | 先楫 |
| QEI | default / AB / with home / with fault | A B Z (H0 / F) | 先楫增量编码器 |
| QEP | default / AB / with STROBE | A B INDEX (STROBE) | G32R5xx eQEP |
| SEI | default / no clock | CK DE RX TX | 先楫串行编码器接口（BiSS-C/EnDat 用时钟；多摩川/尼康等 RS485 半双工用 no clock） |
| SDM | ch0~ch3 / 2ch / 3ch / 4ch | CLK_n DAT_n | 先楫 Σ-Δ 解调 |
| SD | ch1~ch4 / 3ch | Dn Cn | G32R5xx SDFM |
| QEO | default / AB | A B Z | 先楫编码器仿真输出 |
| RDC | default | PWM_P PWM_N | 先楫旋变激励 |
| I2C / ETH / SDIO / QSPI / TMR / SMC … | | | 极海（STM32 风格） |

ADC 通道、TRGM、GPTMR、EtherCAT(ESC) 等引脚各异的信号，用「单个信号」写法逐个指定。

## 输出示例

```
查找成功，分配方案（封装 BGA121）：

* PWM0  ← PWM0(3-phase)
  - P_0: PA00 (D1)  [ALT16]
  - P_1: PA01 (C1)  [ALT16]
  ...
* CAN0  ← CAN
  - RX: PD01 (B11)  [ALT7, MCAN0_RXD]
  - TX: PD00 (B10)  [ALT7, MCAN0_TXD]
* ADC0_IN03
  - ADC0_IN03: PF20 (L5)  [ANALOG]
```

格式为 `信号: pad 名 (管脚号/球号) [ALT 编号, 芯片原始信号名]`。分到带注释的引脚（启动模式引脚、电源域引脚等）时，末尾会列出 ⚠ 提示。

无解时提示减少外设、改用灵活实例、去掉部分预留引脚或换更大封装。

## 预置的引脚表

**先楫 HPMicro**（数据手册 PINMUX 表 + HPM SDK `hpm_iomux.h` 逐 pad 交叉核对，全部一致）：

| 文件 | 适用型号 | 封装 | 说明 |
|------|----------|------|------|
| `HPM5E3Y.json` | HPM5E3YIVK1 / HPM5E3YIGN1 | BGA121, BGA196 | 内置双以太网 PHY：**PA16~PA31 被 PHY 占用，已排除** |
| `HPM5E31.json` | HPM5E31IVK1 / IGN1 / IPB1 | BGA121, BGA196, ELQFP100 | 无内置 PHY |
| `HPM6E8Y.json` | HPM6E8YIGN1 / HPM6E8YIVM1 | BGA196, BGA289 | 内置双以太网 PHY：**PA16~PA31 已排除** |
| `HPM6E80.json` | HPM6E80IGN1 / IVM1，HPM6E84 | BGA196, BGA289 | 无内置 PHY |

订货型号后缀：VK = BGA121，GN = BGA196，PB = eLQFP100（HPM5E00）；GN = BGA196，VM = BGA289（HPM6E00）。
HPM6E70/6E60/6E6Y/6E50 与同系列共用晶圆和引脚复用定义，但部分外设被裁剪（如无 TSW、CPU1；HPM5E11 无 HR-PWM），引脚表中仍列有这些信号。用于这些型号时，请对照数据手册「订购信息」表，不要分配芯片上不存在的外设。

**极海 Geehy**：`data/` 下 APM32F0/F1/F4/E/A 系列、G32R501、G32R430、G32A1085、GW3323 等（由 `data/Geehy MCU Pin Table.xlsx` 生成）。

## 注意事项

1. **先楫启动引脚**：PA02/PA03 是 BOOT_MODE0/1，复位时的电平决定启动方式。可以复用，但外部电路不能影响启动电平；不想用就 `--reserve PA02,PA03`。
2. **先楫电源域引脚 PY/PZ**（仅 BGA289）：使用 SOC 外设功能前，需先把 PIOC/BIOC 设为 SOC_Px（ALT3），再在 IOC 里选功能。结果中会有提示。
3. **模拟功能**（ADC/ACMP 输入）在引脚表中标为 `ANALOG`，与数字功能互斥，按引脚冲突处理。
4. **F1 类 remap 架构**（APM32F103 等 STM32F1 兼容芯片）：外设引脚只能整组重映射，而求解器按信号独立选脚，结果可能出现硬件不支持的拆分组合，需人工核对重映射组。逐脚选择的芯片（先楫、APM32F4、G32R5xx 等）没有此问题。
5. 求解器只保证**复用不冲突**，不考虑信号完整性、布线方向、电源域电压（VIO 分组）等，最终方案应由工程师复核数据手册。
6. 信号别名自动处理：NSS ↔ CS ↔ CS_0、SIMO/SOMI → MOSI/MISO、TXD/RXD → TX/RX、MCAN → CAN、字母实例号（SPIA → SPI0）。

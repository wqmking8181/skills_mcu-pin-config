一个供 Agent 使用的 MCU 引脚分配 skill

给定芯片和外设需求，自动求出无冲突的引脚分配方案，输出 pad 名、管脚号/球号和 ALT 编号。

- 极海 Geehy：APM32 / G32R5xx / G32A / GW 系列（原始数据：`data/Geehy MCU Pin Table.xlsx`）
- 先楫 HPMicro：HPM5E3Y、HPM5E31、HPM6E8Y、HPM6E80（BGA121 / BGA196 / BGA289 / eLQFP100），由数据手册 PDF 生成并与 HPM SDK 交叉核对
- 伺服常用外设：三相 PWM、QEI/QEP 编码器、SDM/SDFM Σ-Δ、SEI 串行编码器、RS485、CAN，ADC 通道按信号分配

用法详见 [SKILL.md](./SKILL.md)，脚本说明见 [scripts/Readme.md](./scripts/Readme.md)。

## 安装为 Claude skill

下载 Release 中的 `mcu-pin-config-<版本>.zip`（或把仓库中的 `SKILL.md`、`scripts/`、`data/` 打成 zip），
在 Claude 设置的 Skills 中上传即可；Claude Code 用户可直接把仓库放到 `~/.claude/skills/mcu-pin-config/`。

## 快速试用

```
python scripts/find_pins.py info --pin-table data/HPM5E3Y.json --package BGA121

python scripts/find_pins.py search --pin-table data/HPM5E3Y.json --package BGA121 ^
    "PWM0(3-phase)" QEI0 "SDM0(2ch)" "UART(RS485 DE)" CAN ADC0_IN03 --reserve PA02,PA03

python scripts/find_pins.py search --pin-table data/G32R501.json --package LQFP80 UART CAN SPI
```

## 重新生成引脚表

极海（需要 `pip install openpyxl`）：

```
python scripts/convert_pin_table_to_json.py --dest data "data/Geehy MCU Pin Table.xlsx"
```

先楫（需要 `pip install pdfplumber`），命令见 [scripts/Readme.md](./scripts/Readme.md#convert_hpm_datasheetpy)。

## 致谢

基于 [Quincy-Zh/skills_mcu-pin-config](https://github.com/Quincy-Zh/skills_mcu-pin-config)（MIT），在其求解器基础上扩展了先楫 HPM 支持与伺服外设定义。

MCU 外设引脚分配工具

# find_pins.py

```
usage: find-pins [-h] [--peri-def PERI_DEF] {list,info,search} ...

  list     打印外设（及变种）信号列表
  info     打印引脚表中的封装、外设实例、排除的 pad 和引脚注释
  search   搜索引脚分配方案

search 参数:
  --package PACKAGE      封装类型（如 LQFP64、BGA121）
  --pin-table PIN_TABLE  引脚定义 JSON 文件
  --reserve RESERVE      预留引脚（pad 名或管脚号，逗号分隔）
  --json                 以 JSON 输出
  PERIPH ...             需求列表，如: USART1 "SPI1(with NSS)" I2C ADC0_IN03
```

仅依赖 Python 标准库（Python ≥ 3.8）。

示例：
```
python find_pins.py search --pin-table ../data/APM32F427.json --package LQFP64 USART
查找成功，分配方案（封装 LQFP64）：

* USART1  ← USART
  - RX: PA10 (43)
  - TX: PA9 (42)
```

退出码：0 成功；1 文件/封装错误；2 需求写错；3 无解。

Python 中调用：
```python
from find_pins import search
result = search("data/HPM5E3Y.json", "BGA121", ["PWM0(3-phase)", "QEI0"], reserve=["PA02", "PA03"])
```

## peri_def.json

描述每类外设的变种及信号，`--peri-def` 可指定其他文件（默认用本目录下的）。示例：
```json
{
  "UART": {
    "default": ["RX", "TX"],
    "RS485 DE": ["DE", "RX", "TX"]
  },
  "PWM": {
    "3-phase": ["P_0", "P_1", "P_2", "P_3", "P_4", "P_5"]
  }
}
```

- 外设类型按「精确匹配 → 最长前缀」查找；信号名为去掉实例前缀后的部分（`UART0_TX` → `TX`）。
- `force_` 列出的信号每个变种都必须有（如 ETH 的 MDC/MDIO）。

# 引脚表 JSON 格式

```json
{
  "_meta": {"chip": "HPM5E3Y", "source": "...", "excluded_pads": ["PA16", "..."]},
  "BGA121": {
    "pin_map": {"D1": "PA00", "A1": "VSS"},
    "peripheral_table": {
      "UART0_TX": {"actual": "UART0_TXD", "pad-number": ["D1", "..."], "alt": {"D1": 2}},
      "ADC0_IN03": {"pad-number": ["L5"], "alt": {"L5": "ANALOG"}}
    },
    "notes": {"C2": "BOOT_MODE0 启动模式选择..."}
  }
}
```

- 顶层键为封装名；以 `_` 开头的键是元数据。
- `peripheral_table` 的键是规范化后的信号名，`actual` 为芯片原始名称（与规范化名相同时省略）。
- `alt`、`notes`、`_meta` 为可选字段（极海表没有）。

# convert_pin_table_to_json.py（极海）

```
usage: convert_pin_table_to_json.py [-h] --dest DEST filepath

  filepath     Excel 文件路径（.xlsx）
  --dest DEST  输出目录
```

需要 `pip install openpyxl`。Excel 每个工作表对应一个型号，**工作表名需包含 `_OK`**（表示已审核）才会转换，输出文件名取工作表名第一个 `_` 之前的部分。

工作表首行为列标题，至少包含：
- 名称（引脚名）
- 类型（只有 `I/O` 引脚参与外设复用）
- 复用功能 / 附加功能（列名含「功能」「FUNCTION」或「REMAP」）
- 封装列，可以多列，列名以 BGA/LQFP/QFN/SOP/TSSOP/WLCSP 等开头且不重复

# convert_hpm_datasheet.py（先楫）

从先楫数据手册「引脚配置及功能 PINMUX」表生成 JSON。需要 `pip install pdfplumber`。

```
usage: convert_hpm_datasheet.py pdf --chip CHIP [--dest DEST] [--packages P1,P2]
                                [--exclude PADS] [--exclude-reason TEXT]
                                [--note "PAD=TEXT"]... [--iomux hpm_iomux.h]... [--prefer-iomux]
```

- `--exclude`：不参与分配的 pad（如内置 PHY 占用的 `PA16-PA31`），写入 notes 和 `_meta`。
- `--note`：给 pad 加注释，分配到该引脚时提示（如启动引脚）。
- `--iomux`：HPM SDK 的 `soc/<系列>/<芯片>/hpm_iomux.h`（及 `hpm_pmic_iomux.h`、`hpm_batt_iomux.h`），逐 pad 核对手册与 SDK 的 ALT 定义并打印差异；`--prefer-iomux` 时数字功能以 SDK 为准。
- PY/PZ 等电源域 pad 会自动加上「需先将 PIOC/BIOC 设为 SOC_Px」的注释。

预置数据的生成命令（手册：HPM5E00 Rev0.3、HPM6E00 Rev0.10；SDK：hpmicro/hpm_sdk 2026-09）：

```
set BOOT=--note "PA02=BOOT_MODE0 启动模式选择，上电/复位时电平决定启动方式" --note "PA03=BOOT_MODE1 启动模式选择，上电/复位时电平决定启动方式"
set SOC=path\to\hpm_sdk\soc

python convert_hpm_datasheet.py HPM5E00_DS.pdf --chip HPM5E3Y --packages BGA196,BGA121 ^
    --exclude PA16-PA31 --exclude-reason "内置以太网 PHY 占用（HPM5E*Y*），不可复用" %BOOT% ^
    --iomux %SOC%\HPM5E00\HPM5E3Y\hpm_iomux.h --dest ..\data

python convert_hpm_datasheet.py HPM5E00_DS.pdf --chip HPM5E31 --packages BGA196,BGA121,ELQFP100 %BOOT% ^
    --iomux %SOC%\HPM5E00\HPM5E31\hpm_iomux.h --dest ..\data

python convert_hpm_datasheet.py HPM6E00_DS.pdf --chip HPM6E8Y --packages BGA289,BGA196 ^
    --exclude PA16-PA31 --exclude-reason "内置以太网 PHY 占用（HPM6E*Y*），不可复用" %BOOT% ^
    --iomux %SOC%\HPM6E00\HPM6E80\hpm_iomux.h --iomux %SOC%\HPM6E00\HPM6E80\hpm_pmic_iomux.h ^
    --iomux %SOC%\HPM6E00\HPM6E80\hpm_batt_iomux.h --dest ..\data

python convert_hpm_datasheet.py HPM6E00_DS.pdf --chip HPM6E80 --packages BGA289,BGA196 %BOOT% ^
    --iomux %SOC%\HPM6E00\HPM6E80\hpm_iomux.h --iomux %SOC%\HPM6E00\HPM6E80\hpm_pmic_iomux.h ^
    --iomux %SOC%\HPM6E00\HPM6E80\hpm_batt_iomux.h --dest ..\data
```

其他先楫芯片（HPM6200/6300/6P00/5300 等）的数据手册通常采用相同的 PINMUX 表格式，可以按同样方式尝试生成，并务必用 `--iomux` 与 SDK 核对；注意查阅手册中内置 PHY / 内置闪存 / 启动引脚的说明，用 `--exclude`、`--note` 标注。

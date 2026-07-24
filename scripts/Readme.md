MCU 外设引脚分配工具

# find_pins.py
```
usage: find-pins [-h] [--peri-def PERI_DEF] {list,search} ...

查找外设引脚组合

positional arguments:
  {list,search}
    list               打印外设（及变种）信号列表
    search             搜索引脚分配方案

options:
  -h, --help           show this help message and exit
  --peri-def PERI_DEF  外设变种定义文件 (默认 peri_def.json)
```

示例：
```
python .\find_pins.py search --pin-table .\tmp\output.json --package LQFP64  USART
查找成功，分配方案：

* USART1 
  - RX: PA10 (43)
  - TX: PA9 (42)
```

`--peri-def` 指明的文件是用于描述外设信号，示例：
```
{
  "ETH": {
    "force_": [
      "ETH_MDC",
      "ETH_MDIO"
    ],
    "MII, full-duplex": [
      "MII_RX_CLK",
      "MII_RX_DV",
      "MII_RX_ER",
      "MII_RXD0",
      "MII_RXD1",
      "MII_RXD2",
      "MII_RXD3",
      "MII_TX_CLK",
      "MII_TX_EN",
      "MII_TXD0",
      "MII_TXD1",
      "MII_TXD2",
      "MII_TXD3"
    ],
    "MII, half-duplex": [
      "MII_COL",
      "MII_CRS",
      "MII_RX_CLK",
      "MII_RX_DV",
      "MII_RX_ER",
      "MII_RXD0",
      "MII_RXD1",
      "MII_RXD2",
      "MII_RXD3",
      "MII_TX_CLK",
      "MII_TX_EN",
      "MII_TXD0",
      "MII_TXD1",
      "MII_TXD2",
      "MII_TXD3"
    ],
    "RMII": [
      "RMII_CRS_DV",
      "RMII_REF_CLK",
      "RMII_RXD0",
      "RMII_RXD1",
      "RMII_TX_EN",
      "RMII_TXD0",
      "RMII_TXD1"
    ]
  },
  "I2C": {
    "default": [
      "SCL",
      "SDA"
    ],
    "SMBus": [
      "SCL",
      "SDA"
    ],
    "SMBus with alarm": [
      "SCL",
      "SDA",
      "SMBA"
    ]
  }
}
```

可以参考 [peri_def.json](./peri_def.json).

# convert_pin_table_to_json.py
`find_pins.py` 命令行参数 `--pin-table` 可以通过 `convert_pin_table_to_json.py` 生成。

```
usage: convert_pin_table_to_json.py [-h] --dest DEST filepath

positional arguments:
  filepath     Excel 文件路径

options:
  -h, --help   show this help message and exit
  --dest DEST  输出文件路径
```

## CSV 文件格式要求
使用 Tab 作为分隔符，首行为列标题，至少包含：
- 名称
- 类型
- 复用功能
- 附加功能
- 封装名称, 可以多列，并保证封装名称唯一

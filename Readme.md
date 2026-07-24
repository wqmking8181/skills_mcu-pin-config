一个供 Agent 使用的 MCU 引脚分配 skill

初始化时可执行类似命令/脚本:

```
@echo off

echo 创建/更新引脚信息

python .\scripts\convert_pin_table_to_json.py --dest .\data ".\data\Geehy MCU Pin Table.xlsx"
```

简单测试

```
python .\scripts\find_pins.py search --pin-table .\data\G32R501.json --package LQFP80 UART
```

#!/usr/bin/env python3
# Copyright (c) 2026 Quincy.W
# SPDX-License-Identifier: MIT

"""把 Excel 引脚表转换为 JSON 格式文件

将包含引脚复用信息的 Excel 文件转换为机器可读的 JSON 格式，
用于后续外设引脚分配方案的搜索和验证。

支持的 Excel 文件格式：
    - 工作表名需包含 "_OK"（表示已审核通过）
    - 支持.xls和.xlsx格式
    - 每张工作表生成独立JSON文件

Excel 文件结构要求：
    - 至少包含 "名称"、"类型" 和 "复用功能" 列
    - 需包含一个封装类型列（以 BGA/LQFP/QFN 等开头）
    - 信号复用功能格式：外设名称 + 序号 + 信号名（如 SPI1_TX）

输出 JSON 结构示例：
    {
        "LQFP48": {
            "pin_map": {"1": "VBAT", "2": "RST", ...},
            "peripheral_table": {
                "USART1_TX": [{"pad-number": [42], "actual": "PA10"}]
            }
        }
    }

Usage: python convert_pin_table_to_json.py --dest output --filepath pins.xlsx
"""

import argparse
import csv
import json
import os
import sys
import tempfile

from openpyxl import load_workbook

from normalization_signal import normalization

# 封装名称前缀
PACKAGE_NAME_PREFIX = (
    "BGA",
    "LQFP",
    "QFN",
    "SOP",
    "TFBGA",
    "TSSOP",
    "UFBGA",
    "WLCSP",
)


def build_pin_table(
    csv_path,
    pin_name_columon_title: str | None = None,
    pin_type_columon_title: str | None = None,
    delimiter=",",
    encoding="utf-8-sig",
):
    """解析结果，返回格式：
    {
        "LQFP48": {
            "pin_map": {
                "1": "VBAT",
                ...
            },
            "peripheral_table": {
                "CAN2_RX": [
                    "25",
                    "41"
                ],
                "CAN2_TX": [
                    "26",
                    "42"
                ]
                ...
            },
        }
    }
    """
    col_name_func = []  # '功能' 列
    col_name_package = []  # '封装' 列

    spec = {}
    with open(csv_path, encoding=encoding) as f:
        reader = csv.DictReader(f, delimiter=delimiter)

        if reader.fieldnames is None:
            return

        fieldnames = [x for x in reader.fieldnames if x]

        if pin_name_columon_title is None:
            for name in fieldnames:
                if "名称" in name or "NAME" in name.upper():
                    pin_name_columon_title = name
                    fieldnames.remove(name)
                    break

        if pin_type_columon_title is None:
            for name in fieldnames:
                if "类型" in name or "TYPE" in name.upper():
                    pin_type_columon_title = name
                    fieldnames.remove(name)
                    break

        # '功能' 列
        for name in fieldnames:
            if "功能" in name or "FUNCTION" in name.upper() or "REMAP" in name.upper():
                col_name_func.append(name)
                
        # '封装' 列
        for name in fieldnames:
            name_ = name.strip()

            for p in PACKAGE_NAME_PREFIX:
                if name_.startswith(p):
                    col_name_package.append(name)
                    spec[name] = {
                        "pin_map": {},
                        "peripheral_table": {},
                    }
                    break

        if 'Structure' in fieldnames:
            fieldnames.remove('Structure')

        # 移除已经决定采用的列名称
        for name in col_name_func + col_name_package:
            fieldnames.remove(name)

        if fieldnames:
            print(f"! Unprocessed: {','.join(fieldnames)}")

        for row in reader:
            pin_name = row[pin_name_columon_title]
            pin_type = row[pin_type_columon_title]
            func_text = ",".join([row[c] for c in col_name_func])
            functions = [f for f in func_text.split(",") if f != "-" and f != ""]

            for package in col_name_package:
                pin_num = row[package].strip()
                if pin_num == "-" or pin_num == "":
                    continue

                spec[package]["pin_map"][pin_num] = pin_name

                if pin_type != "I/O":
                    continue

                for func in functions:
                    if func == "EVENTOUT":
                        continue

                    res = normalization(func)
                    actual_name = ""

                    if res is None:
                        pin_func = func
                    else:
                        peri_name, peri_index, signal_name = res

                        pin_func = f"{peri_name}{peri_index}_{signal_name}"
                        actual_name = func

                    if pin_func in spec[package]["peripheral_table"]:
                        spec[package]["peripheral_table"][pin_func]["pad-number"] += [
                            pin_num
                        ]
                    else:
                        obj = {}
                        if actual_name:
                            obj["actual"] = actual_name

                        obj["pad-number"] = [pin_num]

                        spec[package]["peripheral_table"][pin_func] = obj
                    # end-if
                # end-for
            # end-for
        # end-for
    # end-with

    return spec


def main():
    parse = argparse.ArgumentParser()

    parse.add_argument("--dest", required=True, help="输出文件路径")
    parse.add_argument("filepath", help="Excel 文件路径")

    args = parse.parse_args(sys.argv[1:])

    if not os.path.exists(args.dest):
        print(f'输出文件路径: "{args.dest}" 不存在, 现在创建 ...')
        os.makedirs(args.dest, exist_ok=True)
    elif os.path.isfile(args.dest):
        print(f'输出文件路径: "{args.dest}" 不是一个目录，请重新指定')
        sys.exit(1)

    if not os.path.isfile(args.filepath):
        print(f'文件: "{args.filepath}" 不存在')
        sys.exit(1)

    _, ext_ = os.path.splitext(args.filepath)
    if ext_ not in (".xls", ".xlsx"):
        print(f'不支持的文件格式: "{ext_}"')
        sys.exit(1)

    wb = load_workbook(args.filepath)

    with tempfile.TemporaryDirectory(prefix="mcu-pin-config") as temp_dir:
        for sheet_name in wb.sheetnames:

            if "SUMMARY" in sheet_name.upper() or "INDEX" in sheet_name.upper():
                continue

            if "_OK" not in sheet_name.upper():
                print(f"未审核的 sheet: {sheet_name}，跳过")
                continue

            # 剔除版本信息及 "_OK" 字符
            items = sheet_name.split("_", maxsplit=1)
            file_basename = f"{items[0]}.json"
            
            tmp_filename = os.path.join(temp_dir, file_basename)

            sheet = wb[sheet_name]

            with open(tmp_filename, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                for row in sheet.iter_rows(values_only=True):
                    writer.writerow(row)

            json_object = build_pin_table(tmp_filename)

            outut_filepath = os.path.join(args.dest, file_basename)
            with open(outut_filepath, "w", encoding="utf-8") as f:
                json.dump(json_object, f, indent=2, ensure_ascii=False)
                print(f"文件已经输出：{outut_filepath}")
        # end-for
    # END


if __name__ == "__main__":
    main()

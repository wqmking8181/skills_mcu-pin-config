#!/usr/bin/env python3
# Copyright (c) 2026 Quincy.W
# SPDX-License-Identifier: MIT

"""在引脚表里搜索外设 PAD 组合，引脚分配。

提供查找外设引脚组合的命令行工具。支持搜索指定外设实例在特定封装中的引脚分配方案。

注意：统一工作目录中的已处理的引脚复用表文件

示例用法：
    python find_pins.py search --package LQFP64 --pin-table pins_lqfp64.json USART1 "SPI1(with NSS)" I2C1

支持命令：
    list：打印外设及其变种信号列表
    search：搜索引脚分配方案

API：
    find_pins.search(pin_table_path, package, requirements) -> dict
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from itertools import product

from normalization_signal import unpack_signal_name

# 信号别名
SIGNAL_ALIASES = {
    "NSS": ["CS"],
    "CS": ["NSS"],
}


def _load_peri_def(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pin_number_to_int(pin_numnber: str) -> int:
    try:
        return int(pin_numnber)
    except (ValueError, TypeError):
        m = re.match(r"([A-Z])(\d+)", pin_numnber)
        if m:
            row, col = m.group(1), m.group(2)

            return (ord(row[0]) - ord("A")) * 100 + int(col)

    return 0


def get_pin_name(func: str, pad_number: int, pin_map: dict[str, str]) -> str:
    for pin_name, value in pin_map.items():
        if pin_number_to_int(pin_name) == pad_number:
            return f"{func}: {value} ({pin_name})"

    return f"{func}: {pad_number}"


class PinMapper:
    def __init__(self, af_table, peri_def):
        """
        af_table:  dict { "USART1_TX": [pad, ...], ... }
        peri_def:  dict 从 peri_def.json 加载的外设变种定义
        """
        self.af_table = af_table
        self.peri_def = peri_def

    def _expand_instance(self, inst_name, variant):
        """将单个实例展开为候选列表 [{inst_name, signals}]"""
        mt = re.match(r"([A-Za-z]+(?:\d[A-Za-z])*)", inst_name)
        ptype = mt.group(1).upper()
        peri_variants = None
        for key, value in self.peri_def.items():
            if ptype.startswith(key):
                peri_variants = value
                break
        if peri_variants is None:
            raise ValueError(f"未知外设类型: {ptype} <-- {inst_name}")

        vname = variant if variant else "default"
        if vname not in peri_variants:
            avail = [k for k in peri_variants if k != "force_"]
            raise ValueError(f'变种 "{vname}" 不存在, {ptype} 可用: {avail}')
        variant_sigs = peri_variants[vname]

        # 检查是否有实例编号: "USART1" → 有, "I2C" → 无
        # 从 inst_name 中去掉类型名前缀，剩余部分即为实例编号
        has_number = bool(re.sub(rf"^{re.escape(ptype)}", "", inst_name))

        if has_number:
            # 固定实例: 只展开这一个
            c = self._expand_one(inst_name, ptype, variant_sigs, peri_variants)
            return [c] if c else []
        else:
            # 灵活实例: 枚举 af_table 中所有同类型实例
            prefix = ptype
            found = set()
            for key in self.af_table:
                m = re.match(rf"({re.escape(prefix)}[A-Z0-9]+)_", key)
                if m:
                    found.add(m.group(1))
            if not found:
                # 无编号实例(如 ETH), 用类型名本身作为唯一候选
                c = self._expand_one(inst_name, ptype, variant_sigs, peri_variants)
                return [c] if c else []
            candidates = []
            for name in sorted(found):
                c = self._expand_one(name, ptype, variant_sigs, peri_variants)
                if c:
                    candidates.append(c)
            return candidates

    def _expand_one(self, inst_name, ptype, variant_sigs, peri_variants):
        """展开单个实例，返回 {inst_name, signals} 或 None"""
        signals = []
        for fs in peri_variants.get("force_", []):
            if fs not in self.af_table:
                return None
            signals.append(fs)
        for s in variant_sigs:
            full = f"{inst_name}_{s}"
            if full in self.af_table:
                signals.append(full)
            else:
                for alias in SIGNAL_ALIASES.get(s, []):
                    full_alias = f"{inst_name}_{alias}"
                    if full_alias in self.af_table:
                        signals.append(full_alias)
                        break
                else:
                    return None
        return {"inst_name": inst_name, "signals": signals}

    def solve(self, required_instances, alias=None):
        """
        required_instances: list of str
            "USART1"             → 固定实例, 只用 USART1
            "USART"              → 灵活匹配, 自动选 USART1/2/3 中任一
            "SPI1(with NSS)"     → 固定实例 + 指定变种
        优先级: 固定实例先占位, 灵活实例填剩余空间。
        返回: dict {信号名: 引脚号} 或 None
        """
        fixed = []  # 有编号: 每个只有 1 个候选
        flexible = []  # 无编号: 每个有多个候选

        for inst in required_instances:
            m = re.match(r"^(.+?)(?:\((.+?)\))?$", inst)
            if not m:
                return None

            inst_name = m.group(1).strip()
            variant = m.group(2).strip() if m.group(2) else None

            mt = re.match(r"([A-Za-z]+(?:\d[A-Za-z])*)", inst_name)
            if not mt:
                return None

            ptype = mt.group(1).upper()
            has_number = bool(re.sub(rf"^{re.escape(ptype)}", "", inst_name))

            candidates = self._expand_instance(inst_name, variant)
            if not candidates:
                print(f"⚠️ 警告: {inst_name} 无可用引脚组合，该实例将无法分配")
                return None

            entry = {"inst_key": inst_name, "candidates": candidates}
            if has_number:
                fixed.append(entry)
            else:
                flexible.append(entry)

        # MRV 排序: 信号数多的优先, 同信号数时固定实例优先
        def sort_key(item):
            sig_count = max(len(c["signals"]) for c in item["candidates"])
            cand_count = len(item["candidates"])
            return (-sig_count, cand_count)

        sorted_instances = sorted(fixed + flexible, key=sort_key)

        used_mask = 0
        used_instances = set()
        assignment = {}

        def backtrack(idx, af_table):
            nonlocal used_mask
            if idx == len(sorted_instances):
                return True

            entry = sorted_instances[idx]
            for cand in entry["candidates"]:
                signals = cand["signals"]
                inst_name = cand["inst_name"]

                # 同一物理实例不能被两个逻辑 slot 选中
                if inst_name in used_instances:
                    continue

                # 收集每个信号的可用引脚
                candidates_per_signal = []
                for sig in signals:
                    avail = [
                        p
                        for p in af_table[sig]["pad-number"]
                        if not (used_mask & (1 << p))
                    ]
                    if not avail:
                        break
                    candidates_per_signal.append(avail)
                else:
                    used_instances.add(inst_name)
                    # 所有信号都有可用引脚, 尝试组合
                    for combo in product(*candidates_per_signal):
                        if len(set(combo)) != len(combo):
                            continue
                        for pin in combo:
                            used_mask |= 1 << pin
                        for sig, pin in zip(signals, combo):
                            assignment[sig] = pin
                        if backtrack(idx + 1, af_table):
                            return True
                        for pin in combo:
                            used_mask &= ~(1 << pin)
                        for sig in signals:
                            assignment.pop(sig, None)
                    used_instances.discard(inst_name)

            return False

        # 把引脚编号（字符串格式）转换为整数
        af_table = {}
        for prei in self.af_table:
            pads = [pin_number_to_int(p) for p in self.af_table[prei]["pad-number"]]

            if "actual" in self.af_table[prei]:
                af_table[prei] = {"actual": self.af_table[prei], "pad-number": pads}
            else:
                af_table[prei] = {"pad-number": pads}

        if backtrack(0, af_table):
            r = {}

            for k, v in assignment.items():
                peri = self.af_table[k]
                key = peri.get("actual", k)

                r[key] = v

            return r

        return None


def build_af_table(json_path, package: str):
    """
    加载 JSON 文件格式的引脚复用表。
    返回 af_table (dict) 和 pin_map (dict: pad→GPIO名)。
    """
    with open(json_path, encoding="utf-8") as f:
        json_object = json.load(f)

    if package not in json_object:
        return None

    package_object = json_object[package]
    af = package_object["peripheral_table"]
    pin_map = package_object.get("pin_map", {})

    return af, pin_map


if __name__ == "__main__":

    parser = argparse.ArgumentParser("find-pins", description="查找外设引脚组合")
    parser.add_argument(
        "--peri-def",
        help="外设变种定义文件 (默认 peri_def.json)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sp_list = subparsers.add_parser("list", help="打印外设（及变种）信号列表")
    sp_search = subparsers.add_parser("search", help="搜索引脚分配方案")

    sp_search.add_argument("--package", required=True, help="封装类型")
    sp_search.add_argument("--pin-table", required=True, help="引脚定义 JSON 文件")
    sp_search.add_argument("--alias", help="别名映射文件，JSON格式，可选")
    sp_search.add_argument(
        "requirements",
        nargs="*",
        metavar="PERIPH",
        help='需求列表，如: USART1 "SPI1(with NSS)" I2C1',
    )

    args = parser.parse_args()

    if not args.peri_def:
        # 使用默认的 peri_def.json 文件
        args.peri_def = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "peri_def.json"
        )

    if not os.path.isfile(args.peri_def):
        print(f'--peri-def 文件 "{args.peri_def}" 不存在', file=sys.stderr)
        sys.exit(1)

    peri_def = _load_peri_def(args.peri_def)

    if args.command == "list":
        for ptype in sorted(peri_def):
            variants = peri_def[ptype]
            force = variants.get("force_", [])
            print(f"{ptype}:")
            if force:
                print(f"  force_: {', '.join(force)}")
            for vname, sigs in variants.items():
                if vname == "force_":
                    continue
                print(f"  {vname}: {', '.join(sigs)}")
        print()
    elif args.command == "search":
        if not os.path.isfile(args.pin_table):
            print(f'--pin-table 文件 "{args.pin_table}" 不存在', file=sys.stderr)
            sys.exit(1)

        if args.alias and not os.path.isfile(args.alias):
            print(f'别名文件已指定 "{args.alias}"，但是文件不存在', file=sys.stderr)
            sys.exit(1)

        if not args.requirements:
            print("请指定外设需求，示例:", file=sys.stderr)
            print(
                '  python find_pins.py --pin-table pins_lqfp48.json USART1 "SPI1(with NSS)" I2C1',
                file=sys.stderr,
            )
            print("使用 --list 查看可选外设及变种", file=sys.stderr)
            sys.exit(1)

        rc = build_af_table(args.pin_table, args.package)
        if not rc:
            print("引脚复用表发生错误")
            sys.exit(1)

        af_table, pin_map = rc
        mapper = PinMapper(af_table, peri_def)
        result = mapper.solve(args.requirements, args.alias)

        if result:
            print("查找成功，分配方案：\n")
            grouped = defaultdict(lambda: defaultdict(dict))
            for sig, pin in result.items():

                r = unpack_signal_name(sig)
                if r is None:
                    continue

                inst_key = f"{r[0]}{r[1]}"
                phys = f"{r[0]}{r[1]}"
                func = r[2]
                grouped[inst_key][phys][func] = pin

            for inst_key, instances in grouped.items():
                for phys, funcs in instances.items():
                    pin_str = "\n  - ".join(
                        [
                            f"{get_pin_name(func, pin, pin_map)}"
                            for func, pin in funcs.items()
                        ]
                    )
                    print(f"* {phys} {'\n  - ' + pin_str}")
        else:
            print("在当前复用表下，无法同时满足所有外设需求。")
            print("   建议：更换更大封装的芯片，或减少外设数量。")

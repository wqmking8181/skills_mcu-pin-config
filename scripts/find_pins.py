#!/usr/bin/env python3
# Copyright (c) 2026 Quincy.W
# SPDX-License-Identifier: MIT

"""在引脚表里搜索外设 PAD 组合，引脚分配。

提供查找外设引脚组合的命令行工具。支持搜索指定外设实例在特定封装中的引脚分配方案。

示例用法：
    python find_pins.py search --package LQFP64 --pin-table pins.json USART1 "SPI1(with NSS)" I2C1
    python find_pins.py search --package BGA121 --pin-table HPM5E3Y.json \\
        "PWM0(3-phase)" QEI0 "SDM0(2ch)" "UART(RS485 DE)" CAN ADC0_IN03 --reserve PA02,PA03

需求写法：
    USART1              固定实例
    USART               灵活实例，自动从 USART1/2/3... 中选一个可用的
    SPI1(with NSS)      固定实例 + 指定变种（变种见 list 子命令）
    ADC0_IN03           单个信号（引脚表中的信号名，或其原始名称）

支持命令：
    list：打印外设及其变种信号列表
    info：打印引脚表中的封装、外设实例
    search：搜索引脚分配方案

API：
    find_pins.search(pin_table_path, package, requirements, peri_def_path=None, reserve=None) -> dict | None
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict
from itertools import product

# 信号别名：peri_def 中的信号名 → 引脚表里可能出现的名字
SIGNAL_ALIASES = {
    "NSS": ["CS", "CS_0"],
    "CS": ["NSS", "CS_0"],
}

RE_PTYPE = re.compile(r"([A-Za-z]+(?:\d[A-Za-z])*)")
RE_REQ = re.compile(r"^(.+?)(?:\((.+?)\))?$")


def _default_peri_def_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "peri_def.json")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_packages(json_object):
    return [k for k in json_object if not k.startswith("_")]


def build_af_table(json_path, package):
    """
    加载 JSON 文件格式的引脚复用表。
    返回 (af_table, pin_map, notes)，封装不存在时返回 None。
    """
    json_object = _load_json(json_path)
    if package not in json_object or package.startswith("_"):
        return None

    package_object = json_object[package]
    af = package_object["peripheral_table"]
    pin_map = package_object.get("pin_map", {})
    notes = package_object.get("notes", {})

    return af, pin_map, notes


class RequirementError(ValueError):
    pass


class PinMapper:
    def __init__(self, af_table, peri_def, pin_map=None, notes=None):
        """
        af_table:  dict { "USART1_TX": {"pad-number": [pad, ...], "actual": "...", "alt": {...}}, ... }
        peri_def:  dict 从 peri_def.json 加载的外设变种定义
        """
        self.af_table = af_table
        self.peri_def = peri_def
        self.pin_map = pin_map or {}
        self.notes = notes or {}
        self.actual_index = {}
        for key, entry in af_table.items():
            actual = entry.get("actual")
            if actual:
                self.actual_index.setdefault(actual, key)

    # ---------- 外设类型 ----------
    def _peri_variants(self, ptype, inst_name):
        if ptype in self.peri_def:
            return self.peri_def[ptype]
        # 最长前缀匹配，避免 "SD" 抢先匹配 "SDM"
        best = None
        for key in self.peri_def:
            if ptype.startswith(key) and (best is None or len(key) > len(best)):
                best = key
        if best is None:
            raise RequirementError(
                f"未知外设类型: {ptype} <-- {inst_name}（可直接写单个信号名，或在 peri_def.json 中补充定义）"
            )
        return self.peri_def[best]

    def resolve_pin(self, pin):
        """把 pad 名(PA02)或管脚号(C2)统一为管脚号"""
        if pin in self.pin_map:
            return pin
        for num, name in self.pin_map.items():
            if name == pin:
                return num
        return pin

    # ---------- 实例展开 ----------
    def _expand_instance(self, inst_name, variant):
        """将单个实例展开为候选列表 [{inst_name, signals}]"""
        mt = RE_PTYPE.match(inst_name)
        if not mt:
            raise RequirementError(f"无法识别的外设: {inst_name}")
        ptype = mt.group(1).upper()
        peri_variants = self._peri_variants(ptype, inst_name)

        vname = variant if variant else "default"
        if vname not in peri_variants:
            avail = [k for k in peri_variants if k != "force_"]
            raise RequirementError(f'变种 "{vname}" 不存在, {ptype} 可用: {avail}')
        variant_sigs = peri_variants[vname]

        # 检查是否有实例编号: "USART1" → 有, "I2C" → 无
        has_number = bool(re.sub(rf"^{re.escape(ptype)}", "", inst_name, flags=re.I))

        if has_number:
            c = self._expand_one(inst_name, variant_sigs, peri_variants)
            return [c] if c else []

        # 灵活实例: 枚举 af_table 中所有同类型实例
        found = set()
        for key in self.af_table:
            m = re.match(rf"({re.escape(ptype)}[0-9]+)_", key)
            if m:
                found.add(m.group(1))
        if not found:
            # 无编号实例(如 ETH), 用类型名本身作为唯一候选
            c = self._expand_one(inst_name, variant_sigs, peri_variants)
            return [c] if c else []
        candidates = []
        for name in sorted(found, key=lambda s: (len(s), s)):
            c = self._expand_one(name, variant_sigs, peri_variants)
            if c:
                candidates.append(c)
        return candidates

    def _expand_one(self, inst_name, variant_sigs, peri_variants):
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
                continue
            for alias in SIGNAL_ALIASES.get(s, []):
                full_alias = f"{inst_name}_{alias}"
                if full_alias in self.af_table:
                    signals.append(full_alias)
                    break
            else:
                return None
        return {"inst_name": inst_name, "signals": signals}

    def _parse_requirement(self, req):
        """返回 (label, candidates)"""
        req = req.strip()
        # 单个信号：精确命中信号名或原始名称
        if req in self.af_table:
            return req, [{"inst_name": req, "signals": [req]}]
        if req in self.actual_index:
            key = self.actual_index[req]
            return req, [{"inst_name": key, "signals": [key]}]

        if "(" not in req and re.match(r"^[A-Za-z][A-Za-z0-9-]*?\d*_\S+$", req):
            # 形如单个信号名，但当前封装中没有
            stem = req.rsplit("_", 1)[0]
            near = sorted(k for k in self.af_table if k.startswith(stem))[:12]
            hint = f"，当前封装中相近的信号: {' '.join(near)}" if near else ""
            raise RequirementError(f"信号 {req} 在当前封装中不存在（未引出或已排除）{hint}")

        m = RE_REQ.match(req)
        if not m:
            raise RequirementError(f"无法识别的需求: {req}")
        inst_name = m.group(1).strip()
        variant = m.group(2).strip() if m.group(2) else None
        return req, self._expand_instance(inst_name, variant)

    # ---------- 求解 ----------
    def solve(self, required_instances, reserve=None):
        """
        required_instances: list of str（写法见模块说明）
        reserve: 预留（不参与分配）的引脚，管脚号或 pad 名
        返回: [{"requirement", "instance", "signals": [{signal, actual, pin, pad, alt, note}]}] 或 None
        """
        entries = []
        for req in required_instances:
            label, candidates = self._parse_requirement(req)
            if not candidates:
                raise RequirementError(f"{label} 在当前封装中没有可用的引脚组合（信号不全或未引出）")
            entries.append({"label": label, "candidates": candidates})

        # MRV 排序: 信号数多的优先, 同信号数时候选少的优先
        order = sorted(
            range(len(entries)),
            key=lambda i: (
                -max(len(c["signals"]) for c in entries[i]["candidates"]),
                len(entries[i]["candidates"]),
            ),
        )

        used_pins = {self.resolve_pin(p) for p in (reserve or [])}
        used_instances = set()
        chosen = {}  # entry index -> (cand, combo)

        def free_pins(sig):
            return [p for p in self.af_table[sig]["pad-number"] if p not in used_pins]

        def feasible(i):
            for cand in entries[i]["candidates"]:
                if cand["inst_name"] in used_instances:
                    continue
                if all(free_pins(s) for s in cand["signals"]):
                    return True
            return False

        def backtrack(k):
            if k == len(order):
                return True
            i = order[k]
            for cand in entries[i]["candidates"]:
                inst_name = cand["inst_name"]
                # 同一物理实例不能被两个需求同时选中
                if inst_name in used_instances:
                    continue
                pins_per_signal = [free_pins(s) for s in cand["signals"]]
                if not all(pins_per_signal):
                    continue
                used_instances.add(inst_name)
                for combo in product(*pins_per_signal):
                    if len(set(combo)) != len(combo):
                        continue
                    used_pins.update(combo)
                    # 前向检查：剩余每个需求至少还有一个候选
                    if all(feasible(order[j]) for j in range(k + 1, len(order))):
                        chosen[i] = (cand, combo)
                        if backtrack(k + 1):
                            return True
                        chosen.pop(i, None)
                    used_pins.difference_update(combo)
                used_instances.discard(inst_name)
            return False

        if not backtrack(0):
            return None

        result = []
        for i, entry in enumerate(entries):
            cand, combo = chosen[i]
            sigs = []
            for sig, pin in zip(cand["signals"], combo):
                info = self.af_table[sig]
                sigs.append(
                    {
                        "signal": sig,
                        "actual": info.get("actual", sig),
                        "pin": pin,
                        "pad": self.pin_map.get(pin, ""),
                        "alt": info.get("alt", {}).get(pin),
                        "note": self.notes.get(pin, ""),
                    }
                )
            result.append({"requirement": entry["label"], "instance": cand["inst_name"], "signals": sigs})
        return result


def search(pin_table_path, package, requirements, peri_def_path=None, reserve=None):
    """Python API：返回分配结果列表，无解时返回 None"""
    rc = build_af_table(pin_table_path, package)
    if not rc:
        raise RequirementError(f"引脚表中没有封装 {package}")
    af_table, pin_map, notes = rc
    peri_def = _load_json(peri_def_path or _default_peri_def_path())
    return PinMapper(af_table, peri_def, pin_map, notes).solve(requirements, reserve)


def _short_signal(inst, sig):
    prefix = f"{inst}_"
    return sig[len(prefix):] if sig.startswith(prefix) else sig


def format_result(result, package):
    lines = [f"查找成功，分配方案（封装 {package}）：", ""]
    warnings = []
    for item in result:
        inst = item["instance"]
        head = f"* {inst}"
        if item["requirement"] != inst:
            head += f"  ← {item['requirement']}"
        lines.append(head)
        for s in item["signals"]:
            func = _short_signal(inst, s["signal"])
            where = f"{s['pad']} ({s['pin']})" if s["pad"] else str(s["pin"])
            extra = []
            if s["alt"] is not None:
                extra.append(s["alt"] if isinstance(s["alt"], str) else f"ALT{s['alt']}")
            if s["actual"] != s["signal"]:
                extra.append(s["actual"])
            tail = f"  [{', '.join(extra)}]" if extra else ""
            lines.append(f"  - {func}: {where}{tail}")
            if s["note"]:
                warnings.append(f"  {where} {s['actual']}: {s['note']}")
    if warnings:
        lines += ["", "⚠ 注意以下引脚："] + warnings
    return "\n".join(lines)


def print_info(json_path, package=None):
    obj = _load_json(json_path)
    meta = obj.get("_meta")
    if meta:
        print(f"芯片: {meta.get('chip', '')}  来源: {meta.get('source', '')}")
        if meta.get("excluded_pads"):
            print(f"已排除 pad: {', '.join(meta['excluded_pads'])}（{meta.get('excluded_reason', '')}）")
    pkgs = list_packages(obj)
    print(f"封装: {', '.join(pkgs)}")
    for pkg in [package] if package else pkgs:
        if pkg not in pkgs:
            print(f"没有封装 {pkg}", file=sys.stderr)
            sys.exit(1)
        table = obj[pkg]["peripheral_table"]
        groups = defaultdict(set)
        singles = []
        for key in table:
            m = re.match(r"^([A-Z][A-Z0-9-]*?\d+)_", key)
            if m:
                ptype = RE_PTYPE.match(m.group(1)).group(1)
                groups[ptype].add(m.group(1))
            else:
                singles.append(key)
        print(f"\n[{pkg}] 信号 {len(table)} 个，外设实例：")
        for ptype in sorted(groups):
            insts = sorted(groups[ptype], key=lambda s: (len(s), s))
            print(f"  {ptype}: {' '.join(insts)}")
        if singles:
            print(f"  其他信号: {' '.join(sorted(singles)[:40])}{' ...' if len(singles) > 40 else ''}")
        notes = obj[pkg].get("notes", {})
        if notes:
            print("  引脚注释: " + "; ".join(f"{k} {obj[pkg]['pin_map'].get(k, '')}: {v}" for k, v in list(notes.items())[:20]))


def main():
    parser = argparse.ArgumentParser("find-pins", description="查找外设引脚组合")
    parser.add_argument("--peri-def", help="外设变种定义文件 (默认与本脚本同目录的 peri_def.json)")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    subparsers.add_parser("list", help="打印外设（及变种）信号列表")

    sp_info = subparsers.add_parser("info", help="打印引脚表中的封装和外设实例")
    sp_info.add_argument("--pin-table", required=True, help="引脚定义 JSON 文件")
    sp_info.add_argument("--package", help="只看某个封装")

    sp_search = subparsers.add_parser("search", help="搜索引脚分配方案")
    sp_search.add_argument("--package", required=True, help="封装类型")
    sp_search.add_argument("--pin-table", required=True, help="引脚定义 JSON 文件")
    sp_search.add_argument("--reserve", default="", help="预留引脚（管脚号或 pad 名，逗号分隔），不参与分配")
    sp_search.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    sp_search.add_argument("--alias", help=argparse.SUPPRESS)  # 兼容旧参数，未使用
    sp_search.add_argument(
        "requirements",
        nargs="*",
        metavar="PERIPH",
        help='需求列表，如: USART1 "SPI1(with NSS)" I2C1 ADC0_IN03',
    )

    args = parser.parse_args()
    peri_def_path = args.peri_def or _default_peri_def_path()
    if not os.path.isfile(peri_def_path):
        print(f'--peri-def 文件 "{peri_def_path}" 不存在', file=sys.stderr)
        sys.exit(1)
    peri_def = _load_json(peri_def_path)

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
        return

    if not os.path.isfile(args.pin_table):
        print(f'--pin-table 文件 "{args.pin_table}" 不存在', file=sys.stderr)
        sys.exit(1)

    if args.command == "info":
        print_info(args.pin_table, args.package)
        return

    if not args.requirements:
        print("请指定外设需求，示例:", file=sys.stderr)
        print('  python find_pins.py search --pin-table pins.json --package LQFP48 USART1 "SPI1(with NSS)" I2C1', file=sys.stderr)
        print("使用 list 子命令查看可选外设及变种，info 子命令查看引脚表内容", file=sys.stderr)
        sys.exit(1)

    rc = build_af_table(args.pin_table, args.package)
    if not rc:
        pkgs = list_packages(_load_json(args.pin_table))
        print(f"引脚表中没有封装 {args.package}，可用: {', '.join(pkgs)}", file=sys.stderr)
        sys.exit(1)

    af_table, pin_map, notes = rc
    mapper = PinMapper(af_table, peri_def, pin_map, notes)
    reserve = [x.strip() for x in args.reserve.split(",") if x.strip()]
    try:
        result = mapper.solve(args.requirements, reserve)
    except RequirementError as e:
        print(f"需求有误: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(
            {"package": args.package, "ok": result is not None, "assignment": result or []},
            ensure_ascii=False, indent=2,
        ))
        sys.exit(0 if result else 3)

    if result:
        print(format_result(result, args.package))
    else:
        print("在当前复用表下，无法同时满足所有外设需求。")
        print("   建议：减少外设数量、改用灵活实例（如 UART 代替 UART3）、去掉部分预留引脚，或更换更大封装。")
        sys.exit(3)


if __name__ == "__main__":
    main()

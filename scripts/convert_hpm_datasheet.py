#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""从先楫 (HPMicro) 数据手册 PDF 生成引脚复用 JSON 表

先楫数据手册「引脚配置及功能 PINMUX」一节是一张大表，每行一个 pad：
    | 封装列(1~N 个) | PIN 名称 | 数字功能(含 ALTn) | 模拟功能 | 供电分组 |
本脚本用 pdfplumber 逐页提取该表，生成与 find_pins.py 兼容的 JSON：

    {
      "_meta": {...},
      "BGA121": {
        "pin_map":  {"D1": "PA00", "A1": "VSS", ...},
        "peripheral_table": {
          "UART0_TX": {"actual": "UART0_TXD", "pad-number": ["D1", ...], "alt": {"D1": 2}},
          "ADC0_IN08": {"pad-number": ["K6"], "alt": {"K6": "ANALOG"}}
        },
        "notes": {"C2": "BOOT_MODE0 启动模式选择引脚"}
      }
    }

可选 --iomux 指定 HPM SDK 中的 hpm_iomux.h（及 hpm_pmic_iomux.h 等），
脚本会逐 pad 交叉核对手册与 SDK 的 ALT 定义并报告差异；加 --prefer-iomux
时数字功能以 SDK 为准（手册仍提供封装管脚号与模拟功能）。

用法示例（HPM5E3Y，内置 PHY 占用 PA16~PA31）：
    python convert_hpm_datasheet.py HPM5E00_DS.pdf --chip HPM5E3Y \\
        --packages BGA196,BGA121 --exclude PA16-PA31 \\
        --exclude-reason "内置以太网 PHY 占用" \\
        --note "PA02=BOOT_MODE0 启动模式选择" --note "PA03=BOOT_MODE1 启动模式选择" \\
        --iomux hpm_sdk/soc/HPM5E00/HPM5E3Y/hpm_iomux.h --dest ../data

依赖：pdfplumber（pip install pdfplumber）
"""

import argparse
import json
import os
import re
import sys

from normalization_signal import normalization

RE_PAD = re.compile(r"^P[A-Z]\d{2}$")
RE_DIGITAL = re.compile(r"([A-Z][A-Z0-9_]*)\(ALT(\d+)\)")
RE_IOMUX = re.compile(
    r"#define\s+([A-Z]*IOC)_(P[A-Z]\d{2})_FUNC_CTL_([A-Z0-9_]+)\s+"
    r"IOC_PAD_FUNC_CTL_ALT_SELECT_SET\((\d+)\)"
)
# PY/PZ 等电源域 pad 有两级复用：电源域 PIOC/BIOC 与 SOC 侧 IOC
RE_DOMAIN_FUNC = re.compile(r"^[PB]GPIO_")
DOMAIN_NOTE = "电源域引脚：使用 SOC 外设功能前，需先将电源域 IOC（PIOC/BIOC）设为 SOC_P{port}{num}（ALT3），再在 IOC 中选择功能"
# 纯 GPIO 及电源域内部路由功能不参与外设分配
RE_SKIP_FUNC = re.compile(r"^(GPIO_|[PB]GPIO_|SOC_P[YZ]_)")


def _clean(cell):
    return (cell or "").strip()


def _norm_package(title):
    t = title.replace("\n", "").replace("_", "").replace(" ", "").upper()
    return t


def parse_range_list(text):
    """'PA16-PA31,PB02' -> {'PA16',...,'PA31','PB02'}"""
    pads = set()
    for item in filter(None, [x.strip() for x in (text or "").split(",")]):
        m = re.fullmatch(r"(P[A-Z])(\d{2})-(P[A-Z])?(\d{2})", item)
        if m:
            port, a, port2, b = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            if port2 and port2 != port:
                raise ValueError(f"范围不能跨端口: {item}")
            for i in range(a, b + 1):
                pads.add(f"{port}{i:02d}")
        elif RE_PAD.fullmatch(item):
            pads.add(item)
        else:
            raise ValueError(f"无法识别的 pad: {item}")
    return pads


def split_analog(cell):
    """模拟功能列会折行（如 'ACMP0_CH0_I' + 'NP1'），把不成词的碎片接回前一项"""
    tokens = []
    for line in _clean(cell).split("\n"):
        line = line.strip()
        if not line or line == "-":
            continue
        if tokens and not re.match(r"^[A-Z]+\d*_", line):
            tokens[-1] += line
        else:
            tokens.append(line)
    return tokens


def extract_rows(pdf_path):
    """返回 (packages, pads, power)
    pads:  [{pad, balls{pkg: ball|None}, digital[(name, alt)], analog[...], group}]
    power: [{name, balls{pkg: [ball,...]}}]
    """
    import pdfplumber

    packages = None
    pads, power = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "").replace(" ", "")
            if "PIN名称" not in text:
                continue
            for table in page.extract_tables():
                for row in table:
                    cells = [c or "" for c in row]
                    flat = [c.replace("\n", "") for c in cells]
                    if "PIN名称" in flat:
                        if packages is None:
                            idx = flat.index("PIN名称")
                            packages = [_norm_package(c) for c in cells[:idx]]
                        continue
                    if packages is None or flat[0] == "封装":
                        continue
                    n = len(packages)
                    if len(cells) < n + 3:
                        continue
                    name = flat[n].strip()
                    digital_cell = cells[n + 1]
                    analog_cell = cells[n + 2] if len(cells) >= n + 4 else ""
                    group = _clean(cells[-1])

                    if RE_PAD.fullmatch(name):
                        balls = {}
                        for pkg, c in zip(packages, flat[:n]):
                            c = c.strip()
                            balls[pkg] = None if c in ("", "-") else c
                        digital = [
                            (m.group(1), int(m.group(2)))
                            for m in RE_DIGITAL.finditer(digital_cell.replace("\n", ""))
                        ]
                        pads.append(
                            {
                                "pad": name,
                                "balls": balls,
                                "digital": digital,
                                "analog": split_analog(analog_cell),
                                "group": group,
                            }
                        )
                    elif not name and pads and _clean(digital_cell):
                        # 跨页续行：功能接到上一个 pad
                        prev = pads[-1]
                        prev["digital"] += [
                            (m.group(1), int(m.group(2)))
                            for m in RE_DIGITAL.finditer(digital_cell.replace("\n", ""))
                        ]
                        prev["analog"] += split_analog(analog_cell)
                    elif name and name != "-":
                        balls = {}
                        for pkg, c in zip(packages, flat[:n]):
                            balls[pkg] = [
                                b.strip() for b in c.split(",") if b.strip() not in ("", "-")
                            ]
                        power.append({"name": name, "balls": balls})
    if packages is None:
        raise RuntimeError("未在 PDF 中找到 PINMUX 表（表头需含 'PIN名称'）")
    return packages, pads, power


def _row_ctrl(digital):
    """手册中同一 pad 可能出现两行：SOC 侧 IOC 与电源域 PIOC/BIOC"""
    return "DOMAIN" if any(RE_DOMAIN_FUNC.match(n) for n, _ in digital) else "IOC"


def load_iomux(paths):
    """返回 {(ctrl, pad): {(func, alt)}}，ctrl 为 'IOC' 或 'DOMAIN'(PIOC/BIOC)"""
    funcs = {}
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as f:
            for m in RE_IOMUX.finditer(f.read()):
                ctrl = "IOC" if m.group(1) == "IOC" else "DOMAIN"
                funcs.setdefault((ctrl, m.group(2)), set()).add((m.group(3), int(m.group(4))))
    return funcs


def cross_check(pads, iomux):
    """返回差异列表 [(pad, only_in_datasheet, only_in_sdk)]"""
    diffs = []
    for p in pads:
        key = (_row_ctrl(p["digital"]), p["pad"])
        if key not in iomux:
            continue
        ds = {(n, a) for n, a in p["digital"] if not RE_SKIP_FUNC.match(n)}
        sdk = {(n, a) for n, a in iomux[key] if not RE_SKIP_FUNC.match(n)}
        if ds != sdk:
            label = p["pad"] + ("(PIOC/BIOC)" if key[0] == "DOMAIN" else "")
            diffs.append((label, sorted(ds - sdk), sorted(sdk - ds)))
    return diffs


def normalize_func(name):
    res = normalization(name)
    if res is None:
        return name, None
    peri, idx, sig = res
    key = f"{peri}{idx}_{sig}"
    return key, (name if key != name else None)


def build_json(packages, pads, power, chip, source, exclude, exclude_reason, notes, iomux_funcs, prefer_iomux):
    out = {
        "_meta": {
            "chip": chip,
            "source": source,
            "generator": "convert_hpm_datasheet.py",
            "packages": packages,
            "excluded_pads": sorted(exclude),
            "excluded_reason": exclude_reason if exclude else "",
        }
    }
    domain_pads = {p["pad"] for p in pads if _row_ctrl(p["digital"]) == "DOMAIN"}
    for pkg in packages:
        pin_map, table, pkg_notes = {}, {}, {}
        for pw in power:
            for b in pw["balls"].get(pkg, []):
                pin_map[b] = pw["name"]
        for p in pads:
            ball = p["balls"].get(pkg)
            if not ball:
                continue
            pin_map[ball] = p["pad"]
            if p["pad"] in domain_pads:
                pkg_notes[ball] = DOMAIN_NOTE.format(port=p["pad"][1], num=p["pad"][2:])
            if p["pad"] in notes:
                pkg_notes[ball] = notes[p["pad"]]
            if p["pad"] in exclude:
                pkg_notes[ball] = exclude_reason or "已排除，不参与分配"
                continue

            digital = p["digital"]
            key = (_row_ctrl(digital), p["pad"])
            if prefer_iomux and key in iomux_funcs:
                digital = sorted(iomux_funcs[key], key=lambda x: x[1])

            funcs = [(n, a) for n, a in digital if not RE_SKIP_FUNC.match(n)]
            funcs += [(n, "ANALOG") for n in p["analog"]]
            for name, alt in funcs:
                key, actual = normalize_func(name)
                entry = table.setdefault(key, {"pad-number": [], "alt": {}})
                if actual:
                    entry["actual"] = actual
                if ball not in entry["pad-number"]:
                    entry["pad-number"].append(ball)
                    entry["alt"][ball] = alt
        out[pkg] = {
            "pin_map": pin_map,
            "peripheral_table": dict(sorted(table.items())),
            "notes": pkg_notes,
        }
    return out


def main():
    ap = argparse.ArgumentParser(description="先楫数据手册 PDF → 引脚复用 JSON")
    ap.add_argument("pdf", help="数据手册 PDF")
    ap.add_argument("--chip", required=True, help="输出 JSON 的芯片名，也是文件名，如 HPM5E3Y")
    ap.add_argument("--dest", default=".", help="输出目录")
    ap.add_argument("--packages", help="只输出这些封装，逗号分隔，如 BGA196,BGA121")
    ap.add_argument("--exclude", default="", help="不参与分配的 pad，如 PA16-PA31,PB02")
    ap.add_argument("--exclude-reason", default="", help="排除原因（写入 notes）")
    ap.add_argument("--note", action="append", default=[], help='pad 注释，如 "PA02=BOOT_MODE0"，可多次')
    ap.add_argument("--iomux", action="append", default=[], help="HPM SDK hpm_iomux.h，可多次")
    ap.add_argument("--prefer-iomux", action="store_true", help="数字功能以 SDK 为准")
    ap.add_argument("--source", default="", help="数据来源说明（写入 _meta）")
    args = ap.parse_args()

    packages, pads, power = extract_rows(args.pdf)
    print(f"解析到封装: {', '.join(packages)}；IO pad {len(pads)} 个；电源/特殊引脚 {len(power)} 行")

    if args.packages:
        want = [_norm_package(x) for x in args.packages.split(",")]
        missing = [w for w in want if w not in packages]
        if missing:
            print(f"手册中没有封装: {missing}", file=sys.stderr)
            sys.exit(1)
        packages = want

    exclude = parse_range_list(args.exclude)
    notes = {}
    for n in args.note:
        pad, _, text = n.partition("=")
        notes[pad.strip()] = text.strip()

    iomux_funcs = load_iomux(args.iomux) if args.iomux else {}
    if iomux_funcs:
        diffs = cross_check(pads, iomux_funcs)
        ds_keys = {(_row_ctrl(p["digital"]), p["pad"]) for p in pads}
        sdk_only = sorted({pad for ctrl, pad in set(iomux_funcs) - ds_keys})
        print(f"与 SDK 交叉核对: {len(pads) - len(diffs)}/{len(pads)} 个 pad 完全一致")
        for pad, a, b in diffs:
            print(f"  ! {pad}: 仅手册 {a}  仅SDK {b}")
        if sdk_only:
            print(f"  SDK 中有、手册未列出的 pad（通常为芯片内部 pad）: {' '.join(sdk_only)}")

    data = build_json(
        packages, pads, power, args.chip, args.source or os.path.basename(args.pdf),
        exclude, args.exclude_reason, notes, iomux_funcs, args.prefer_iomux,
    )
    os.makedirs(args.dest, exist_ok=True)
    path = os.path.join(args.dest, f"{args.chip}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    for pkg in packages:
        io = sum(1 for v in data[pkg]["pin_map"].values() if RE_PAD.fullmatch(v))
        print(f"  {pkg}: {len(data[pkg]['pin_map'])} 个引脚（IO {io}），{len(data[pkg]['peripheral_table'])} 个信号")
    print(f"文件已经输出：{path}")


if __name__ == "__main__":
    main()

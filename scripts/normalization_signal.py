#!/usr/bin/env python3
# Copyright (c) 2026 Quincy.W
# SPDX-License-Identifier: MIT

"""信号名称标准化模块

MCU外设信号名称标准化处理模块，负责将各种格式的信号名称
转换为统一的标准格式，便于后续处理和匹配。

支持的输入信号格式：
    1. 外设名称 + 序号 + 信号名（如 SPI1_TX）
    2. 外设名称 + 信号名（如 SPI_TX）
    3. 外设名称 + 下划线 + 信号名（如 SPI_TX）
    4. 外设名称 + A-Z序号 + 信号名（如 SPIA_TX） - 会转成 SPI0_TX

标准化规则：
    - 将 A-Z 格式的序号转换为数字（A-0, B-1, ...）
    - 处理已知信号别名（如 SPI中的NSS对应CS）
    - 保留原始信号名称的 actual 字段信息

函数:
    normalization(signal_in) -> (peri_name, peri_index, signal_name) | None
    unpack_signal_name(signal_in) -> (peri_name, peri_index, signal_name) | None

示例：
    normalization("SPI1_TX") -> ("SPI", "1", "TX")
    normalization("SPI_TX") -> ("SPI", "", "TX")
    normalization("SPIA_TX") -> ("SPI", "0", "TX")  # A-Z转数字
"""

import re

# 外设名称前缀
PERIPHERAL_PREFIXES = (
    "ADC",
    "CAN",
    "DAC",
    "ETH",
    "I2C",
    "I2S",
    "JTCK",
    "JTDI",
    "JTDO",
    "JTMS",
    "MCO",
    "NJTRST",
    "OSC",
    "OSC32",
    "QSPI",
    "RTC",
    "SDIO",
    "SMC",
    "SPI",
    "SWCLK",
    "SWDIO",
    "TMR",
    "TRACE",
    "UART",
    "USART",
    "OTG-FS",
    "OTG-HS",
    "WKUP",
)

# 记录一些信号别名
SIGNAL_ALIAS = {
    "SPI": {
        # CS
        "NSS": "CS",
        "NSEL": "CS",
        "STE": "CS",
        # SCK
        "CLK": "SCK",
        "SCLK": "SCK",
        # MOSI
        "SIMO": "MOSI",  # G32R5xx
        "DO": "MOSI",  # GW3323
        # MISO
        "SOMI": "MISO",  # G32R5xx
        "DI": "MISO",  # GW3323
    },
    "QSPI": {
        "SS_N": "CS",
        "SCLK": "SCK",
    },
}

# "外设信号"正则表达式
rex_peri = re.compile(f"^({"|".join([f"{p}" for p in PERIPHERAL_PREFIXES])})(\\S+)$")
# 外设的"信号"正则表达式
rex_signal_name = re.compile("^([A-Z0-9]+)_(\\S+)$")


def unpack_signal_name(signal_in: str):
    m = rex_peri.match(signal_in)
    if not m:
        return None

    peri_index = ""
    signal_name = ""

    peri_name, func_signal_name = m.group(1), m.group(2)

    if func_signal_name[0] == "_":
        # 符合 [外设]_[信号名称] 的格式，保持文字内容不变
        peri_index = ""
        signal_name = func_signal_name[1:]
    else:
        m = rex_signal_name.match(func_signal_name)
        if not m:
            # 符合 [外设][信号名称] 的格式，增加下划线作为分隔符
            peri_index = ""
            signal_name = func_signal_name
        else:
            # 符合 [外设][序号]_[信号名称] 的格式，增加下划线作为分隔符
            peri_index, signal_name = m.group(1), m.group(2)

    return peri_name, peri_index, signal_name


def normalization(signal_in) -> tuple[str, str, str] | None:
    """把符合以下格式的*非正规化*信号名称，转化
    - [外设名称][信号名称]
    - [外设名称]_[信号名称]
    - [外设名称][字母序号]_[信号名称]
    """

    res = unpack_signal_name(signal_in)
    if res is None:
        return None

    peri_name, peri_index, signal_name = res

    if peri_index and peri_index in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        # 规范化：把A-Z 的序号改为数值，A-0, B-1 ...
        peri_index = f"{ord(peri_index) - ord('A')}"

    if peri_name in SIGNAL_ALIAS and signal_name in SIGNAL_ALIAS[peri_name]:
        signal_name = SIGNAL_ALIAS[peri_name][signal_name]

    return peri_name, peri_index, signal_name

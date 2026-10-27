#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""回归测试：python -m unittest discover -s tests"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from find_pins import RequirementError, search  # noqa: E402
from normalization_signal import normalization  # noqa: E402

DATA = os.path.join(ROOT, "data")


def pins_of(result):
    return [s["pin"] for item in result for s in item["signals"]]


def by_signal(result):
    return {s["signal"]: s for item in result for s in item["signals"]}


class TestNormalization(unittest.TestCase):
    def test_vendor_names(self):
        self.assertEqual(normalization("SPIA_SOMI"), ("SPI", "0", "MISO"))
        self.assertEqual(normalization("MCAN0_TXD"), ("CAN", "0", "TX"))
        self.assertEqual(normalization("UART3_RXD"), ("UART", "3", "RX"))
        # 长前缀优先：SDM 不能被识别成 SD
        self.assertEqual(normalization("SDM0_CLK_0"), ("SDM", "0", "CLK_0"))
        self.assertEqual(normalization("SD1_D1"), ("SD", "1", "D1"))


class TestGeehy(unittest.TestCase):
    def test_apm32f427_readme_example(self):
        r = search(os.path.join(DATA, "APM32F427.json"), "LQFP64", ["USART1", "SPI1(with NSS)", "I2C1", "CAN1"])
        self.assertIsNotNone(r)
        self.assertEqual(len(set(pins_of(r))), len(pins_of(r)))

    def test_g32r501_motor(self):
        r = search(os.path.join(DATA, "G32R501.json"), "LQFP80", ["PWM1", "PWM2", "PWM3", "QEP1", "SD1(3ch)"])
        self.assertIsNotNone(r)
        self.assertEqual(len(set(pins_of(r))), len(pins_of(r)))


class TestHPM(unittest.TestCase):
    def test_hpm5e3y_bga121_servo(self):
        req = ["PWM0(3-phase)", "QEI0", "SDM0(2ch)", "UART(RS485 DE)", "CAN", "ADC0_IN03"]
        r = search(os.path.join(DATA, "HPM5E3Y.json"), "BGA121", req, reserve=["PA02", "PA03"])
        self.assertIsNotNone(r)
        pads = [s["pad"] for item in r for s in item["signals"]]
        self.assertEqual(len(set(pads)), len(pads))
        # 预留与 PHY 占用的 pad 不得出现
        for p in ["PA02", "PA03"] + [f"PA{i}" for i in range(16, 32)]:
            self.assertNotIn(p, pads)
        # 手册核对点：PWM0_P_0 只能在 PA00(D1)，ALT16
        s = by_signal(r)["PWM0_P_0"]
        self.assertEqual((s["pad"], s["pin"], s["alt"]), ("PA00", "D1", 16))

    def test_hpm6e8y_bga196_dual_axis(self):
        req = ["PWM0(3-phase)", "PWM1(3-phase)", "SEI", "SEI(no clock)", "QEI", "SDM0(4ch)", "CAN", "CAN"]
        r = search(os.path.join(DATA, "HPM6E8Y.json"), "BGA196", req)
        self.assertIsNotNone(r)
        self.assertEqual(len(set(pins_of(r))), len(pins_of(r)))
        insts = [item["instance"] for item in r]
        self.assertEqual(len(set(insts)), len(insts))

    def test_missing_signal_message(self):
        with self.assertRaises(RequirementError) as cm:
            search(os.path.join(DATA, "HPM5E3Y.json"), "BGA121", ["ADC1_IN04"])
        self.assertIn("不存在", str(cm.exception))

    def test_impossible(self):
        # BGA121 上 SPI 只引出 SPI1，要两个 SPI 必然无解
        r = search(os.path.join(DATA, "HPM5E3Y.json"), "BGA121", ["SPI", "SPI"])
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()

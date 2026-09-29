import unittest
from pathlib import Path

import hwlab_prog
from hwlab_prog import ProgError, UsbDevice


def dev(name, vid, pid):
    return UsbDevice(name, vid, pid)


class ProbeTests(unittest.TestCase):
    def test_classifies_the_three_probes(self):
        devices = [
            dev("STM32 STLink", 0x0483, 0x374B),
            dev("USBasp", 0x16C0, 0x05DC),
            dev("CMSIS-DAP", 0x0D28, 0x0204),
            dev("USB Serial", 0x1A86, 0x7523),
        ]
        grouped = hwlab_prog.group_probes(devices)
        self.assertEqual(grouped["stlink"][0].name, "STM32 STLink")
        self.assertEqual(grouped["asp"][0].name, "USBasp")
        self.assertEqual(grouped["nanodap"][0].name, "CMSIS-DAP")

    def test_stlink_is_not_also_nanodap(self):
        grouped = hwlab_prog.group_probes([dev("CMSIS-DAP", 0x0483, 0x374B)])
        self.assertEqual(grouped["stlink"][0].pid, 0x374B)
        self.assertEqual(grouped["nanodap"], [])

    def test_parses_system_profiler_ids(self):
        tree = {
            "SPUSBDataType": [
                {
                    "_name": "USB2.0 Hub",
                    "vendor_id": "0x2109  (VIA Labs, Inc.)",
                    "product_id": "0x2815",
                    "_items": [
                        {
                            "_name": "USBasp",
                            "vendor_id": "0x16c0",
                            "product_id": "0x05dc",
                        }
                    ],
                }
            ]
        }
        devices = hwlab_prog.iter_devices(tree)
        self.assertEqual(hwlab_prog.probe_of(devices[1]), "asp")

    def test_list_marks_absent_probes(self):
        text = hwlab_prog.format_list(hwlab_prog.group_probes([]))
        self.assertIn("nanodap  absent", text)
        self.assertIn("stlink  absent", text)
        self.assertIn("asp  absent", text)


class ArgvTests(unittest.TestCase):
    def test_openocd_requires_matching_interface(self):
        files = {
            "board.cfg": "source [find interface/cmsis-dap.cfg]\n",
        }
        argv = hwlab_prog.build_openocd_argv(
            "nanodap",
            ["-f", "board.cfg", "-c", "program a.elf verify reset exit"],
            files.__getitem__,
        )
        self.assertEqual(argv[0], "openocd")
        self.assertIn("board.cfg", argv)

    def test_openocd_rejects_stlink_cfg_on_nanodap(self):
        files = {"board.cfg": "source [find interface/stlink.cfg]\n"}
        with self.assertRaises(ProgError):
            hwlab_prog.build_openocd_argv(
                "nanodap", ["-f", "board.cfg"], files.__getitem__
            )

    def test_openocd_ignores_commented_interface(self):
        files = {
            "board.cfg": "# source [find interface/stlink.cfg]\n"
            "source [find interface/cmsis-dap.cfg]\n",
        }
        hwlab_prog.build_openocd_argv(
            "nanodap", ["-f", "board.cfg"], files.__getitem__
        )

    def test_real_board_cfgs_match_their_probes(self):
        root = Path(__file__).resolve().parents[1]
        pairs = [
            ("motor-ctrl/src/firmware/stm32f030/openocd.cfg", "nanodap"),
            ("tars-io-crosspoint/firmware/stm32f030f4/openocd.cfg", "nanodap"),
            ("tars-io-mux/firmware/stm32f030/openocd.cfg", "nanodap"),
            ("tars/openocd.cfg", "stlink"),
        ]

        def read_text(path):
            return Path(path).read_text(encoding="utf-8")

        for rel, probe in pairs:
            cfg = root / rel
            argv = hwlab_prog.build_openocd_argv(probe, ["-f", str(cfg)], read_text)
            self.assertEqual(argv[0], "openocd")

    def test_avrdude_injects_usbasp_and_rejects_c(self):
        argv = hwlab_prog.build_avrdude_argv(["-p", "t13", "-U", "flash:w:a.hex:i"])
        self.assertEqual(argv[:3], ["avrdude", "-c", "usbasp"])
        with self.assertRaises(ProgError):
            hwlab_prog.build_avrdude_argv(["-c", "avrisp", "-p", "t13"])


if __name__ == "__main__":
    unittest.main()

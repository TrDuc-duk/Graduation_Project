#!/usr/bin/env python3
"""Kiểm tra xử lý lỗi AHT10 trên máy, không truy cập USB hay database."""
from pathlib import Path
import subprocess
import tempfile

host_dir = Path(__file__).resolve().parent
node_dir = host_dir.parents[1]
with tempfile.TemporaryDirectory(prefix="aqi-sensor-test-") as work:
    for driver, flags in [("aht10", []), ("ccs811", ["-DTEST_CCS811"])]:
        executable = Path(work) / ("test-" + driver)
        subprocess.run([
            "g++", "-std=c++17", *flags, "-I" + str(host_dir / "stubs"),
            "-I" + str(node_dir / "src"), "-I" + str(node_dir / "include"),
            str(node_dir / f"src/drivers/{driver}.cpp"),
            str(host_dir / f"test_{driver}_read.cpp"), "-o", str(executable),
        ], check=True)
        subprocess.run([str(executable)], check=True)

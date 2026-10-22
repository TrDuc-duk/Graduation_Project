"""Cờ chất lượng `qc_flags` của số đo (database_design 8.1). Định nghĩa duy nhất cho mọi module."""

from enum import IntFlag


class QcFlag(IntFlag):
    """Mỗi bit đánh dấu một vấn đề của bản ghi."""

    PM_OUT_OF_RANGE = 1 << 0  # PM ngoài [0, 1000] → null
    PM10_LT_PM25 = 1 << 1  # PM10 < PM2.5 (giữ nguyên giá trị)
    GAS_NOT_READY = 1 << 2  # CO2 = 0: CCS811 chưa sẵn sàng
    GAS_INVALID = 1 << 3  # CO2/TVOC lỗi hoặc ngoài khoảng
    TH_OUT_OF_RANGE = 1 << 4  # nhiệt độ/độ ẩm ngoài khoảng
    HIGH_HUMIDITY = 1 << 5  # độ ẩm > 95%: PMS7003 đo cao
    TIME_ESTIMATED = 1 << 6  # thời điểm đo do server ước lượng
    PM_SPIKE = 1 << 7  # PM2.5 tăng đột ngột (chỉ đánh dấu)
    UNTRUSTED_GATEWAY = 1 << 8  # qua Gateway chưa duyệt: cách ly
    TIME_UNRELIABLE = 1 << 9  # batch nghi chứa dữ liệu cũ
    INTERVAL_UNKNOWN = 1 << 10  # chưa biết chu kỳ node
    TIME_FROM_MSG_ID = 1 << 11  # lùi thời gian theo msg_id
    SUPERSEDED = 1 << 12  # bị thay bằng bản sao tốt hơn
    DEVICE_CLOCK_AHEAD = 1 << 13  # thời điểm firmware vượt thời điểm nhận


# Bản ghi mang một trong các cờ này không dùng cho tổng hợp, ML, số đo hiện tại, cảnh báo
EXCLUDE_MASK = QcFlag.UNTRUSTED_GATEWAY | QcFlag.TIME_UNRELIABLE | QcFlag.SUPERSEDED  # = 4864


def is_state_trusted(flags: int) -> bool:
    """True nếu bản ghi được phép cập nhật trạng thái vận hành và dùng cho tổng hợp (R18)."""
    return flags & EXCLUDE_MASK == 0

"""Cấu hình log cho cả tiến trình."""

import logging


def setup_logging(level: str) -> None:
    """Ghi log ra stdout theo một định dạng thống nhất (Docker thu log từ stdout)."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    # Log truy cập của uvicorn quá nhiều với Gateway gửi mỗi 30 giây
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

"""Cấu hình đọc từ biến môi trường (backend_design 15.1)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Toàn bộ biến môi trường backend cần. Biến compose chưa truyền thì dùng giá trị mặc định ở đây."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    migration_database_url: str = ""
    app_role: Literal["all", "api", "worker"] = "all"
    app_tz: str = "Asia/Ho_Chi_Minh"
    jwt_secret: str = ""
    # Danh sách secret Gateway được chấp nhận, cách nhau bằng dấu phẩy (backend_design 14.1)
    gateway_secrets: Annotated[list[str], NoDecode] = []
    provision_key: str
    scheduler_enabled: bool = True
    log_level: str = "INFO"
    enable_api_docs: bool = False
    # Endpoint chỉ đọc cho dashboard demo (xem cả node pending). Chỉ bật ở môi trường dev
    enable_dev_endpoints: bool = False
    # Token tĩnh quyền assistant:read cho xiaozhi-bridge; để trống thì không mở API trợ lý (09-xiaozhi-mcp)
    assistant_token: str = ""

    @field_validator("gateway_secrets", mode="before")
    @classmethod
    def split_secrets(cls, value: object) -> object:
        """Đổi chuỗi "a,b" trong .env thành danh sách ["a", "b"], bỏ phần tử rỗng."""
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return value

    @property
    def scheduler_active(self) -> bool:
        """Job nền chỉ chạy ở vai trò all/worker và khi không bị tắt (test tắt đi)."""
        return self.scheduler_enabled and self.app_role in ("all", "worker")


@lru_cache
def get_settings() -> Settings:
    """Đọc cấu hình một lần rồi dùng lại cho cả tiến trình."""
    return Settings()

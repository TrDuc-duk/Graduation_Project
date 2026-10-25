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
    # Ngôn ngữ khi request không gửi Accept-Language (backend_design 11.1)
    default_language: Literal["vi", "en"] = "vi"
    # OpenWeatherMap (backend_design 11.11): để trống key thì tắt thẻ thời tiết
    weather_api_key: str = ""
    weather_cache_ttl_s: int = 900
    # Thư mục model, mỗi phiên bản một thư mục con (backend_design 8.1)
    model_dir: str = "/models/xgb"
    # Gốc URL công khai, dùng tạo đường dẫn trong thông báo
    public_base_url: str = ""
    # Tài khoản admin đầu tiên cho scripts.create_admin (bí mật, chỉ trong .env; không truyền vào container chạy lâu)
    admin_username: str = ""
    admin_password: str = ""
    # Origin được gọi API từ trình duyệt khác origin (chỉ dev, vd http://localhost:5173); production để trống
    cors_origins: Annotated[list[str], NoDecode] = []

    @field_validator("gateway_secrets", "cors_origins", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
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

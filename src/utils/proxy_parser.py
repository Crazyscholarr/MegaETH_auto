import re
import random
import string
from pathlib import Path
from typing import Literal, TypedDict, Union

from pydantic import BaseModel, Field, field_validator
from pydantic.networks import HttpUrl, IPv4Address


Protocol = Literal["http", "https"]
PROXY_FORMATS_REGEXP = [
    re.compile(
        r"^(?:(?P<protocol>.+)://)?"  # Tùy chọn: giao thức
        r"(?P<login>[^@:]+)"  # Tên đăng nhập (không chứa ':' hoặc '@')
        r":(?P<password>[^@]+)"  # Mật khẩu (có thể chứa ':', nhưng không chứa '@')
        r"[@:]"  # Ký tự '@' hoặc ':' làm dấu phân cách
        r"(?P<host>[^@:\s]+)"  # Máy chủ (không chứa ':' hoặc '@')
        r":(?P<port>\d{1,5})"  # Cổng: từ 1 đến 5 chữ số
        r"(?:\[(?P<refresh_url>https?://[^\s\]]+)\])?$"  # Tùy chọn: [refresh_url]
    ),
    re.compile(
        r"^(?:(?P<protocol>.+)://)?"  # Tùy chọn: giao thức
        r"(?P<host>[^@:\s]+)"  # Máy chủ (không chứa ':' hoặc '@')
        r":(?P<port>\d{1,5})"  # Cổng: từ 1 đến 5 chữ số
        r"[@:]"  # Ký tự '@' hoặc ':' làm dấu phân cách
        r"(?P<login>[^@:]+)"  # Tên đăng nhập (không chứa ':' hoặc '@')
        r":(?P<password>[^@]+)"  # Mật khẩu (có thể chứa ':', nhưng không chứa '@')
        r"(?:\[(?P<refresh_url>https?://[^\s\]]+)\])?$"  # Tùy chọn: [refresh_url]
    ),
    re.compile(
        r"^(?:(?P<protocol>.+)://)?"  # Tùy chọn: giao thức
        r"(?P<host>[^@:\s]+)"  # Máy chủ (không chứa ':' hoặc '@')
        r":(?P<port>\d{1,5})"  # Cổng: từ 1 đến 5 chữ số
        r"(?:\[(?P<refresh_url>https?://[^\s\]]+)\])?$"  # Tùy chọn: [refresh_url]
    ),
]


class ParsedProxy(TypedDict):
    host: str
    port: int
    protocol: Protocol | None
    login: str | None
    password: str | None
    refresh_url: str | None


def parse_proxy_str(proxy: str) -> ParsedProxy:
    if not proxy:
        raise ValueError(f"Proxy không thể là chuỗi rỗng")

    for pattern in PROXY_FORMATS_REGEXP:
        match = pattern.match(proxy)
        if match:
            groups = match.groupdict()
            return {
                "host": groups["host"],
                "port": int(groups["port"]),
                "protocol": groups.get("protocol"),
                "login": groups.get("login"),
                "password": groups.get("password"),
                "refresh_url": groups.get("refresh_url"),
            }

    raise ValueError(f"Định dạng proxy không được hỗ trợ: '{proxy}'")


def _load_lines(filepath: Path | str) -> list[str]:
    with open(filepath, "r") as file:
        return [line.strip() for line in file.readlines() if line != "\n"]


class PlaywrightProxySettings(TypedDict, total=False):
    server: str
    bypass: str | None
    username: str | None
    password: str | None


class Proxy(BaseModel):
    host: str
    port: int = Field(gt=0, le=65535)
    protocol: Protocol = "http"
    login: str | None = None
    password: str | None = None
    refresh_url: str | None = None

    @field_validator("host")
    def host_validator(cls, v):
        if v.replace(".", "").isdigit():
            IPv4Address(v)
        else:
            HttpUrl(f"http://{v}")
        return v

    @field_validator("refresh_url")
    def refresh_url_validator(cls, v):
        if v:
            HttpUrl(v)
        return v

    @field_validator("protocol")
    def protocol_validator(cls, v):
        if v not in ["http", "https"]:
            raise ValueError("Chỉ hỗ trợ giao thức http và https")
        return v

    @classmethod
    def from_str(cls, proxy: Union[str, "Proxy"]) -> "Proxy":
        if proxy is None:
            raise ValueError("Proxy không thể là None")

        if isinstance(proxy, (cls, Proxy)):
            return proxy

        parsed_proxy = parse_proxy_str(proxy)
        parsed_proxy["protocol"] = parsed_proxy["protocol"] or "http"
        return cls(**parsed_proxy)

    @classmethod
    def from_file(cls, filepath: Path | str) -> list["Proxy"]:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Tệp proxy không tồn tại: {filepath}")
        return [cls.from_str(proxy) for proxy in _load_lines(path)]

    @property
    def as_url(self) -> str:
        return (
            f"{self.protocol}://"
            + (f"{self.login}:{self.password}@" if self.login and self.password else "")
            + f"{self.host}:{self.port}"
        )

    @property
    def server(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def as_playwright_proxy(self) -> PlaywrightProxySettings:
        return PlaywrightProxySettings(
            server=self.server,
            password=self.password,
            username=self.login,
        )

    @property
    def as_proxies_dict(self) -> dict:
        """
        Trả về một từ điển chứa cài đặt proxy ở định dạng có thể sử dụng với thư viện `requests`.

        Từ điển sẽ có định dạng như sau:

        - Nếu giao thức proxy là "http", "https", hoặc không được chỉ định, từ điển sẽ có các khóa "http" và "https" với giá trị là URL proxy.
        - Nếu giao thức proxy là một giao thức khác (ví dụ: "socks5"), từ điển sẽ chỉ có một khóa với tên giao thức và giá trị là URL proxy.
        """
        proxies = {}
        if self.protocol in ("http", "https", None):
            proxies["http"] = self.as_url
            proxies["https"] = self.as_url
        elif self.protocol:
            proxies[self.protocol] = self.as_url
        return proxies

    @property
    def fixed_length(self) -> str:
        return f"[{self.host:>15}:{str(self.port):<5}]".replace(" ", "_")

    def __repr__(self):
        if self.refresh_url:
            return f"Proxy({self.as_url}, [{self.refresh_url}])"

        return f"Proxy({self.as_url})"

    def __str__(self) -> str:
        return self.as_url

    def __hash__(self):
        return hash(
            (
                self.host,
                self.port,
                self.protocol,
                self.login,
                self.password,
                self.refresh_url,
            )
        )

    def __eq__(self, other):
        if isinstance(other, Proxy):
            return (
                self.host == other.host
                and self.port == other.port
                and self.protocol == other.protocol
                and self.login == other.login
                and self.password == other.password
                and self.refresh_url == other.refresh_url
            )
        return False

    def get_default_format(self) -> str:
        """Trả về chuỗi proxy ở định dạng user:pass@ip:port"""
        if not (self.login and self.password):
            raise ValueError("Proxy phải có tên đăng nhập và mật khẩu")
        return f"{self.login}:{self.password}@{self.host}:{self.port}"
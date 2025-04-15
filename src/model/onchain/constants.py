from decimal import Decimal
from typing import Dict
from dataclasses import dataclass


@dataclass
class Balance:
    """Biểu diễn số dư ở các định dạng khác nhau."""

    _wei: int
    decimals: int = 18  # ETH mặc định có 18 chữ số thập phân
    symbol: str = "ETH"  # Ký hiệu ETH mặc định

    @property
    def wei(self) -> int:
        """Lấy số dư ở đơn vị wei."""
        return self._wei

    @property
    def formatted(self) -> float:
        """Lấy số dư ở đơn vị token."""
        return float(Decimal(str(self._wei)) / Decimal(str(10**self.decimals)))

    @property
    def gwei(self) -> float:
        """Lấy số dư ở đơn vị gwei (chỉ áp dụng cho ETH)."""
        if self.symbol != "ETH":
            raise ValueError("gwei chỉ áp dụng cho ETH")
        return float(Decimal(str(self._wei)) / Decimal("1000000000"))  # 1e9

    @property
    def ether(self) -> float:
        """Lấy số dư ở đơn vị ether (chỉ áp dụng cho ETH)."""
        if self.symbol != "ETH":
            raise ValueError("ether chỉ áp dụng cho ETH")
        return self.formatted

    @property
    def eth(self) -> float:
        """Bí danh cho ether (chỉ áp dụng cho ETH)."""
        return self.ether

    def __str__(self) -> str:
        """Biểu diễn chuỗi của số dư."""
        return f"{self.formatted} {self.symbol} ({self._wei} wei)"

    def __repr__(self) -> str:
        """Biểu diễn chuỗi chi tiết của số dư."""
        base_repr = f"Balance(wei={self._wei}, formatted={self.formatted}, symbol={self.symbol})"
        if self.symbol == "ETH":
            base_repr = (
                f"Balance(wei={self._wei}, gwei={self.gwei}, ether={self.ether})"
            )
        return base_repr

    def to_dict(self) -> Dict[str, float]:
        """Chuyển đổi số dư sang biểu diễn từ điển."""
        if self.symbol == "ETH":
            return {"wei": self.wei, "gwei": self.gwei, "ether": self.ether}
        return {"wei": self.wei, "formatted": self.formatted}

    @classmethod
    def from_wei(
        cls, wei_amount: int, decimals: int = 18, symbol: str = "ETH"
    ) -> "Balance":
        """Tạo thể hiện Balance từ số tiền wei."""
        return cls(_wei=wei_amount, decimals=decimals, symbol=symbol)

    @classmethod
    def from_formatted(
        cls, amount: float, decimals: int = 18, symbol: str = "ETH"
    ) -> "Balance":
        """Tạo thể hiện Balance từ số tiền đã định dạng."""
        wei_amount = int(Decimal(str(amount)) * Decimal(str(10**decimals)))
        return cls(_wei=wei_amount, decimals=decimals, symbol=symbol)

    @classmethod
    def from_ether(cls, ether_amount: float) -> "Balance":
        """Tạo thể hiện Balance từ số tiền ether."""
        wei_amount = int(Decimal(str(ether_amount)) * Decimal("1000000000000000000"))
        return cls(_wei=wei_amount)

    @classmethod
    def from_gwei(cls, gwei_amount: float) -> "Balance":
        """Tạo thể hiện Balance từ số tiền gwei."""
        wei_amount = int(Decimal(str(gwei_amount)) * Decimal("1000000000"))
        return cls(_wei=wei_amount)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Balance):
            return NotImplemented
        return self._wei == other._wei

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Balance):
            return NotImplemented
        return self._wei < other._wei

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Balance):
            return NotImplemented
        return self._wei > other._wei

    def __add__(self, other: object) -> "Balance":
        if not isinstance(other, Balance):
            return NotImplemented
        return Balance(_wei=self._wei + other._wei)

    def __sub__(self, other: object) -> "Balance":
        if not isinstance(other, Balance):
            return NotImplemented
        return Balance(_wei=self._wei - other._wei)
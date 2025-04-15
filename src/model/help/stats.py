from eth_account import Account
from typing import Optional, Tuple
from dataclasses import dataclass
from threading import Lock
from loguru import logger
from src.utils.config import Config
from src.model.onchain.web3_custom import Web3Custom


@dataclass
class WalletInfo:
    account_index: int
    private_key: str
    address: str
    balance: float
    transactions: int


class WalletStats:
    def __init__(self, config: Config, web3: Web3Custom):
        # Sử dụng node RPC công khai của Base
        self.w3 = web3
        self.config = config
        self._lock = Lock()

    async def get_wallet_stats(
        self, private_key: str, account_index: int
    ) -> Optional[bool]:
        """
        Lấy thống kê ví và lưu vào cấu hình

        Args:
            private_key: Khóa riêng của ví
            account_index: Chỉ số tài khoản

        Returns:
            bool: True nếu thành công, False nếu có lỗi
        """
        try:
            # Lấy địa chỉ từ khóa riêng
            account = Account.from_key(private_key)
            address = account.address

            # Lấy số dư
            balance = await self.w3.get_balance(address)
            balance_eth = balance.ether

            # Lấy số lượng giao dịch (nonce)
            tx_count = await self.w3.web3.eth.get_transaction_count(address)

            wallet_info = WalletInfo(
                account_index=account_index,
                private_key=private_key,
                address=address,
                balance=float(balance_eth),
                transactions=tx_count,
            )

            with self._lock:
                self.config.WALLETS.wallets.append(wallet_info)

            logger.info(
                f"{account_index} | {address} | "
                f"Số dư = {balance_eth:.7f} M-ETH, "
                f"Giao dịch = {tx_count}"
            )

            return True

        except Exception as e:
            logger.error(f"Lỗi khi lấy thống kê ví: {e}")
            return False
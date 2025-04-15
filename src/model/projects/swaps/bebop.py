import asyncio
import random
import hashlib
import time
import os

from eth_account.messages import encode_typed_data
from eth_account import Account
from src.model.onchain.web3_custom import Web3Custom
from loguru import logger
import primp
from web3 import Web3
from curl_cffi.requests import AsyncSession

from src.utils.decorators import retry_async
from src.utils.config import Config
from src.utils.constants import EXPLORER_URL_MEGAETH

CHAIN_ID = 6342  # From constants.py comment

# Contract addresses
WETH_CONTRACT = Web3.to_checksum_address("0x4eb2bd7bee16f38b1f4a0a5796fffd028b6040e9")
SPENDER_CONTRACT = Web3.to_checksum_address(
    "0x000000000022D473030F116dDEE9F6B43aC78BA3"
)  # Hợp đồng để phê duyệt chi tiêu WETH
ROUTER_CONTRACT = Web3.to_checksum_address(
    "0xbeb0b0623f66be8ce162ebdfa2ec543a522f4ea6"
)  # Router Bebop
CUSD_CONTRACT = Web3.to_checksum_address(
    "0xe9b6e75c243b6100ffcb1c66e8f78f96feea727f"
)  # Token cUSD

# ABIs
WETH_ABI = [
    {
        "constant": False,
        "inputs": [],
        "name": "deposit",
        "outputs": [],
        "payable": True,
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "wad", "type": "uint256"}],
        "name": "withdraw",
        "outputs": [],
        "type": "function",
    },
]

# ERC20 ABI for approve function
ERC20_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

# Constants
MAX_UINT256 = 2**256 - 1  # Giá trị uint256 tối đa cho phê duyệt không giới hạn

# Default swap amount in ETH (0.0000006 ETH)
DEFAULT_SWAP_AMOUNT_ETH = 0.0000006


class Bebop:
    def __init__(
        self,
        account_index: int,
        session: primp.AsyncClient,
        web3: Web3Custom,
        config: Config,
        wallet: Account,
        proxy: str,
        private_key: str,
    ):
        self.account_index = account_index
        self.session = session
        self.web3 = web3
        self.config = config
        self.wallet = wallet
        self.proxy = proxy
        self.private_key = private_key

    def _eth_to_wei(self, eth_amount):
        """Chuyển đổi số lượng ETH sang wei"""
        return int(eth_amount * 10**18)

    async def swaps(self):
        try:
            logger.info(f"{self.account_index} | Đang bắt đầu thao tác hoán đổi tại Bebop...")

            # Kiểm tra số dư WETH
            weth_contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(WETH_CONTRACT), abi=WETH_ABI
            )
            weth_balance_wei = await weth_contract.functions.balanceOf(
                self.wallet.address
            ).call()
            weth_balance = weth_balance_wei / 10**18

            logger.info(f"{self.account_index} | Số dư WETH: {weth_balance} WETH")

            # Lấy số dư ETH
            eth_balance_wei = await self.web3.web3.eth.get_balance(self.wallet.address)
            eth_balance = eth_balance_wei / 10**18

            logger.info(f"{self.account_index} | Số dư ETH: {eth_balance} ETH")

            # Kiểm tra xem "SWAP_ALL_TO_ETH" có được bật trong cấu hình không
            swap_all_to_eth = self.config.SWAPS.BEBOP.SWAP_ALL_TO_ETH

            # Nếu SWAP_ALL_TO_ETH là true, luôn bán WETH sang ETH nếu có WETH
            if swap_all_to_eth:
                if weth_balance > 0:
                    logger.info(
                        f"{self.account_index} | Cấu hình đặt để hoán đổi tất cả WETH sang ETH"
                    )
                    # Mở gói tất cả WETH sang ETH
                    await self._approve_weth()
                    return await self._unwrap_weth_to_eth(weth_balance)
                else:
                    logger.info(
                        f"{self.account_index} | SWAP_ALL_TO_ETH được bật nhưng không có số dư WETH. Bỏ qua."
                    )
                    return True

            # Logic hoán đổi thông thường (khi SWAP_ALL_TO_ETH là false)
            if weth_balance > 0:
                # Nếu có WETH, bán tất cả
                logger.info(
                    f"{self.account_index} | Tìm thấy số dư WETH. Đang mở gói WETH sang ETH..."
                )
                await self._approve_weth()
                return await self._unwrap_weth_to_eth(weth_balance)
                
            else:
                # Nếu không có WETH, mua một ít bằng phần trăm ETH
                # Lấy phạm vi phần trăm từ cấu hình
                percentage_range = self.config.SWAPS.BEBOP.BALANCE_PERCENTAGE_TO_SWAP
                percentage = random.uniform(percentage_range[0], percentage_range[1])

                # Tính toán số lượng để hoán đổi (phần trăm số dư ETH)
                swap_amount = (eth_balance * percentage) / 100

                # Làm tròn đến 8 chữ số thập phân
                swap_amount = round(swap_amount, 8)

                logger.info(
                    f"{self.account_index} | Hoán đổi {swap_amount} ETH ({percentage:.2f}% số dư) sang WETH"
                )

                # Kiểm tra nếu số lượng quá nhỏ
                if swap_amount < 0.00000001:
                    logger.warning(
                        f"{self.account_index} | Số lượng hoán đổi quá nhỏ. Sử dụng số lượng tối thiểu."
                    )
                    swap_amount = 0.00000001

                # Bước 1: Gói ETH thành WETH
                return await self._swap_eth_to_weth(swap_amount)

        except Exception as e:
            logger.error(f"{self.account_index} | Lỗi khi hoán đổi token tại Bebop: {e}")
            return False

    @retry_async(default_value=False)
    async def _check_cusd_balance(self):
        """Kiểm tra số dư cUSD của ví"""
        try:
            logger.info(f"{self.account_index} | Đang kiểm tra số dư cUSD...")

            # Tạo phiên bản hợp đồng
            cusd_contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(CUSD_CONTRACT), abi=ERC20_ABI
            )

            # Lấy số dư
            balance_wei = await cusd_contract.functions.balanceOf(
                self.wallet.address
            ).call()

            # Chuyển đổi từ wei sang cUSD (18 chữ số thập phân)
            balance_cusd = balance_wei / 10**18

            logger.info(f"{self.account_index} | Số dư cUSD: {balance_cusd} cUSD")
            return balance_cusd

        except Exception as e:
            logger.error(f"{self.account_index} | Không thể kiểm tra số dư cUSD: {e}")
            return 0

    @retry_async(default_value=False)
    async def _swap_eth_to_weth(self, amount_eth):
        try:
            # Chuyển đổi ETH sang wei
            amount_wei = self._eth_to_wei(amount_eth)

            logger.info(f"{self.account_index} | Đang gói {amount_eth} ETH thành WETH...")

            # Tạo phiên bản hợp đồng
            weth_contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(WETH_CONTRACT), abi=WETH_ABI
            )

            # Lấy tham số gas
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy tham số gas")

            # Chuẩn bị tham số giao dịch
            tx_params = {
                "from": self.wallet.address,
                "value": amount_wei,
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
                "chainId": CHAIN_ID,
                **gas_params,
            }

            # Đặt loại giao dịch dựa trên tham số gas
            if "maxFeePerGas" in gas_params:
                tx_params["type"] = 2

            # Xây dựng giao dịch sử dụng hàm deposit
            tx = await weth_contract.functions.deposit().build_transaction(tx_params)

            # Thực hiện giao dịch
            tx_hash = await self.web3.execute_transaction(
                tx,
                wallet=self.wallet,
                chainId=CHAIN_ID,
                explorer_url=EXPLORER_URL_MEGAETH,
            )

            if tx_hash:
                logger.success(
                    f"{self.account_index} | Đã gói {amount_eth} ETH thành WETH thành công! TX: {EXPLORER_URL_MEGAETH}{tx_hash}"
                )
                return True
            else:
                logger.error(f"{self.account_index} | Giao dịch thất bại.")
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể hoán đổi ETH sang WETH: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    @retry_async(default_value=False)
    async def _approve_weth(self):
        try:
            logger.info(f"{self.account_index} | Đang phê duyệt WETH để chi tiêu...")

            # Tạo phiên bản hợp đồng
            weth_contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(WETH_CONTRACT), abi=WETH_ABI
            )

            # Lấy tham số gas
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy tham số gas")

            # Chuẩn bị tham số giao dịch
            tx_params = {
                "from": self.wallet.address,
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
                "chainId": CHAIN_ID,
                **gas_params,
            }

            # Đặt loại giao dịch dựa trên tham số gas
            if "maxFeePerGas" in gas_params:
                tx_params["type"] = 2

            # Xây dựng giao dịch để phê duyệt số lượng tối đa
            tx = await weth_contract.functions.approve(
                self.web3.web3.to_checksum_address(SPENDER_CONTRACT), MAX_UINT256
            ).build_transaction(tx_params)

            # Thực hiện giao dịch
            tx_hash = await self.web3.execute_transaction(
                tx,
                wallet=self.wallet,
                chainId=CHAIN_ID,
                explorer_url=EXPLORER_URL_MEGAETH,
            )

            if tx_hash:
                logger.success(
                    f"{self.account_index} | Đã phê duyệt WETH để chi tiêu thành công! TX: {EXPLORER_URL_MEGAETH}{tx_hash}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch phê duyệt WETH thất bại."
                )
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể phê duyệt WETH: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    @retry_async(default_value=False)
    async def _approve_cusd(self):
        try:
            logger.info(f"{self.account_index} | Đang phê duyệt cUSD để chi tiêu...")

            # Payload phê duyệt từ giao dịch ví dụ
            approve_data = "0x095ea7b3000000000000000000000000000000000022d473030f116ddee9f6b43ac78ba3ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

            # Lấy tham số gas
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy tham số gas")

            # Chuẩn bị tham số giao dịch
            tx = {
                "from": self.wallet.address,
                "to": CUSD_CONTRACT,  # Hợp đồng token cUSD
                "data": approve_data,
                "value": 0,  # Không gửi giá trị ETH
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
                "chainId": CHAIN_ID,
                **gas_params,
            }

            # Ước tính gas
            try:
                gas_limit = await self.web3.estimate_gas(tx)
                tx["gas"] = gas_limit
            except Exception as e:
                raise e

            # Đặt loại giao dịch dựa trên tham số gas
            if "maxFeePerGas" in gas_params:
                tx["type"] = 2

            # Ký giao dịch
            signed_tx = self.web3.web3.eth.account.sign_transaction(tx, self.wallet.key)

            # Gửi giao dịch
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_tx.raw_transaction
            )
            tx_hex = tx_hash.hex()

            # Đợi biên lai giao dịch
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Đã phê duyệt cUSD để chi tiêu thành công! TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch phê duyệt cUSD thất bại."
                )
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể phê duyệt cUSD: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    @retry_async(default_value=False)
    async def _unwrap_weth_to_eth(self, amount_eth):
        try:
            # Chuyển đổi ETH sang wei
            amount_wei = self._eth_to_wei(amount_eth)

            logger.info(
                f"{self.account_index} | Đang mở gói {amount_eth} ETH từ WETH sang ETH..."
            )

            # Tạo bộ chọn hàm và mã hóa tham số số lượng
            function_selector = "0x2e1a7d4d"  # withdraw(uint256)
            amount_hex = hex(amount_wei)[2:].zfill(
                64
            )  # Chuyển sang hex không có '0x' và đệm thành 64 ký tự

            # Xây dựng payload hoàn chỉnh
            withdraw_data = function_selector + amount_hex

            # Lấy tham số gas
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy tham số gas")

            # Chuẩn bị tham số giao dịch
            tx = {
                "from": self.wallet.address,
                "to": WETH_CONTRACT,  # Hợp đồng token WETH
                "data": withdraw_data,
                "value": 0,  # Không gửi giá trị ETH
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
                "chainId": CHAIN_ID,
                **gas_params,
            }

            # Ước tính gas
            try:
                gas_limit = await self.web3.estimate_gas(tx)
                tx["gas"] = gas_limit
            except Exception as e:
                logger.warning(
                    f"{self.account_index} | Lỗi khi ước tính gas: {e}. Sử dụng giới hạn gas mặc định."
                )
                tx["gas"] = 40000  # Giới hạn gas mặc định cho rút WETH

            # Đặt loại giao dịch dựa trên tham số gas
            if "maxFeePerGas" in gas_params:
                tx["type"] = 2

            # Ký giao dịch
            signed_tx = self.web3.web3.eth.account.sign_transaction(tx, self.wallet.key)

            # Gửi giao dịch
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_tx.raw_transaction
            )
            tx_hex = tx_hash.hex()

            # Đợi biên lai giao dịch
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Đã mở gói {amount_eth} ETH từ WETH sang ETH thành công! TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch mở gói WETH sang ETH thất bại."
                )
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể mở gói WETH sang ETH: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise
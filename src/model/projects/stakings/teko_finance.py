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

CHAIN_ID = 6342  # Từ bình luận trong constants.py


class TekoFinance:
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

    async def faucet(self):
        try:
            payloads = [
                {
                    "token": "tkETH",
                    "payload": f"0x40c10f19000000000000000000000000{self.wallet.address.lower()[2:]}0000000000000000000000000000000000000000000000000de0b6b3a7640000",
                    "contract": Web3.to_checksum_address(
                        "0x176735870dc6C22B4EBFBf519DE2ce758de78d94"
                    ),
                },
                {
                    "token": "tkUSDC",
                    "payload": f"0x40c10f19000000000000000000000000{self.wallet.address.lower()[2:]}0000000000000000000000000000000000000000000000000000000077359400",
                    "contract": Web3.to_checksum_address(
                        "0xFaf334e157175Ff676911AdcF0964D7f54F2C424"
                    ),
                },
                {
                    "token": "tkWBTC",
                    "payload": f"0x40c10f19000000000000000000000000{self.wallet.address.lower()[2:]}00000000000000000000000000000000000000000000000000000000001e8480",
                    "contract": Web3.to_checksum_address(
                        "0xF82ff0799448630eB56Ce747Db840a2E02Cde4D8"
                    ),
                },
                {
                    "token": "cUSD",
                    "payload": f"0x40c10f19000000000000000000000000{self.wallet.address.lower()[2:]}00000000000000000000000000000000000000000000003635c9adc5dea00000",
                    "contract": Web3.to_checksum_address(
                        "0xE9b6e75C243B6100ffcb1c66e8f78F96FeeA727F"
                    ),
                },
            ]

            random.shuffle(payloads)

            for payload in payloads:
                await self._request_faucet_token(
                    payload["token"], payload["payload"], payload["contract"]
                )

            return True
        except Exception as e:
            logger.error(f"{self.account_index} | Không thể thực hiện faucet: {e}")
            return False

    async def stake(self):
        try:
            logger.info(f"{self.account_index} | Đang staking trong Teko Finance...")

            # Địa chỉ token cho tkUSDC
            token_address = Web3.to_checksum_address(
                "0xFaf334e157175Ff676911AdcF0964D7f54F2C424"
            )

            # Lấy số dư token tkUSDC
            token_contract = self.web3.web3.eth.contract(
                address=token_address,
                abi=[
                    {
                        "constant": True,
                        "inputs": [{"name": "_owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"name": "balance", "type": "uint256"}],
                        "type": "function",
                    }
                ],
            )

            token_balance = await token_contract.functions.balanceOf(
                self.wallet.address
            ).call()

            if token_balance == 0:
                logger.warning(f"{self.account_index} | Không có số dư tkUSDC để stake")
                return False

            # Định dạng số dư để hiển thị
            formatted_balance = token_balance / 10**6
            logger.info(
                f"{self.account_index} | Số dư tkUSDC hiện tại: {formatted_balance:.6f} USDC"
            )

            # Phê duyệt token để chi tiêu
            approve_data = "0x095ea7b300000000000000000000000013c051431753fce53eaec02af64a38a273e198d0ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            await self._approve(token_address, "tkUSDC", approve_data)

            # Tính toán số lượng stake dựa trên phần trăm trong cấu hình
            min_percent, max_percent = (
                self.config.STAKINGS.TEKO_FINANCE.BALANCE_PERCENTAGE_TO_STAKE
            )
            stake_percentage = random.uniform(min_percent, max_percent)
            amount_to_stake = int(token_balance * stake_percentage / 100)

            # Định dạng số lượng để stake
            formatted_amount = amount_to_stake / 10**6
            logger.info(
                f"{self.account_index} | Sẽ stake {stake_percentage:.2f}% tkUSDC: {formatted_amount:.6f} USDC"
            )

            # Thực hiện deposit
            await self._deposit_tkUSDC(amount_to_stake)

            return True
        except Exception as e:
            logger.error(f"{self.account_index} | Không thể thực hiện staking: {e}")
            return False

    @retry_async(default_value=False)
    async def _deposit(self, token_name: str, token_address: str, approve_data: str):
        try:
            logger.info(f"{self.account_index} | Đang deposit {token_name}...")

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể deposit: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    @retry_async(default_value=False)
    async def _request_faucet_token(self, token_name: str, payload: str, contract: str):
        try:
            logger.info(
                f"{self.account_index} | Đang yêu cầu token faucet Teko Finance: {token_name}"
            )

            # Chuẩn bị giao dịch cơ bản
            tx = {
                "from": self.wallet.address,
                "to": contract,
                "data": payload,
                "value": 0,
            }

            # Ước tính gas
            try:
                gas_limit = await self.web3.estimate_gas(tx)
                tx["gas"] = gas_limit
            except Exception as e:
                raise e

            # Thực hiện giao dịch sử dụng phương thức của web3_custom
            tx_hex = await self.web3.execute_transaction(
                tx_data=tx,
                wallet=self.wallet,
                chain_id=CHAIN_ID,
                explorer_url=EXPLORER_URL_MEGAETH,
            )

            if tx_hex:
                logger.success(
                    f"{self.account_index} | Mint {token_name} của Teko Finance thành công!"
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
                f"{self.account_index} | Lỗi khi yêu cầu token faucet Teko Finance: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    @retry_async(default_value=False)
    async def _approve(self, token_address: str, token_name: str, approve_data: str):
        try:
            logger.info(f"{self.account_index} | Đang phê duyệt {token_name}...")

            # Lấy thông số gas
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy thông số gas")

            # Chuẩn bị thông số giao dịch
            tx = {
                "from": self.wallet.address,
                "to": token_address,
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

            # Đặt loại giao dịch dựa trên thông số gas
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
                    f"{self.account_index} | Đã phê duyệt {token_name} để chi tiêu thành công! TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch phê duyệt {token_name} thất bại."
                )
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Lỗi khi phê duyệt {token_name} cho Teko Finance: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    @retry_async(default_value=False)
    async def _deposit_tkUSDC(self, amount):
        try:
            # Định dạng số lượng để ghi log
            formatted_amount = amount / 10**6
            logger.info(
                f"{self.account_index} | Đang deposit {formatted_amount:.6f} USDC vào Teko Finance..."
            )

            # Định dạng số lượng dưới dạng hex, sử dụng 8 ký tự
            hex_amount = hex(amount)[2:].zfill(8)

            # Định dạng địa chỉ ví không có tiền tố 0x
            wallet_address_no_prefix = self.wallet.address[2:].lower()

            # Xây dựng payload
            payload = f"0x8dbdbe6d57841b7b735a58794b8d4d8c38644050529cec291846e80e5afa791048c9410a00000000000000000000000000000000000000000000000000000000{hex_amount}000000000000000000000000{wallet_address_no_prefix}"

            # Địa chỉ hợp đồng để deposit
            contract_address = Web3.to_checksum_address(
                "0x13c051431753fCE53eaEC02af64A38A273E198D0"
            )

            # Chuẩn bị nonce
            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)

            # Chuẩn bị giao dịch
            base_tx = {
                "from": self.wallet.address,
                "to": contract_address,
                "data": payload,
                "value": 0,
                "nonce": nonce,
                "chainId": CHAIN_ID,
            }

            # Thử ước tính gas, nếu không được thì sử dụng giá trị cố định
            try:
                # Lấy giá gas
                gas_price = await self.web3.web3.eth.gas_price
                base_tx["gasPrice"] = gas_price

                # Ước tính gas
                estimated_gas = await self.web3.web3.eth.estimate_gas(base_tx)
                base_tx["gas"] = int(estimated_gas * 1.2)
            except Exception:
                # Sử dụng giá trị cố định
                base_tx["gas"] = 127769

            # Ký giao dịch
            signed_tx = self.web3.web3.eth.account.sign_transaction(
                base_tx, self.private_key
            )

            # Gửi giao dịch
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_tx.raw_transaction
            )
            tx_hex = tx_hash.hex()

            # Đợi xác nhận deposit
            logger.info(f"{self.account_index} | Đang đợi xác nhận deposit...")
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Đã stake thành công {formatted_amount:.6f} USDC trong Teko Finance! TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Không thể stake USDC trong Teko Finance."
                )
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể stake: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    async def unstake(self):
        try:
            logger.info(f"{self.account_index} | Đang rút từ Teko Finance...")

            # Hợp đồng để rút tiền
            contract_address = Web3.to_checksum_address(
                "0x13c051431753fCE53eaEC02af64A38A273E198D0"
            )

            # ID pool chính xác cho tkUSDC
            tkUSDC_pool_id = 39584631314667805491088689848282554447608744687563418855093496965842959155466

            # ABI cho các hàm lấy số dư và rút
            abi = [
                {
                    "type": "function",
                    "name": "getAssetsOf",
                    "inputs": [
                        {"name": "poolId", "type": "uint256"},
                        {"name": "guy", "type": "address"},
                    ],
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                },
                {
                    "type": "function",
                    "name": "withdraw",
                    "inputs": [
                        {"name": "poolId", "type": "uint256"},
                        {"name": "assets", "type": "uint256"},
                        {"name": "receiver", "type": "address"},
                        {"name": "owner", "type": "address"},
                    ],
                    "outputs": [{"name": "shares", "type": "uint256"}],
                    "stateMutability": "nonpayable",
                },
            ]

            contract = self.web3.web3.eth.contract(address=contract_address, abi=abi)

            # Lấy số dư của người dùng trong pool
            try:
                balance = await contract.functions.getAssetsOf(
                    tkUSDC_pool_id, self.wallet.address
                ).call()

                # Định dạng số dư để hiển thị
                formatted_balance = balance / 10**6

                if balance == 0:
                    logger.warning(
                        f"{self.account_index} | Không có tkUSDC để rút"
                    )
                    return False

                logger.info(
                    f"{self.account_index} | Số tkUSDC có thể rút: {formatted_balance:.6f} USDC"
                )

                # Rút số dư có sẵn
                return await self._withdraw_tkUSDC(contract, tkUSDC_pool_id, balance)

            except Exception as e:
                logger.error(f"{self.account_index} | Không thể rút: {e}")
                return False

        except Exception as e:
            logger.error(f"{self.account_index} | Không thể rút: {e}")
            return False

    @retry_async(default_value=False)
    async def _withdraw_tkUSDC(self, contract, pool_id, amount):
        try:
            # Định dạng số lượng để ghi log
            formatted_amount = amount / 10**6
            logger.info(
                f"{self.account_index} | Đang rút {formatted_amount:.6f} USDC từ Teko Finance..."
            )

            # Lấy nonce
            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)

            # Lấy giá gas hiện tại
            gas_price = await self.web3.web3.eth.gas_price
            logger.info(
                f"{self.account_index} | Giá gas hiện tại: {gas_price / 10**9:.9f} Gwei"
            )

            # Tạo giao dịch cơ bản không có gas
            base_tx = {"from": self.wallet.address, "nonce": nonce, "chainId": CHAIN_ID}

            # Nếu mạng hỗ trợ EIP-1559, sử dụng maxFeePerGas và maxPriorityFeePerGas
            if hasattr(self.web3.web3.eth, "max_priority_fee"):
                try:
                    # Lấy phí ưu tiên tối đa
                    max_priority_fee = await self.web3.web3.eth.max_priority_fee

                    # Đặt maxFeePerGas và maxPriorityFeePerGas
                    base_tx["maxPriorityFeePerGas"] = max_priority_fee
                    base_tx["maxFeePerGas"] = max_priority_fee + (gas_price * 2)

                    logger.info(
                        f"{self.account_index} | Sử dụng gas EIP-1559: maxPriorityFeePerGas={max_priority_fee / 10**9:.9f} Gwei, maxFeePerGas={(max_priority_fee + (gas_price * 2)) / 10**9:.9f} Gwei"
                    )
                except Exception as e:
                    # Nếu không lấy được max_priority_fee, sử dụng gasPrice thông thường
                    logger.warning(
                        f"{self.account_index} | Không thể lấy max_priority_fee: {e}. Sử dụng gasPrice tiêu chuẩn."
                    )
                    base_tx["gasPrice"] = gas_price
            else:
                # Nếu mạng không hỗ trợ EIP-1559, sử dụng gasPrice thông thường
                base_tx["gasPrice"] = gas_price

            # Chuẩn bị dữ liệu cho hàm rút
            # withdraw(poolId, assets, receiver, owner)
            func_call = contract.functions.withdraw(
                pool_id,  # Pool ID chính xác cho tkUSDC
                amount,  # Số lượng token để rút
                self.wallet.address,  # Người nhận (receiver)
                self.wallet.address,  # Chủ sở hữu (owner)
            )

            # Động thái đánh giá gas cho giao dịch
            try:
                # Thêm to vào giao dịch để đánh giá gas
                est_tx = {**base_tx, "to": contract.address}

                # Lấy dữ liệu giao dịch
                tx_data = func_call.build_transaction(est_tx)

                # Ước tính gas
                estimated_gas = await self.web3.web3.eth.estimate_gas(tx_data)

                # Thêm buffer gas (20%)
                gas_limit = int(estimated_gas * 1.2)
                logger.info(
                    f"{self.account_index} | Ước tính gas: {estimated_gas}, với buffer 20%: {gas_limit}"
                )

                # Thêm gas vào giao dịch cơ bản
                base_tx["gas"] = gas_limit

            except Exception as e:
                # Nếu không thể ước tính gas, sử dụng giá trị dự phòng
                fallback_gas = 250000
                logger.warning(
                    f"{self.account_index} | Không thể ước tính gas: {e}. Sử dụng giá trị dự phòng: {fallback_gas}"
                )
                base_tx["gas"] = fallback_gas

            # Xây dựng giao dịch hoàn chỉnh
            tx = func_call.build_transaction(base_tx)

            # Ký giao dịch
            signed_tx = self.web3.web3.eth.account.sign_transaction(
                tx, self.private_key
            )

            # Gửi giao dịch
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_tx.raw_transaction
            )
            tx_hex = tx_hash.hex()

            # Đợi xác nhận giao dịch
            logger.info(
                f"{self.account_index} | Đang đợi xác nhận rút tiền... TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
            )
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            # Tính toán chi phí gas để ghi log
            gas_used = receipt["gasUsed"]
            gas_cost_wei = gas_used * (
                tx.get("gasPrice") or tx.get("maxFeePerGas", gas_price)
            )
            gas_cost_eth = gas_cost_wei / 10**18

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Đã rút thành công {formatted_amount:.6f} USDC từ Teko Finance! "
                    f"Gas sử dụng: {gas_used} (Chi phí: {gas_cost_eth:.8f} ETH) TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Không thể rút USDC từ Teko Finance. "
                    f"Gas sử dụng: {gas_used} (Chi phí: {gas_cost_eth:.8f} ETH) TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return False

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} | Không thể rút: {e}. Đợi {random_pause} giây..."
            )
            await asyncio.sleep(random_pause)
            raise

    async def borrow(self):
        try:
            logger.info(f"{self.account_index} | Đang vay từ Teko Finance...")

            # Địa chỉ hợp đồng cho Teko Finance
            contract_address = Web3.to_checksum_address(
                "0x13c051431753fCE53eaEC02af64A38A273E198D0"
            )

            # Sử dụng pool tkUSDC để vay
            pool_id = 39584631314667805491088689848282554447608744687563418855093496965842959155466

            # Lấy số dư token tkETH để sử dụng làm tài sản thế chấp
            tk_eth_address = Web3.to_checksum_address(
                "0x176735870dc6C22B4EBFBf519DE2ce758de78d94"
            )

            # Kiểm tra xem đã phê duyệt tkETH chưa
            tk_eth_contract = self.web3.web3.eth.contract(
                address=tk_eth_address,
                abi=[
                    {
                        "constant": True,
                        "inputs": [
                            {"name": "_owner", "type": "address"},
                            {"name": "_spender", "type": "address"},
                        ],
                        "name": "allowance",
                        "outputs": [{"name": "remaining", "type": "uint256"}],
                        "type": "function",
                    },
                    {
                        "constant": False,
                        "inputs": [
                            {"name": "_spender", "type": "address"},
                            {"name": "_value", "type": "uint256"},
                        ],
                        "name": "approve",
                        "outputs": [{"name": "success", "type": "bool"}],
                        "type": "function",
                    },
                    {
                        "constant": True,
                        "inputs": [{"name": "_owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"name": "balance", "type": "uint256"}],
                        "type": "function",
                    },
                ],
            )

            # Kiểm tra số dư tkETH
            tk_eth_balance = await tk_eth_contract.functions.balanceOf(
                self.wallet.address
            ).call()

            formatted_eth_balance = tk_eth_balance / 10**18
            logger.info(
                f"{self.account_index} | Số dư tkETH hiện tại: {formatted_eth_balance:.6f} ETH"
            )

            if tk_eth_balance == 0:
                logger.warning(
                    f"{self.account_index} | Không có số dư tkETH để sử dụng làm tài sản thế chấp"
                )
                return False

            # Phê duyệt tkETH để chi tiêu nếu cần
            allowance = await tk_eth_contract.functions.allowance(
                self.wallet.address, contract_address
            ).call()

            if allowance < tk_eth_balance:
                logger.info(
                    f"{self.account_index} | Đang phê duyệt tkETH cho Teko Finance..."
                )

                # Lấy thông số gas
                gas_params = await self.web3.get_gas_params()
                if gas_params is None:
                    raise Exception("Không thể lấy thông số gas")

                approve_tx = await tk_eth_contract.functions.approve(
                    contract_address, 2**256 - 1  # Phê duyệt tối đa
                ).build_transaction(
                    {
                        "from": self.wallet.address,
                        "nonce": await self.web3.web3.eth.get_transaction_count(
                            self.wallet.address
                        ),
                        "chainId": CHAIN_ID,
                        **gas_params,
                    }
                )

                # Ước tính gas
                try:
                    gas_limit = await self.web3.estimate_gas(approve_tx)
                    approve_tx["gas"] = gas_limit
                except Exception as e:
                    logger.warning(
                        f"{self.account_index} | Lỗi khi ước tính gas: {e}. Sử dụng giới hạn gas mặc định"
                    )
                    approve_tx["gas"] = 200000  # Giới hạn gas mặc định cho phê duyệt

                # Thực hiện giao dịch phê duyệt
                await self.web3.execute_transaction(
                    tx_data=approve_tx,
                    wallet=self.wallet,
                    chain_id=CHAIN_ID,
                    explorer_url=EXPLORER_URL_MEGAETH,
                )

            # Deposit tkETH làm tài sản thế chấp
            amount_to_deposit = int(
                tk_eth_balance * 0.9
            )  # Sử dụng 90% số dư làm tài sản thế chấp
            formatted_deposit = amount_to_deposit / 10**18

            logger.info(
                f"{self.account_index} | Đang deposit {formatted_deposit:.6f} tkETH làm tài sản thế chấp..."
            )

            # Kiểm tra xem có đủ ETH để tiếp tục không
            eth_balance = await self.web3.get_balance(self.wallet.address)
            logger.info(
                f"{self.account_index} | Số dư ETH hiện tại: {eth_balance.ether} ETH"
            )

            # Lưu ABI trực tiếp trong code - bao gồm tất cả các hàm cần thiết
            pool_abi = [
                # Hàm deposit
                {
                    "type": "function",
                    "name": "deposit",
                    "inputs": [
                        {"name": "poolId", "type": "uint256"},
                        {"name": "assets", "type": "uint256"},
                        {"name": "receiver", "type": "address"},
                    ],
                    "outputs": [{"name": "shares", "type": "uint256"}],
                    "stateMutability": "nonpayable",
                },
                # Hàm borrow
                {
                    "type": "function",
                    "name": "borrow",
                    "inputs": [
                        {"name": "poolId", "type": "uint256"},
                        {"name": "position", "type": "address"},
                        {"name": "amt", "type": "uint256"},
                    ],
                    "outputs": [{"name": "borrowShares", "type": "uint256"}],
                    "stateMutability": "nonpayable",
                },
                # Hàm accrue - QUAN TRỌNG để gọi trước các thao tác
                {
                    "type": "function",
                    "name": "accrue",
                    "inputs": [{"name": "id", "type": "uint256"}],
                    "outputs": [],
                    "stateMutability": "nonpayable",
                },
                # Hàm getAssetsOf để kiểm tra số dư
                {
                    "type": "function",
                    "name": "getAssetsOf",
                    "inputs": [
                        {"name": "poolId", "type": "uint256"},
                        {"name": "guy", "type": "address"},
                    ],
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                },
            ]

            # Tạo instance hợp đồng cho pool cho vay
            pool_contract = self.web3.web3.eth.contract(
                address=contract_address, abi=pool_abi
            )

            # Lấy ID pool ETH để deposit tài sản thế chấp
            eth_pool_id = 72572175584673509244743384162953726919624465952543019256792130552168516108177

            # Đầu tiên, tính lãi cho pool trước bất kỳ thao tác nào
            try:
                logger.info(
                    f"{self.account_index} | Đang tính lãi cho pool trước khi deposit..."
                )

                # Lấy thông số gas
                gas_params = await self.web3.get_gas_params()
                if gas_params is None:
                    raise Exception("Không thể lấy thông số gas")

                # Lấy nonce hiện tại
                nonce = await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                )

                # Xây dựng giao dịch accrue
                accrue_tx = await pool_contract.functions.accrue(
                    eth_pool_id  # Pool ID cho tkETH
                ).build_transaction(
                    {
                        "from": self.wallet.address,
                        "nonce": nonce,
                        "chainId": CHAIN_ID,
                        "gas": 200000,  # Giới hạn gas bảo thủ
                        **gas_params,
                    }
                )

                # Thực hiện giao dịch accrue
                accrue_tx_hash = await self.web3.execute_transaction(
                    tx_data=accrue_tx,
                    wallet=self.wallet,
                    chain_id=CHAIN_ID,
                    explorer_url=EXPLORER_URL_MEGAETH,
                )

                if not accrue_tx_hash:
                    logger.warning(
                        f"{self.account_index} | Giao dịch accrue thất bại, nhưng sẽ thử tiếp tục..."
                    )
                else:
                    logger.success(
                        f"{self.account_index} | Đã tính lãi thành công cho pool"
                    )
                    # Đợi một chút để giao dịch được xử lý
                    await asyncio.sleep(2)

            except Exception as e:
                logger.warning(
                    f"{self.account_index} | Lỗi khi tính lãi, nhưng sẽ thử tiếp tục: {e}"
                )

            # Tiếp tục deposit
            # Lấy thông số gas và nonce mới
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy thông số gas")

            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)

            # Xây dựng giao dịch deposit (sử dụng ước tính gas thấp hơn để tiết kiệm ETH)
            deposit_tx = await pool_contract.functions.deposit(
                eth_pool_id,  # Pool ID cho tkETH
                amount_to_deposit,  # Số lượng để deposit
                self.wallet.address,  # Người nhận
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "nonce": nonce,
                    "chainId": CHAIN_ID,
                    "gas": 200000,  # Giới hạn gas giảm để tiết kiệm ETH
                    **gas_params,
                }
            )

            # Thực hiện giao dịch deposit
            deposit_tx_hash = await self.web3.execute_transaction(
                tx_data=deposit_tx,
                wallet=self.wallet,
                chain_id=CHAIN_ID,
                explorer_url=EXPLORER_URL_MEGAETH,
            )

            if not deposit_tx_hash:
                logger.error(f"{self.account_index} | Không thể deposit tài sản thế chấp")
                return False

            logger.success(
                f"{self.account_index} | Đã deposit thành công {formatted_deposit:.6f} tkETH làm tài sản thế chấp"
            )

            # Đợi một chút để deposit được xử lý
            await asyncio.sleep(2)

            # Bây giờ vay một lượng nhỏ tkUSDC để đảm bảo có đủ ETH cho phí gas
            # Sử dụng lượng nhỏ hơn để đảm bảo thành công
            borrow_amount = 500_000  # 0.5 USDC với 6 chữ số thập phân
            formatted_borrow = borrow_amount / 10**6

            logger.info(
                f"{self.account_index} | Đang vay {formatted_borrow:.2f} USDC từ Teko Finance..."
            )

            # Đầu tiên, tính lãi cho pool USDC trước khi vay
            try:
                logger.info(
                    f"{self.account_index} | Đang tính lãi cho pool USDC trước khi vay..."
                )

                # Lấy nonce mới
                nonce = await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                )

                # Xây dựng giao dịch accrue cho pool USDC
                accrue_tx = await pool_contract.functions.accrue(
                    pool_id  # Pool ID cho tkUSDC
                ).build_transaction(
                    {
                        "from": self.wallet.address,
                        "nonce": nonce,
                        "chainId": CHAIN_ID,
                        "gas": 200000,  # Giới hạn gas bảo thủ
                        **gas_params,
                    }
                )

                # Thực hiện giao dịch accrue
                accrue_tx_hash = await self.web3.execute_transaction(
                    tx_data=accrue_tx,
                    wallet=self.wallet,
                    chain_id=CHAIN_ID,
                    explorer_url=EXPLORER_URL_MEGAETH,
                )

                if not accrue_tx_hash:
                    logger.warning(
                        f"{self.account_index} | Giao dịch accrue cho pool USDC thất bại, nhưng sẽ thử tiếp tục..."
                    )
                else:
                    logger.success(
                        f"{self.account_index} | Đã tính lãi thành công cho pool USDC"
                    )
                    # Đợi một chút để giao dịch được xử lý
                    await asyncio.sleep(2)

            except Exception as e:
                logger.warning(
                    f"{self.account_index} | Lỗi khi tính lãi cho pool USDC, nhưng sẽ thử tiếp tục: {e}"
                )

            # Lấy nonce và thông số gas mới
            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)
            gas_params = await self.web3.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy thông số gas")

            # Xây dựng giao dịch vay với ước tính gas thấp hơn
            borrow_tx = await pool_contract.functions.borrow(
                pool_id,  # Pool ID cho tkUSDC
                self.wallet.address,  # Vị trí (người vay)
                borrow_amount,  # Số lượng vay (đã giảm)
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "nonce": nonce,
                    "chainId": CHAIN_ID,
                    "gas": 300000,  # Giới hạn gas giảm
                    **gas_params,
                }
            )

            # Thực hiện giao dịch vay
            borrow_tx_hash = await self.web3.execute_transaction(
                tx_data=borrow_tx,
                wallet=self.wallet,
                chain_id=CHAIN_ID,
                explorer_url=EXPLORER_URL_MEGAETH,
            )

            if not borrow_tx_hash:
                logger.error(f"{self.account_index} | Không thể vay USDC")
                return False

            logger.success(
                f"{self.account_index} | Đã vay thành công {formatted_borrow:.2f} USDC từ Teko Finance!"
            )
            return True

        except Exception as e:
            logger.error(f"{self.account_index} | Không thể vay: {e}")
            return False


ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]

TK_USDC_ADDRESS = "0xFaf334e157175Ff676911AdcF0964D7f54F2C424"
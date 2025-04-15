import asyncio
import random
import hashlib
import time
import os

from eth_account import Account
from src.model.onchain.web3_custom import Web3Custom
from loguru import logger
import primp
from web3 import Web3
from src.utils.decorators import retry_async
from src.utils.config import Config
from src.utils.constants import EXPLORER_URL_MEGAETH

CHAIN_ID = 6342  # Từ bình luận trong constants.py


class XLMeme:
    def __init__(
        self,
        account_index: int,
        session: primp.AsyncClient,
        web3: Web3Custom,
        config: Config,
        wallet: Account,
    ):
        self.account_index = account_index
        self.session = session
        self.web3 = web3
        self.config = config
        self.wallet = wallet

    async def buy_meme(self):
        try:
            # Bây giờ chúng ta hiểu rằng CONTRACTS_TO_BUY là các địa chỉ token, không phải bonding curves
            # Cần lấy địa chỉ bonding curve cho token được chọn
            if len(self.config.MINTS.XL_MEME.CONTRACTS_TO_BUY) > 0:
                random_token_contract = random.choice(
                    self.config.MINTS.XL_MEME.CONTRACTS_TO_BUY
                )
            else:
                random_token_contract = await self._get_random_token_for_mint()
                if not random_token_contract:
                    logger.error(
                        f"{self.account_index} | Không thể lấy token ngẫu nhiên để mint"
                    )
                    return False

            bonding_curve_address = await self._get_bonding_curve_address(
                random_token_contract
            )

            if not bonding_curve_address:
                logger.error(
                    f"{self.account_index} | Không thể lấy địa chỉ bonding curve cho token: {random_token_contract}"
                )
                return False

            random_balance_percentage = random.choice(
                self.config.MINTS.XL_MEME.BALANCE_PERCENTAGE_TO_BUY
            )

            balance = await self.web3.get_balance(self.wallet.address)

            # Tính toán số lượng theo ETH (để ghi log)
            amount_in_eth = balance.ether * random_balance_percentage / 100

            # Đặt số lượng tối thiểu cho giao dịch theo ETH
            min_amount_eth = 0.0000001
            if amount_in_eth < min_amount_eth:
                random_min_balance = random.uniform(0.0000001, 0.000005)
                logger.info(
                    f"{self.account_index} | Số lượng tính toán {amount_in_eth} ETH quá nhỏ, sử dụng số lượng tối thiểu {random_min_balance} ETH"
                )
                amount_in_eth = random_min_balance

            # Chuyển đổi sang wei cho giao dịch
            amount_in_wei = Web3.to_wei(amount_in_eth, "ether")

            # Kiểm tra xem có đủ ETH cho giao dịch không
            if balance.wei < amount_in_wei:
                logger.error(
                    f"{self.account_index} | Không đủ ETH để mint. Yêu cầu: {amount_in_eth:.8f} ETH, Hiện có: {balance.ether:.8f} ETH"
                )
                return False

            return await self._buy(bonding_curve_address, amount_in_wei)
        except Exception as e:
            logger.error(f"{self.account_index} | Không thể mua meme trên XLMeme: {e}")
            return False

    @retry_async(default_value=False)
    async def _buy(self, contract_address: str, amount: int):
        try:
            # Tạo hợp đồng với ABI tối thiểu cho các hàm buyForETH và estimateBuy
            contract_abi = [
                {
                    "inputs": [
                        {"name": "buyer", "type": "address", "internalType": "address"},
                        {
                            "name": "reserveAmountIn",
                            "type": "uint256",
                            "internalType": "uint256",
                        },
                        {
                            "name": "supplyAmountOutMin",
                            "type": "uint256",
                            "internalType": "uint256",
                        },
                    ],
                    "name": "buyForETH",
                    "outputs": [
                        {"name": "", "type": "uint256", "internalType": "uint256"}
                    ],
                    "stateMutability": "payable",
                    "type": "function",
                },
                {
                    "inputs": [
                        {
                            "name": "reserveAmountIn",
                            "type": "uint256",
                            "internalType": "uint256",
                        }
                    ],
                    "name": "estimateBuy",
                    "outputs": [
                        {"name": "", "type": "uint256", "internalType": "uint256"}
                    ],
                    "stateMutability": "view",
                    "type": "function",
                },
            ]

            contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(contract_address),
                abi=contract_abi,
            )

            # Đảm bảo amount là số nguyên
            amount = int(amount)

            # Sử dụng phương thức estimateBuy để lấy số lượng token dự kiến
            try:
                estimated_tokens = await contract.functions.estimateBuy(amount).call()
                # Sử dụng 95% số lượng token dự kiến để tính đến trượt giá
                supply_amount_out_min = int(estimated_tokens * 0.95)
            except Exception as e:
                logger.warning(
                    f"{self.account_index} | Không thể ước tính số lượng mua: {str(e)}. Sử dụng trượt giá mặc định."
                )
                # Nếu không thể ước tính, sử dụng giá trị mặc định (75% của lượng)
                supply_amount_out_min = int(amount * 0.75)

            logger.info(
                f"{self.account_index} | Đang mua {contract_address} với {Web3.from_wei(amount, 'ether'):.8f} ETH"
            )

            # Tạo giao dịch cơ bản với các thiết lập tối thiểu
            tx = await contract.functions.buyForETH(
                self.wallet.address, amount, supply_amount_out_min
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "value": amount,
                    "chainId": CHAIN_ID,
                    "nonce": await self.web3.web3.eth.get_transaction_count(
                        self.wallet.address
                    ),
                }
            )

            # Xóa các tham số gas có thể xung đột
            if "maxFeePerGas" in tx:
                del tx["maxFeePerGas"]
            if "maxPriorityFeePerGas" in tx:
                del tx["maxPriorityFeePerGas"]

            # Chỉ thêm gasPrice
            gas_price = await self.web3.web3.eth.gas_price
            tx["gasPrice"] = int(gas_price * 1.1)  # Tăng 10%

            # Ước tính gas
            try:
                tx_for_estimate = tx.copy()
                estimated_gas = await self.web3.web3.eth.estimate_gas(tx_for_estimate)
                tx["gas"] = int(
                    estimated_gas * 1.3
                )  # Tăng 30% để an toàn
            except Exception as e:
                raise e

            # Ký và gửi giao dịch
            signed_txn = self.web3.web3.eth.account.sign_transaction(
                tx, self.wallet.key
            )
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_txn.raw_transaction
            )
            tx_hash_hex = tx_hash.hex()

            # Đợi giao dịch hoàn tất
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=60
            )

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Mint hoàn thành thành công: {EXPLORER_URL_MEGAETH}{tx_hash_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch thất bại: {tx_hash_hex}"
                )
                return False

        except Exception as e:
            logger.error(f"{self.account_index} | Lỗi khi thực hiện mint: {str(e)}")
            return False

    @retry_async(default_value=None)
    async def _get_bonding_curve_address(self, token_contract: str) -> str:
        try:
            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7,zh-TW;q=0.6,zh;q=0.5",
                "origin": "https://testnet.xlmeme.com",
                "priority": "u=1, i",
                "referer": "https://testnet.xlmeme.com/",
                "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            }

            params = {
                "page": "1",
                "page_size": "50",
            }

            response = await self.session.get(
                f"https://api-testnet.xlmeme.com/api/statistics/megaeth_testnet/1min/bonding-curve/{token_contract}/",
                params=params,
                headers=headers,
            )
            if response.json()["count"] != 0:
                return response.json()["results"][0]["bonding_curve_address"]

            response = await self.session.get(
                f"https://api-testnet.xlmeme.com/api/tokens/network/megaeth_testnet/{token_contract}/",
                headers=headers,
            )
            contract_uuid = response.json()["uuid"]

            response = await self.session.get(
                f"https://api-testnet.xlmeme.com/api/bonding-curves/token/{contract_uuid}/",
                headers=headers,
            )
            return response.json()["address"]
        except Exception as e:
            logger.error(
                f"{self.account_index} | Lỗi khi lấy địa chỉ hợp đồng mint: {str(e)}"
            )
            raise e

    @retry_async(default_value=None)
    async def _get_random_token_for_mint(self) -> str:
        try:
            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7,zh-TW;q=0.6,zh;q=0.5",
                "origin": "https://testnet.xlmeme.com",
                "priority": "u=1, i",
                "referer": "https://testnet.xlmeme.com/",
                "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            }

            params = {
                "page": "1",
                "search": "",
                "ordering": "-market_cap_xlm",
                "page_size": "50",
                "creator_wallet_address": "",
                "blockchain": "megaeth_testnet",
            }

            response = await self.session.get(
                "https://api-testnet.xlmeme.com/api/tokens/",
                params=params,
                headers=headers,
            )

            contracts = response.json()["results"]
            random_contract = random.choice(contracts)

            logger.info(
                f"{self.account_index} | Sẽ cố gắng mint token {random_contract['ticker']} | {random_contract['contract_address']} "
            )
            return random_contract["contract_address"]

        except Exception as e:
            logger.error(
                f"{self.account_index} | Lỗi khi lấy token ngẫu nhiên để mint: {str(e)}"
            )
            raise e
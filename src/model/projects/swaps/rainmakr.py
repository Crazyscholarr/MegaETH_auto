import random
from eth_account.messages import encode_typed_data
from eth_account import Account
from src.model.onchain.web3_custom import Web3Custom
from loguru import logger
import primp
from web3 import Web3
from curl_cffi.requests import AsyncSession
import time
import asyncio
from eth_account.messages import encode_defunct

from src.utils.decorators import retry_async
from src.utils.config import Config
from src.utils.constants import EXPLORER_URL_MEGAETH


CHAIN_ID = 6342  # From constants.py comment
TOKEN_FACTORY_ADDRESS = Web3.to_checksum_address(
    "0x6B82b7BB668dA9EF1834896b1344Ac34B06fc58D"
)

TOKEN_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenAddress", "type": "address"},
            {"internalType": "uint256", "name": "tokenAmount", "type": "uint256"},
            {"internalType": "address", "name": "to", "type": "address"},
        ],
        "name": "buyExactOut",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]

# Minimal ERC20 ABI for balanceOf and approve
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
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
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
]


class Rainmakr:
    def __init__(
        self,
        account_index: int,
        session: primp.AsyncClient,
        web3: Web3Custom,
        config: Config,
        wallet: Account,
        private_key: str,
    ):
        self.account_index = account_index
        self.session = session
        self.web3 = web3
        self.config = config
        self.wallet = wallet
        self.private_key = private_key

        self.bearer_token = ""
        self.contract = self.web3.web3.eth.contract(
            address=self.web3.web3.to_checksum_address(TOKEN_FACTORY_ADDRESS),
            abi=TOKEN_FACTORY_ABI,
        )

    async def buy_meme(self):
        try:
            if not await self._get_bearer_token():
                logger.error(f"{self.account_index} | Không thể lấy mã thông báo bearer")
                return False
            logger.info(f"{self.account_index} | Đã nhận được mã thông báo bearer")

            # Bây giờ chúng ta hiểu rằng CONTRACTS_TO_BUY là địa chỉ token, không phải đường cong liên kết
            # Cần lấy địa chỉ đường cong liên kết cho token được chọn
            if len(self.config.MINTS.RAINMAKR.CONTRACTS_TO_BUY) > 0:
                random_token_contract = random.choice(
                    self.config.MINTS.RAINMAKR.CONTRACTS_TO_BUY
                )
            else:
                random_token_contract = await self._get_random_token_for_mint()
                if not random_token_contract:
                    logger.error(
                        f"{self.account_index} | Không thể lấy token ngẫu nhiên để mint"
                    )
                    return False

            random_amount_of_eth_to_buy = random.uniform(
                self.config.MINTS.RAINMAKR.AMOUNT_OF_ETH_TO_BUY[0],
                self.config.MINTS.RAINMAKR.AMOUNT_OF_ETH_TO_BUY[1],
            )

            balance = await self.web3.get_balance(self.wallet.address)

            # Convert to ETH for logging and comparison
            amount_in_eth = random_amount_of_eth_to_buy

            # Check if we have enough balance
            if balance.ether < amount_in_eth:
                logger.error(
                    f"{self.account_index} | Không đủ ETH để mint. Yêu cầu: {amount_in_eth:.8f} ETH, Hiện có: {balance.ether:.8f} ETH"
                )
                return False

            # Convert to wei for transaction
            amount_in_wei = Web3.to_wei(amount_in_eth, "ether")

            if not await self._buy(random_token_contract, amount_in_wei):
                logger.error(
                    f"{self.account_index} | Không thể mua meme trên Rainmakr: {random_token_contract}"
                )
                return False

            random_pause = random.randint(15, 30)
            # Wait a bit before selling
            logger.info(
                f"{self.account_index} | Đợi {random_pause} giây trước khi bán token..."
            )
            await asyncio.sleep(random_pause)

            # Sell the tokens
            if not await self._sell(random_token_contract):
                logger.error(
                    f"{self.account_index} | Không thể bán token: {random_token_contract}"
                )
                return False

            logger.success(
                f"{self.account_index} | Đã hoàn thành thành công việc mua và bán {random_token_contract}"
            )
            return True
        except Exception as e:
            logger.error(f"{self.account_index} | Không thể mua meme trên Rainmakr: {e}")
            return False

    @retry_async(default_value=False)
    async def _buy(self, contract_address: str, amount: int):
        try:
            # Create payload with token address and user address (both without 0x prefix)
            payload = f"0xb909e38b000000000000000000000000{contract_address[2:]}0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000{self.wallet.address[2:]}"

            # Đảm bảo amount là số nguyên
            amount = int(amount)

            logger.info(
                f"{self.account_index} | Đang mua {contract_address} với {Web3.from_wei(amount, 'ether'):.8f} ETH"
            )

            # Create transaction
            tx = {
                "from": self.wallet.address,
                "to": TOKEN_FACTORY_ADDRESS,  # Gửi đến TOKEN_FACTORY_ADDRESS
                "value": amount,  # Số lượng ETH để chi tiêu
                "data": payload,  # Payload với địa chỉ token và địa chỉ ví
                "chainId": CHAIN_ID,
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
            }

            # Get gas price
            gas_price = await self.web3.web3.eth.gas_price
            tx["gasPrice"] = int(gas_price * 1.1)  # Tăng 10%

            # Estimate gas
            try:
                tx_for_estimate = tx.copy()
                estimated_gas = await self.web3.web3.eth.estimate_gas(tx_for_estimate)
                tx["gas"] = int(
                    estimated_gas * 1.3
                )  # Tăng 30% để đảm bảo an toàn
            except Exception as e:
                raise e

            # Sign and send transaction
            signed_txn = self.web3.web3.eth.account.sign_transaction(
                tx, self.private_key
            )
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_txn.raw_transaction
            )
            tx_hash_hex = tx_hash.hex()

            # Wait for transaction receipt
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=60
            )

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Mua token hoàn thành thành công: {EXPLORER_URL_MEGAETH}{tx_hash_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch thất bại: {tx_hash_hex}"
                )
                return False

        except Exception as e:
            logger.error(
                f"{self.account_index} | Lỗi khi thực hiện mua token: {str(e)}"
            )
            return False

    @retry_async(default_value=False)
    async def _sell(self, contract_address: str):
        try:
            # Create ERC20 contract instance to check balance
            token_contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(contract_address),
                abi=ERC20_ABI,
            )

            # Get token balance for the wallet
            token_balance = await token_contract.functions.balanceOf(
                self.wallet.address
            ).call()

            if token_balance == 0:
                logger.warning(
                    f"{self.account_index} | Không có token để bán trên {contract_address}"
                )
                return False

            # Chuyển đổi số dư sang định dạng dễ đọc (giả định 18 chữ số thập phân)
            try:
                token_balance_ether = Web3.from_wei(token_balance, "ether")
            except Exception:
                token_balance_ether = token_balance  # Nếu không thể, hiển thị như hiện tại

            # QUAN TRỌNG: Đầu tiên phê duyệt TOKEN_FACTORY_ADDRESS để chi tiêu token
            # Kiểm tra mức phê duyệt hiện tại
            current_allowance = await token_contract.functions.allowance(
                self.wallet.address, TOKEN_FACTORY_ADDRESS
            ).call()

            # Sử dụng số dư token thực tế, không phải số lượng cố định
            token_amount = token_balance  # Sử dụng giá trị gốc cho giao dịch
            token_amount_hex = hex(token_amount)[2:]

            # Định dạng chính xác tất cả tham số thành 32 byte (64 ký tự hex)
            token_address_part = contract_address[2:].lower().zfill(64)
            token_amount_hex = token_amount_hex.zfill(64)
            # Sử dụng địa chỉ từ ví dụ đang hoạt động, không phải địa chỉ ví
            final_address_part = "4c4c1b866b433860366f93dc4135a0250cccdcfa".zfill(64)
            # Thêm đệm số 0 giữa số lượng và địa chỉ cuối, như trong ví dụ đang hoạt động
            zero_padding = "0".zfill(64)

            logger.info(
                f"{self.account_index} | Sử dụng số dư token thực tế để bán: {token_balance_ether:.8f} token"
            )
            logger.info(
                f"{self.account_index} | Mức phê duyệt hiện tại: {current_allowance}"
            )

            # Nếu mức phê duyệt không đủ, phê duyệt token
            if current_allowance < token_amount:
                logger.info(
                    f"{self.account_index} | Đang phê duyệt token để hợp đồng trao đổi chi tiêu"
                )

                # Sử dụng uint256 tối đa cho phê duyệt không giới hạn
                max_approval = 2**256 - 1

                # Tạo giao dịch phê duyệt
                approval_tx = await token_contract.functions.approve(
                    TOKEN_FACTORY_ADDRESS, max_approval
                ).build_transaction(
                    {
                        "from": self.wallet.address,
                        "chainId": CHAIN_ID,
                        "nonce": await self.web3.web3.eth.get_transaction_count(
                            self.wallet.address
                        ),
                        "gasPrice": await self.web3.web3.eth.gas_price,
                    }
                )

                # Ước tính gas
                try:
                    gas_estimate = await self.web3.web3.eth.estimate_gas(approval_tx)
                    approval_tx["gas"] = int(gas_estimate * 1.3)
                except Exception as e:
                    raise e

                # Ký và gửi giao dịch phê duyệt
                signed_approval = self.web3.web3.eth.account.sign_transaction(
                    approval_tx, self.private_key
                )
                approval_hash = await self.web3.web3.eth.send_raw_transaction(
                    signed_approval.raw_transaction
                )

                # Đợi giao dịch phê duyệt hoàn thành
                approval_receipt = (
                    await self.web3.web3.eth.wait_for_transaction_receipt(approval_hash)
                )

                if approval_receipt["status"] == 1:
                    logger.success(
                        f"{self.account_index} | Phê duyệt token thành công: {EXPLORER_URL_MEGAETH}{approval_hash.hex()}"
                    )
                else:
                    logger.error(f"{self.account_index} | Phê duyệt token thất bại")
                    return False

                # Đợi một chút sau khi phê duyệt
                await asyncio.sleep(5)

            # Tiến hành giao dịch bán bằng số dư token thực tế
            # Tạo payload bằng các tham số được định dạng đúng (mỗi tham số 64 ký tự) + đệm số 0
            function_selector = "0x0a7f0c9d"
            payload = f"{function_selector}{token_address_part}{token_amount_hex}{zero_padding}{final_address_part}"

            logger.info(
                f"{self.account_index} | Đang bán {token_balance_ether:.8f} token từ {contract_address}"
            )

            # Tạo giao dịch
            tx = {
                "from": self.wallet.address,
                "to": TOKEN_FACTORY_ADDRESS,
                "value": 0,  # Không có giá trị ETH
                "data": payload,
                "chainId": CHAIN_ID,
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
            }

            # Lấy giá gas
            gas_price = await self.web3.web3.eth.gas_price
            tx["gasPrice"] = int(gas_price * 1.1)  # Tăng 10%

            # Ước tính gas
            try:
                tx_for_estimate = tx.copy()
                estimated_gas = await self.web3.web3.eth.estimate_gas(tx_for_estimate)
                tx["gas"] = int(
                    estimated_gas * 1.3
                )  # Tăng 30% để đảm bảo an toàn
            except Exception as e:
                raise e

            # Ký và gửi giao dịch
            signed_txn = self.web3.web3.eth.account.sign_transaction(
                tx, self.private_key
            )
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_txn.raw_transaction
            )
            tx_hash_hex = tx_hash.hex()

            # Đợi biên lai giao dịch
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=60
            )

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | Bán token hoàn thành thành công: {EXPLORER_URL_MEGAETH}{tx_hash_hex}"
                )
                return True
            else:
                logger.error(
                    f"{self.account_index} | Giao dịch thất bại: {tx_hash_hex}"
                )
                return False

        except Exception as e:
            logger.error(f"{self.account_index} | Lỗi khi thực hiện bán token: {str(e)}")
            return False

    @retry_async(default_value=None)
    async def _get_random_token_for_mint(self) -> str:
        try:
            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7,zh-TW;q=0.6,zh;q=0.5",
                "authorization": f"Bearer {self.bearer_token}",
                "if-none-match": 'W/"14730-+Xgomu0RunpleDx7jn8c+zUElMA"',
                "origin": "https://rainmakr.xyz",
                "priority": "u=1, i",
                "referer": "https://rainmakr.xyz/",
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
                "limit": "100",
                "mainFilterToken": "TRENDING",
            }

            response = await self.session.get(
                "https://rain-ai.rainmakr.xyz/api/token", params=params, headers=headers
            )
            contracts = response.json()["data"]
            random.shuffle(contracts)

            random_contract = {}
            for contract in contracts:
                try:
                    if int(contract["numberTransaction"]) > 5:
                        random_contract = contract
                        break
                except:
                    pass

            logger.info(
                f"{self.account_index} | Sẽ cố gắng mint token {random_contract['name']} | {random_contract['contractAddress']}"
            )
            return random_contract["contractAddress"]

        except Exception as e:
            logger.error(
                f"{self.account_index} | Lỗi khi lấy token ngẫu nhiên để mint: {str(e)}"
            )
            raise e

    @retry_async(default_value=False)
    async def _get_bearer_token(self):
        try:
            message = "USER_CONNECT_WALLET"
            encoded_msg = encode_defunct(text=message)
            signed_msg = Web3().eth.account.sign_message(
                encoded_msg, private_key=self.private_key
            )
            signature = signed_msg.signature.hex()
            signature = "0x" + signature

            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7,zh-TW;q=0.6,zh;q=0.5",
                "content-type": "application/json",
                "origin": "https://rainmakr.xyz",
                "priority": "u=1, i",
                "referer": "https://rainmakr.xyz/",
                "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            }

            json_data = {
                "signature": signature,
                "address": self.wallet.address,
            }

            response = await self.session.post(
                "https://rain-ai.rainmakr.xyz/api/auth/connect-wallet",
                headers=headers,
                json=json_data,
            )
            self.bearer_token = response.json()["data"]["access_token"]

            if self.bearer_token:
                return True
            else:
                raise Exception("Không thể lấy mã thông báo bearer")

        except Exception as e:
            logger.error(f"{self.account_index} | Lỗi khi lấy mã thông báo bearer: {str(e)}")
            raise e
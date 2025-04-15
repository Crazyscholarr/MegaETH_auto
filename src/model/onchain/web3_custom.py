from decimal import Decimal
from typing import Dict, Optional, Union
from loguru import logger
from web3 import AsyncWeb3
from eth_account.signers.local import LocalAccount
from src.utils.decorators import retry_async
from src.model.onchain.constants import Balance
import asyncio
import traceback


class Web3Custom:
    def __init__(
        self,
        account_index: int,
        RPC_URLS: list[str],
        use_proxy: bool,
        proxy: str,
        ssl: bool = False,
    ):
        self.account_index = account_index
        self.RPC_URLS = RPC_URLS
        self.use_proxy = use_proxy
        self.proxy = proxy
        self.ssl = ssl
        self.web3 = None

    async def connect_web3(self) -> None:
        """
        Thử kết nối đến từng URL RPC trong danh sách.
        Thực hiện 3 lần thử cho mỗi RPC với độ trễ 1 giây giữa các lần thử.
        """
        for rpc_url in self.RPC_URLS:
            for attempt in range(3):
                try:
                    proxy_settings = (
                        (f"http://{self.proxy}")
                        if (self.use_proxy and self.proxy)
                        else None
                    )
                    self.web3 = AsyncWeb3(
                        AsyncWeb3.AsyncHTTPProvider(
                            rpc_url,
                            request_kwargs={
                                "proxy": proxy_settings,
                                "ssl": self.ssl,
                            },
                        )
                    )

                    # Kiểm tra kết nối
                    await self.web3.eth.chain_id
                    return

                except Exception as e:
                    logger.warning(
                        f"{self.account_index} | Lần thử {attempt + 1}/3 thất bại cho {rpc_url}: {str(e)}"
                    )
                    if attempt < 2:  # Không chờ sau lần thử cuối
                        await asyncio.sleep(1)
                    continue

        raise Exception("Không thể kết nối đến bất kỳ URL RPC nào")

    @retry_async(attempts=3, delay=3.0, default_value=None)
    async def get_balance(self, address: str) -> Balance:
        """
        Lấy số dư của một địa chỉ.

        Returns:
            Đối tượng Balance chứa giá trị ở các đơn vị wei, gwei và ether
        """
        wei_balance = await self.web3.eth.get_balance(address)
        return Balance.from_wei(wei_balance)

    @retry_async(attempts=3, delay=5.0, default_value=None)
    async def get_token_balance(
        self,
        wallet_address: str,
        token_address: str,
        token_abi: list = None,
        decimals: int = 18,
        symbol: str = "TOKEN",
    ) -> Balance:
        """
        Lấy số dư token cho bất kỳ token ERC20 nào.

        Args:
            wallet_address: Địa chỉ để kiểm tra số dư
            token_address: Địa chỉ hợp đồng token
            token_abi: ABI của token (tùy chọn)
            decimals: Số chữ số thập phân của token (mặc định là 18 cho hầu hết token ERC20)
            symbol: Ký hiệu token (tùy chọn)

        Returns:
            Đối tượng Balance chứa số dư token
        """
        if token_abi is None:
            # Sử dụng ABI ERC20 tối thiểu nếu không cung cấp
            token_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function",
                }
            ]

        token_contract = self.web3.eth.contract(
            address=self.web3.to_checksum_address(token_address), abi=token_abi
        )
        wei_balance = await token_contract.functions.balanceOf(wallet_address).call()

        return Balance.from_wei(wei_balance, decimals=decimals, symbol=symbol)

    @retry_async(attempts=3, delay=5.0, default_value=None)
    async def get_gas_params(self) -> Dict[str, int]:
        try:
            gas_price = await self.web3.eth.gas_price
            return {"gasPrice": int(gas_price * 1.5)}
        except Exception as e:
            logger.error(
                f"{self.account_index} | Không thể lấy tham số gas: {str(e)}"
            )
            raise

    def convert_to_wei(self, amount: float, decimals: int) -> int:
        """Chuyển đổi số tiền sang đơn vị wei dựa trên số chữ số thập phân."""
        return int(Decimal(str(amount)) * Decimal(str(10**decimals)))

    def convert_from_wei(self, amount: int, decimals: int) -> float:
        """Chuyển đổi số tiền từ wei về đơn vị token."""
        return float(Decimal(str(amount)) / Decimal(str(10**decimals)))

    @retry_async(attempts=1, delay=5.0, backoff=2.0, default_value=None)
    async def execute_transaction(
        self,
        tx_data: Dict,
        wallet: LocalAccount,
        chain_id: int,
        explorer_url: Optional[str] = None,
    ) -> str:
        """
        Thực hiện giao dịch và chờ xác nhận.

        Args:
            tx_data: Dữ liệu giao dịch
            wallet: Thể hiện ví (eth_account.LocalAccount)
            chain_id: ID chuỗi cho giao dịch
            explorer_url: URL explorer để ghi log (tùy chọn)
        """
        try:
            nonce = await self.web3.eth.get_transaction_count(wallet.address)
            gas_params = await self.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy tham số gas")

            transaction = {
                "from": wallet.address,
                "nonce": nonce,
                "chainId": chain_id,
                **tx_data,
                **gas_params,
            }

            # Thêm type 2 chỉ cho giao dịch EIP-1559
            if "maxFeePerGas" in gas_params:
                transaction["type"] = 2

            signed_txn = self.web3.eth.account.sign_transaction(transaction, wallet.key)
            tx_hash = await self.web3.eth.send_raw_transaction(
                signed_txn.raw_transaction
            )

            logger.info(
                f"{self.account_index} | Đang chờ xác nhận giao dịch..."
            )
            receipt = await self.web3.eth.wait_for_transaction_receipt(
                tx_hash, poll_latency=2
            )

            if receipt["status"] == 1:
                tx_hex = tx_hash.hex()
                success_msg = f"Giao dịch thành công!"
                if explorer_url:
                    success_msg += f" URL Explorer: {explorer_url}{tx_hex}"
                logger.success(success_msg)
                return tx_hex
            else:
                raise Exception("Giao dịch thất bại")
        except Exception as e:
            logger.error(
                f"{self.account_index} | Thực hiện giao dịch thất bại: {str(e)}"
            )
            raise

    @retry_async(attempts=3, delay=5.0, backoff=2.0, default_value=None)
    async def approve_token(
        self,
        token_address: str,
        spender_address: str,
        amount: int,
        wallet: LocalAccount,
        chain_id: int,
        token_abi: list = None,
        explorer_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Phê duyệt chi tiêu token cho bất kỳ hợp đồng nào.

        Args:
            token_address: Địa chỉ hợp đồng token
            spender_address: Địa chỉ hợp đồng được phê duyệt chi tiêu
            amount: Số tiền phê duyệt (tính bằng wei)
            wallet: Thể hiện ví (eth_account.LocalAccount)
            chain_id: ID chuỗi cho giao dịch
            token_abi: ABI hợp đồng token (tùy chọn, sẽ sử dụng ABI tối thiểu nếu không cung cấp)
            explorer_url: URL explorer để ghi log (tùy chọn)
        """
        try:
            if token_abi is None:
                # Sử dụng ABI ERC20 tối thiểu nếu không cung cấp
                token_abi = [
                    {
                        "constant": True,
                        "inputs": [
                            {"name": "_owner", "type": "address"},
                            {"name": "_spender", "type": "address"},
                        ],
                        "name": "allowance",
                        "outputs": [{"name": "", "type": "uint256"}],
                        "type": "function",
                    },
                    {
                        "constant": False,
                        "inputs": [
                            {"name": "_spender", "type": "address"},
                            {"name": "_value", "type": "uint256"},
                        ],
                        "name": "approve",
                        "outputs": [{"name": "", "type": "bool"}],
                        "type": "function",
                    },
                ]

            token_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(token_address), abi=token_abi
            )

            current_allowance = await token_contract.functions.allowance(
                wallet.address, spender_address
            ).call()

            if current_allowance >= amount:
                logger.info(
                    f"{self.account_index} | Quyền chi tiêu đủ cho token {token_address}"
                )
                return None

            gas_params = await self.get_gas_params()
            if gas_params is None:
                raise Exception("Không thể lấy tham số gas")

            approve_tx = await token_contract.functions.approve(
                spender_address, amount
            ).build_transaction(
                {
                    "from": wallet.address,
                    "nonce": await self.web3.eth.get_transaction_count(wallet.address),
                    "chainId": chain_id,
                    **gas_params,
                }
            )

            return await self.execute_transaction(
                approve_tx, wallet=wallet, chain_id=chain_id, explorer_url=explorer_url
            )

        except Exception as e:
            logger.error(
                f"{self.account_index} | Phê duyệt token {token_address} thất bại: {str(e)}"
            )
            raise

    @retry_async(attempts=3, delay=5.0, default_value=None)
    async def wait_for_balance_increase(
        self,
        wallet_address: str,
        initial_balance: float,
        token_address: Optional[str] = None,
        token_abi: Optional[list] = None,
        timeout: int = 60,
        check_interval: int = 5,
        log_interval: int = 15,
        account_index: Optional[int] = None,
    ) -> bool:
        """
        Chờ số dư tăng (hoạt động cho cả coin gốc và token).

        Args:
            wallet_address: Địa chỉ để kiểm tra số dư
            initial_balance: Số dư ban đầu để so sánh
            token_address: Địa chỉ token (nếu chờ số dư token)
            token_abi: ABI token (tùy chọn, dành cho token)
            timeout: Thời gian chờ tối đa tính bằng giây
            check_interval: Tần suất kiểm tra số dư tính bằng giây
            log_interval: Tần suất ghi log tiến trình tính bằng giây
            account_index: Chỉ số tài khoản để ghi log (tùy chọn)
        """
        logger.info(
            f"{self.account_index} | Đang chờ số dư tăng (thời gian chờ tối đa: {timeout} giây)..."
        )
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            # Lấy số dư hiện tại (coin gốc hoặc token)
            if token_address:
                current_balance = await self.get_token_balance(
                    wallet_address, token_address, token_abi
                )
            else:
                current_balance = await self.get_balance(wallet_address)

            if current_balance > initial_balance:
                logger.success(
                    f"{self.account_index} | Số dư đã tăng từ {initial_balance} lên {current_balance}"
                )
                return True

            elapsed = int(asyncio.get_event_loop().time() - start_time)
            if elapsed % log_interval == 0:
                logger.info(
                    f"{self.account_index} | Vẫn đang chờ số dư tăng... ({elapsed}/{timeout} giây)"
                )

            await asyncio.sleep(check_interval)

        logger.error(
            f"{self.account_index} | Số dư không tăng sau {timeout} giây"
        )
        return False

    @retry_async(attempts=3, delay=10.0, default_value=None)
    async def estimate_gas(self, transaction: dict) -> int:
        """Ước lượng gas cho giao dịch và thêm một số đệm."""
        try:
            estimated = await self.web3.eth.estimate_gas(transaction)
            # Thêm 10% vào gas ước lượng để đảm bảo an toàn
            return int(estimated * 2.2)
        except Exception as e:
            logger.warning(f"{self.account_index} | Lỗi khi ước lượng gas: {e}.")
            raise e

    @classmethod
    async def create(
        cls,
        account_index: int,
        RPC_URLS: list[str],
        use_proxy: bool,
        proxy: str,
        ssl: bool = False,
    ) -> "Web3Custom":
        """
        Phương thức factory bất đồng bộ để tạo thể hiện lớp.
        """
        instance = cls(account_index, RPC_URLS, use_proxy, proxy, ssl)
        await instance.connect_web3()
        return instance

    async def cleanup(self):
        """
        Phương thức dọn dẹp để đóng phiên client Web3 đúng cách.
        Nên gọi khi hoàn tất sử dụng thể hiện Web3.
        """
        try:
            if not self.web3:
                logger.warning(
                    f"{self.account_index} | Không tìm thấy thể hiện web3 trong quá trình dọn dẹp"
                )
                return

            if hasattr(self.web3, "provider"):
                provider = self.web3.provider

                # Ngắt kết nối provider
                if hasattr(provider, "disconnect"):
                    await provider.disconnect()
                    logger.info(
                        f"{self.account_index} | Ngắt kết nối provider Web3 thành công"
                    )

                # Thêm bước đóng bất kỳ phiên nào có thể tồn tại
                if hasattr(provider, "_request_kwargs") and isinstance(
                    provider._request_kwargs, dict
                ):
                    session = provider._request_kwargs.get("session")
                    if session and hasattr(session, "close") and not session.closed:
                        await session.close()
                        logger.info(
                            f"{self.account_index} | Hoàn tất dọn dẹp phiên bổ sung"
                        )
            else:
                logger.warning(
                    f"{self.account_index} | Không tìm thấy provider trong thể hiện web3"
                )

        except Exception as e:
            logger.error(
                f"{self.account_index} | Lỗi khi dọn dẹp client Web3: {str(e)}\nTraceback: {traceback.format_exc()}"
            )

    def encode_function_call(self, function_name: str, params: dict, abi: list) -> str:
        """
        Mã hóa dữ liệu gọi hàm sử dụng ABI hợp đồng.

        Args:
            function_name: Tên hàm để gọi
            params: Tham số cho hàm
            abi: ABI hợp đồng
        """
        contract = self.web3.eth.contract(abi=abi)
        return contract.encodeABI(fn_name=function_name, args=[params])

    async def send_transaction(
        self,
        to: str,
        data: str,
        wallet: LocalAccount,
        value: int = 0,
        chain_id: Optional[int] = None,
    ) -> str:
        """
        Gửi giao dịch với dữ liệu đã mã hóa.

        Args:
            to: Địa chỉ hợp đồng
            data: Dữ liệu gọi hàm đã mã hóa
            wallet: Thể hiện ví
            value: Số lượng token gốc để gửi
            chain_id: ID chuỗi (tùy chọn)
        """
        if chain_id is None:
            chain_id = await self.web3.eth.chain_id

        # Lấy ước lượng gas
        tx_params = {
            "from": wallet.address,
            "to": to,
            "data": data,
            "value": value,
            "chainId": chain_id,
        }

        try:
            gas_limit = await self.estimate_gas(tx_params)
            tx_params["gas"] = gas_limit
        except Exception as e:
            raise e

        # Lấy tham số giá gas
        gas_params = await self.get_gas_params()
        tx_params.update(gas_params)

        # Lấy nonce
        tx_params["nonce"] = await self.web3.eth.get_transaction_count(wallet.address)

        # Ký và gửi giao dịch
        signed_tx = self.web3.eth.account.sign_transaction(tx_params, wallet.key)
        tx_hash = await self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        return tx_hash.hex()
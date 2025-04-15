import random
from eth_account import Account
from src.model.onchain.web3_custom import Web3Custom
from loguru import logger
import primp
import asyncio
from src.utils.config import Config
from web3 import AsyncWeb3
from src.model.onchain.bridges.crusty_swap.constants import (
    CONTRACT_ADDRESSES,
    DESTINATION_CONTRACT_ADDRESS,
    CRUSTY_SWAP_ABI,
    CHAINLINK_ETH_PRICE_CONTRACT_ADDRESS,
    CHAINLINK_ETH_PRICE_ABI,
    ZERO_ADDRESS,
    CRUSTY_SWAP_RPCS
)
from src.utils.constants import EXPLORER_URLS
from typing import Dict


class CrustySwap:
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
        self.megaeth_web3 = web3
        self.config = config
        self.wallet = wallet
        self.proxy = proxy
        self.private_key = private_key

        self.eth_web3 = None
        self.megaeth_contract = self.megaeth_web3.web3.eth.contract(
            address=DESTINATION_CONTRACT_ADDRESS, abi=CRUSTY_SWAP_ABI
        )

    async def initialize(self):
        """
        Khởi tạo kết nối Web3 cho mạng Ethereum.
        """
        try:
            self.eth_web3 = await self.create_web3("Ethereum")
            return True
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi: {e}")
            return False

    async def create_web3(self, network: str) -> AsyncWeb3:
        """
        Tạo thể hiện Web3 cho một mạng cụ thể.

        Args:
            network: Tên mạng (ví dụ: Ethereum, Arbitrum, Optimism, Base)

        Returns:
            Thể hiện Web3Custom hoặc False nếu thất bại
        """
        try:
            web3 = await Web3Custom.create(
                self.account_index,
                [CRUSTY_SWAP_RPCS[network]],
                self.config.OTHERS.USE_PROXY_FOR_RPC,
                self.proxy,
                self.config.OTHERS.SKIP_SSL_VERIFICATION,
            )
            return web3
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi khi tạo Web3 cho {network}: {e}")
            return False

    async def get_megaeth_balance(self) -> float:
        """
        Lấy số dư MEGAETH gốc.
        """
        try:
            balance_wei = await self.megaeth_web3.web3.eth.get_balance(self.wallet.address)
            return float(self.megaeth_web3.web3.from_wei(balance_wei, 'ether'))
        except Exception as e:
            logger.error(f"[{self.account_index}] Không thể lấy số dư MEGAETH: {str(e)}")
            return 0

    async def get_native_balance(self, network: str) -> float:
        """
        Lấy số dư token gốc cho một mạng cụ thể.

        Args:
            network: Tên mạng để kiểm tra số dư
        """
        try:
            web3 = await self.create_web3(network)
            return await web3.web3.eth.get_balance(self.wallet.address)
        except Exception as e:
            logger.error(f"[{self.account_index}] Không thể lấy số dư cho {network}: {str(e)}")
            return None

    async def wait_for_balance_increase(self, initial_balance: float) -> bool:
        """
        Chờ số dư MEGAETH tăng sau khi nạp.

        Args:
            initial_balance: Số dư ban đầu để so sánh
        """
        timeout = self.config.CRUSTY_SWAP.MAX_WAIT_TIME

        logger.info(
            f"[{self.account_index}] Đang chờ số dư tăng (thời gian chờ tối đa: {timeout} giây)..."
        )
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            current_balance = await self.get_megaeth_balance()
            if current_balance > initial_balance:
                logger.success(
                    f"[{self.account_index}] Số dư đã tăng từ {initial_balance:.9f} lên {current_balance:.9f} MEGAETH"
                )
                return True

            elapsed = int(asyncio.get_event_loop().time() - start_time)
            if elapsed % 15 == 0:
                logger.info(
                    f"[{self.account_index}] Vẫn đang chờ số dư tăng... ({elapsed}/{timeout} giây)"
                )

            await asyncio.sleep(5)

        logger.error(f"[{self.account_index}] Số dư không tăng sau {timeout} giây")
        return False

    async def get_gas_params(self, web3: AsyncWeb3) -> Dict[str, int]:
        """
        Lấy tham số gas cho giao dịch.

        Args:
            web3: Thể hiện Web3 cho mạng cụ thể
        """
        latest_block = await web3.web3.eth.get_block('latest')
        base_fee = latest_block['baseFeePerGas']
        max_priority_fee = await web3.web3.eth.max_priority_fee
        max_fee = int((base_fee + max_priority_fee) * 1.5)

        return {
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority_fee,
        }

    async def get_minimum_deposit(self, network: str) -> int:
        """
        Lấy số tiền nạp tối thiểu cho một mạng cụ thể.

        Args:
            network: Tên mạng để kiểm tra
        """
        try:
            web3 = await self.create_web3(network)
            contract = web3.web3.eth.contract(address=CONTRACT_ADDRESSES[network], abi=CRUSTY_SWAP_ABI)
            return await contract.functions.minimumDeposit().call()
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi khi lấy số tiền nạp tối thiểu: {str(e)}")
            return 0

    async def get_eligible_networks(self, max_retries=5, retry_delay=5):
        """
        Lấy danh sách các mạng đủ điều kiện để nạp với cơ chế thử lại.

        Args:
            max_retries: Số lần thử lại tối đa (mặc định: 5)
            retry_delay: Độ trễ giữa các lần thử lại tính bằng giây (mặc định: 5)

        Returns:
            Danh sách các bộ (mạng, số dư) hoặc False nếu không tìm thấy mạng nào đủ điều kiện
        """
        for attempt in range(1, max_retries + 1):
            try:
                eligible_networks = []

                networks_to_refuel_from = self.config.CRUSTY_SWAP.NETWORKS_TO_REFUEL_FROM
                for network in networks_to_refuel_from:
                    balance = await self.get_native_balance(network)
                    if balance > await self.get_minimum_deposit(network):
                        eligible_networks.append((network, balance))
                return eligible_networks
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"[{self.account_index}] Lần thử {attempt}/{max_retries} thất bại khi lấy mạng đủ điều kiện: {str(e)}"
                    )
                    logger.info(
                        f"[{self.account_index}] Thử lại sau {retry_delay} giây..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(
                        f"[{self.account_index}] Tất cả {max_retries} lần thử thất bại khi lấy mạng đủ điều kiện: {str(e)}"
                    )
                    return False

        return False

    async def pick_network_to_refuel_from(self):
        """
        Chọn một mạng để nạp từ danh sách các mạng đủ điều kiện.
        """
        eligible_networks = await self.get_eligible_networks()
        if not eligible_networks:
            logger.info(f"[{self.account_index}] Không tìm thấy mạng nào đủ điều kiện")
            return False
        return random.choice(eligible_networks)

    async def refuel(self) -> bool:
        """
        Nạp MEGAETH từ một trong các mạng được hỗ trợ.
        """
        try:
            await self.initialize()
            initial_balance = await self.get_megaeth_balance()
            logger.info(f"[{self.account_index}] Số dư MEGAETH ban đầu: {initial_balance:.9f}")
            if initial_balance > self.config.CRUSTY_SWAP.MINIMUM_BALANCE_TO_REFUEL:
                logger.info(
                    f"[{self.account_index}] Số dư hiện tại ({initial_balance:.9f}) vượt quá mức tối thiểu "
                    f"({self.config.CRUSTY_SWAP.MINIMUM_BALANCE_TO_REFUEL}), bỏ qua nạp"
                )
                return False

            network_info = await self.pick_network_to_refuel_from()
            if not network_info:
                logger.error(f"[{self.account_index}] Không tìm thấy mạng nào")
                return False

            network, balance = network_info

            web3 = await self.create_web3(network)
            gas_params = await self.get_gas_params(web3)
            contract = web3.web3.eth.contract(address=CONTRACT_ADDRESSES[network], abi=CRUSTY_SWAP_ABI)

            gas_estimate = await web3.web3.eth.estimate_gas({
                'from': self.wallet.address,
                'to': CONTRACT_ADDRESSES[network],
                'value': await contract.functions.minimumDeposit().call(),
                'data': contract.functions.deposit(
                    ZERO_ADDRESS,
                    self.wallet.address
                )._encode_transaction_data(),
            })

            if self.config.CRUSTY_SWAP.BRIDGE_ALL:
                gas_units = int(gas_estimate * 1.2)
                max_total_gas_cost = (gas_units * gas_params['maxFeePerGas']) * random.uniform(1.15, 1.2)
                max_total_gas_cost = int(max_total_gas_cost + web3.web3.to_wei(random.uniform(0.00001, 0.00002), 'ether'))

                amount_wei = balance - max_total_gas_cost

                if web3.web3.from_wei(amount_wei, 'ether') > self.config.CRUSTY_SWAP.BRIDGE_ALL_MAX_AMOUNT:
                    amount_wei = int(web3.web3.to_wei(
                        self.config.CRUSTY_SWAP.BRIDGE_ALL_MAX_AMOUNT * random.uniform(0.95, 0.99), 'ether'
                    ))

                total_needed = amount_wei + max_total_gas_cost

                if total_needed > balance:
                    raise Exception(
                        f"Số dư không đủ. Có: {balance}, Cần: {total_needed}, Thiếu: {total_needed - balance}"
                    )
            else:
                amount_ether = random.uniform(
                    self.config.CRUSTY_SWAP.AMOUNT_TO_REFUEL[0],
                    self.config.CRUSTY_SWAP.AMOUNT_TO_REFUEL[1]
                )
                amount_wei = int(round(web3.web3.to_wei(amount_ether, 'ether'), random.randint(8, 12)))

            nonce = await web3.web3.eth.get_transaction_count(self.wallet.address)
            has_enough_megaeth = await self.check_available_megaeth(amount_wei, contract)
            if not has_enough_megaeth:
                logger.error(
                    f"[{self.account_index}] Không đủ MEGAETH trong hợp đồng cho số ETH nạp, vui lòng thử lại sau"
                )
                return False

            tx = {
                'from': self.wallet.address,
                'to': CONTRACT_ADDRESSES[network],
                'value': amount_wei,
                'data': contract.functions.deposit(
                    ZERO_ADDRESS,
                    self.wallet.address
                )._encode_transaction_data(),
                'nonce': nonce,
                'gas': int(gas_estimate * 1.1),
                'chainId': await web3.web3.eth.chain_id,
                **gas_params
            }

            signed_tx = web3.web3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = await web3.web3.eth.send_raw_transaction(signed_tx.raw_transaction)

            logger.info(f"[{self.account_index}] Đang chờ xác nhận giao dịch nạp...")
            receipt = await web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            explorer_url = f"{EXPLORER_URLS[network]}{tx_hash.hex()}"

            if receipt['status'] == 1:
                logger.success(f"[{self.account_index}] Giao dịch nạp thành công! URL Explorer: {explorer_url}")

                if self.config.CRUSTY_SWAP.WAIT_FOR_FUNDS_TO_ARRIVE:
                    logger.success(f"[{self.account_index}] Đang chờ số dư tăng...")
                    if await self.wait_for_balance_increase(initial_balance):
                        logger.success(f"[{self.account_index}] Nạp thành công từ {network}")
                        return True
                    logger.warning(f"[{self.account_index}] Số dư không tăng, nhưng giao dịch thành công")
                    return True
                else:
                    logger.success(f"[{self.account_index}] Nạp thành công từ {network} (không chờ số dư)")
                    return True
            else:
                logger.error(f"[{self.account_index}] Giao dịch nạp thất bại! URL Explorer: {explorer_url}")
                return False

        except Exception as e:
            logger.error(f"[{self.account_index}] Nạp thất bại: {str(e)}")
            return False

    def _convert_private_keys_to_addresses(self, private_keys_to_distribute):
        """
        Chuyển đổi khóa riêng thành địa chỉ.
        """
        addresses = []
        for private_key in private_keys_to_distribute:
            addresses.append(Account.from_key(private_key).address)
        return addresses

    async def check_available_megaeth(self, eth_amount_wei, contract, max_retries=5, retry_delay=5) -> bool:
        """
        Kiểm tra xem hợp đồng Crusty Swap có đủ MEGAETH để thực hiện lệnh mua.
        Bao gồm cơ chế thử lại để tăng độ bền trước các lỗi tạm thời.

        Args:
            eth_amount_wei: Số ETH tính bằng wei để sử dụng cho lệnh mua
            contract: Hợp đồng Crusty Swap
            max_retries: Số lần thử lại tối đa
            retry_delay: Độ trễ giữa các lần thử lại tính bằng giây

        Returns:
            bool: True nếu có đủ MEGAETH, False nếu không
        """
        for attempt in range(1, max_retries + 1):
            try:
                available_megaeth_wei = await self.megaeth_web3.web3.eth.get_balance(
                    DESTINATION_CONTRACT_ADDRESS
                )

                chainlink_eth_price_contract = self.eth_web3.web3.eth.contract(
                    address=CHAINLINK_ETH_PRICE_CONTRACT_ADDRESS,
                    abi=CHAINLINK_ETH_PRICE_ABI
                )
                eth_price_usd = await chainlink_eth_price_contract.functions.latestAnswer().call()

                megaeth_price_usd = await contract.functions.pricePerETH().call()

                eth_amount_ether = eth_amount_wei / 10**18
                eth_price_usd_real = eth_price_usd / 10**8
                eth_value_usd = eth_amount_ether * eth_price_usd_real

                megaeth_price_usd_real = megaeth_price_usd / 10**8
                expected_megaeth_amount = eth_value_usd / megaeth_price_usd_real
                expected_megaeth_amount_wei = int(expected_megaeth_amount * 10**18)

                logger.info(
                    f"[{self.account_index}] Số ETH: {eth_amount_ether} ETH (${eth_value_usd:.2f})"
                )
                logger.info(f"[{self.account_index}] Giá ETH: ${eth_price_usd_real:.2f}")
                logger.info(f"[{self.account_index}] Giá MEGAETH: ${megaeth_price_usd_real:.4f}")
                logger.info(
                    f"[{self.account_index}] MEGAETH khả dụng: "
                    f"{self.megaeth_web3.web3.from_wei(available_megaeth_wei, 'ether')} MEGAETH"
                )
                logger.info(
                    f"[{self.account_index}] Dự kiến nhận: {expected_megaeth_amount:.4f} MEGAETH"
                )

                has_enough_megaeth = available_megaeth_wei >= expected_megaeth_amount_wei

                if has_enough_megaeth:
                    logger.success(f"[{self.account_index}] Hợp đồng có đủ MEGAETH để thực hiện lệnh")
                else:
                    logger.warning(
                        f"[{self.account_index}] Hợp đồng không đủ MEGAETH! "
                        f"Khả dụng: {self.megaeth_web3.web3.from_wei(available_megaeth_wei, 'ether')} MEGAETH, "
                        f"Cần: {expected_megaeth_amount:.4f} MEGAETH"
                    )

                return has_enough_megaeth

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"[{self.account_index}] Lần thử {attempt}/{max_retries} thất bại khi kiểm tra MEGAETH khả dụng: {str(e)}"
                    )
                    logger.info(
                        f"[{self.account_index}] Thử lại sau {retry_delay} giây..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(
                        f"[{self.account_index}] Tất cả {max_retries} lần thử thất bại khi kiểm tra MEGAETH khả dụng: {str(e)}"
                    )
                    return False

        return False

    async def _get_megaeth_balance(self, address) -> float:
        """
        Lấy số dư MEGAETH gốc cho một địa chỉ cụ thể.

        Args:
            address: Địa chỉ để kiểm tra số dư
        """
        try:
            balance_wei = await self.megaeth_web3.web3.eth.get_balance(address)
            return float(self.megaeth_web3.web3.from_wei(balance_wei, 'ether'))
        except Exception as e:
            logger.error(f"[{self.account_index}] Không thể lấy số dư MEGAETH: {str(e)}")
            return None

    async def _wait_for_balance_increase(self, initial_balance: float, address: str) -> bool:
        """
        Chờ số dư MEGAETH tăng sau khi nạp cho một địa chỉ cụ thể.

        Args:
            initial_balance: Số dư ban đầu để so sánh
            address: Địa chỉ để kiểm tra số dư
        """
        timeout = self.config.CRUSTY_SWAP.MAX_WAIT_TIME

        logger.info(
            f"[{self.account_index}] Đang chờ số dư tăng (thời gian chờ tối đa: {timeout} giây)..."
        )
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            current_balance = await self._get_megaeth_balance(address)
            if current_balance > initial_balance:
                logger.success(
                    f"[{self.account_index}] Số dư đã tăng từ {initial_balance} lên {current_balance} MEGAETH"
                )
                return True

            elapsed = int(asyncio.get_event_loop().time() - start_time)
            if elapsed % 15 == 0:
                logger.info(
                    f"[{self.account_index}] Vẫn đang chờ số dư tăng... ({elapsed}/{timeout} giây)"
                )

            await asyncio.sleep(5)

        logger.error(f"[{self.account_index}] Số dư không tăng sau {timeout} giây")
        return False

    async def _handle_transaction_status(self, receipt, explorer_url, initial_balance, network, address) -> bool:
        """
        Xử lý trạng thái giao dịch nạp.

        Args:
            receipt: Biên nhận giao dịch
            explorer_url: URL explorer để ghi log
            initial_balance: Số dư ban đầu
            network: Mạng được sử dụng để nạp
            address: Địa chỉ nhận MEGAETH
        """
        if receipt['status'] == 1:
            logger.success(f"[{self.account_index}] Giao dịch nạp thành công! URL Explorer: {explorer_url}")

            if self.config.CRUSTY_SWAP.WAIT_FOR_FUNDS_TO_ARRIVE:
                logger.success(f"[{self.account_index}] Đang chờ số dư tăng...")
                if await self._wait_for_balance_increase(initial_balance, address):
                    logger.success(f"[{self.account_index}] Nạp thành công từ {network}")
                    return True
                logger.warning(f"[{self.account_index}] Số dư không tăng, nhưng giao dịch thành công")
                return True
            else:
                logger.success(f"[{self.account_index}] Nạp thành công từ {network} (không chờ số dư)")
                return True
        else:
            logger.error(f"[{self.account_index}] Giao dịch nạp thất bại! URL Explorer: {explorer_url}")
            return False

    async def send_refuel_from_one_to_all(self, address) -> bool:
        """
        Gửi giao dịch nạp MEGAETH từ một mạng được hỗ trợ đến một địa chỉ.

        Args:
            address: Địa chỉ nhận MEGAETH
        """
        try:
            initial_balance = await self._get_megaeth_balance(address)
            if initial_balance is None:
                logger.error(
                    f"[{self.account_index}] Không thể lấy số dư MEGAETH cho địa chỉ: {address}"
                )
                return False
            logger.info(f"[{self.account_index}] Số dư MEGAETH ban đầu: {initial_balance}")
            if initial_balance > self.config.CRUSTY_SWAP.MINIMUM_BALANCE_TO_REFUEL:
                logger.info(
                    f"[{self.account_index}] Số dư hiện tại ({initial_balance}) vượt quá mức tối thiểu "
                    f"({self.config.CRUSTY_SWAP.MINIMUM_BALANCE_TO_REFUEL}), bỏ qua nạp"
                )
                return False

            network_info = await self.pick_network_to_refuel_from()
            if not network_info:
                logger.error(f"[{self.account_index}] Không tìm thấy mạng nào")
                return False

            network, balance = network_info

            web3 = await self.create_web3(network)
            gas_params = await self.get_gas_params(web3)
            contract = web3.web3.eth.contract(address=CONTRACT_ADDRESSES[network], abi=CRUSTY_SWAP_ABI)

            gas_estimate = await web3.web3.eth.estimate_gas({
                'from': self.wallet.address,
                'to': CONTRACT_ADDRESSES[network],
                'value': await contract.functions.minimumDeposit().call(),
                'data': contract.functions.deposit(
                    ZERO_ADDRESS,
                    address
                )._encode_transaction_data(),
            })

            if self.config.CRUSTY_SWAP.BRIDGE_ALL:
                gas_units = int(gas_estimate * 1.2)
                max_total_gas_cost = (gas_units * gas_params['maxFeePerGas']) * random.uniform(1.15, 1.2)
                max_total_gas_cost = int(max_total_gas_cost + web3.web3.to_wei(
                    random.uniform(0.00001, 0.00002), 'ether'
                ))

                amount_wei = balance - max_total_gas_cost

                if web3.web3.from_wei(amount_wei, 'ether') > self.config.CRUSTY_SWAP.BRIDGE_ALL_MAX_AMOUNT:
                    amount_wei = int(web3.web3.to_wei(
                        self.config.CRUSTY_SWAP.BRIDGE_ALL_MAX_AMOUNT * random.uniform(0.95, 0.99), 'ether'
                    ))

                total_needed = amount_wei + max_total_gas_cost

                if total_needed > balance:
                    raise Exception(
                        f"Số dư không đủ. Có: {balance}, Cần: {total_needed}, Thiếu: {total_needed - balance}"
                    )
            else:
                amount_ether = random.uniform(
                    self.config.CRUSTY_SWAP.AMOUNT_TO_REFUEL[0],
                    self.config.CRUSTY_SWAP.AMOUNT_TO_REFUEL[1]
                )
                amount_wei = int(round(web3.web3.to_wei(amount_ether, 'ether'), random.randint(8, 12)))

            nonce = await web3.web3.eth.get_transaction_count(self.wallet.address)
            has_enough_megaeth = await self.check_available_megaeth(amount_wei, contract)
            if not has_enough_megaeth:
                logger.error(
                    f"[{self.account_index}] Không đủ MEGAETH trong hợp đồng cho số ETH nạp, vui lòng thử lại sau"
                )
                return False

            tx = {
                'from': self.wallet.address,
                'to': CONTRACT_ADDRESSES[network],
                'value': amount_wei,
                'data': contract.functions.deposit(
                    ZERO_ADDRESS,
                    address
                )._encode_transaction_data(),
                'nonce': nonce,
                'gas': int(gas_estimate * 1.1),
                'chainId': await web3.web3.eth.chain_id,
                **gas_params
            }

            signed_tx = web3.web3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = await web3.web3.eth.send_raw_transaction(signed_tx.raw_transaction)

            logger.info(f"[{self.account_index}] Đang chờ xác nhận giao dịch nạp...")
            receipt = await web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            explorer_url = f"{EXPLORER_URLS[network]}{tx_hash.hex()}"
            return await self._handle_transaction_status(receipt, explorer_url, initial_balance, network, address)

        except Exception as e:
            logger.error(f"[{self.account_index}] Nạp thất bại: {str(e)}")
            return False

    async def refuel_from_one_to_all(self, private_keys_to_distribute) -> bool:
        """
        Nạp MEGAETH từ một mạng được hỗ trợ đến nhiều địa chỉ.

        Args:
            private_keys_to_distribute: Danh sách khóa riêng để phân phối MEGAETH
        """
        try:
            await self.initialize()
            addresses = self._convert_private_keys_to_addresses(private_keys_to_distribute)
            for index, address in enumerate(addresses):
                logger.info(
                    f"[{self.account_index}] - [{index}/{len(addresses)}] Đang nạp từ CHÍNH: {self.wallet.address} đến: {address}"
                )
                status = await self.send_refuel_from_one_to_all(address)
                pause = random.uniform(
                    self.config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACCOUNTS[0],
                    self.config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACCOUNTS[1]
                )
                await asyncio.sleep(pause)
            return True
        except Exception as e:
            logger.error(f"[{self.account_index}] Nạp thất bại: {str(e)}")
            return False
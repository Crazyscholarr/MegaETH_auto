import random
import ccxt.async_support as ccxt
import asyncio
import time
from decimal import Decimal
from src.utils.config import Config
from eth_account import Account
from loguru import logger
from web3 import Web3
from src.model.offchain.cex.constants import (
    CEX_WITHDRAWAL_RPCS,
    NETWORK_MAPPINGS,
    EXCHANGE_PARAMS,
    SUPPORTED_EXCHANGES
)
from typing import Dict, Optional


class CexWithdraw:
    def __init__(self, account_index: int, private_key: str, config: Config):
        self.account_index = account_index
        self.private_key = private_key
        self.config = config
        
        # Thiết lập sàn giao dịch dựa trên cấu hình
        exchange_name = config.EXCHANGES.name.lower()
        if exchange_name not in SUPPORTED_EXCHANGES:
            raise ValueError(f"Sàn giao dịch không được hỗ trợ: {exchange_name}")
            
        # Khởi tạo sàn giao dịch
        self.exchange = getattr(ccxt, exchange_name)()
            
        # Thiết lập thông tin xác thực cho sàn giao dịch
        self.exchange.apiKey = config.EXCHANGES.apiKey
        self.exchange.secret = config.EXCHANGES.secretKey
        if config.EXCHANGES.passphrase:
            self.exchange.password = config.EXCHANGES.passphrase
        
        self.account = Account.from_key(private_key)
        self.address = self.account.address
        
        # Lấy mạng rút tiền từ cấu hình
        if not self.config.EXCHANGES.withdrawals:
            raise ValueError("Không tìm thấy cấu hình rút tiền")
            
        withdrawal_config = self.config.EXCHANGES.withdrawals[0]
        if not withdrawal_config.networks:
            raise ValueError("Không có mạng nào được chỉ định trong cấu hình rút tiền")
            
        # Mạng sẽ được chọn trong quá trình rút tiền, không phải trong __init__
        # Web3 sẽ được khởi tạo sau khi chọn mạng trong phương thức withdraw
        self.network = None
        self.web3 = None

    async def __aenter__(self):
        """Vào trình quản lý ngữ cảnh bất đồng bộ"""
        await self.check_auth()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Thoát trình quản lý ngữ cảnh bất đồng bộ"""
        await self.exchange.close()

    async def check_auth(self) -> None:
        """Kiểm tra xác thực sàn giao dịch"""
        logger.info(f"[{self.account_index}] Đang kiểm tra xác thực sàn giao dịch...")
        try:
            await self.exchange.fetch_balance()
            logger.success(f"[{self.account_index}] Xác thực thành công")
        except ccxt.AuthenticationError as e:
            logger.error(f"[{self.account_index}] Lỗi xác thực: {str(e)}")
            await self.exchange.close()
            raise
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi không mong muốn trong quá trình xác thực: {str(e)}")
            await self.exchange.close()
            raise
            
    async def get_chains_info(self) -> Dict:
        """Lấy thông tin mạng rút tiền"""
        logger.info(f"[{self.account_index}] Đang lấy dữ liệu mạng rút tiền...")
        
        try:
            await self.exchange.load_markets()
            
            chains_info = {}
            withdrawal_config = self.config.EXCHANGES.withdrawals[0]
            currency = withdrawal_config.currency.upper()
            
            if currency not in self.exchange.currencies:
                logger.error(f"[{self.account_index}] Không tìm thấy tiền tệ {currency} trên {self.config.EXCHANGES.name}")
                return {}
                
            networks = self.exchange.currencies[currency]["networks"]
            
            for key, info in networks.items():
                withdraw_fee = info["fee"]
                withdraw_min = info["limits"]["withdraw"]["min"]
                network_id = info["id"]
                
                logger.info(f"[{self.account_index}]   - Mạng: {key} (ID: {network_id})")
                logger.info(f"[{self.account_index}]     Phí: {withdraw_fee}, Số tiền tối thiểu: {withdraw_min}")
                logger.info(f"[{self.account_index}]     Kích hoạt: {info['withdraw']}")
                
                if info["withdraw"]:
                    chains_info[key] = {
                        "chainId": network_id,
                        "withdrawEnabled": True,
                        "withdrawFee": withdraw_fee,
                        "withdrawMin": withdraw_min
                    }
                        
            return chains_info
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi khi lấy thông tin mạng: {str(e)}")
            await self.exchange.close()
            raise
        
    def _is_withdrawal_enabled(self, key: str, info: Dict) -> bool:
        """Kiểm tra xem rút tiền có được kích hoạt cho mạng không"""
        return info["withdraw"]
        
    def _get_chain_id(self, key: str, info: Dict) -> str:
        """Lấy ID chuỗi mạng"""
        return info["id"]
        
    def _get_withdraw_fee(self, info: Dict) -> float:
        """Lấy phí rút tiền"""
        return info["fee"]
        
    @staticmethod
    def _get_withdraw_min(info: Dict) -> float:
        """Lấy số tiền rút tối thiểu"""
        return info["limits"]["withdraw"]["min"]
        
    async def check_balance(self, amount: float) -> bool:
        """Kiểm tra xem sàn giao dịch có đủ số dư để rút tiền không"""
        try:
            # Lấy tham số số dư cụ thể cho sàn giao dịch
            exchange_name = self.config.EXCHANGES.name.lower()
            params = EXCHANGE_PARAMS[exchange_name]["balance"]
            
            balances = await self.exchange.fetch_balance(params=params)
            withdrawal_config = self.config.EXCHANGES.withdrawals[0]
            currency = withdrawal_config.currency.upper()
            
            balance = float(balances[currency]["total"])
            logger.info(f"[{self.account_index}] Số dư sàn giao dịch: {balance:.8f} {currency}")
            
            if balance < amount:
                logger.error(f"[{self.account_index}] Số dư không đủ để rút tiền {balance} {currency} < {amount} {currency}")
                await self.exchange.close()
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi khi kiểm tra số dư: {str(e)}")
            await self.exchange.close()
            raise

    async def get_eth_balance(self) -> Decimal:
        """Lấy số dư ETH cho địa chỉ ví"""
        if self.web3 is None:
            raise ValueError(f"[{self.account_index}] Phiên bản Web3 chưa được khởi tạo. Phải chọn mạng trước.")

        balance_wei = self.web3.eth.get_balance(self.address)
        return Decimal(self.web3.from_wei(balance_wei, 'ether'))

    async def wait_for_balance_update(self, initial_balance: Decimal, timeout: int = 600) -> bool:
        """
        Chờ số dư tăng từ số dư ban đầu.
        Trả về True nếu số dư tăng, False nếu hết thời gian chờ.
        """
        start_time = time.time()
        logger.info(f"[{self.account_index}] Đang chờ tiền đến. Số dư ban đầu: {initial_balance} ETH")
        
        while time.time() - start_time < timeout:
            try:
                current_balance = await self.get_eth_balance()
                if current_balance > initial_balance:
                    increase = current_balance - initial_balance
                    logger.success(f"[{self.account_index}] Đã nhận được tiền! Số dư tăng thêm {increase} ETH")
                    return True
                
                logger.info(f"[{self.account_index}] Số dư hiện tại: {current_balance} ETH. Đang chờ...")
                await asyncio.sleep(10)  # Kiểm tra mỗi 10 giây
                
            except Exception as e:
                logger.error(f"[{self.account_index}] Lỗi khi kiểm tra số dư: {str(e)}")
                await asyncio.sleep(5)
                
        logger.warning(f"[{self.account_index}] Đã hết thời gian chờ sau {timeout} giây. Không nhận được tiền.")
        return False

    async def withdraw(self) -> bool:
        """
        Rút tiền từ sàn giao dịch đến địa chỉ được chỉ định với cơ chế thử lại.
        Trả về True nếu rút tiền thành công và tiền đã đến.
        """
        try:
            if not self.config.EXCHANGES.withdrawals:
                raise ValueError("Không tìm thấy cấu hình rút tiền")
                
            withdrawal_config = self.config.EXCHANGES.withdrawals[0]
            if not withdrawal_config.networks:
                raise ValueError("Không có mạng nào được chỉ định trong cấu hình rút tiền")
                
            # Lấy thông tin mạng và xác thực rút tiền được kích hoạt
            chains_info = await self.get_chains_info()
            if not chains_info:
                logger.error(f"[{self.account_index}] Không tìm thấy mạng rút tiền khả dụng")
                return False
                
            currency = withdrawal_config.currency
            exchange_name = self.config.EXCHANGES.name.lower()
            
            # Lấy các mạng khả dụng khớp với cấu hình
            available_networks = []
            for network in withdrawal_config.networks:
                mapped_network = NETWORK_MAPPINGS[exchange_name].get(network)
                if not mapped_network:
                    continue
                    
                # Kiểm tra xem mạng có tồn tại và được kích hoạt trong chains_info không
                for key, info in chains_info.items():
                    if key == mapped_network and info["withdrawEnabled"]:
                        available_networks.append((network, mapped_network, info))
                        break
                        
            if not available_networks:
                logger.error(f"[{self.account_index}] Không tìm thấy mạng rút tiền được kích hoạt khớp với cấu hình")
                return False
                
            # Chọn ngẫu nhiên từ các mạng khả dụng
            network, exchange_network, network_info = random.choice(available_networks)
            logger.info(f"[{self.account_index}] Đã chọn mạng để rút tiền: {network} ({exchange_network})")
            
            # Cập nhật phiên bản web3 với URL RPC đúng cho mạng đã chọn
            self.network = network
            rpc_url = CEX_WITHDRAWAL_RPCS.get(self.network)
            if not rpc_url:
                logger.error(f"[{self.account_index}] Không tìm thấy URL RPC cho mạng: {self.network}")
                return False
            self.web3 = Web3(Web3.HTTPProvider(rpc_url))
            
            # Đảm bảo số tiền rút tôn trọng mức tối thiểu của mạng
            min_amount = max(withdrawal_config.min_amount, network_info["withdrawMin"])
            max_amount = withdrawal_config.max_amount
            
            if min_amount > max_amount:
                logger.error(f"[{self.account_index}] Số tiền tối thiểu của mạng ({network_info['withdrawMin']}) cao hơn mức tối đa được cấu hình ({max_amount})")
                await self.exchange.close()
                return False
                
            amount = round(random.uniform(min_amount, max_amount), random.randint(5, 12))
            
            # Kiểm tra xem có đủ số dư để rút tiền không
            if not await self.check_balance(amount):
                return False
                
            # Kiểm tra xem số dư ví đích có vượt quá tối đa trên BẤT KỲ mạng nào không
            # Ngăn rút tiền nếu ví đã có đủ tiền trên bất kỳ chuỗi nào
            if not await self.check_all_networks_balance(withdrawal_config.max_balance):
                logger.warning(f"[{self.account_index}] Bỏ qua rút tiền vì số dư ví đích vượt quá tối đa trên ít nhất một mạng")
                await self.exchange.close()
                return False
             
            max_retries = withdrawal_config.retries
            
            for attempt in range(max_retries):
                try:
                    # Lấy số dư ban đầu trước khi rút
                    initial_balance = await self.get_eth_balance()
                    logger.info(f"[{self.account_index}] Đang thử rút tiền lần {attempt + 1}/{max_retries}")
                    logger.info(f"[{self.account_index}] Rút {amount} {currency} đến {self.address}")
                    
                    # Lấy tham số rút tiền cụ thể cho sàn giao dịch
                    params = {
                        'network': exchange_network,
                        'fee': network_info["withdrawFee"],
                        **EXCHANGE_PARAMS[exchange_name]["withdraw"]
                    }
                    
                    withdrawal = await self.exchange.withdraw(
                        currency,
                        amount,
                        self.address,
                        params=params
                    )
                    
                    logger.success(f"[{self.account_index}] Đã khởi tạo rút tiền thành công")
                    
                    # Chờ tiền đến nếu được cấu hình
                    if withdrawal_config.wait_for_funds:
                        funds_received = await self.wait_for_balance_update(
                            initial_balance,
                            timeout=withdrawal_config.max_wait_time
                        )
                        if funds_received:
                            await self.exchange.close()
                            return True
                        
                        logger.warning(f"[{self.account_index}] Chưa nhận được tiền, sẽ thử lại rút tiền")
                    else:
                        await self.exchange.close()
                        return True  # Nếu không chờ tiền, coi như thành công
                    
                except ccxt.NetworkError as e:
                    if attempt == max_retries - 1:
                        logger.error(f"[{self.account_index}] Lỗi mạng ở lần thử cuối: {str(e)}")
                        await self.exchange.close()
                        raise
                    logger.warning(f"[{self.account_index}] Lỗi mạng, đang thử lại: {str(e)}")
                    await asyncio.sleep(5)
                    
                except ccxt.ExchangeError as e:
                    error_msg = str(e).lower()
                    if "insufficient balance" in error_msg:
                        logger.error(f"[{self.account_index}] Số dư không đủ trong tài khoản sàn giao dịch")
                        await self.exchange.close()
                        return False
                    if "whitelist" in error_msg or "not in withdraw whitelist" in error_msg:
                        logger.error(f"[{self.account_index}] Địa chỉ không nằm trong danh sách trắng: {str(e)}")
                        await self.exchange.close()
                        return False
                    if attempt == max_retries - 1:
                        logger.error(f"[{self.account_index}] Lỗi sàn giao dịch ở lần thử cuối: {str(e)}")
                        await self.exchange.close()
                        raise
                    logger.warning(f"[{self.account_index}] Lỗi sàn giao dịch, đang thử lại: {str(e)}")
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.error(f"[{self.account_index}] Lỗi không mong muốn trong quá trình rút tiền: {str(e)}")
                    await self.exchange.close()
                    raise
                    
            logger.error(f"[{self.account_index}] Rút tiền thất bại sau {max_retries} lần thử")
            await self.exchange.close()
            return False
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi nghiêm trọng trong quá trình rút tiền: {str(e)}")
            await self.exchange.close()
            raise 

    async def check_all_networks_balance(self, max_balance: float) -> bool:
        """
        Kiểm tra số dư trên tất cả mạng trong cấu hình rút tiền.
        Trả về False nếu số dư của bất kỳ mạng nào vượt quá mức tối đa cho phép.
        """
        withdrawal_config = self.config.EXCHANGES.withdrawals[0]
        if not withdrawal_config.networks:
            raise ValueError("Không có mạng nào được chỉ định trong cấu hình rút tiền")
            
        # Lưu trữ mạng hiện tại và phiên bản web3 để khôi phục sau này
        original_network = self.network
        original_web3 = self.web3
        
        try:
            # Kiểm tra số dư trên mỗi mạng
            for network in withdrawal_config.networks:
                rpc_url = CEX_WITHDRAWAL_RPCS.get(network)
                if not rpc_url:
                    logger.warning(f"[{self.account_index}] Không tìm thấy URL RPC cho mạng: {network}, bỏ qua kiểm tra số dư")
                    continue
                    
                # Thiết lập web3 cho mạng này
                self.network = network
                self.web3 = Web3(Web3.HTTPProvider(rpc_url))
                
                try:
                    current_balance = await self.get_eth_balance()
                    if current_balance >= Decimal(str(max_balance)):
                        logger.warning(f"[{self.account_index}] Số dư ví đích trên {network} ({current_balance}) vượt quá mức tối đa cho phép ({max_balance})")
                        return False
                    logger.info(f"[{self.account_index}] Số dư trên {network}: {current_balance} ETH (dưới mức tối đa: {max_balance})")
                except Exception as e:
                    logger.warning(f"[{self.account_index}] Lỗi khi kiểm tra số dư trên {network}: {str(e)}")
                    
            return True
            
        finally:
            # Khôi phục mạng và phiên bản web3 ban đầu
            self.network = original_network
            self.web3 = original_web3
import random
from eth_account.messages import encode_typed_data
from eth_account import Account
from src.model.projects.swaps.constants import GTE_SWAPS_ABI, GTE_SWAPS_CONTRACT, GTE_TOKENS
from src.model.onchain.web3_custom import Web3Custom
from loguru import logger
import primp
from web3 import Web3
from curl_cffi.requests import AsyncSession
import time
import asyncio

from src.utils.decorators import retry_async
from src.utils.config import Config
from src.utils.constants import EXPLORER_URL_MEGAETH, ERC20_ABI, BALANCE_CHECKER_ABI, BALANCE_CHECKER_CONTRACT_ADDRESS


class GteSwaps:
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
        self.contract = self.web3.web3.eth.contract(
            address=self.web3.web3.to_checksum_address(GTE_SWAPS_CONTRACT), 
            abi=GTE_SWAPS_ABI
        )

    @retry_async(default_value=([], None))
    async def _get_path(self, balances: dict) -> tuple[list[str], str]:
        try:
            # Get tokens with non-zero balance (excluding native ETH)
            tokens_with_balance = {token: balance for token, balance in balances.items() 
                                if token != "native" and balance > 0}
            
            # Path format: [from_token_address, to_token_address]
            path = []
            swap_type = ""
            
            # 50/50 chance to do native->token swap regardless of token balances
            do_native_swap = random.choice([True, False])
            
            # CASE 1: If no tokens have balance or we randomly chose to do a native swap
            if not tokens_with_balance or do_native_swap:
                logger.info(f"[{self.account_index}] Đang tạo đường dẫn ETH -> token" + 
                           (" (lựa chọn ngẫu nhiên)" if tokens_with_balance and do_native_swap else " (không có số dư token)"))
                
                # Choose a random token from GTE_TOKENS excluding WETH (to prevent ETH->WETH swaps)
                available_tokens = [token for token in GTE_TOKENS.keys() if token != "WETH"]
                target_token = random.choice(available_tokens)
                
                # Path: ETH (WETH address) -> random token
                weth_address = self.web3.web3.to_checksum_address(GTE_TOKENS["WETH"]["address"])
                token_address = self.web3.web3.to_checksum_address(GTE_TOKENS[target_token]["address"])
                
                path = [weth_address, token_address]
                swap_type = "native_token"
                logger.info(f"[{self.account_index}] Đã tạo đường dẫn ETH -> {target_token}: {path}, loại hoán đổi: {swap_type}")
            
            # CASE 2 & 3: If tokens have balance and we randomly chose to use them
            else:
                # Choose a random token with balance
                source_token_symbol = random.choice(list(tokens_with_balance.keys()))
                source_token_address = self.web3.web3.to_checksum_address(GTE_TOKENS[source_token_symbol]["address"])
                
                # 50% chance to swap to ETH, 50% chance to swap to another token
                swap_to_eth = random.choice([True, False])
                
                if swap_to_eth:
                    # CASE 2: Token -> ETH path
                    weth_address = self.web3.web3.to_checksum_address(GTE_TOKENS["WETH"]["address"])
                    path = [source_token_address, weth_address]
                    swap_type = "token_native"
                    logger.info(f"[{self.account_index}] Đã tạo đường dẫn {source_token_symbol} -> ETH: {path}, loại hoán đổi: {swap_type}")
                else:
                    # CASE 3: Token -> Token path
                    # Get available target tokens (excluding the source token and WETH)
                    available_targets = [token for token in GTE_TOKENS.keys() 
                                       if token != source_token_symbol and token != "WETH"]
                    
                    if available_targets:
                        target_token = random.choice(available_targets)
                        target_address = self.web3.web3.to_checksum_address(GTE_TOKENS[target_token]["address"])
                        
                        path = [source_token_address, target_address]
                        swap_type = "token_token"
                        logger.info(f"[{self.account_index}] Đã tạo đường dẫn {source_token_symbol} -> {target_token}: {path}, loại hoán đổi: {swap_type}")
                    else:
                        # Fallback: swap to ETH if no other tokens available
                        weth_address = self.web3.web3.to_checksum_address(GTE_TOKENS["WETH"]["address"])
                        path = [source_token_address, weth_address]
                        swap_type = "token_native"
                        logger.info(f"[{self.account_index}] Dự phòng: Đã tạo đường dẫn {source_token_symbol} -> ETH: {path}, loại hoán đổi: {swap_type}")
            
            return path, swap_type
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong _get_path: {e}")
            return [], None

    @retry_async(default_value=False)
    async def _get_balances(self) -> dict:
        logger.info(f"[{self.account_index}] Đang lấy số dư")
        try:
            balances = {}
            # Multicall contract for balance checking
                     
            # Create multicall contract instance
            multicall_contract = self.web3.web3.eth.contract(
                address=self.web3.web3.to_checksum_address(BALANCE_CHECKER_CONTRACT_ADDRESS),
                abi=BALANCE_CHECKER_ABI
            )
            
            # Prepare token addresses list (include ETH as 0x0 address)
            token_addresses = [
                "0x0000000000000000000000000000000000000000"  # ETH address
            ]
            
            # Add all token addresses from GTE_TOKENS
            for token_symbol, token_data in GTE_TOKENS.items():
                token_addresses.append(self.web3.web3.to_checksum_address(token_data["address"]))
            
            # Prepare users list (single user in this case)
            users = [self.wallet.address]
            all_balances = await multicall_contract.functions.balances(
                users, token_addresses
            ).call()
            
            # ETH balance is the first one
            eth_balance = all_balances[0]
            balances["native"] = eth_balance
            logger.info(f"[{self.account_index}] Số dư của ETH: {eth_balance}")
            
            # Process token balances
            token_symbols = list(GTE_TOKENS.keys())
            for i, token_symbol in enumerate(token_symbols):
                # Token balance is offset by 1 (since ETH is at index 0)
                token_balance = all_balances[i + 1]
                balances[token_symbol] = token_balance
                logger.info(f"[{self.account_index}] Số dư của {token_symbol}: {token_balance}")
            
            return balances
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong _get_balances: {e}")
            return False
    
    async def execute_swap(self):
        try:
            swaps_amount = random.randint(self.config.SWAPS.GTE.SWAPS_AMOUNT[0], self.config.SWAPS.GTE.SWAPS_AMOUNT[1])
            logger.info(f"[{self.account_index}] Đang lên kế hoạch thực hiện {swaps_amount} hoán đổi")
            
            successful_swaps = 0
            
            for i in range(swaps_amount):
                logger.info(f"[{self.account_index}] Đang thực hiện hoán đổi {i+1}/{swaps_amount}")
                
                balances = await self._get_balances()
                if not balances:
                    logger.error(f"[{self.account_index}] Không thể lấy số dư")
                    continue
                
                # Regular swap logic first regardless of SWAP_ALL_TO_ETH setting
                path, swap_type = await self._get_path(balances)
                if not path or not swap_type:
                    logger.error(f"[{self.account_index}] Không thể tạo đường dẫn hợp lệ cho hoán đổi")
                    continue
                
                # Execute the appropriate swap type
                swap_result = False
                if swap_type == "native_token":
                    swap_result = await self._swap_native_to_token(path)
                elif swap_type == "token_native":
                    swap_result = await self._swap_token_to_native(path, balances)
                elif swap_type == "token_token":
                    swap_result = await self._swap_token_to_token(path, balances)
                else:
                    logger.error(f"[{self.account_index}] Loại hoán đổi không xác định: {swap_type}")
                    continue
                
                if swap_result:
                    successful_swaps += 1
                    logger.success(f"[{self.account_index}] Hoán đổi {i+1} hoàn thành thành công")
                else:
                    logger.error(f"[{self.account_index}] Hoán đổi {i+1} thất bại")
                
                # Add a small delay between swaps
                await asyncio.sleep(random.uniform(1, 3))
            
            # If SWAP_ALL_TO_ETH is enabled, swap all tokens to ETH after the loop
            if self.config.SWAPS.GTE.SWAP_ALL_TO_ETH:
                logger.info(f"[{self.account_index}] SWAP_ALL_TO_ETH được kích hoạt, giờ đang hoán đổi tất cả token còn lại sang ETH")
                
                # Get fresh balances after the previous swaps
                updated_balances = await self._get_balances()
                
                # Get tokens with non-zero balance (excluding native ETH)
                tokens_with_balance = {token: balance for token, balance in updated_balances.items() 
                                      if token != "native" and balance > 0}
                
                if not tokens_with_balance:
                    logger.info(f"[{self.account_index}] Không tìm thấy token nào có số dư để hoán đổi sang ETH")
                else:
                    # Swap each token to ETH one by one
                    for token_symbol, balance in tokens_with_balance.items():
                        logger.info(f"[{self.account_index}] Đang hoán đổi {token_symbol} sang ETH")
                        # Create path for this token to ETH
                        source_token_address = self.web3.web3.to_checksum_address(GTE_TOKENS[token_symbol]["address"])
                        weth_address = self.web3.web3.to_checksum_address(GTE_TOKENS["WETH"]["address"])
                        path = [source_token_address, weth_address]
                        
                        # Execute token to ETH swap
                        result = await self._swap_token_to_native(path, updated_balances)
                        if result:
                            successful_swaps += 1
                            logger.success(f"[{self.account_index}] Hoán đổi {token_symbol} sang ETH thành công")
                        else:
                            logger.error(f"[{self.account_index}] Không thể hoán đổi {token_symbol} sang ETH")
                        
                        # Add a small delay between swaps
                        delay = random.uniform(self.config.SETTINGS.PAUSE_BETWEEN_SWAPS[0], self.config.SETTINGS.PAUSE_BETWEEN_SWAPS[1])
                        await asyncio.sleep(delay)
            
            # Return True if at least one swap was successful
            return successful_swaps > 0
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong execute_swap: {e}")
            return False
            
    async def _sign_and_send_transaction(self, tx, operation_name="giao dịch"):
        """Ký, gửi và đợi giao dịch được khai thác"""
        try:
            # Sign and send transaction
            signed_tx = self.web3.web3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = await self.web3.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            explorer_link = f"{EXPLORER_URL_MEGAETH}{tx_hash_hex}"
            
            logger.info(f"[{self.account_index}] {operation_name} đã gửi: {explorer_link}")
            
            # Wait for transaction to be mined
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                logger.success(f"[{self.account_index}] {operation_name} thành công! TX: {explorer_link}")
            else:
                logger.error(f"[{self.account_index}] {operation_name} thất bại! TX: {explorer_link}")
            
            return receipt
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong _sign_and_send_transaction ({operation_name}): {e}")
            return None

    async def _calculate_min_output(self, path, amount_in, slippage_percentage=10):
        """
        Tính toán lượng đầu ra tối thiểu dựa trên giá hiện tại và mức độ trượt giá cho phép
        
        Args:
            path: Đường dẫn hoán đổi [from_token, to_token]
            amount_in: Số lượng đầu vào, có thể là số nguyên hoặc đối tượng Balance
            slippage_percentage: Phần trăm trượt giá cho phép (mặc định: 10%)
            
        Returns:
            int: Số lượng đầu ra tối thiểu sau khi tính trượt giá
        """
        try:
            # Convert amount_in to int if it's a Balance object
            if hasattr(amount_in, 'wei'):
                amount_in = amount_in.wei
            # Otherwise ensure it's still an integer
            elif not isinstance(amount_in, int):
                amount_in = int(amount_in)
            
            # Ensure path addresses are checksum
            checksum_path = [self.web3.web3.to_checksum_address(addr) for addr in path]
            
            # Get expected output amounts for the path
            amounts = await self.contract.functions.getAmountsOut(
                amount_in,
                checksum_path
            ).call()
            
            # The last amount in the array is the expected output amount
            expected_output = amounts[-1]
            
            # Calculate minimum output with slippage tolerance using integer division
            min_output = expected_output * (100 - slippage_percentage) // 100
            
            logger.info(f"[{self.account_index}] Đầu ra dự kiến: {expected_output}, Đầu ra tối thiểu sau {slippage_percentage}% trượt giá: {min_output}")
            
            return min_output
        except Exception as e:
            logger.warning(f"[{self.account_index}] Lỗi khi tính toán đầu ra tối thiểu: {e}. Sử dụng 0 làm dự phòng.")
            return 0

    async def _swap_native_to_token(self, path):
        """Thực hiện hoán đổi ETH -> Token"""
        try:
            # Get target token info (the token we're swapping to)
            target_token_address = self.web3.web3.to_checksum_address(path[1])
            target_token_symbol, _, _ = await self._get_token_info(target_token_address, {}, "đích")
            
            # Get the current ETH balance - this returns a Balance object
            eth_balance = await self.web3.get_balance(self.wallet.address)
            # Convert the Balance object to an integer in wei
            eth_balance_wei = eth_balance.wei
            
            # Get percentage range from config, or use default if not available
            percentage_range = self.config.SWAPS.GTE.BALANCE_PERCENTAGE_TO_SWAP
            swap_percentage = random.uniform(percentage_range[0], percentage_range[1])
            
            # Calculate amount to swap (percentage of balance) using integer math
            amount_eth = int(eth_balance_wei * swap_percentage / 100)
            
            # Make sure we're not trying to swap the entire balance (leave some for gas)
            max_amount = int(eth_balance_wei * 0.9)  # Max 90% of balance
            amount_eth = min(amount_eth, max_amount)
            

            logger.info(f"[{self.account_index}] Thực hiện hoán đổi ETH -> {target_token_symbol} với {amount_eth} wei ({swap_percentage:.2f}% số dư)")
            
            gas = await self.web3.get_gas_params()
            deadline = int(time.time()) + 20 * 60

            # Get the current nonce for the address
            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)
            logger.info(f"[{self.account_index}] Sử dụng nonce {nonce} cho hoán đổi ETH -> {target_token_symbol}")

            # Ensure path addresses are checksum
            checksum_path = [self.web3.web3.to_checksum_address(addr) for addr in path]
            
            # Calculate minimum output amount with slippage tolerance
            min_output = await self._calculate_min_output(checksum_path, amount_eth, 10)

            # Build transaction without gas limit first
            tx = await self.contract.functions.swapExactETHForTokens(
                min_output,  # Use calculated min amount instead of 0
                checksum_path,
                self.wallet.address,
                deadline
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "value": amount_eth,
                    "nonce": nonce,
                    **gas,
                }
            )
            
            # Estimate gas dynamically
            tx["gas"] = await self.web3.estimate_gas(tx)
            logger.info(f"[{self.account_index}] Ước tính gas cho hoán đổi ETH -> {target_token_symbol}: {tx['gas']}")
            
            receipt = await self._sign_and_send_transaction(tx, f"Hoán đổi ETH -> {target_token_symbol}")
            return receipt and receipt.status == 1
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong _swap_native_to_token: {e}")
            return False
            
    async def _get_token_info(self, token_address, balances, position="nguồn"):
        """
        Hàm hỗ trợ để lấy ký hiệu token và số dư từ địa chỉ
        
        Args:
            token_address: Địa chỉ token để lấy thông tin
            balances: Từ điển số dư token
            position: Token này là token nguồn hay đích (cho mục đích ghi log)
            
        Returns:
            tuple: (token_symbol, token_balance, decimals)
        """
        try:
            # Ensure the address is in checksum format for comparison
            checksum_address = self.web3.web3.to_checksum_address(token_address)
            
            # Find the token symbol by comparing addresses (case-insensitive)
            token_symbol = next(symbol for symbol, data in GTE_TOKENS.items()
                                if self.web3.web3.to_checksum_address(data["address"]).lower() == checksum_address.lower())
            
            # Get token balance and decimals
            token_balance = balances.get(token_symbol, 0)
            token_decimals = GTE_TOKENS[token_symbol]["decimals"]
            
            logger.info(f"[{self.account_index}] Token {position}: {token_symbol}, số dư: {token_balance}, thập phân: {token_decimals}")
            
            return token_symbol, token_balance, token_decimals
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi khi lấy thông tin token cho {token_address}: {e}")
            raise e

    async def _swap_token_to_native(self, path, balances):
        """Thực hiện hoán đổi Token -> ETH"""
        try:
            # Get source token info
            source_token_address = self.web3.web3.to_checksum_address(path[0])
            source_token_symbol, token_balance, _ = await self._get_token_info(source_token_address, balances, "nguồn")
            
            # Ensure token_balance is an integer
            token_balance = int(token_balance)
            
            # Use 100% of the token balance for the swap
            amount_in = token_balance
            
            if amount_in == 0:
                logger.error(f"[{self.account_index}] Không đủ số dư cho {source_token_symbol} để hoán đổi")
                return False
                
            logger.info(f"[{self.account_index}] Thực hiện hoán đổi Token -> ETH với {amount_in} {source_token_symbol} (100% số dư)")
            
            gas = await self.web3.get_gas_params()
            deadline = int(time.time()) + 20 * 60
            
            # Get the current nonce for the address
            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)
            logger.info(f"[{self.account_index}] Sử dụng nonce {nonce} cho phê duyệt")
            
            # Create token contract for approval
            token_contract = self.web3.web3.eth.contract(address=source_token_address, abi=ERC20_ABI)
            
            # Build approval transaction without gas limit first
            approval_tx = await token_contract.functions.approve(
                self.web3.web3.to_checksum_address(GTE_SWAPS_CONTRACT),
                amount_in
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "nonce": nonce,
                    **gas,
                }
            )
            
            # Estimate gas for approval
            approval_tx["gas"] = await self.web3.estimate_gas(approval_tx)
            logger.info(f"[{self.account_index}] Ước tính gas cho phê duyệt token: {approval_tx['gas']}")
            
            # Sign and send approval
            approval_receipt = await self._sign_and_send_transaction(approval_tx, f"Phê duyệt {source_token_symbol}")
            if not approval_receipt or approval_receipt.status != 1:
                logger.error(f"[{self.account_index}] Giao dịch phê duyệt thất bại")
                return False
            
            # Increment nonce for the next transaction
            nonce += 1
            logger.info(f"[{self.account_index}] Sử dụng nonce {nonce} cho hoán đổi Token -> ETH")
            
            # Ensure path addresses are checksum
            checksum_path = [self.web3.web3.to_checksum_address(addr) for addr in path]
            
            # Calculate minimum output amount with slippage tolerance
            min_output = await self._calculate_min_output(checksum_path, amount_in, 10)
            
            # Build swap transaction without gas limit first
            tx = await self.contract.functions.swapExactTokensForETH(
                amount_in,
                min_output,  # Use calculated min amount instead of 0
                checksum_path,
                self.wallet.address,
                deadline
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "nonce": nonce,
                    **gas,
                }
            )
            
            # Estimate gas for swap
            tx["gas"] = await self.web3.estimate_gas(tx)
            logger.info(f"[{self.account_index}] Ước tính gas cho hoán đổi Token -> ETH: {tx['gas']}")
            
            receipt = await self._sign_and_send_transaction(tx, f"Hoán đổi {source_token_symbol} -> ETH")
            return receipt and receipt.status == 1
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong _swap_token_to_native: {e}")
            return False
            
    async def _swap_token_to_token(self, path, balances):
        """Thực hiện hoán đổi Token -> Token"""
        try:
            # Get source token info
            source_token_address = self.web3.web3.to_checksum_address(path[0])
            source_token_symbol, token_balance, _ = await self._get_token_info(source_token_address, balances, "nguồn")
            
            # Get target token info
            target_token_address = self.web3.web3.to_checksum_address(path[1])
            target_token_symbol, _, _ = await self._get_token_info(target_token_address, balances, "đích")
            
            # Ensure token_balance is an integer
            token_balance = int(token_balance)
            
            # Use 100% of the token balance for the swap
            amount_in = token_balance
            
            if amount_in == 0:
                logger.error(f"[{self.account_index}] Không đủ số dư cho {source_token_symbol} để hoán đổi")
                return False
                
            logger.info(f"[{self.account_index}] Thực hiện hoán đổi Token -> Token với {amount_in} {source_token_symbol} (100% số dư) sang {target_token_symbol}")
            
            gas = await self.web3.get_gas_params()
            deadline = int(time.time()) + 20 * 60
            
            # Get the current nonce for the address
            nonce = await self.web3.web3.eth.get_transaction_count(self.wallet.address)
            logger.info(f"[{self.account_index}] Sử dụng nonce {nonce} cho phê duyệt")
            
            # Create token contract for approval
            token_contract = self.web3.web3.eth.contract(address=source_token_address, abi=ERC20_ABI)
            
            # Build approval transaction without gas limit first
            approval_tx = await token_contract.functions.approve(
                self.web3.web3.to_checksum_address(GTE_SWAPS_CONTRACT),
                amount_in
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "nonce": nonce,
                    **gas,
                }
            )
            
            # Estimate gas for approval
            approval_tx["gas"] = await self.web3.estimate_gas(approval_tx)
            logger.info(f"[{self.account_index}] Ước tính gas cho phê duyệt token: {approval_tx['gas']}")
            
            # Sign and send approval
            approval_receipt = await self._sign_and_send_transaction(approval_tx, f"Phê duyệt {source_token_symbol}")
            if not approval_receipt or approval_receipt.status != 1:
                logger.error(f"[{self.account_index}] Giao dịch phê duyệt thất bại")
                return False
            
            # Increment nonce for the next transaction
            nonce += 1
            logger.info(f"[{self.account_index}] Sử dụng nonce {nonce} cho hoán đổi Token -> Token")
            
            # Ensure path addresses are checksum
            checksum_path = [self.web3.web3.to_checksum_address(addr) for addr in path]
            
            # Calculate minimum output amount with slippage tolerance
            min_output = await self._calculate_min_output(checksum_path, amount_in, 10)
            
            # Build swap transaction without gas limit first
            tx = await self.contract.functions.swapExactTokensForTokens(
                amount_in,
                min_output,  # Use calculated min amount instead of 0
                checksum_path,
                self.wallet.address,
                deadline
            ).build_transaction(
                {
                    "from": self.wallet.address,
                    "nonce": nonce,
                    **gas,
                }
            )
            
            # Estimate gas for swap
            tx["gas"] = await self.web3.estimate_gas(tx)
            logger.info(f"[{self.account_index}] Ước tính gas cho hoán đổi Token -> Token: {tx['gas']}")
            
            receipt = await self._sign_and_send_transaction(tx, f"Hoán đổi {source_token_symbol} -> {target_token_symbol}")
            return receipt and receipt.status == 1
            
        except Exception as e:
            logger.error(f"[{self.account_index}] Lỗi trong _swap_token_to_token: {e}")
            return False
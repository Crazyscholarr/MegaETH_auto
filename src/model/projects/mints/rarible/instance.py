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

CHAIN_ID = 6342  # From constants.py comment


class Rarible:
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

    @retry_async(default_value=False)
    async def mint_nft(self):
        try:
            # Contract address for minting
            contract_address = Web3.to_checksum_address("0xb8027dca96746f073896c45f65b720f9bd2afee7")

            # Prepare transaction
            tx = {
                "from": self.wallet.address,
                "to": contract_address,
                "value": 0,
                "data": "0x1249c58b",  # Mint function selector
                "chainId": CHAIN_ID,
                "nonce": await self.web3.web3.eth.get_transaction_count(
                    self.wallet.address
                ),
            }

            # Estimate gas
            try:
                gas_limit = await self.web3.estimate_gas(tx)
                tx["gas"] = gas_limit
            except Exception as e:
                raise e

            # Get gas price parameters
            gas_params = await self.web3.get_gas_params()
            tx.update(gas_params)

            # Sign transaction
            signed_tx = self.web3.web3.eth.account.sign_transaction(tx, self.wallet.key)

            # Send transaction
            tx_hash = await self.web3.web3.eth.send_raw_transaction(
                signed_tx.raw_transaction
            )
            tx_hex = tx_hash.hex()

            # Wait for transaction receipt
            receipt = await self.web3.web3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt["status"] == 1:
                logger.success(
                    f"{self.account_index} | NFT được đúc thành công! TX: {EXPLORER_URL_MEGAETH}{tx_hex}"
                )
                return True
            else:
                raise Exception(f"Giao dịch không thành công. Tình trạng: {receipt['status']}")

        except Exception as e:
            random_pause = random.randint(
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                self.config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.error(
                f"{self.account_index} |Lỗi đúc NFT: {e}. Đang chờ {random_pause} seconds..."
            )
            await asyncio.sleep(random_pause)
            raise

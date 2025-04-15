from eth_account import Account
from loguru import logger
import primp
import random
import asyncio

from src.model.projects.mints.rarible.instance import Rarible
from src.model.projects.swaps.rainmakr import Rainmakr
from src.model.projects.deploy.owlto.instance import Owlto
from src.model.projects.other.hopnetwork.instance import HopNetwork
from src.model.projects.deploy.easynode.instance import EasyNode
from src.model.projects.deploy.mintair.instance import Mintair
from src.model.projects.mints.omnihub.instance import OmniHub
from src.model.offchain.cex.instance import CexWithdraw
from src.model.onchain.bridges.crusty_swap.instance import CrustySwap
from src.model.projects.mints.xl_meme.instance import XLMeme
from src.model.projects.other.onchaingm.instance import OnchainGm
from src.model.projects.stakings.teko_finance import TekoFinance
from src.model.projects.swaps.bebop import Bebop
from src.model.projects.swaps.gte import GteSwaps
from src.model.projects.mints.cap_app import CapApp
from src.model.megaeth.faucet import faucet
from src.model.projects.other.gte_faucet.instance import GteFaucet
from src.model.help.stats import WalletStats
from src.model.onchain.web3_custom import Web3Custom
from src.utils.client import create_client
from src.utils.config import Config
from src.model.database.db_manager import Database
from src.utils.telegram_logger import send_telegram_message
from src.utils.reader import read_private_keys


class Start:
    def __init__(
        self,
        account_index: int,
        proxy: str,
        private_key: str,
        config: Config,
    ):
        self.account_index = account_index
        self.proxy = proxy
        self.private_key = private_key
        self.config = config

        self.session: primp.AsyncClient | None = None
        self.megaeth_web3: Web3Custom | None = None

        self.wallet = Account.from_key(self.private_key)
        self.wallet_address = self.wallet.address

    async def initialize(self):
        try:
            self.session = await create_client(
                self.proxy, self.config.OTHERS.SKIP_SSL_VERIFICATION
            )
            self.megaeth_web3 = await Web3Custom.create(
                self.account_index,
                self.config.RPCS.MEGAETH,
                self.config.OTHERS.USE_PROXY_FOR_RPC,
                self.proxy,
                self.config.OTHERS.SKIP_SSL_VERIFICATION,
            )

            return True
        except Exception as e:
            logger.error(f"{self.account_index} | Lỗi: {e}")
            return False

    async def flow(self):
        try:
            try:
                wallet_stats = WalletStats(self.config, self.megaeth_web3)
                await wallet_stats.get_wallet_stats(
                    self.private_key, self.account_index
                )
            except Exception as e:
                pass

            db = Database()
            try:
                tasks = await db.get_wallet_pending_tasks(self.private_key)
            except Exception as e:
                if "no such table: wallets" in str(e):
                    logger.error(
                        f"{self.account_index} | Cơ sở dữ liệu chưa được tạo hoặc bảng wallets không tồn tại"
                    )
                    if self.config.SETTINGS.SEND_TELEGRAM_LOGS:
                        error_message = (
                            f"⚠️ Lỗi cơ sở dữ liệu\n\n"
                            f"Tài khoản #{self.account_index}\n"
                            f"Ví: <code>{self.private_key[:6]}...{self.private_key[-4:]}</code>\n"
                            f"Lỗi: Cơ sở dữ liệu chưa được tạo hoặc bảng wallets không tồn tại"
                        )
                        await send_telegram_message(self.config, error_message)
                    return False
                else:
                    logger.error(
                        f"{self.account_index} | Lỗi khi lấy nhiệm vụ từ cơ sở dữ liệu: {e}"
                    )
                    raise

            if not tasks:
                logger.warning(
                    f"{self.account_index} | Không tìm thấy nhiệm vụ đang chờ xử lý trong cơ sở dữ liệu cho ví này. Thoát..."
                )
                if self.megaeth_web3:
                    await self.megaeth_web3.cleanup()
                return True

            task_plan_msg = [f"{i+1}. {task['name']}" for i, task in enumerate(tasks)]
            logger.info(
                f"{self.account_index} | Kế hoạch thực hiện nhiệm vụ: {' | '.join(task_plan_msg)}"
            )

            completed_tasks = []
            failed_tasks = []

            # Thực hiện các nhiệm vụ
            for task in tasks:
                task_name = task["name"]

                if task_name == "skip":
                    logger.info(f"{self.account_index} | Bỏ qua nhiệm vụ: {task_name}")
                    continue

                logger.info(f"{self.account_index} | Đang thực hiện nhiệm vụ: {task_name}")

                success = await self.execute_task(task_name)

                if success:
                    await db.update_task_status(
                        self.private_key, task_name, "completed"
                    )
                    completed_tasks.append(task_name)
                    await self.sleep(task_name)
                else:
                    failed_tasks.append(task_name)
                    if not self.config.FLOW.SKIP_FAILED_TASKS:
                        logger.error(
                            f"{self.account_index} | Không hoàn thành nhiệm vụ {task_name}. Dừng thực thi ví."
                        )
                        break
                    else:
                        logger.warning(
                            f"{self.account_index} | Không hoàn thành nhiệm vụ {task_name}. Chuyển sang nhiệm vụ tiếp theo."
                        )
                        await self.sleep(task_name)

            # Gửi tin nhắn Telegram chỉ khi hoàn thành toàn bộ công việc
            if self.config.SETTINGS.SEND_TELEGRAM_LOGS:
                message = (
                    f"🐰 Báo cáo Bot MegaETH Crazyscholar\n\n"
                    f"💳 Ví: {self.account_index} | <code>{self.private_key[:6]}...{self.private_key[-4:]}</code>\n\n"
                )

                if completed_tasks:
                    message += f"✅ Nhiệm vụ đã hoàn thành:\n"
                    for i, task in enumerate(completed_tasks, 1):
                        message += f"{i}. {task}\n"
                    message += "\n"

                if failed_tasks:
                    message += f"❌ Nhiệm vụ thất bại:\n"
                    for i, task in enumerate(failed_tasks, 1):
                        message += f"{i}. {task}\n"
                    message += "\n"

                total_tasks = len(tasks)
                completed_count = len(completed_tasks)
                message += (
                    f"📊 Thống kê:\n"
                    f"Tổng số nhiệm vụ: {total_tasks}\n"
                    f"Đã hoàn thành: {completed_count}\n"
                    f"Thất bại: {len(failed_tasks)}\n"
                    f"Tỷ lệ thành công: {(completed_count/total_tasks)*100:.1f}%\n\n"
                    f"⚙️ Cài đặt:\n"
                    f"Bỏ qua nhiệm vụ thất bại: {'Có' if self.config.FLOW.SKIP_FAILED_TASKS else 'Không'}\n"
                )

                await send_telegram_message(self.config, message)

            return len(failed_tasks) == 0

        except Exception as e:
            logger.error(f"{self.account_index} | Lỗi: {e}")

            if self.config.SETTINGS.SEND_TELEGRAM_LOGS:
                error_message = (
                    f"⚠️ Báo cáo lỗi\n\n"
                    f"Tài khoản #{self.account_index}\n"
                    f"Ví: <code>{self.private_key[:6]}...{self.private_key[-4:]}</code>\n"
                    f"Lỗi: {str(e)}"
                )
                await send_telegram_message(self.config, error_message)

            return False
        finally:
            # Dọn dẹp tài nguyên
            try:
                if self.megaeth_web3:
                    await self.megaeth_web3.cleanup()
                logger.info(f"{self.account_index} | Tất cả phiên đã đóng thành công")
            except Exception as e:
                logger.error(f"{self.account_index} | Lỗi trong quá trình dọn dẹp: {e}")

    async def execute_task(self, task):
        """Thực thi một nhiệm vụ đơn lẻ"""
        task = task.lower()

        if task == "faucet":
            return await faucet(
                self.session,
                self.account_index,
                self.config,
                self.wallet,
                self.proxy,
            )

        if task == "cap_app":
            cap_app = CapApp(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await cap_app.mint_cUSD()

        if task == "bebop":
            bebop = Bebop(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.proxy,
                self.private_key,
            )
            return await bebop.swaps()
        if task == "gte_swaps":
            gte = GteSwaps(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.proxy,
                self.private_key,
            )
            return await gte.execute_swap()

        if task == "teko_finance":
            teko_finance = TekoFinance(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.proxy,
                self.private_key,
            )
            return await teko_finance.stake()
        
        if task == "teko_faucet":
            teko_finance = TekoFinance(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.proxy,
                self.private_key,
            )
            return await teko_finance.faucet()
        
        if task == "onchain_gm":
            onchain_gm = OnchainGm(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await onchain_gm.GM()

        if task == "crusty_refuel":
            crusty_swap = CrustySwap(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.proxy,
                self.private_key,
            )
            return await crusty_swap.refuel()
        
        if task == "crusty_refuel_from_one_to_all":
            private_keys = read_private_keys("data/private_keys.txt")

            crusty_swap = CrustySwap(
                1,
                self.session,
                self.megaeth_web3,
                self.config,
                Account.from_key(private_keys[0]),
                self.proxy,
                private_keys[0],
            )
            private_keys = private_keys[1:]
            return await crusty_swap.refuel_from_one_to_all(private_keys)
        
        elif task == "cex_withdrawal":
            cex_withdrawal = CexWithdraw(
                self.account_index,
                self.private_key,
                self.config,
            )
            return await cex_withdrawal.withdraw()
        
        if task == "xl_meme":
            xl_meme = XLMeme(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await xl_meme.buy_meme()

        if task == "gte_faucet":
            gte_faucet = GteFaucet(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await gte_faucet.faucet()

        
        if task == "omnihub":
            omnihub = OmniHub(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await omnihub.mint()
        
        if task == "mintair":
            mintair = Mintair(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await mintair.deploy_timer_contract()
        
        if task == "easynode":
            easynode = EasyNode(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await easynode.deploy_contract()
        
        if task == "hopnetwork":
            hopnetwork = HopNetwork(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.private_key,
            )
            return await hopnetwork.waitlist()
        
        if task == "owlto":
            owlto = Owlto(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await owlto.deploy_contract()
        
        if task == "rainmakr":
            rainmakr = Rainmakr(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
                self.private_key,
            )
            return await rainmakr.buy_meme()
        
        if task == "rarible":
            rarible = Rarible(
                self.account_index,
                self.session,
                self.megaeth_web3,
                self.config,
                self.wallet,
            )
            return await rarible.mint_nft()
        
        logger.error(f"{self.account_index} | Nhiệm vụ {task} không tìm thấy")
        return False

    async def sleep(self, task_name: str):
        """Tạo khoảng dừng ngẫu nhiên giữa các hành động"""
        pause = random.randint(
            self.config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACTIONS[0],
            self.config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACTIONS[1],
        )
        logger.info(
            f"{self.account_index} | Nghỉ {pause} giây sau nhiệm vụ {task_name}"
        )
        await asyncio.sleep(pause)
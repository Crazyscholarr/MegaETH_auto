import json
from typing import Optional, List, Dict
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from loguru import logger

Base = declarative_base()


class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True)
    private_key = Column(String, unique=True)
    proxy = Column(String, nullable=True)
    status = Column(String)  # Trạng thái chung của ví (pending/completed)
    tasks = Column(String)  # Chuỗi JSON chứa các nhiệm vụ


class Database:
    def __init__(self):
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///data/accounts.db",  # Đường dẫn và tên cơ sở dữ liệu
            echo=False,
        )
        self.session = sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self):
        """Khởi tạo cơ sở dữ liệu"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.success("Khởi tạo cơ sở dữ liệu thành công")

    async def clear_database(self):
        """Xóa toàn bộ cơ sở dữ liệu"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        logger.success("Đã xóa cơ sở dữ liệu thành công")

    async def add_wallet(
        self,
        private_key: str,
        proxy: Optional[str] = None,
        tasks_list: Optional[List[str]] = None,
    ) -> None:
        """
        Thêm ví mới

        :param private_key: Khóa riêng của ví
        :param proxy: Proxy (tùy chọn)
        :param tasks_list: Danh sách tên nhiệm vụ
        """
        # Chuyển đổi danh sách nhiệm vụ sang định dạng cho cơ sở dữ liệu
        tasks = []
        for task in tasks_list or []:
            tasks.append(
                {
                    "name": task,
                    "status": "pending",
                    "index": len(tasks) + 1,  # Thêm chỉ số để giữ thứ tự
                }
            )

        async with self.session() as session:
            wallet = Wallet(
                private_key=private_key,
                proxy=proxy,
                status="pending",
                tasks=json.dumps(tasks),
            )
            session.add(wallet)
            await session.commit()
            logger.success(f"Đã thêm ví {private_key[:4]}...{private_key[-4:]}")

    async def update_task_status(
        self, private_key: str, task_name: str, new_status: str
    ) -> None:
        """
        Cập nhật trạng thái của một nhiệm vụ cụ thể

        :param private_key: Khóa riêng của ví
        :param task_name: Tên nhiệm vụ
        :param new_status: Trạng thái mới (pending/completed)
        """
        async with self.session() as session:
            wallet = await self._get_wallet(session, private_key)
            if not wallet:
                logger.error(f"Không tìm thấy ví {private_key[:4]}...{private_key[-4:]}")
                return

            tasks = json.loads(wallet.tasks)
            for task in tasks:
                if task["name"] == task_name:
                    task["status"] = new_status
                    break

            wallet.tasks = json.dumps(tasks)

            # Kiểm tra xem tất cả nhiệm vụ đã hoàn thành chưa
            if all(task["status"] == "completed" for task in tasks):
                wallet.status = "completed"

            await session.commit()
            logger.info(
                f"Đã cập nhật nhiệm vụ {task_name} thành {new_status} cho ví {private_key[:4]}...{private_key[-4:]}"
            )

    async def clear_wallet_tasks(self, private_key: str) -> None:
        """
        Xóa tất cả nhiệm vụ của ví

        :param private_key: Khóa riêng của ví
        """
        async with self.session() as session:
            wallet = await self._get_wallet(session, private_key)
            if not wallet:
                return

            wallet.tasks = json.dumps([])
            wallet.status = "pending"
            await session.commit()
            logger.info(
                f"Đã xóa tất cả nhiệm vụ cho ví {private_key[:4]}...{private_key[-4:]}"
            )

    async def update_wallet_proxy(self, private_key: str, new_proxy: str) -> None:
        """
        Cập nhật proxy của ví

        :param private_key: Khóa riêng của ví
        :param new_proxy: Proxy mới
        """
        async with self.session() as session:
            wallet = await self._get_wallet(session, private_key)
            if not wallet:
                return

            wallet.proxy = new_proxy
            await session.commit()
            logger.info(
                f"Đã cập nhật proxy cho ví {private_key[:4]}...{private_key[-4:]}"
            )

    async def get_wallet_tasks(self, private_key: str) -> List[Dict]:
        """
        Lấy tất cả nhiệm vụ của ví

        :param private_key: Khóa riêng của ví
        :return: Danh sách nhiệm vụ với trạng thái của chúng
        """
        async with self.session() as session:
            wallet = await self._get_wallet(session, private_key)
            if not wallet:
                return []
            return json.loads(wallet.tasks)

    async def get_pending_tasks(self, private_key: str) -> List[str]:
        """
        Lấy tất cả nhiệm vụ chưa hoàn thành của ví

        :param private_key: Khóa riêng của ví
        :return: Danh sách tên các nhiệm vụ chưa hoàn thành
        """
        tasks = await self.get_wallet_tasks(private_key)
        return [task["name"] for task in tasks if task["status"] == "pending"]

    async def get_completed_tasks(self, private_key: str) -> List[str]:
        """
        Lấy tất cả nhiệm vụ đã hoàn thành của ví

        :param private_key: Khóa riêng của ví
        :return: Danh sách tên các nhiệm vụ đã hoàn thành
        """
        tasks = await self.get_wallet_tasks(private_key)
        return [task["name"] for task in tasks if task["status"] == "completed"]

    async def get_uncompleted_wallets(self) -> List[Dict]:
        """
        Lấy danh sách tất cả ví có nhiệm vụ chưa hoàn thành

        :return: Danh sách ví với dữ liệu của chúng
        """
        async with self.session() as session:
            from sqlalchemy import select

            query = select(Wallet).filter_by(status="pending")
            result = await session.execute(query)
            wallets = result.scalars().all()

            # Chuyển đổi thành danh sách từ điển để sử dụng dễ dàng
            return [
                {
                    "private_key": wallet.private_key,
                    "proxy": wallet.proxy,
                    "status": wallet.status,
                    "tasks": json.loads(wallet.tasks),
                }
                for wallet in wallets
            ]

    async def get_wallet_status(self, private_key: str) -> Optional[str]:
        """
        Lấy trạng thái của ví

        :param private_key: Khóa riêng của ví
        :return: Trạng thái của ví hoặc None nếu ví không tồn tại
        """
        async with self.session() as session:
            wallet = await self._get_wallet(session, private_key)
            return wallet.status if wallet else None

    async def _get_wallet(
        self, session: AsyncSession, private_key: str
    ) -> Optional[Wallet]:
        """Phương thức nội bộ để lấy ví theo private_key"""
        from sqlalchemy import select

        result = await session.execute(
            select(Wallet).filter_by(private_key=private_key)
        )
        return result.scalar_one_or_none()

    async def add_tasks_to_wallet(self, private_key: str, new_tasks: List[str]) -> None:
        """
        Thêm nhiệm vụ mới vào ví hiện có

        :param private_key: Khóa riêng của ví
        :param new_tasks: Danh sách nhiệm vụ mới để thêm
        """
        async with self.session() as session:
            wallet = await self._get_wallet(session, private_key)
            if not wallet:
                return

            current_tasks = json.loads(wallet.tasks)
            current_task_names = {task["name"] for task in current_tasks}

            # Chỉ thêm các nhiệm vụ mới
            for task in new_tasks:
                if task not in current_task_names:
                    current_tasks.append({"name": task, "status": "pending"})

            wallet.tasks = json.dumps(current_tasks)
            wallet.status = (
                "pending"  # Nếu thêm nhiệm vụ mới, trạng thái trở lại pending
            )
            await session.commit()
            logger.info(
                f"Đã thêm nhiệm vụ mới cho ví {private_key[:4]}...{private_key[-4:]}"
            )

    async def get_completed_wallets_count(self) -> int:
        """
        Lấy số lượng ví đã hoàn thành tất cả nhiệm vụ

        :return: Số lượng ví đã hoàn thành
        """
        async with self.session() as session:
            from sqlalchemy import select, func

            query = (
                select(func.count()).select_from(Wallet).filter_by(status="completed")
            )
            result = await session.execute(query)
            return result.scalar()

    async def get_total_wallets_count(self) -> int:
        """
        Lấy tổng số ví trong cơ sở dữ liệu

        :return: Tổng số ví
        """
        async with self.session() as session:
            from sqlalchemy import select, func

            query = select(func.count()).select_from(Wallet)
            result = await session.execute(query)
            return result.scalar()

    async def get_wallet_completed_tasks(self, private_key: str) -> List[str]:
        """
        Lấy danh sách nhiệm vụ đã hoàn thành của ví

        :param private_key: Khóa riêng của ví
        :return: Danh sách tên nhiệm vụ đã hoàn thành
        """
        tasks = await self.get_wallet_tasks(private_key)
        return [task["name"] for task in tasks if task["status"] == "completed"]

    async def get_wallet_pending_tasks(self, private_key: str) -> List[Dict]:
        """
        Lấy danh sách nhiệm vụ chưa hoàn thành của ví

        :param private_key: Khóa riêng của ví
        :return: Danh sách nhiệm vụ với chỉ số và trạng thái của chúng
        """
        tasks = await self.get_wallet_tasks(private_key)
        return [task for task in tasks if task["status"] == "pending"]

    async def get_completed_wallets(self) -> List[Dict]:
        """
        Lấy danh sách tất cả ví đã hoàn thành nhiệm vụ

        :return: Danh sách ví với dữ liệu của chúng
        """
        async with self.session() as session:
            from sqlalchemy import select

            query = select(Wallet).filter_by(status="completed")
            result = await session.execute(query)
            wallets = result.scalars().all()

            return [
                {
                    "private_key": wallet.private_key,
                    "proxy": wallet.proxy,
                    "status": wallet.status,
                    "tasks": json.loads(wallet.tasks),
                }
                for wallet in wallets
            ]

    async def get_wallet_tasks_info(self, private_key: str) -> Dict:
        """
        Lấy thông tin đầy đủ về nhiệm vụ của ví

        :param private_key: Khóa riêng của ví
        :return: Từ điển chứa thông tin về nhiệm vụ
        """
        tasks = await self.get_wallet_tasks(private_key)
        completed = [task["name"] for task in tasks if task["status"] == "completed"]
        pending = [task["name"] for task in tasks if task["status"] == "pending"]

        return {
            "total_tasks": len(tasks),
            "completed_tasks": completed,
            "pending_tasks": pending,
            "completed_count": len(completed),
            "pending_count": len(pending),
        }

    async def add_wallets_batch(
        self,
        wallet_data: List[Dict],
    ) -> int:
        """
        Thêm ví hàng loạt vào cơ sở dữ liệu

        :param wallet_data: Danh sách từ điển chứa dữ liệu ví
                            (private_key, proxy, tasks_list)
        :return: Số lượng ví được thêm thành công
        """
        added_count = 0
        async with self.session() as session:
            try:
                wallets_to_add = []

                for data in wallet_data:
                    private_key = data["private_key"]
                    proxy = data.get("proxy")
                    tasks_list = data.get("tasks_list", [])

                    # Chuyển đổi danh sách nhiệm vụ sang định dạng cho cơ sở dữ liệu
                    tasks = []
                    for task in tasks_list:
                        tasks.append(
                            {
                                "name": task,
                                "status": "pending",
                                "index": len(tasks)
                                + 1,  # Thêm chỉ số để giữ thứ tự
                            }
                        )

                    wallet = Wallet(
                        private_key=private_key,
                        proxy=proxy,
                        status="pending",
                        tasks=json.dumps(tasks),
                    )
                    wallets_to_add.append(wallet)

                session.add_all(wallets_to_add)
                await session.commit()
                added_count = len(wallets_to_add)
                logger.success(f"Đã thêm {added_count} ví ở chế độ hàng loạt")

            except Exception as e:
                await session.rollback()
                logger.error(f"Lỗi khi thêm ví hàng loạt: {e}")

        return added_count

    async def update_wallets_tasks_batch(self, wallet_tasks_data: List[Dict]) -> int:
        """
        Cập nhật nhiệm vụ hàng loạt cho nhiều ví

        :param wallet_tasks_data: Danh sách từ điển chứa dữ liệu {private_key, tasks_list}
        :return: Số lượng ví được cập nhật thành công
        """
        updated_count = 0
        async with self.session() as session:
            try:
                from sqlalchemy import select

                for data in wallet_tasks_data:
                    private_key = data["private_key"]
                    new_tasks = data["tasks_list"]

                    # Lấy ví
                    result = await session.execute(
                        select(Wallet).filter_by(private_key=private_key)
                    )
                    wallet = result.scalar_one_or_none()

                    if not wallet:
                        logger.warning(
                            f"Không tìm thấy ví {private_key[:4]}...{private_key[-4:]} để cập nhật nhiệm vụ hàng loạt"
                        )
                        continue

                    # Chuẩn bị nhiệm vụ mới
                    tasks = []
                    for task in new_tasks:
                        tasks.append(
                            {"name": task, "status": "pending", "index": len(tasks) + 1}
                        )

                    # Cập nhật nhiệm vụ và trạng thái
                    wallet.tasks = json.dumps(tasks)
                    wallet.status = "pending"
                    updated_count += 1

                # Lưu tất cả thay đổi bằng một commit
                await session.commit()
                logger.success(
                    f"Đã cập nhật nhiệm vụ cho {updated_count} ví ở chế độ hàng loạt"
                )

            except Exception as e:
                await session.rollback()
                logger.error(f"Lỗi khi cập nhật nhiệm vụ ví hàng loạt: {e}")

        return updated_count
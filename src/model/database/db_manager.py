import asyncio
import json
import random
from typing import List
from tabulate import tabulate
from loguru import logger

from src.model.database.instance import Database
from src.utils.config import get_config
from src.utils.reader import read_private_keys
from src.utils.proxy_parser import Proxy


async def show_database_menu():
    while True:
        print("\nCác tùy chọn quản lý cơ sở dữ liệu:\n")
        print("[1] 🗑  Tạo lại/Đặt lại cơ sở dữ liệu")
        print("[2] ➕ Tạo mới nhiệm vụ cho các ví đã hoàn thành")
        print("[3] 📊 Hiển thị nội dung cơ sở dữ liệu")
        print("[4] 🔄 Tái tạo nhiệm vụ cho tất cả ví")
        print("[5] 📝 Thêm ví vào cơ sở dữ liệu")
        print("[6] 👋 Thoát")
        print()

        try:
            choice = input("Nhập tùy chọn (1-6): ").strip()

            if choice == "1":
                await reset_database()
            elif choice == "2":
                await regenerate_tasks_for_completed()
            elif choice == "3":
                await show_database_contents()
            elif choice == "4":
                await regenerate_tasks_for_all()
            elif choice == "5":
                await add_new_wallets()
            elif choice == "6":
                print("\nThoát khỏi quản lý cơ sở dữ liệu...")
                break
            else:
                logger.error("Tùy chọn không hợp lệ. Vui lòng nhập số từ 1 đến 6.")

        except Exception as e:
            logger.error(f"Lỗi trong quản lý cơ sở dữ liệu: {e}")
            await asyncio.sleep(1)


async def reset_database():
    """Tạo mới hoặc đặt lại cơ sở dữ liệu hiện có"""
    print("\n⚠️ CẢNH BÁO: Thao tác này sẽ xóa toàn bộ dữ liệu hiện có.")
    print("[1] Có")
    print("[2] Không")

    confirmation = input("\nNhập lựa chọn của bạn (1-2): ").strip()

    if confirmation != "1":
        logger.info("Đã hủy đặt lại cơ sở dữ liệu")
        return

    try:
        db = Database()
        await db.clear_database()
        await db.init_db()

        # Tạo nhiệm vụ cho cơ sở dữ liệu mới
        config = get_config()
        private_keys = read_private_keys("data/private_keys.txt")

        # Đọc proxy
        try:
            proxy_objects = Proxy.from_file("data/proxies.txt")
            proxies = [proxy.get_default_format() for proxy in proxy_objects]
            if len(proxies) == 0:
                logger.error("Không tìm thấy proxy trong data/proxies.txt")
                return
        except Exception as e:
            logger.error(f"Không thể tải proxy: {e}")
            return

        # Chuẩn bị dữ liệu để thêm ví hàng loạt
        wallet_data = []
        for i, private_key in enumerate(private_keys):
            proxy = proxies[i % len(proxies)]

            # Tạo danh sách nhiệm vụ mới cho mỗi ví
            tasks = generate_tasks_from_config(config)

            if not tasks:
                logger.error(
                    f"Không tạo được nhiệm vụ cho ví {private_key[:4]}...{private_key[-4:]}"
                )
                continue

            wallet_data.append(
                {"private_key": private_key, "proxy": proxy, "tasks_list": tasks}
            )

        # Thêm ví hàng loạt
        if wallet_data:
            added_count = await db.add_wallets_batch(wallet_data)
            logger.success(
                f"Cơ sở dữ liệu đã được đặt lại và khởi tạo với {added_count} ví ở chế độ hàng loạt!"
            )
        else:
            logger.warning("Không có dữ liệu ví nào được chuẩn bị để thêm vào cơ sở dữ liệu")

    except Exception as e:
        logger.error(f"Lỗi khi đặt lại cơ sở dữ liệu: {e}")


def generate_tasks_from_config(config) -> List[str]:
    """Tạo danh sách nhiệm vụ từ cấu hình, tương tự định dạng trong start.py"""
    planned_tasks = []

    # Lấy danh sách nhiệm vụ từ cấu hình
    for task_name in config.FLOW.TASKS:
        # Nhập tasks.py để lấy danh sách nhiệm vụ cụ thể
        import tasks

        # Lấy danh sách các nhiệm vụ con cho nhiệm vụ hiện tại
        task_list = getattr(tasks, task_name)

        # Xử lý từng nhiệm vụ con
        for task_item in task_list:
            if isinstance(task_item, list):
                # Đối với nhiệm vụ trong [], chọn ngẫu nhiên một nhiệm vụ
                selected_task = random.choice(task_item)
                planned_tasks.append(selected_task)
            elif isinstance(task_item, tuple):
                # Đối với nhiệm vụ trong (), xáo trộn tất cả
                shuffled_tasks = list(task_item)
                random.shuffle(shuffled_tasks)
                # Thêm tất cả nhiệm vụ từ tuple
                planned_tasks.extend(shuffled_tasks)
            else:
                # Nhiệm vụ thông thường
                planned_tasks.append(task_item)

    logger.info(f"Đã tạo chuỗi nhiệm vụ: {planned_tasks}")
    return planned_tasks


async def regenerate_tasks_for_completed():
    """Tạo mới nhiệm vụ cho các ví đã hoàn thành"""
    try:
        db = Database()
        config = get_config()

        # Lấy danh sách các ví đã hoàn thành
        completed_wallets = await db.get_completed_wallets()

        if not completed_wallets:
            logger.info("Không tìm thấy ví nào đã hoàn thành")
            return

        print("\n[1] Có")
        print("[2] Không")
        confirmation = input(
            "\nThao tác này sẽ thay thế tất cả nhiệm vụ cho các ví đã hoàn thành. Tiếp tục? (1-2): "
        ).strip()

        if confirmation != "1":
            logger.info("Đã hủy tái tạo nhiệm vụ")
            return

        # Chuẩn bị dữ liệu để cập nhật hàng loạt
        wallet_tasks_data = []

        # Tạo danh sách nhiệm vụ mới cho mỗi ví đã hoàn thành
        for wallet in completed_wallets:
            # Tạo danh sách nhiệm vụ mới
            new_tasks = generate_tasks_from_config(config)

            wallet_tasks_data.append(
                {"private_key": wallet["private_key"], "tasks_list": new_tasks}
            )

        # Cập nhật nhiệm vụ cho tất cả ví hàng loạt
        updated_count = await db.update_wallets_tasks_batch(wallet_tasks_data)
        logger.success(
            f"Đã tạo nhiệm vụ mới cho {updated_count} ví đã hoàn thành ở chế độ hàng loạt"
        )

    except Exception as e:
        logger.error(f"Lỗi khi tái tạo nhiệm vụ: {e}")


async def regenerate_tasks_for_all():
    """Tạo mới nhiệm vụ cho tất cả ví"""
    try:
        db = Database()
        config = get_config()

        # Lấy tất cả ví
        completed_wallets = await db.get_completed_wallets()
        uncompleted_wallets = await db.get_uncompleted_wallets()
        all_wallets = completed_wallets + uncompleted_wallets

        if not all_wallets:
            logger.info("Không tìm thấy ví nào trong cơ sở dữ liệu")
            return

        print("\n[1] Có")
        print("[2] Không")
        confirmation = input(
            "\nThao tác này sẽ thay thế tất cả nhiệm vụ cho TẤT CẢ ví. Tiếp tục? (1-2): "
        ).strip()

        if confirmation != "1":
            logger.info("Đã hủy tái tạo nhiệm vụ")
            return

        # Chuẩn bị dữ liệu để cập nhật hàng loạt
        wallet_tasks_data = []

        # Tạo danh sách nhiệm vụ mới cho mỗi ví
        for wallet in all_wallets:
            # Tạo danh sách nhiệm vụ mới
            new_tasks = generate_tasks_from_config(config)

            wallet_tasks_data.append(
                {"private_key": wallet["private_key"], "tasks_list": new_tasks}
            )

        # Cập nhật nhiệm vụ cho tất cả ví hàng loạt
        updated_count = await db.update_wallets_tasks_batch(wallet_tasks_data)
        logger.success(
            f"Đã tạo nhiệm vụ mới cho tất cả {updated_count} ví ở chế độ hàng loạt"
        )

    except Exception as e:
        logger.error(f"Lỗi khi tái tạo nhiệm vụ cho tất cả ví: {e}")


async def show_database_contents():
    """Hiển thị nội dung cơ sở dữ liệu dưới dạng bảng"""
    try:
        db = Database()

        # Lấy tất cả ví
        completed_wallets = await db.get_completed_wallets()
        uncompleted_wallets = await db.get_uncompleted_wallets()
        all_wallets = completed_wallets + uncompleted_wallets

        if not all_wallets:
            logger.info("Cơ sở dữ liệu trống")
            return

        # Chuẩn bị dữ liệu cho bảng
        table_data = []
        for wallet in all_wallets:
            tasks = (
                json.loads(wallet["tasks"])
                if isinstance(wallet["tasks"], str)
                else wallet["tasks"]
            )

            # Định dạng danh sách nhiệm vụ
            completed_tasks = [
                task["name"] for task in tasks if task["status"] == "completed"
            ]
            pending_tasks = [
                task["name"] for task in tasks if task["status"] == "pending"
            ]

            # Rút ngắn khóa riêng để hiển thị
            short_key = f"{wallet['private_key'][:6]}...{wallet['private_key'][-4:]}"

            # Định dạng proxy để hiển thị
            proxy = wallet["proxy"]
            if proxy and len(proxy) > 20:
                proxy = f"{proxy[:17]}..."

            table_data.append(
                [
                    short_key,
                    proxy or "Không có proxy",
                    wallet["status"],
                    f"{len(completed_tasks)}/{len(tasks)}",
                    ", ".join(completed_tasks) or "Không có",
                    ", ".join(pending_tasks) or "Không có",
                ]
            )

        # Tạo bảng
        headers = [
            "Ví",
            "Proxy",
            "Trạng thái",
            "Tiến độ",
            "Nhiệm vụ đã hoàn thành",
            "Nhiệm vụ đang chờ",
        ]
        table = tabulate(table_data, headers=headers, tablefmt="grid", stralign="left")

        # Hiển thị thống kê
        total_wallets = len(all_wallets)
        completed_count = len(completed_wallets)
        print(f"\nThống kê cơ sở dữ liệu:")
        print(f"Tổng số ví: {total_wallets}")
        print(f"Ví đã hoàn thành: {completed_count}")
        print(f"Ví đang chờ: {total_wallets - completed_count}")

        # Hiển thị bảng
        print("\nNội dung cơ sở dữ liệu:")
        print(table)

    except Exception as e:
        logger.error(f"Lỗi khi hiển thị nội dung cơ sở dữ liệu: {e}")


async def add_new_wallets():
    """Thêm ví mới từ tệp vào cơ sở dữ liệu"""
    try:
        db = Database()
        config = get_config()

        # Đọc tất cả khóa riêng từ tệp
        private_keys = read_private_keys("data/private_keys.txt")

        # Đọc proxy
        try:
            proxy_objects = Proxy.from_file("data/proxies.txt")
            proxies = [proxy.get_default_format() for proxy in proxy_objects]
            if len(proxies) == 0:
                logger.error("Không tìm thấy proxy trong data/proxies.txt")
                return
        except Exception as e:
            logger.error(f"Không thể tải proxy: {e}")
            return

        # Lấy các ví hiện có từ cơ sở dữ liệu
        completed_wallets = await db.get_completed_wallets()
        uncompleted_wallets = await db.get_uncompleted_wallets()
        existing_wallets = {
            w["private_key"] for w in (completed_wallets + uncompleted_wallets)
        }

        # Tìm các ví mới
        new_wallets = [pk for pk in private_keys if pk not in existing_wallets]

        if not new_wallets:
            logger.info("Không tìm thấy ví mới nào để thêm")
            return

        print(f"\nTìm thấy {len(new_wallets)} ví mới để thêm vào cơ sở dữ liệu")
        print("\n[1] Có")
        print("[2] Không")
        confirmation = input("\nBạn có muốn thêm các ví này không? (1-2): ").strip()

        if confirmation != "1":
            logger.info("Đã hủy thêm ví mới")
            return

        # Chuẩn bị dữ liệu để thêm hàng loạt
        wallet_data = []
        for i, private_key in enumerate(new_wallets):
            proxy = proxies[i % len(proxies)]
            tasks = generate_tasks_from_config(config)

            if not tasks:
                logger.error(
                    f"Không tạo được nhiệm vụ cho ví {private_key[:4]}...{private_key[-4:]}"
                )
                continue

            wallet_data.append(
                {"private_key": private_key, "proxy": proxy, "tasks_list": tasks}
            )

        # Thêm ví hàng loạt
        if wallet_data:
            added_count = await db.add_wallets_batch(wallet_data)
            logger.success(
                f"Đã thêm thành công {added_count} ví mới vào cơ sở dữ liệu ở chế độ hàng loạt!"
            )
        else:
            logger.warning("Không có dữ liệu ví nào được chuẩn bị để thêm vào cơ sở dữ liệu")

    except Exception as e:
        logger.error(f"Lỗi khi thêm ví mới: {e}")
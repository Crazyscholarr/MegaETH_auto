import asyncio
import random
from loguru import logger


import src.utils
from src.utils.output import show_dev_info, show_logo
from src.utils.proxy_parser import Proxy
import src.model
from src.utils.statistics import print_wallets_stats
from src.utils.check_github_version import check_version
from src.utils.logs import ProgressTracker, create_progress_tracker
from src.utils.config_browser import run

async def start():
    async def launch_wrapper(index, proxy, private_key):
        async with semaphore:
            await account_flow(
                index,
                proxy,
                private_key,
                config,
                lock,
                progress_tracker,
            )

    try:
        await check_version("0xStarLabs", "StarLabs-MegaETH")
    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Không thể kiểm tra phiên bản: {e}")
        logger.info("Tiếp tục với phiên bản hiện tại\n")

    print("\nCác tùy chọn có sẵn:\n")
    print("[1] ⭐️ Bắt đầu farming")
    print("[2] 🔧 Chỉnh sửa cấu hình")
    print("[3] 💾 Hành động cơ sở dữ liệu")
    print("[4] 👋 Thoát")
    print()

    try:
        choice = input("Nhập tùy chọn (1-4): ").strip()
    except Exception as e:
        logger.error(f"Lỗi nhập liệu: {e}")
        return

    if choice == "4" or not choice:
        return
    elif choice == "2":
        run()
        return
    elif choice == "1":
        pass
    elif choice == "3":
        from src.model.database.db_manager import show_database_menu

        await show_database_menu()
        await start()
    else:
        logger.error(f"Tùy chọn không hợp lệ: {choice}")
        return

    config = src.utils.get_config()

    # Tải proxy bằng cách sử dụng proxy parser
    try:
        proxy_objects = Proxy.from_file("data/proxies.txt")
        proxies = [proxy.get_default_format() for proxy in proxy_objects]
        if len(proxies) == 0:
            logger.error("Không tìm thấy proxy trong data/proxies.txt")
            return
    except Exception as e:
        logger.error(f"Không thể tải proxy: {e}")
        return

    private_keys = src.utils.read_private_keys("data/private_keys.txt")

    # Xác định phạm vi tài khoản
    start_index = config.SETTINGS.ACCOUNTS_RANGE[0]
    end_index = config.SETTINGS.ACCOUNTS_RANGE[1]

    # Nếu cả hai đều là 0, kiểm tra EXACT_ACCOUNTS_TO_USE
    if start_index == 0 and end_index == 0:
        if config.SETTINGS.EXACT_ACCOUNTS_TO_USE:
            # Chuyển đổi số tài khoản thành chỉ số (số - 1)
            selected_indices = [i - 1 for i in config.SETTINGS.EXACT_ACCOUNTS_TO_USE]
            accounts_to_process = [private_keys[i] for i in selected_indices]
            logger.info(
                f"Sử dụng các tài khoản cụ thể: {config.SETTINGS.EXACT_ACCOUNTS_TO_USE}"
            )

            # Để tương thích với phần còn lại của mã
            start_index = min(config.SETTINGS.EXACT_ACCOUNTS_TO_USE)
            end_index = max(config.SETTINGS.EXACT_ACCOUNTS_TO_USE)
        else:
            # Nếu danh sách rỗng, lấy tất cả tài khoản như trước
            accounts_to_process = private_keys
            start_index = 1
            end_index = len(private_keys)
    else:
        # Python slice không bao gồm phần tử cuối, vì vậy +1
        accounts_to_process = private_keys[start_index - 1 : end_index]

    threads = config.SETTINGS.THREADS

    # Chuẩn bị proxy cho các tài khoản đã chọn
    cycled_proxies = [
        proxies[i % len(proxies)] for i in range(len(accounts_to_process))
    ]

    # Tạo danh sách chỉ số
    indices = list(range(len(accounts_to_process)))

    # Xáo trộn chỉ số chỉ khi SHUFFLE_WALLETS được bật
    if config.SETTINGS.SHUFFLE_WALLETS:
        random.shuffle(indices)
        shuffle_status = "ngẫu nhiên"
    else:
        shuffle_status = "tuần tự"

    # Tạo chuỗi với thứ tự tài khoản
    if config.SETTINGS.EXACT_ACCOUNTS_TO_USE:
        # Tạo danh sách số tài khoản theo thứ tự cần thiết
        ordered_accounts = [config.SETTINGS.EXACT_ACCOUNTS_TO_USE[i] for i in indices]
        account_order = " ".join(map(str, ordered_accounts))
        logger.info(f"Bắt đầu với các tài khoản cụ thể theo thứ tự {shuffle_status}...")
    else:
        account_order = " ".join(str(start_index + idx) for idx in indices)
        logger.info(
            f"Bắt đầu với các tài khoản từ {start_index} đến {end_index} theo thứ tự {shuffle_status}..."
        )
    logger.info(f"Thứ tự tài khoản: {account_order}")

    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(value=threads)
    tasks = []

    # Thêm trước khi tạo tác vụ
    progress_tracker = await create_progress_tracker(
        total=len(accounts_to_process), description="Tài khoản đã hoàn thành"
    )

    # Sử dụng chỉ số để tạo tác vụ
    for idx in indices:
        actual_index = (
            config.SETTINGS.EXACT_ACCOUNTS_TO_USE[idx]
            if config.SETTINGS.EXACT_ACCOUNTS_TO_USE
            else start_index + idx
        )
        tasks.append(
            asyncio.create_task(
                launch_wrapper(
                    actual_index,
                    cycled_proxies[idx],
                    accounts_to_process[idx],
                )
            )
        )

    await asyncio.gather(*tasks)

    logger.success("Đã lưu tài khoản và khóa riêng vào tệp.")

    print_wallets_stats(config)

    input("Nhấn Enter để tiếp tục...")


async def account_flow(
    account_index: int,
    proxy: str,
    private_key: str,
    config: src.utils.config.Config,
    lock: asyncio.Lock,
    progress_tracker: ProgressTracker,
):
    try:
        pause = random.randint(
            config.SETTINGS.RANDOM_INITIALIZATION_PAUSE[0],
            config.SETTINGS.RANDOM_INITIALIZATION_PAUSE[1],
        )
        logger.info(f"[{account_index}] Nghỉ {pause} giây trước khi bắt đầu...")
        await asyncio.sleep(pause)

        instance = src.model.Start(account_index, proxy, private_key, config)

        result = await wrapper(instance.initialize, config)
        if not result:
            raise Exception("Không thể khởi tạo")

        result = await wrapper(instance.flow, config)
        if not result:
            report = True

        pause = random.randint(
            config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACCOUNTS[0],
            config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACCOUNTS[1],
        )
        logger.info(f"Nghỉ {pause} giây trước tài khoản tiếp theo...")
        await asyncio.sleep(pause)

        # Cập nhật tiến độ
        await progress_tracker.increment(1)

    except Exception as err:
        logger.error(f"{account_index} | Quy trình tài khoản thất bại: {err}")
        # Cập nhật tiến độ ngay cả khi có lỗi
        await progress_tracker.increment(1)


async def wrapper(function, config: src.utils.config.Config, *args, **kwargs):
    attempts = config.SETTINGS.ATTEMPTS
    attempts = 1
    for attempt in range(attempts):
        result = await function(*args, **kwargs)
        if isinstance(result, tuple) and result and isinstance(result[0], bool):
            if result[0]:
                return result
        elif isinstance(result, bool):
            if result:
                return True

        if attempt < attempts - 1:  # Không nghỉ sau lần thử cuối
            pause = random.randint(
                config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.info(
                f"Nghỉ {pause} giây trước lần thử tiếp theo {attempt+1}/{config.SETTINGS.ATTEMPTS}..."
            )
            await asyncio.sleep(pause)

    return result


def task_exists_in_config(task_name: str, tasks_list: list) -> bool:
    """Kiểm tra đệ quy sự tồn tại của một nhiệm vụ trong danh sách nhiệm vụ, bao gồm các danh sách lồng nhau"""
    for task in tasks_list:
        if isinstance(task, list):
            if task_exists_in_config(task_name, task):
                return True
        elif task == task_name:
            return True
    return Falseimport 
import asyncio
import random
from loguru import logger


import src.utils
from src.utils.output import show_dev_info, show_logo
from src.utils.proxy_parser import Proxy
import src.model
from src.utils.statistics import print_wallets_stats
from src.utils.check_github_version import check_version
from src.utils.logs import ProgressTracker, create_progress_tracker
from src.utils.config_browser import run

async def start():
    async def launch_wrapper(index, proxy, private_key):
        async with semaphore:
            await account_flow(
                index,
                proxy,
                private_key,
                config,
                lock,
                progress_tracker,
            )

    try:
        await check_version("Crazyscholarr", "MegaETH_auto")
    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Không thể kiểm tra phiên bản: {e}")
        logger.info("Tiếp tục với phiên bản hiện tại\n")

    print("\nCác tùy chọn có sẵn:\n")
    print("[1] ⭐️ Bắt đầu farming")
    print("[2] 🔧 Chỉnh sửa cấu hình")
    print("[3] 💾 Hành động cơ sở dữ liệu")
    print("[4] 👋 Thoát")
    print()

    try:
        choice = input("Nhập tùy chọn (1-4): ").strip()
    except Exception as e:
        logger.error(f"Lỗi nhập liệu: {e}")
        return

    if choice == "4" or not choice:
        return
    elif choice == "2":
        run()
        return
    elif choice == "1":
        pass
    elif choice == "3":
        from src.model.database.db_manager import show_database_menu

        await show_database_menu()
        await start()
    else:
        logger.error(f"Tùy chọn không hợp lệ: {choice}")
        return

    config = src.utils.get_config()

    # Tải proxy bằng cách sử dụng proxy parser
    try:
        proxy_objects = Proxy.from_file("data/proxies.txt")
        proxies = [proxy.get_default_format() for proxy in proxy_objects]
        if len(proxies) == 0:
            logger.error("Không tìm thấy proxy trong data/proxies.txt")
            return
    except Exception as e:
        logger.error(f"Không thể tải proxy: {e}")
        return

    private_keys = src.utils.read_private_keys("data/private_keys.txt")

    # Xác định phạm vi tài khoản
    start_index = config.SETTINGS.ACCOUNTS_RANGE[0]
    end_index = config.SETTINGS.ACCOUNTS_RANGE[1]

    # Nếu cả hai đều là 0, kiểm tra EXACT_ACCOUNTS_TO_USE
    if start_index == 0 and end_index == 0:
        if config.SETTINGS.EXACT_ACCOUNTS_TO_USE:
            # Chuyển đổi số tài khoản thành chỉ số (số - 1)
            selected_indices = [i - 1 for i in config.SETTINGS.EXACT_ACCOUNTS_TO_USE]
            accounts_to_process = [private_keys[i] for i in selected_indices]
            logger.info(
                f"Sử dụng các tài khoản cụ thể: {config.SETTINGS.EXACT_ACCOUNTS_TO_USE}"
            )

            # Để tương thích với phần còn lại của mã
            start_index = min(config.SETTINGS.EXACT_ACCOUNTS_TO_USE)
            end_index = max(config.SETTINGS.EXACT_ACCOUNTS_TO_USE)
        else:
            # Nếu danh sách rỗng, lấy tất cả tài khoản như trước
            accounts_to_process = private_keys
            start_index = 1
            end_index = len(private_keys)
    else:
        # Python slice không bao gồm phần tử cuối, vì vậy +1
        accounts_to_process = private_keys[start_index - 1 : end_index]

    threads = config.SETTINGS.THREADS

    # Chuẩn bị proxy cho các tài khoản đã chọn
    cycled_proxies = [
        proxies[i % len(proxies)] for i in range(len(accounts_to_process))
    ]

    # Tạo danh sách chỉ số
    indices = list(range(len(accounts_to_process)))

    # Xáo trộn chỉ số chỉ khi SHUFFLE_WALLETS được bật
    if config.SETTINGS.SHUFFLE_WALLETS:
        random.shuffle(indices)
        shuffle_status = "ngẫu nhiên"
    else:
        shuffle_status = "tuần tự"

    # Tạo chuỗi với thứ tự tài khoản
    if config.SETTINGS.EXACT_ACCOUNTS_TO_USE:
        # Tạo danh sách số tài khoản theo thứ tự cần thiết
        ordered_accounts = [config.SETTINGS.EXACT_ACCOUNTS_TO_USE[i] for i in indices]
        account_order = " ".join(map(str, ordered_accounts))
        logger.info(f"Bắt đầu với các tài khoản cụ thể theo thứ tự {shuffle_status}...")
    else:
        account_order = " ".join(str(start_index + idx) for idx in indices)
        logger.info(
            f"Bắt đầu với các tài khoản từ {start_index} đến {end_index} theo thứ tự {shuffle_status}..."
        )
    logger.info(f"Thứ tự tài khoản: {account_order}")

    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(value=threads)
    tasks = []

    # Thêm trước khi tạo tác vụ
    progress_tracker = await create_progress_tracker(
        total=len(accounts_to_process), description="Tài khoản đã hoàn thành"
    )

    # Sử dụng chỉ số để tạo tác vụ
    for idx in indices:
        actual_index = (
            config.SETTINGS.EXACT_ACCOUNTS_TO_USE[idx]
            if config.SETTINGS.EXACT_ACCOUNTS_TO_USE
            else start_index + idx
        )
        tasks.append(
            asyncio.create_task(
                launch_wrapper(
                    actual_index,
                    cycled_proxies[idx],
                    accounts_to_process[idx],
                )
            )
        )

    await asyncio.gather(*tasks)

    logger.success("Đã lưu tài khoản và khóa riêng vào tệp.")

    print_wallets_stats(config)

    input("Nhấn Enter để tiếp tục...")


async def account_flow(
    account_index: int,
    proxy: str,
    private_key: str,
    config: src.utils.config.Config,
    lock: asyncio.Lock,
    progress_tracker: ProgressTracker,
):
    try:
        pause = random.randint(
            config.SETTINGS.RANDOM_INITIALIZATION_PAUSE[0],
            config.SETTINGS.RANDOM_INITIALIZATION_PAUSE[1],
        )
        logger.info(f"[{account_index}] Nghỉ {pause} giây trước khi bắt đầu...")
        await asyncio.sleep(pause)

        instance = src.model.Start(account_index, proxy, private_key, config)

        result = await wrapper(instance.initialize, config)
        if not result:
            raise Exception("Không thể khởi tạo")

        result = await wrapper(instance.flow, config)
        if not result:
            report = True

        pause = random.randint(
            config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACCOUNTS[0],
            config.SETTINGS.RANDOM_PAUSE_BETWEEN_ACCOUNTS[1],
        )
        logger.info(f"Nghỉ {pause} giây trước tài khoản tiếp theo...")
        await asyncio.sleep(pause)

        # Cập nhật tiến độ
        await progress_tracker.increment(1)

    except Exception as err:
        logger.error(f"{account_index} | Quy trình tài khoản thất bại: {err}")
        # Cập nhật tiến độ ngay cả khi có lỗi
        await progress_tracker.increment(1)


async def wrapper(function, config: src.utils.config.Config, *args, **kwargs):
    attempts = config.SETTINGS.ATTEMPTS
    attempts = 1
    for attempt in range(attempts):
        result = await function(*args, **kwargs)
        if isinstance(result, tuple) and result and isinstance(result[0], bool):
            if result[0]:
                return result
        elif isinstance(result, bool):
            if result:
                return True

        if attempt < attempts - 1:  # Không nghỉ sau lần thử cuối
            pause = random.randint(
                config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
                config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
            )
            logger.info(
                f"Nghỉ {pause} giây trước lần thử tiếp theo {attempt+1}/{config.SETTINGS.ATTEMPTS}..."
            )
            await asyncio.sleep(pause)

    return result


def task_exists_in_config(task_name: str, tasks_list: list) -> bool:
    """Kiểm tra đệ quy sự tồn tại của một nhiệm vụ trong danh sách nhiệm vụ, bao gồm các danh sách lồng nhau"""
    for task in tasks_list:
        if isinstance(task, list):
            if task_exists_in_config(task_name, task):
                return True
        elif task == task_name:
            return True
    return False
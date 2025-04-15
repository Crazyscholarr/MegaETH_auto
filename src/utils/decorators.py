from functools import wraps
import asyncio
from typing import TypeVar, Callable, Any, Optional
from loguru import logger
from src.utils.config import get_config

T = TypeVar("T")


# @retry_async(attempts=3, default_value=False)
# async def deploy_contract(self):
#     try:
#         # mã triển khai của bạn
#         return True
#     except Exception as e:
#         # xử lý lỗi của bạn với thời gian nghỉ
#         await asyncio.sleep(your_pause)
#         raise  # trả lại quyền điều khiển cho decorator để thử lại lần tiếp theo
#
# @retry_async(default_value=False)
# async def some_function():
#     ...

def retry_async(
    attempts: int = None,  # Tùy chọn số lần thử
    delay: float = 1.0,
    backoff: float = 2.0,
    default_value: Any = None,
):
    """
    Decorator thử lại bất đồng bộ với thời gian chờ tăng cấp số nhân.
    Nếu số lần thử không được cung cấp, sử dụng SETTINGS.ATTEMPTS từ cấu hình.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Lấy số lần thử từ cấu hình nếu không được cung cấp
            retry_attempts = attempts if attempts is not None else get_config().SETTINGS.ATTEMPTS
            current_delay = delay

            for attempt in range(retry_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt < retry_attempts - 1:  # Không nghỉ ở lần thử cuối
                        logger.warning(
                            f"Lần thử {attempt + 1}/{retry_attempts} thất bại cho {func.__name__}: {str(e)}. "
                            f"Thử lại sau {current_delay:.1f} giây..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"Tất cả {retry_attempts} lần thử thất bại cho {func.__name__}: {str(e)}"
                        )
                        raise e  # Ném lại ngoại lệ cuối cùng

            return default_value

        return wrapper

    return decorator
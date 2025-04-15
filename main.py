from loguru import logger
import urllib3
import sys
import asyncio
import platform
import logging
from datetime import datetime
import pytz

from process import start
from src.utils.output import show_logo, show_dev_info
from src.utils.check_github_version import check_version

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    show_logo()
    show_dev_info()
    
    configuration()
    await start()

def configuration():
    urllib3.disable_warnings()
    logger.remove()

    # Tắt logging của primp và web3
    logging.getLogger("primp").setLevel(logging.WARNING)
    logging.getLogger("web3").setLevel(logging.WARNING)

    # Vietnam timezone (UTC+7)
    def vietnam_time_formatter(record):
        vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
        vn_time = datetime.now(vn_tz)
        record["extra"]["vn_time"] = vn_time.strftime("%H:%M:%S")
        record["extra"]["vn_day"] = vn_time.strftime("%Y-%m-%d")

    logger.configure(
        extra={"vn_time": "", "vn_day": ""}
    )

    log_format = (
        "<light-blue>[</light-blue><yellow>{extra[vn_time]}</yellow> | <yellow>{extra[vn_day]}</yellow><light-blue>]</light-blue> "
        "<magenta>[ Crazyscholar x 0G Lab ]</magenta> | "
        "<level>{level: <8}</level> | "
        "<cyan>{file}:{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        colorize=True,
        format=log_format,
        diagnose=True,
        backtrace=True,
        catch=True,
        filter=lambda record: vietnam_time_formatter(record) or True
    )
    logger.add(
        "logs/app.log",
        rotation="10 MB",
        retention="1 month",
        format="[{extra[vn_time]} | {extra[vn_day]}] [ Crazyscholar x 0G Lab ] | {level} | {name}:{line} - {message}",
        level="INFO",
    )

if __name__ == "__main__":
    asyncio.run(main())
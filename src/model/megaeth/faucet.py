import asyncio
from loguru import logger
import random
import primp
from src.model.help.captcha import Capsolver, Solvium
from src.utils.config import Config
from eth_account import Account
import hashlib
from curl_cffi.requests import AsyncSession
import json
import platform
from pynocaptcha import CloudFlareCracker, TlsV1Cracker

from src.utils.decorators import retry_async


@retry_async(default_value=False)
async def faucet(
    session: primp.AsyncClient,
    account_index: int,
    config: Config,
    wallet: Account,
    proxy: str,
) -> bool:

    try:
        logger.info(
            f"[{account_index}] | Bắt đầu faucet cho tài khoản {wallet.address}..."
        )

        if config.FAUCET.USE_CAPSOLVER:
            logger.info(
                f"[{account_index}] | Đang giải thử thách Cloudflare với Capsolver..."
            )
            capsolver = Capsolver(
                api_key=config.FAUCET.CAPSOLVER_API_KEY,
                proxy=proxy,
                session=session,
            )
            cf_result = await capsolver.solve_turnstile(
                "0x4AAAAAABA4JXCaw9E2Py-9",
                "https://testnet.megaeth.com/",
            )
        else:
            logger.info(
                f"[{account_index}] | Đang giải thử thách Cloudflare với Solvium..."
            )
            solvium = Solvium(
                api_key=config.FAUCET.SOLVIUM_API_KEY,
                session=session,
                proxy=proxy,
            )
            
            result = await solvium.solve_captcha(
                sitekey="0x4AAAAAABA4JXCaw9E2Py-9",
                pageurl="https://testnet.megaeth.com/",
            )
            cf_result = result

        if not cf_result:
            raise Exception("Không thể giải thử thách Cloudflare")

        logger.success(f"[{account_index}] | Đã giải thành công thử thách Cloudflare")

        headers = {
            "accept": "*/*",
            "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,ru;q=0.7,zh-TW;q=0.6,zh;q=0.5",
            "content-type": "text/plain;charset=UTF-8",
            "origin": "https://testnet.megaeth.com",
            "priority": "u=1, i",
            "referer": "https://testnet.megaeth.com/",
            "sec-ch-ua": '"Chromium";v="131", "Not:A-Brand";v="24", "Google Chrome";v="131"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }

        data = f'{{"addr":"{wallet.address}","token":"{cf_result}"}}'

        curl_session = AsyncSession(
            impersonate="chrome131",
            proxies={"http": f"http://{proxy}", "https": f"http://{proxy}"},
            verify=False,
        )

        claim_result = await curl_session.post(
            "https://carrot.megaeth.com/claim",
            headers=headers,
            data=data,
        )
        response_text = claim_result.text
        status_code = claim_result.status_code
    
        logger.info(
            f"[{account_index}] | Nhận phản hồi với mã trạng thái: {status_code}"
        )

        if claim_result.json()['success']:
            logger.success(
                f"[{account_index}] | Đã nhận token thành công từ faucet"
            )
            return True

        if "less than 24 hours have passed" in response_text:
            logger.success(
                f"[{account_index}] | Chưa đủ 24 giờ kể từ lần nhận trước, vui lòng chờ..."
            )
            return True

        if "used Cloudflare to restrict access" in response_text:
            raise Exception("IP proxy của bạn bị Cloudflare chặn. Hãy thử đổi proxy")

        if not response_text:
            raise Exception("Không thể gửi yêu cầu nhận token")

        if '"Success"' in response_text:
            logger.success(
                f"[{account_index}] | Đã nhận token thành công từ faucet"
            )
            return True

        if "Claimed already" in response_text:
            logger.success(
                f"[{account_index}] | Đã nhận token từ faucet trước đó"
            )
            return True

        else:
            logger.error(
                f"[{account_index}] | Không thể nhận token từ faucet: {response_text}"
            )
        await asyncio.sleep(3)

    except Exception as e:
        random_pause = random.randint(
            config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[0],
            config.SETTINGS.PAUSE_BETWEEN_ATTEMPTS[1],
        )
        if "operation timed out" in str(e):
            logger.error(
                f"[{account_index}] | Lỗi faucet tới megaeth.com: Kết nối hết thời gian. Thử lại sau {random_pause} giây"
            )
        else:
            logger.error(
                f"[{account_index}] | Lỗi faucet tới megaeth.com: {e}. Thử lại sau {random_pause} giây"
            )
        await asyncio.sleep(random_pause)
        raise
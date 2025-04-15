import asyncio
from loguru import logger
from primp import AsyncClient
import requests
from typing import Optional, Dict
from enum import Enum
import time
import re


class CaptchaError(Exception):
    """Lớp ngoại lệ cơ bản cho lỗi captcha"""
    pass


class ErrorCodes(Enum):
    ERROR_WRONG_USER_KEY = "ERROR_WRONG_USER_KEY"
    ERROR_KEY_DOES_NOT_EXIST = "ERROR_KEY_DOES_NOT_EXIST"
    ERROR_ZERO_BALANCE = "ERROR_ZERO_BALANCE"
    ERROR_PAGEURL = "ERROR_PAGEURL"
    IP_BANNED = "IP_BANNED"
    ERROR_PROXY_FORMAT = "ERROR_PROXY_FORMAT"
    ERROR_BAD_PARAMETERS = "ERROR_BAD_PARAMETERS"
    ERROR_BAD_PROXY = "ERROR_BAD_PROXY"
    ERROR_SITEKEY = "ERROR_SITEKEY"
    CAPCHA_NOT_READY = "CAPCHA_NOT_READY"
    ERROR_CAPTCHA_UNSOLVABLE = "ERROR_CAPTCHA_UNSOLVABLE"
    ERROR_WRONG_CAPTCHA_ID = "ERROR_WRONG_CAPTCHA_ID"
    ERROR_EMPTY_ACTION = "ERROR_EMPTY_ACTION"


class Capsolver:
    def __init__(
        self,
        api_key: str,
        proxy: Optional[str] = None,
        session: AsyncClient = None,
    ):
        self.api_key = api_key
        self.base_url = "https://api.capsolver.com"
        self.proxy = self._format_proxy(proxy) if proxy else None
        self.session = session or AsyncClient(verify=False)

    def _format_proxy(self, proxy: str) -> str:
        if not proxy:
            return None
        if "@" in proxy:
            return proxy
        return proxy

    async def create_task(
        self,
        sitekey: str,
        pageurl: str,
        invisible: bool = False,
    ) -> Optional[str]:
        """Tạo nhiệm vụ giải captcha"""
        data = {
            "clientKey": self.api_key,
            "appId": "0F6B2D90-7CA4-49AC-B0D3-D32C70238AD8",
            "task": {
                "type": "ReCaptchaV2Task",
                "websiteURL": pageurl,
                "websiteKey": sitekey,
                "isInvisible": False,
                # "pageAction": "drip_request",
            },
        }

        if self.proxy:
            data["task"]["proxy"] = self.proxy

        try:
            response = await self.session.post(
                f"{self.base_url}/createTask",
                json=data,
                timeout=30,
            )
            result = response.json()

            if "taskId" in result:
                return result["taskId"]

            logger.error(f"Lỗi khi tạo nhiệm vụ: {result}")
            return None

        except Exception as e:
            logger.error(f"Lỗi khi tạo nhiệm vụ: {e}")
            return None

    async def get_task_result(self, task_id: str) -> Optional[str]:
        """Lấy kết quả giải captcha"""
        data = {"clientKey": self.api_key, "taskId": task_id}

        max_attempts = 30
        for _ in range(max_attempts):
            try:
                response = await self.session.post(
                    f"{self.base_url}/getTaskResult",
                    json=data,
                    timeout=30,
                )
                result = response.json()

                if result.get("status") == "ready":
                    # Xử lý cả phản hồi reCAPTCHA và Turnstile
                    solution = result.get("solution", {})
                    return solution.get("token") or solution.get("gRecaptchaResponse")
                elif "errorId" in result and result["errorId"] != 0:
                    logger.error(f"Lỗi khi lấy kết quả: {result}")
                    return None

                await asyncio.sleep(3)

            except Exception as e:
                logger.error(f"Lỗi khi lấy kết quả: {e}")
                return None

        return None

    async def solve_recaptcha(
        self,
        sitekey: str,
        pageurl: str,
        invisible: bool = False,
    ) -> Optional[str]:
        """Giải ReCaptchaV2 và trả về token"""
        task_id = await self.create_task(sitekey, pageurl, invisible)
        if not task_id:
            return None

        return await self.get_task_result(task_id)

    async def create_turnstile_task(
        self,
        sitekey: str,
        pageurl: str,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
    ) -> Optional[str]:
        """Tạo nhiệm vụ giải captcha Turnstile"""
        data = {
            "clientKey": self.api_key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": pageurl,
                "websiteKey": sitekey,
            },
        }

        try:
            response = await self.session.post(
                f"{self.base_url}/createTask",
                json=data,
                timeout=30,
            )
            result = response.json()

            if "taskId" in result:
                return result["taskId"]

            logger.error(f"Lỗi khi tạo nhiệm vụ Turnstile: {result}")
            return None

        except Exception as e:
            logger.error(f"Lỗi khi tạo nhiệm vụ Turnstile: {e}")
            return None

    async def solve_turnstile(
        self,
        sitekey: str,
        pageurl: str,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
    ) -> Optional[str]:
        """Giải captcha Cloudflare Turnstile và trả về token"""
        task_id = await self.create_turnstile_task(
            sitekey=sitekey,
            pageurl=pageurl,
            action=action,
            cdata=cdata,
        )
        if not task_id:
            return None

        return await self.get_task_result(task_id)


class TwoCaptcha:
    def __init__(
        self,
        api_key: str,
        proxy: Optional[str] = None,
        session: AsyncClient = None,
    ):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"
        self.proxy = self._format_proxy(proxy) if proxy else None
        self.session = session or AsyncClient(verify=False)

    def _format_proxy(self, proxy: str) -> str:
        if not proxy:
            return None
        if "@" in proxy:
            return proxy
        return proxy

    async def create_turnstile_task(
        self,
        sitekey: str,
        pageurl: str,
        action: Optional[str] = None,
        data: Optional[str] = None,
        pagedata: Optional[str] = None,
    ) -> Optional[str]:
        """Tạo nhiệm vụ giải captcha Turnstile"""
        form_data = {
            "key": self.api_key,
            "method": "turnstile",
            "sitekey": sitekey,
            "pageurl": pageurl,
            "json": "1",
        }

        if action:
            form_data["action"] = action
        if data:
            form_data["data"] = data
        if pagedata:
            form_data["pagedata"] = pagedata
        if self.proxy:
            form_data["proxy"] = self.proxy

        try:
            response = await self.session.post(
                f"{self.base_url}/in.php",
                data=form_data,
                timeout=30,
            )
            result = response.json()

            if result.get("status") == 1:
                return result["request"]

            logger.error(f"Lỗi khi tạo nhiệm vụ Turnstile: {result}")
            return None

        except Exception as e:
            logger.error(f"Lỗi khi tạo nhiệm vụ Turnstile: {e}")
            return None

    async def get_task_result(self, task_id: str) -> Optional[str]:
        """Lấy kết quả giải captcha"""
        params = {
            "key": self.api_key,
            "action": "get",
            "id": task_id,
            "json": "1",
        }

        max_attempts = 30
        for _ in range(max_attempts):
            try:
                response = await self.session.get(
                    f"{self.base_url}/res.php",
                    params=params,
                    timeout=30,
                )
                result = response.json()

                if result.get("status") == 1:
                    return result["request"]
                elif result.get("request") == "CAPCHA_NOT_READY":
                    await asyncio.sleep(5)
                    continue

                logger.error(f"Lỗi khi lấy kết quả: {result}")
                return None

            except Exception as e:
                logger.error(f"Lỗi khi lấy kết quả: {e}")
                return None

        return None

    async def solve_turnstile(
        self,
        sitekey: str,
        pageurl: str,
        action: Optional[str] = None,
        data: Optional[str] = None,
        pagedata: Optional[str] = None,
    ) -> Optional[str]:
        """Giải captcha Cloudflare Turnstile và trả về token"""
        task_id = await self.create_turnstile_task(
            sitekey=sitekey,
            pageurl=pageurl,
            action=action,
            data=data,
            pagedata=pagedata,
        )
        if not task_id:
            return None

        return await self.get_task_result(task_id)


class Solvium:
    def __init__(
        self, 
        api_key: str, 
        session: AsyncClient,
        proxy: Optional[str] = None,
    ):
        self.api_key = api_key
        self.proxy = proxy
        self.base_url = "https://captcha.solvium.io/api/v1"
        self.session = session

    def _format_proxy(self, proxy: str) -> str:
        if not proxy:
            return None
        if "@" in proxy:
            return proxy
        return f"http://{proxy}"

    async def create_turnstile_task(self, sitekey: str, pageurl: str) -> Optional[str]:
        """Tạo nhiệm vụ giải captcha Turnstile"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        url = f"{self.base_url}/task/turnstile?url={pageurl}&sitekey={sitekey}&ref=starlabs"

        try:
            response = await self.session.get(url, headers=headers, timeout=30)
            result = response.json()
            
            if result.get("message") == "Task created" and "task_id" in result:
                return result["task_id"]

            logger.error(f"Lỗi khi tạo nhiệm vụ Turnstile với Solvium: {result}")
            return None

        except Exception as e:
            logger.error(f"Lỗi khi tạo nhiệm vụ Turnstile với Solvium: {e}")
            return None

    async def get_task_result(self, task_id: str) -> Optional[str]:
        """Lấy kết quả giải captcha"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        max_attempts = 30
        for _ in range(max_attempts):
            try:
                response = await self.session.get(
                    f"{self.base_url}/task/status/{task_id}",
                    headers=headers,
                    timeout=30,
                )
                
                result = response.json()

                # Kiểm tra trạng thái nhiệm vụ
                if result.get("status") == "completed" and result.get("result") and result["result"].get("solution"):
                    solution = result["result"]["solution"]
                    
                    # Kiểm tra định dạng giải pháp hợp lệ
                    if re.match(r'^[a-zA-Z0-9\.\-_]+$', solution):
                        return solution
                    else:
                        logger.error(f"Định dạng giải pháp không hợp lệ từ Solvium: {solution}")
                        return None
                        
                elif result.get("status") == "running" or result.get("status") == "pending":
                    # Nhiệm vụ vẫn đang thực hiện, chờ
                    await asyncio.sleep(5)
                    continue
                else:
                    # Lỗi hoặc trạng thái không xác định
                    logger.error(f"Lỗi khi lấy kết quả với Solvium: {result}")
                    return None

            except Exception as e:
                logger.error(f"Lỗi khi lấy kết quả với Solvium: {e}")
                return None

        logger.error("Đã đạt số lần thử tối đa mà không lấy được kết quả với Solvium")
        return None

    async def solve_captcha(self, sitekey: str, pageurl: str) -> Optional[str]:
        """Giải captcha Cloudflare Turnstile và trả về token"""
        task_id = await self.create_turnstile_task(sitekey, pageurl)
        if not task_id:
            return None

        return await self.get_task_result(task_id)
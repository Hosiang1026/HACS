import asyncio
import json
import datetime
import time
import logging
import base64
import hashlib
import random
import string
from urllib import parse
import aiohttp
import async_timeout
from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util.dt import utcnow

from .const import (
    COORDINATE_GCJ02,
    DOMAIN,
    FLAG_EMAIL,
    FLAG_PHONE,
)
_LOGGER = logging.getLogger(__name__)

LOGIN_OK = "ok"
LOGIN_NEED_VERIFY = "need_verify"
LOGIN_INVALID = "invalid_auth"
LOGIN_FAIL = "fail"


class XiaomiCloudDataUpdateCoordinator(DataUpdateCoordinator):
    """小米云服务数据更新协调器."""
    def __init__(
        self,
        hass,
        user,
        password,
        scan_interval,
        pass_token=None,
        user_id=None,
        device_id=None,
        schedule_refresh=True,
    ):
        """初始化协调器."""
        self._username = user
        self._password = password
        self._pass_token = pass_token
        self._device_id = device_id or "".join(
            random.choice(string.ascii_uppercase + string.digits) for _ in range(16)
        )
        if not device_id:
            self.token_updated = True
        else:
            self.token_updated = False
        self._headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        }
        self._cookies = {}
        self._device_info = {}
        self._serviceLoginAuth2_json = {}
        self._sign = None
        self._login_qs = None
        self._login_callback = None
        self._scan_interval = int(scan_interval)
        self._verify_flag = None
        self._identity_session = None
        self.verify_target = None

        self.service_data = None
        self.userId = user_id
        self.login_result = False
        self.service = None
        self._last_position_update = {}
        self._Service_Token = None
        self._last_devices_data = []

        _LOGGER.info("初始化小米云服务 - 位置更新间隔设置为 %s 分钟", self._scan_interval)
        _LOGGER.info("坐标系: GCJ-02（高德）")

        update_interval = datetime.timedelta(minutes=self._scan_interval)
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=update_interval)

        if schedule_refresh:
            hass.async_create_task(self._schedule_initial_refresh())

    def _parse_xiaomi_json(self, text: str) -> dict:
        if text.startswith("&&&START&&&"):
            text = text[11:]
        return json.loads(text)

    def export_tokens(self) -> dict:
        return {
            "pass_token": self._pass_token,
            "user_id": self.userId,
            "device_id": self._device_id,
        }

    async def async_setup_login(self, session) -> str:
        """配置流程登录，返回 LOGIN_*."""
        return await self._relogin(session, allow_2fa=True)

    async def _relogin(self, session, allow_2fa: bool = False) -> str:
        """优先 passToken，失败再用密码。后台 allow_2fa=False 不会自动发验证码."""
        if self._pass_token and self.userId:
            if await self._login_with_pass_token(session):
                if await self._get_device_info(session):
                    self.login_result = True
                    return LOGIN_OK
                self.login_result = False
        result = await self._password_login(session, allow_2fa=allow_2fa)
        if result == LOGIN_OK:
            if await self._get_device_info(session):
                self.login_result = True
                return LOGIN_OK
            self.login_result = False
            return LOGIN_FAIL
        return result

    async def async_verify_ticket(self, session, ticket: str) -> str:
        """提交短信/邮箱验证码."""
        if not self._identity_session or self._verify_flag is None:
            return LOGIN_FAIL
        key = "Phone" if self._verify_flag == FLAG_PHONE else "Email"
        try:
            with async_timeout.timeout(15):
                r = await session.post(
                    f"https://account.xiaomi.com/identity/auth/verify{key}",
                    cookies={"identity_session": self._identity_session},
                    params={
                        "_flag": self._verify_flag,
                        "ticket": ticket.strip(),
                        "trust": "true",
                        "_json": "true",
                    },
                    headers=self._headers,
                )
            resp = self._parse_xiaomi_json(await r.text())
            if resp.get("code") != 0:
                _LOGGER.warning("验证码错误: %s", resp.get("description") or resp.get("desc"))
                return LOGIN_INVALID
            self._collect_auth_cookies(session, r, resp)
            if not await self._finish_credentials(session, resp):
                return LOGIN_FAIL
            if not await self._get_device_info(session):
                return LOGIN_FAIL
            self.login_result = True
            return LOGIN_OK
        except Exception as e:
            _LOGGER.warning("验证码校验失败: %s", str(e))
            return LOGIN_FAIL

    def _collect_auth_cookies(self, session, response, data: dict | None = None) -> None:
        sources = list(getattr(response, "history", ()) or ()) + [response]
        for resp in sources:
            for key, morsel in resp.cookies.items():
                if key == "passToken" and morsel.value:
                    self._pass_token = morsel.value
                    self.token_updated = True
                elif key == "serviceToken" and morsel.value:
                    self._Service_Token = morsel.value
                elif key == "userId" and morsel.value:
                    self.userId = str(morsel.value)
                elif key == "cUserId" and morsel.value:
                    self._cookies["cUserId"] = morsel.value
            ext = resp.headers.get("extension-pragma")
            if ext:
                try:
                    payload = json.loads(ext)
                    if data is not None:
                        data.update(payload)
                    if payload.get("ssecurity"):
                        self._serviceLoginAuth2_json.update(payload)
                    if payload.get("passToken"):
                        self._pass_token = payload["passToken"]
                        self.token_updated = True
                except Exception:
                    pass
        if data:
            if data.get("passToken"):
                self._pass_token = data["passToken"]
                self.token_updated = True
            if data.get("userId"):
                self.userId = str(data["userId"])
        if not self._pass_token:
            self._pass_token = self._cookie_from_jar(session, "passToken") or self._pass_token
        if not self.userId:
            jar_uid = self._cookie_from_jar(session, "userId")
            if jar_uid:
                self.userId = str(jar_uid)
        if not self._Service_Token:
            self._Service_Token = self._cookie_from_jar(session, "serviceToken")

    @staticmethod
    def _extract_skip_url(url: str) -> str | None:
        parsed = parse.urlparse(url)
        if not parsed.path.startswith("/fe/"):
            return None
        skip = parse.parse_qs(parsed.query).get("skipUrl", [None])[0]
        if not skip:
            return None
        if skip.startswith("http"):
            return skip
        return "https://account.xiaomi.com" + skip

    async def _finish_credentials(self, session, data: dict) -> bool:
        """二次验证后：跟随 location → 再用 passToken 换 i.mi.com 票据."""
        try:
            location = data.get("location") or ""
            if location.startswith("/"):
                location = "https://account.xiaomi.com" + location
            if location:
                with async_timeout.timeout(20):
                    r = await session.get(
                        location, headers=self._headers, allow_redirects=True
                    )
                self._collect_auth_cookies(session, r, data)
                skip = self._extract_skip_url(str(r.url))
                if skip:
                    with async_timeout.timeout(20):
                        r2 = await session.get(
                            skip, headers=self._headers, allow_redirects=True
                        )
                    self._collect_auth_cookies(session, r2, data)

            if self._pass_token and self.userId:
                if await self._login_with_pass_token(session):
                    return True

            if data.get("ssecurity") and data.get("location"):
                self._serviceLoginAuth2_json = {
                    **self._serviceLoginAuth2_json,
                    **data,
                }
                if await self._login_miai(session):
                    return True

            if self._Service_Token and self.userId:
                return True

            _LOGGER.warning(
                "验证后换票失败 passToken=%s userId=%s",
                bool(self._pass_token),
                self.userId,
            )
            return False
        except Exception as e:
            _LOGGER.warning("完成登录凭据失败: %s", str(e))
            return False

    async def _login_with_pass_token(self, session) -> bool:
        """用 passToken 换 i.mi.com 的 ssecurity/serviceToken（使用干净会话，避免二次验证残留 cookie）。"""
        try:
            jar = aiohttp.CookieJar(unsafe=True)
            async with aiohttp.ClientSession(cookie_jar=jar) as clean:
                cookies = {
                    "userId": str(self.userId),
                    "passToken": self._pass_token,
                    "sdkVersion": "accountsdk-18.8.15",
                    "deviceId": self._device_id,
                }
                with async_timeout.timeout(15):
                    r = await clean.get(
                        "https://account.xiaomi.com/pass/serviceLogin",
                        cookies=cookies,
                        params={"_json": "true", "sid": "i.mi.com", "_locale": "zh_CN"},
                        headers=self._headers,
                    )
                text = await r.text()
                resp = self._parse_xiaomi_json(text)
                if resp.get("passToken"):
                    self._pass_token = resp["passToken"]
                    self.token_updated = True
                if resp.get("userId"):
                    self.userId = str(resp["userId"])
                if not resp.get("ssecurity") or not resp.get("location"):
                    _LOGGER.warning(
                        "passToken 登录未拿到 ssecurity: code=%s desc=%s keys=%s",
                        resp.get("code"),
                        resp.get("description") or resp.get("desc"),
                        list(resp.keys()),
                    )
                    return False
                self._serviceLoginAuth2_json = resp
                return await self._sts_exchange(clean, resp)
        except Exception as e:
            _LOGGER.warning("passToken 登录出错: %s", str(e))
            return False

    def _set_cookie_values(self, response) -> dict[str, str]:
        found: dict[str, str] = {}
        for resp in list(getattr(response, "history", ()) or ()) + [response]:
            for key, morsel in resp.cookies.items():
                if morsel.value:
                    found[key] = morsel.value
            raw = resp.headers.getall("Set-Cookie", [])
            for item in raw:
                part = item.split(";", 1)[0]
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                name = name.strip()
                value = value.strip()
                if name and value:
                    found[name] = value
        return found

    async def _sts_exchange(self, session, auth: dict) -> bool:
        location = auth.get("location")
        if not location:
            return False
        if auth.get("passToken"):
            self._pass_token = auth["passToken"]
            self.token_updated = True
        if auth.get("userId"):
            self.userId = str(auth["userId"])

        urls: list[str] = []
        if auth.get("nonce") is not None and auth.get("ssecurity"):
            nsec = "nonce={}&{}".format(auth["nonce"], auth["ssecurity"])
            client_sign = base64.b64encode(hashlib.sha1(nsec.encode("utf-8")).digest()).decode()
            sep = "&" if "?" in location else "?"
            urls.append(f"{location}{sep}clientSign={parse.quote(client_sign)}")
        urls.append(location)

        headers = {
            "User-Agent": "MISoundBox/1.4.0,iosPassportSDK/iOS-3.2.7 iOS/11.2.5",
            "Accept-Language": "zh-cn",
            "Connection": "keep-alive",
            "Cookie": (
                f"userId={self.userId}; passToken={self._pass_token}; "
                f"deviceId={self._device_id}; sdkVersion=accountsdk-18.8.15"
            ),
        }
        last_status = None
        last_body = ""
        for url in urls:
            for allow_redirects in (False, True):
                with async_timeout.timeout(15):
                    r = await session.get(
                        url, headers=headers, allow_redirects=allow_redirects
                    )
                last_status = r.status
                cookies = self._set_cookie_values(r)
                body = ""
                if allow_redirects or r.status == 200:
                    body = (await r.text()) or ""
                    last_body = body[:200]
                service_token = cookies.get("serviceToken")
                user_id = cookies.get("userId") or self.userId
                if service_token and user_id:
                    self._Service_Token = service_token
                    self.userId = str(user_id)
                    if cookies.get("passToken"):
                        self._pass_token = cookies["passToken"]
                        self.token_updated = True
                    _LOGGER.debug("STS 换票成功，用户ID: %s", self.userId)
                    return True
                if body and ("<html" in body.lower() or "<!doctype" in body.lower()):
                    break
                if not allow_redirects and r.status in (301, 302, 303, 307, 308):
                    loc = r.headers.get("Location")
                    if loc:
                        with async_timeout.timeout(15):
                            r2 = await session.get(
                                loc, headers=headers, allow_redirects=True
                            )
                        cookies.update(self._set_cookie_values(r2))
                        service_token = cookies.get("serviceToken")
                        user_id = cookies.get("userId") or self.userId
                        if service_token and user_id:
                            self._Service_Token = service_token
                            self.userId = str(user_id)
                            _LOGGER.debug("STS 重定向换票成功，用户ID: %s", self.userId)
                            return True
                        last_status = r2.status
                        last_body = ((await r2.text()) or "")[:200]
        _LOGGER.warning(
            "登录小米云服务失败，状态码: %s body=%s",
            last_status,
            last_body,
        )
        return False

    async def _login_miai(self, session):
        """登录小米云服务."""
        try:
            auth = self._serviceLoginAuth2_json
            jar = aiohttp.CookieJar(unsafe=True)
            async with aiohttp.ClientSession(cookie_jar=jar) as clean:
                return await self._sts_exchange(clean, auth)
        except Exception as e:
            _LOGGER.warning("登录小米云服务时出错: %s", str(e))
            return False

    async def _password_login(self, session, allow_2fa: bool = True) -> str:
        if not await self._get_sign(session):
            return LOGIN_FAIL
        if self._sign is True and self._serviceLoginAuth2_json.get("ssecurity"):
            if await self._login_miai(session):
                return LOGIN_OK
            return LOGIN_FAIL
        auth = await self._serviceLoginAuth2(session, allow_2fa=allow_2fa)
        if auth == LOGIN_NEED_VERIFY:
            return LOGIN_NEED_VERIFY
        if auth != LOGIN_OK:
            return auth
        if self._serviceLoginAuth2_json.get("code", -1) not in (0, None):
            if not self._serviceLoginAuth2_json.get("ssecurity"):
                return LOGIN_INVALID
        if not await self._login_miai(session):
            return LOGIN_FAIL
        return LOGIN_OK

    async def _get_sign(self, session):
        """获取签名信息."""
        url = 'https://account.xiaomi.com/pass/serviceLogin?sid=i.mi.com&_json=true&_locale=zh_CN'
        _LOGGER.debug("开始获取签名")
        try:
            with async_timeout.timeout(15):
                r = await session.get(url, headers=self._headers)
            resp = self._parse_xiaomi_json(await r.text())
            if resp.get("ssecurity") and resp.get("location"):
                self._serviceLoginAuth2_json = resp
                self._sign = True
                return True
            if not resp.get("_sign"):
                _LOGGER.warning("获取签名失败: %s", resp.get("description") or resp.get("desc") or resp)
                return False
            self._sign = resp["_sign"]
            self._login_qs = resp.get("qs") or "%3Fsid%3Di.mi.com"
            self._login_callback = resp.get("callback") or "https://i.mi.com/sts"
            for key, morsel in r.cookies.items():
                self._cookies[key] = morsel.value
            _LOGGER.debug("获取到签名: %s", self._sign)
            return True
        except Exception as e:
            _LOGGER.warning("获取签名时出错: %s", str(e))
            return False

    async def _serviceLoginAuth2(self, session, captCode=None, allow_2fa: bool = True):
        """执行服务登录认证，返回 LOGIN_*."""
        if self._sign is True and self._serviceLoginAuth2_json.get("ssecurity"):
            return LOGIN_OK

        url = 'https://account.xiaomi.com/pass/serviceLoginAuth2'
        headers = {
            **self._headers,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': '*/*',
            'Origin': 'https://account.xiaomi.com',
            'Referer': 'https://account.xiaomi.com/pass/serviceLogin?sid=i.mi.com&_locale=zh_CN',
        }

        auth_post_data = {
            '_json': 'true',
            '_sign': self._sign,
            'callback': self._login_callback or 'https://i.mi.com/sts',
            'hash': hashlib.md5(self._password.encode('utf-8')).hexdigest().upper(),
            'qs': self._login_qs or '%3Fsid%3Di.mi.com',
            'sid': 'i.mi.com',
            'user': self._username,
        }
        try:
            cookies = dict(self._cookies)
            cookies.setdefault("deviceId", self._device_id)
            cookies.setdefault("sdkVersion", "accountsdk-18.8.15")
            if captCode is not None:
                url = 'https://account.xiaomi.com/pass/serviceLoginAuth2?_dc={}'.format(
                    int(round(time.time() * 1000)))
                auth_post_data['captCode'] = captCode
                if self._cookies.get('ick'):
                    cookies['ick'] = self._cookies['ick']

            _LOGGER.debug("执行服务登录认证")
            with async_timeout.timeout(15):
                r = await session.post(url, headers=headers, data=auth_post_data, cookies=cookies)

            resp = self._parse_xiaomi_json(await r.text())
            self._serviceLoginAuth2_json = resp

            pass_token = resp.get('passToken')
            if not pass_token and r.cookies.get('passToken'):
                pass_token = r.cookies.get('passToken').value
            if pass_token:
                self._pass_token = pass_token
                self._cookies['pwdToken'] = pass_token
                self._cookies['passToken'] = pass_token
                self.token_updated = True
            if resp.get('userId'):
                self.userId = str(resp['userId'])

            if resp.get('notificationUrl'):
                notify = resp['notificationUrl']
                if notify.startswith('/'):
                    notify = 'https://account.xiaomi.com' + notify
                if not allow_2fa:
                    _LOGGER.warning(
                        "运行中需要二次验证，已跳过自动发码。请删除集成后重新添加并完成验证码"
                    )
                    return LOGIN_NEED_VERIFY
                if await self._start_verify(session, notify):
                    return LOGIN_NEED_VERIFY
                _LOGGER.warning("二次验证初始化失败，链接: %s", notify)
                return LOGIN_FAIL

            if resp.get('captchaUrl'):
                _LOGGER.warning("登录需要图形验证码: %s", resp.get('captchaUrl'))
                return LOGIN_FAIL

            if not resp.get('ssecurity') or not resp.get('location'):
                _LOGGER.warning(
                    "登录认证失败: code=%s desc=%s",
                    resp.get('code'),
                    resp.get('description') or resp.get('desc'),
                )
                return LOGIN_INVALID

            _LOGGER.debug("服务登录认证成功")
            return LOGIN_OK
        except Exception as e:
            _LOGGER.warning("服务登录认证时出错: %s", str(e))
            return LOGIN_FAIL

    async def _start_verify(self, session, notification_url: str) -> bool:
        list_url = notification_url
        if "/fe/service/identity/authStart" in list_url:
            list_url = list_url.replace("/fe/service/identity/authStart", "/identity/list")
        elif "/identity/authStart" in list_url:
            list_url = list_url.replace("/identity/authStart", "/identity/list")
        try:
            with async_timeout.timeout(15):
                r = await session.get(list_url, headers=self._headers)
            resp = self._parse_xiaomi_json(await r.text())
            if resp.get("code") != 2:
                _LOGGER.warning("获取验证方式失败: %s", resp)
                return False
            flag = resp.get("flag")
            if flag not in (FLAG_PHONE, FLAG_EMAIL):
                _LOGGER.warning("不支持的验证方式 flag=%s", flag)
                return False
            identity_session = r.cookies.get("identity_session")
            if not identity_session:
                _LOGGER.warning("未获取到 identity_session")
                return False
            identity_session = identity_session.value
            key = "Phone" if flag == FLAG_PHONE else "Email"
            with async_timeout.timeout(15):
                r2 = await session.get(
                    f"https://account.xiaomi.com/identity/auth/verify{key}",
                    cookies={"identity_session": identity_session},
                    params={"_flag": flag, "_json": "true"},
                    headers=self._headers,
                )
            res2 = self._parse_xiaomi_json(await r2.text())
            if res2.get("code") != 0:
                _LOGGER.warning("获取验证目标失败: %s", res2)
                return False
            masked = res2.get(f"masked{key}") or ""
            with async_timeout.timeout(15):
                r3 = await session.post(
                    f"https://account.xiaomi.com/identity/auth/send{key}Ticket",
                    cookies={"identity_session": identity_session},
                    data={"retry": 0, "icode": "", "_json": "true"},
                    headers=self._headers,
                )
            res3 = self._parse_xiaomi_json(await r3.text())
            if res3.get("code") != 0:
                _LOGGER.warning("发送验证码失败: %s", res3)
                return False
            self._verify_flag = flag
            self._identity_session = identity_session
            self.verify_target = masked
            _LOGGER.info("已向 %s 发送验证码", masked)
            return True
        except Exception as e:
            _LOGGER.warning("启动二次验证失败: %s", str(e))
            return False

    def _cookie_from_response(self, response, name: str) -> str | None:
        morsel = response.cookies.get(name)
        if morsel:
            return morsel.value
        for hist in response.history:
            morsel = hist.cookies.get(name)
            if morsel:
                return morsel.value
        return None

    def _cookie_from_jar(self, session, name: str) -> str | None:
        try:
            for cookie in session.cookie_jar:
                if cookie.key == name and cookie.value:
                    return cookie.value
        except Exception:
            pass
        return None

    async def _get_device_info(self, session):
        """获取设备信息."""
        url = 'https://i.mi.com/find/device/full/status?ts={}'.format(
            int(round(time.time() * 1000)))
        get_device_list_header = {'Cookie': 'userId={};serviceToken={}'.format(
            self.userId, self._Service_Token)}
        try:
            _LOGGER.debug("开始获取设备信息")
            with async_timeout.timeout(15):
                r = await session.get(url, headers=get_device_list_header)
            
            # 检查HTTP状态码
            if r.status == 401:
                _LOGGER.warning("获取设备信息时登录失效(401)，需要重新登录")
                self.login_result = False
                return False
                
            if r.status == 200:
                response_data = json.loads(await r.text())
                
                # 检查API返回的错误码
                if isinstance(response_data, dict) and response_data.get('code') in [401, 6]:
                    _LOGGER.warning("获取设备信息API返回登录失效错误码(%s)，需要重新登录", response_data.get('code'))
                    self.login_result = False
                    return False
                
                if 'data' not in response_data or 'devices' not in response_data['data']:
                    _LOGGER.warning("设备信息数据格式异常，未找到设备列表")
                    return False
                    
                device_count = len(response_data['data']['devices'])
                _LOGGER.debug('获取到%d个设备信息', device_count)
                data = response_data['data']['devices']

                self._device_info = data
                return True
            else:
                _LOGGER.warning("获取设备信息失败，HTTP状态码: %s", r.status)
                self.login_result = False
                return False
        except Exception as e:
            _LOGGER.warning("获取设备信息时出错: %s", str(e))
            return False
    
    async def _send_find_device_command(self, session:aiohttp.ClientSession):
        """发送查找设备命令，触发手机定位."""
        if not self._device_info:
            _LOGGER.warning("没有设备信息，无法发送查找命令")
            return False

        target_imei = None
        if self.service == "find" and self.service_data:
            target_imei = self.service_data.get("imei")

        flag = True
        devices = self._device_info
        if target_imei:
            devices = [d for d in self._device_info if d.get("imei") == target_imei]
        device_count = len(devices)
        _LOGGER.info("开始向%d个设备发送查找命令", device_count)

        for vin in devices:
            imei = vin.get("imei")
            model = vin.get("model", "未知设备")
            
            if not imei:
                _LOGGER.warning(f"设备[{model}]没有IMEI，跳过")
                continue
                
            url = 'https://i.mi.com/find/device/{}/location'.format(imei)
            _send_find_device_command_header = {
                'Cookie': 'userId={};serviceToken={}'.format(self.userId, self._Service_Token)}
            data = {'userId': self.userId, 'imei': imei,
                    'auto': 'false', 'channel': 'web', 'serviceToken': self._Service_Token}
            try:
                _LOGGER.info(f"向设备[{model}]发送查找命令，触发定位...")
                with async_timeout.timeout(15):
                    r = await session.post(url, headers=_send_find_device_command_header, data=data)
                
                if r.status != 200:
                    _LOGGER.warning(f"查找设备[{model}]失败，HTTP状态码: {r.status}")
                    if r.status == 401:
                        self.login_result = False
                        flag = False
                        break
                    continue
                
                try:
                    response_json = await r.json()
                    
                    # 检查返回状态和状态码，处理登录失效的情况
                    if isinstance(response_json, dict) and response_json.get('code') in [401, 6]:
                        _LOGGER.warning(f"查找设备[{model}]时登录失效(401)，需要重新登录")
                        self.login_result = False
                        flag = False
                        break
                    _LOGGER.info(f"成功发送查找命令到设备[{model}]")
                except Exception as e:
                    _LOGGER.warning(f"解析查找设备[{model}]响应时出错: {str(e)}")
            except Exception as e:
                _LOGGER.warning(f"向设备[{model}]发送查找命令时出错: {str(e)}")
                self.login_result = False
                flag = False
        
        _LOGGER.info("发送查找命令完成，结果: %s", "成功" if flag else "失败")
        return flag
    
    async def _send_noise_command(self, session:aiohttp.ClientSession):
        """发送播放声音命令."""
        if not self.service_data or 'imei' not in self.service_data:
            _LOGGER.warning("没有指定设备IMEI，无法发送声音命令")
            return False
            
        flag = True
        imei = self.service_data['imei']  
        url = 'https://i.mi.com/find/device/{}/noise'.format(imei)
        _send_noise_command_header = {
            'Cookie': 'userId={};serviceToken={}'.format(self.userId, self._Service_Token)}
        data = {'userId': self.userId, 'imei': imei,
                'auto': 'false', 'channel': 'web', 'serviceToken': self._Service_Token}
        try:
            _LOGGER.info("向设备[%s]发送播放声音命令", imei)
            with async_timeout.timeout(15):
                r = await session.post(url, headers=_send_noise_command_header, data=data)
            
            if r.status != 200:
                _LOGGER.warning("发送声音命令失败，HTTP状态码: %s", r.status)
                self.login_result = False
                return False
                
            response_json = await r.json()
            _LOGGER.debug("声音命令响应: %s", response_json)
            
            # 检查返回状态和状态码，处理登录失效的情况
            if isinstance(response_json, dict) and response_json.get('code') in [401, 6]:
                _LOGGER.warning("发送声音指令时登录失效(401)，需要重新登录")
                self.login_result = False
                flag = False
            else:
                _LOGGER.info("成功发送声音命令到设备[%s]", imei)
                self.service = None
                self.service_data = None
            
            return flag
        except Exception as e:
            _LOGGER.warning("发送声音命令时出错: %s", str(e))
            self.login_result = False
            return False

    async def _send_lost_command(self, session:aiohttp.ClientSession):
        """发送设备丢失命令."""
        if not self.service_data or 'imei' not in self.service_data:
            _LOGGER.warning("没有指定设备IMEI，无法发送丢失命令")
            return False
        
        flag = True
        imei = self.service_data['imei']  
        content = self.service_data.get('content', "")  
        phone = self.service_data.get('phone', "")  
        message = {"content": content, "phone": phone}
        onlinenotify = self.service_data.get('onlinenotify', True)
        url = 'https://i.mi.com/find/device/{}/lost'.format(imei)
        _send_lost_command_header = {
            'Cookie': 'userId={};serviceToken={}'.format(self.userId, self._Service_Token)}
        data = {'userId': self.userId, 'imei': imei,
                'deleteCard': 'false', 'channel': 'web', 'serviceToken': self._Service_Token, 
                'onlineNotify': onlinenotify, 'message': json.dumps(message)}
        try:
            _LOGGER.info("向设备[%s]发送丢失命令", imei)
            with async_timeout.timeout(15):
                r = await session.post(url, headers=_send_lost_command_header, data=data)
            
            if r.status != 200:
                _LOGGER.warning("发送丢失命令失败，HTTP状态码: %s", r.status)
                self.login_result = False
                return False
                
            response_json = await r.json()
            _LOGGER.debug("丢失命令响应: %s", response_json)
            
            if isinstance(response_json, dict) and response_json.get('code') in [401, 6]:
                _LOGGER.warning("发送丢失指令时登录失效(401)，需要重新登录")
                self.login_result = False
                flag = False
            else:
                _LOGGER.info("成功发送丢失命令到设备[%s]", imei)
                self.service = None
                self.service_data = None
            
            return flag
        except Exception as e:
            _LOGGER.warning("发送丢失命令时出错: %s", str(e))
            self.login_result = False
            return False

    async def _send_clipboard_command(self, session:aiohttp.ClientSession):
        """发送剪贴板命令."""
        if not self.service_data or 'text' not in self.service_data:
            _LOGGER.warning("没有指定文本内容，无法发送剪贴板命令")
            return False
            
        flag = True
        text = self.service_data['text']  
        url = 'https://i.mi.com/clipboard/lite/text'
        _send_clipboard_command_header = {
            'Cookie': 'userId={};serviceToken={}'.format(self.userId, self._Service_Token)}
        data = {'text': text, 'serviceToken': self._Service_Token}
        try:
            _LOGGER.info("发送剪贴板命令，文本内容长度: %d", len(text))
            with async_timeout.timeout(15):
                r = await session.post(url, headers=_send_clipboard_command_header, data=data)
            
            if r.status != 200:
                _LOGGER.warning("发送剪贴板命令失败，HTTP状态码: %s", r.status)
                self.login_result = False
                return False
                
            response_json = await r.json()
            _LOGGER.debug("剪贴板命令响应: %s", response_json)
            
            if isinstance(response_json, dict) and response_json.get('code') in [401, 6]:
                _LOGGER.warning("发送剪贴板指令时登录失效(401)，需要重新登录")
                self.login_result = False
                flag = False
            else:
                _LOGGER.info("成功发送剪贴板命令")
                self.service = None
                self.service_data = None
            
            return flag
        except Exception as e:
            _LOGGER.warning("发送剪贴板命令时出错: %s", str(e))
            self.login_result = False
            return False
  
    async def _send_command(self, data):
        """发送命令入口."""
        if not data or 'service' not in data or 'data' not in data:
            _LOGGER.warning("命令数据格式不正确，无法发送命令")
            return
            
        self.service_data = data['data']
        self.service = data['service']
        _LOGGER.info("准备发送命令: %s", self.service)
        await self.async_refresh()

    async def _get_device_location(self, session:aiohttp.ClientSession):
        """获取设备位置信息."""
        if not self._device_info:
            _LOGGER.warning("没有设备信息，无法获取位置")
            return []
            
        devices_info = []
        device_count = len(self._device_info)
        _LOGGER.info("开始获取%d个设备的位置信息", device_count)
        
        for vin in self._device_info:
            imei = vin.get("imei") 
            model = vin.get("model", "未知设备") 
            version = vin.get("version", "未知版本")
            
            if not imei:
                _LOGGER.warning(f"设备[{model}]没有IMEI，跳过获取位置")
                continue
                
            url = 'https://i.mi.com/find/device/status?ts={}&fid={}'.format(
                int(round(time.time() * 1000)), imei)
            _send_find_device_command_header = {
                'Cookie': 'userId={};serviceToken={}'.format(self.userId, self._Service_Token)}
            try:
                with async_timeout.timeout(15):
                    r = await session.get(url, headers=_send_find_device_command_header)
                
                # 检查HTTP状态码
                if r.status == 401:
                    _LOGGER.warning("获取设备位置时登录失效(401)，需要重新登录")
                    self.login_result = False
                    return []
                
                if r.status != 200:
                    _LOGGER.warning(f"获取设备[{model}]位置失败，HTTP状态码: {r.status}")
                    continue
                    
                response_data = json.loads(await r.text())
                
                # 检查API返回的错误码
                if isinstance(response_data, dict) and response_data.get('code') in [401, 6]:
                    _LOGGER.warning("API返回登录失效错误码(%s)，需要重新登录", response_data.get('code'))
                    self.login_result = False
                    return []
                
                if 'data' not in response_data:
                    _LOGGER.warning(f"设备[{model}]位置数据格式异常，缺少data字段")
                    continue
                
                _LOGGER.debug(f"获取设备[{model}]位置数据成功")

                # 创建设备基本信息字典
                device_info = {
                    "imei": imei,
                    "model": model,
                    "version": version
                }
                
                # 提取电量信息（如果可用）
                if "powerLevel" in response_data['data']:
                    device_info["device_power"] = response_data['data']['powerLevel'].get('value', 0)
                
                # 提取设备状态（开启/关闭）
                if "status" in response_data['data']:
                    device_info["device_status"] = response_data['data']['status']
                
                # 检查是否有位置数据
                location_data_available = False

                if "location" in response_data['data'] and "receipt" in response_data['data']['location']:
                    location_receipt = response_data['data']['location']['receipt']
                    
                    gpsInfoTransformed = location_receipt.get('gpsInfoTransformed', [])
                    
                    # 记录坐标系转换列表
                    if not gpsInfoTransformed:
                        _LOGGER.warning(f"设备[{model}]无可用坐标系转换列表")

                    # 获取位置更新时间
                    if 'infoTime' in location_receipt:
                        info_time_ms = int(location_receipt['infoTime'])
                        time_array = time.localtime(info_time_ms / 1000)
                        formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time_array)
                        device_info["device_location_update_time"] = formatted_time
                        
                        # 判断位置是否更新
                        last_update = self._last_position_update.get(imei, 0)
                        if info_time_ms > last_update:
                            self._last_position_update[imei] = info_time_ms
                            _LOGGER.info(f"设备[{model}]位置已更新，时间: {formatted_time}")

                    # 处理GPS坐标
                    if gpsInfoTransformed:
                        location_info_json = None
                        for item in gpsInfoTransformed:
                            if item.get("coordinateType") == COORDINATE_GCJ02:
                                location_info_json = item
                                break
                        if not location_info_json and gpsInfoTransformed:
                            location_info_json = gpsInfoTransformed[0]
                            _LOGGER.warning(
                                "设备[%s]未返回 GCJ-02 坐标，使用 %s",
                                model,
                                location_info_json.get("coordinateType"),
                            )
                        if location_info_json:
                            device_info["device_lat"] = location_info_json.get("latitude")
                            device_info["device_lon"] = location_info_json.get("longitude")
                            device_info["device_accuracy"] = int(
                                location_info_json.get("accuracy", 0)
                            )
                            device_info["coordinate_type"] = "gcj02"
                            location_data_available = True
                        else:
                            _LOGGER.warning(f"设备[{model}]未找到任何坐标系数据")

                        # 添加其他位置数据
                        if 'phone' in location_receipt:
                            device_info["device_phone"] = location_receipt.get('phone', 0)
                
                # 如果没有位置数据，记录日志
                if not location_data_available:
                    _LOGGER.warning(f"设备[{model}]没有位置数据可用，查找设备可能未成功触发")
                
                # 添加设备信息到列表，即使位置数据不完整
                devices_info.append(device_info)
            except Exception as e:
                _LOGGER.error(f"处理设备[{model}]位置时出错: {str(e)}")
        
        # 记录警告如果没有设备数据
        devices_count = len(devices_info)
        if devices_count > 0:
            _LOGGER.info(f"成功获取了{devices_count}个设备的数据")
        else:
            _LOGGER.warning("未能获取任何有效设备数据")
        
        return devices_info

    async def _async_update_data(self):
        """更新数据，定时调用."""
        _LOGGER.debug("开始数据更新周期，当前更新间隔为 %s 分钟，服务: %s", self._scan_interval, self.service)
        
        # 获取设备数据
        devices_data = []
        
        try:
            session = async_get_clientsession(self.hass)
            
            # 如果设置了特定服务，优先处理
            if self.service in ["noise", "lost", "clipboard", "find"]:
                if self.login_result is True:
                    _LOGGER.info("执行服务: %s", self.service)
                    if self.service == "noise":
                        service_result = await self._send_noise_command(session)
                    elif self.service == 'lost':
                        service_result = await self._send_lost_command(session)
                    elif self.service == 'clipboard':
                        service_result = await self._send_clipboard_command(session)
                    elif self.service == 'find':
                        service_result = await self._send_find_device_command(session)
                        self.service = None
                        self.service_data = None
                    
                    # 如果服务执行失败可能是登录失效，尝试重新登录
                    if not service_result:
                        _LOGGER.info("服务执行失败，尝试重新登录")
                        self.login_result = False
                else:
                    _LOGGER.info("用户未登录，将在下一步中执行登录")
                        
            # 处理登录状态
            if not self.login_result:
                _LOGGER.info("开始执行登录流程")
                session.cookie_jar.clear()

                login_status = await self._relogin(session, allow_2fa=False)
                if login_status == LOGIN_NEED_VERIFY:
                    _LOGGER.warning(
                        "会话失效且需要二次验证，请重新添加集成完成验证码（后台不会自动发码）"
                    )
                    return self._last_devices_data or []
                if login_status != LOGIN_OK:
                    _LOGGER.warning('登录验证失败')
                    return self._last_devices_data or []

                _LOGGER.info("登录成功，获取到%d个设备信息", len(self._device_info))
                self.login_result = True

                if self.service in ["noise", "lost", "clipboard", "find"]:
                    _LOGGER.info("重新尝试执行服务: %s", self.service)
                    if self.service == "noise":
                        await self._send_noise_command(session)
                    elif self.service == 'lost':
                        await self._send_lost_command(session)
                    elif self.service == 'clipboard':
                        await self._send_clipboard_command(session)
                    elif self.service == 'find':
                        await self._send_find_device_command(session)
            
            # 执行定时查找设备逻辑
            _LOGGER.info("执行定时查找设备操作...")
            find_result = await self._send_find_device_command(session)
            
            # 如果发送查找命令失败且是因为登录问题，尝试重新登录并再次查找
            if not find_result and not self.login_result:
                _LOGGER.info("查找设备失败，尝试重新登录")
                session.cookie_jar.clear()
                login_status = await self._relogin(session, allow_2fa=False)
                if login_status == LOGIN_OK:
                    self.login_result = True
                    _LOGGER.info("重新登录成功，再次尝试查找设备")
                    find_result = await self._send_find_device_command(session)
                else:
                    _LOGGER.warning("重新登录失败")
            
            _LOGGER.info("查找设备执行结果: %s", "成功" if find_result else "失败")
            
            # 查找命令发送后，等待一段时间让设备响应
            wait_time = 15
            _LOGGER.info(f"等待{wait_time}秒让设备响应定位请求...")
            await asyncio.sleep(wait_time)
            
            # 获取最新位置
            _LOGGER.info("开始获取设备位置数据...")
            location_data = await self._get_device_location(session)
            
            if not location_data:
                _LOGGER.warning("未能获取设备位置数据")
                # 如果是登录原因导致的失败，返回上次的数据
                if not self.login_result:
                    _LOGGER.info("登录状态已失效，返回上次的设备数据")
                    return self._last_devices_data or []
                    
                # 如果不是登录原因，可能是其他原因，创建基本设备信息
                if self._device_info:
                    _LOGGER.info("尝试创建基本设备信息...")
                    basic_devices = []
                    last_by_imei = {
                        str(item.get("imei")): item
                        for item in (self._last_devices_data or [])
                        if item.get("imei")
                    }
                    for vin in self._device_info:
                        imei = vin.get("imei", "")
                        basic = {
                            "imei": imei,
                            "model": vin.get("model", "未知设备"),
                            "version": vin.get("version", "未知版本"),
                            "device_status": "unknown"
                        }
                        prev = last_by_imei.get(str(imei)) or {}
                        for key in (
                            "device_lat",
                            "device_lon",
                            "device_accuracy",
                            "device_location_update_time",
                            "coordinate_type",
                            "device_power",
                        ):
                            if prev.get(key) is not None:
                                basic[key] = prev[key]
                        basic_devices.append(basic)
                    _LOGGER.debug("创建了%d个基本设备信息对象", len(basic_devices))
                    return basic_devices
                return self._last_devices_data or []
            else:
                _LOGGER.info(f"获取设备位置成功，返回{len(location_data)}个设备数据")
                last_by_imei = {
                    str(item.get("imei")): item
                    for item in (self._last_devices_data or [])
                    if item.get("imei")
                }
                for item in location_data:
                    if item.get("device_lat") is not None:
                        continue
                    prev = last_by_imei.get(str(item.get("imei"))) or {}
                    for key in (
                        "device_lat",
                        "device_lon",
                        "device_accuracy",
                        "device_location_update_time",
                        "coordinate_type",
                    ):
                        if item.get(key) is None and prev.get(key) is not None:
                            item[key] = prev[key]
                self._last_devices_data = location_data
                devices_data = location_data

            return devices_data

        except ClientConnectorError as error:
            _LOGGER.error(f"网络连接错误: {error}")
            if self._last_devices_data:
                _LOGGER.info("使用上次获取的设备数据")
                return self._last_devices_data
            raise UpdateFailed(f"网络连接错误: {error}")
        except Exception as e:
            _LOGGER.error(f"更新数据时发生未处理的异常: {str(e)}")
            if self._last_devices_data:
                _LOGGER.info("使用上次获取的设备数据")
                return self._last_devices_data
            raise UpdateFailed(f"未处理的异常: {str(e)}")

    async def async_config_entry_first_refresh(self):
        """执行首次刷新，在Home Assistant启动时调用."""
        _LOGGER.info("执行小米云服务首次数据刷新...")
        try:
            await super().async_config_entry_first_refresh()
        except ConfigEntryNotReady as err:
            # 如果有上次的设备数据，先使用它
            if self._last_devices_data:
                _LOGGER.warning("首次刷新失败，但使用缓存数据保持实体可用: %s", err)
                self.data = self._last_devices_data
                # 设置一个短暂的重试间隔
                asyncio.create_task(self._schedule_refresh_retry())
                return
            raise
            
    async def _schedule_refresh_retry(self):
        """在短暂延迟后尝试重新刷新数据."""
        await asyncio.sleep(60)  # 等待60秒
        _LOGGER.info("尝试重新刷新小米云服务数据...")
        await self.async_refresh()

    async def _update_interval_changed(self, new_interval):
        """更新间隔时间发生变化时处理."""
        try:
            new_interval = int(new_interval)  # 确保转换为整数
            if new_interval != self._scan_interval:
                old_interval = self._scan_interval
                self._scan_interval = new_interval
                _LOGGER.info("位置更新间隔已从 %s 分钟更改为 %s 分钟", old_interval, new_interval)
                
                # 更新协调器的更新间隔
                self.update_interval = datetime.timedelta(minutes=self._scan_interval)
                
                # 取消现有的刷新计划并重新安排
                self._schedule_refresh()
                
                # 可选：立即触发一次刷新以应用新设置
                await self.async_refresh()
                
                return True
            _LOGGER.debug("更新间隔未变化，仍为 %s 分钟", self._scan_interval)
            return False
        except Exception as e:
            _LOGGER.error("更新间隔设置失败: %s", str(e))
            return False
        
    def _schedule_refresh(self):
        """重新安排下一次刷新."""
        if self._unsub_refresh:
            self._unsub_refresh()
            
        self._unsub_refresh = async_track_point_in_utc_time(
            self.hass,
            self._handle_refresh_interval,
            utcnow() + self.update_interval
        )
        _LOGGER.info("已重新安排刷新时间，下次将在 %s 分钟后执行", self._scan_interval)

    async def _schedule_initial_refresh(self):
        """在初始化后立即调度一次以确保正确应用更新间隔."""
        await self.async_refresh()

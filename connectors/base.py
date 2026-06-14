"""
数据源连接器基类
提供统一的 API 调用封装：认证、限流、重试、分页、错误处理
"""

import time
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, Callable
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class RateLimiter:
    """简单的请求速率限制器"""

    def __init__(self, calls_per_second: float = 5.0):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self._last_call = 0.0

    def wait(self):
        """等待直到可以发起下一次请求"""
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call = time.monotonic()


class BaseConnector(ABC):
    """
    广告平台连接器基类

    所有平台连接器继承此类，统一实现：
    - HTTP Session 管理（连接池、重试策略）
    - API 限流
    - 分页自动翻页
    - 错误处理与重试
    - 请求日志
    """

    platform_name: str = "base"
    base_url: str = ""

    # 子类需覆盖
    max_retries: int = 3
    retry_backoff: float = 2.0  # 递增退避倍数
    rate_limit_cps: float = 5.0  # 每秒请求数
    page_size: int = 100
    timeout: int = 30  # 请求超时秒数

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.platform_name}")
        self.rate_limiter = RateLimiter(self.rate_limit_cps)
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建带有重试策略的 HTTP Session"""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.retry_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session

    @abstractmethod
    def authenticate(self) -> bool:
        """
        执行平台认证
        Returns: True 表示认证成功
        """
        pass

    @abstractmethod
    def get_headers(self) -> dict:
        """获取请求头（含认证 token）"""
        pass

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        data: dict = None,
        json_body: dict = None,
        **kwargs
    ) -> dict:
        """
        统一请求封装

        Args:
            method: HTTP method
            endpoint: API endpoint (相对于 base_url)
            params: URL 查询参数
            data: form data
            json_body: JSON body

        Returns:
            dict: 响应 JSON 数据

        Raises:
            APIError: API 返回错误
        """
        self.rate_limiter.wait()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self.get_headers()

        # 统一超时
        kwargs.setdefault("timeout", self.timeout)

        self.logger.debug(f"[{method}] {url} params={params}")

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_body,
                headers=headers,
                **kwargs
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            self._handle_http_error(e, url)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request failed: {e}")
            raise APIError(f"Network error: {e}", platform=self.platform_name, url=url)

    def _get(self, endpoint: str, params: dict = None) -> dict:
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, data: dict = None, json_body: dict = None) -> dict:
        return self._request("POST", endpoint, data=data, json_body=json_body)

    def _handle_http_error(self, error: requests.HTTPError, url: str):
        """处理 HTTP 错误"""
        status_code = error.response.status_code if error.response else None
        error_body = error.response.text if error.response else ""

        if status_code == 429:
            raise APIRateLimitError(
                f"Rate limited for {self.platform_name}",
                platform=self.platform_name,
                url=url,
                retry_after=error.response.headers.get("Retry-After")
            )
        elif status_code == 401 or status_code == 403:
            raise APIAuthError(
                f"Authentication failed for {self.platform_name}: {error_body}",
                platform=self.platform_name,
                url=url
            )
        else:
            raise APIError(
                f"API error {status_code}: {error_body}",
                platform=self.platform_name,
                url=url,
                status_code=status_code
            )

    def paginate(
        self,
        endpoint: str,
        params: dict = None,
        page_param: str = "page",
        size_param: str = "page_size",
        max_pages: int = None,
        data_key: str = "data",
        next_page_handler: Callable = None
    ) -> list[dict]:
        """
        自动分页拉取全量数据

        Args:
            endpoint: API endpoint
            params: 基础查询参数
            page_param: 翻页参数名 (page / offset / after)
            size_param: 页面大小参数名
            max_pages: 最大页数限制
            data_key: 响应中数据数组的 key
            next_page_handler: 自定义翻页逻辑 (resp) -> (next_params, has_more)

        Returns:
            list[dict]: 所有分页数据的合并列表
        """
        all_data = []
        current_params = (params or {}).copy()
        current_params.setdefault(size_param, self.page_size)
        page_count = 0

        while True:
            page_count += 1
            if max_pages and page_count > max_pages:
                self.logger.warning(f"Reached max pages limit ({max_pages})")
                break

            response = self._get(endpoint, current_params)

            # 自定义翻页
            if next_page_handler:
                next_params, has_more = next_page_handler(response)
                data = response.get(data_key, [])
                all_data.extend(data)
                if not has_more or not next_params:
                    break
                current_params = next_params
                continue

            # 默认翻页逻辑：data_key 数组 + page+1
            data = response.get(data_key, [])
            if not data:
                break

            all_data.extend(data)

            # 检查是否还有更多数据
            total = response.get("total_count") or response.get("total") or response.get("count")
            if total and len(all_data) >= total:
                break

            # 下一页
            current_params[page_param] = page_count + 1

        self.logger.info(f"Paginated {len(all_data)} records in {page_count} pages from {endpoint}")
        return all_data

    def fetch_date_range(
        self,
        fetch_func: Callable,
        start_date: str,
        end_date: str,
        date_format: str = "%Y-%m-%d",
        interval_days: int = 7
    ) -> list[dict]:
        """
        按日期范围拆分请求（避免单次查询数据量过大）

        Args:
            fetch_func: 接受 (start, end) 返回 list[dict] 的数据拉取函数
            start_date: 起始日期
            end_date: 结束日期
            date_format: 日期格式
            interval_days: 每次拉取的天数跨度

        Returns:
            list[dict]: 合并数据
        """
        all_data = []
        start = datetime.strptime(start_date, date_format)
        end = datetime.strptime(end_date, date_format)

        current = start
        while current <= end:
            chunk_end = min(current + timedelta(days=interval_days - 1), end)
            start_str = current.strftime(date_format)
            end_str = chunk_end.strftime(date_format)

            self.logger.info(f"Fetching {start_str} ~ {end_str}")
            chunk_data = fetch_func(start_str, end_str)
            all_data.extend(chunk_data)

            current = chunk_end + timedelta(days=1)

        return all_data


# ==================== 异常类定义 ====================


class APIError(Exception):
    """API 通用异常"""
    def __init__(self, message: str, platform: str = "unknown", url: str = "", status_code: int = None):
        self.platform = platform
        self.url = url
        self.status_code = status_code
        super().__init__(message)


class APIAuthError(APIError):
    """认证异常"""
    pass


class APIRateLimitError(APIError):
    """限流异常"""
    def __init__(self, message: str, platform: str = "unknown", url: str = "", retry_after: str = None):
        self.retry_after = retry_after
        super().__init__(message, platform, url)


class DataSourceError(APIError):
    """数据源异常（网络中断、空数据等）"""
    pass

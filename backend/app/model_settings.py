"""Request-scoped model connections. Credentials never enter persistent storage."""
import ipaddress
import socket
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

import httpx

from .errors import ApiError


def validate_endpoint(base_url: str, resolve_dns: bool = True) -> str:
    """Allow public HTTPS and explicit local model servers, block metadata/LAN.

    The application remains a local, single-user development service. Do not
    expose credential-bearing endpoints to untrusted users on a public network.
    """
    try:
        parts = urlsplit(base_url)
        port = parts.port
        host = parts.hostname
        if (not host or parts.scheme not in {'http', 'https'} or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment
                or any(ord(c) < 33 or ord(c) == 127 for c in base_url)
                or '\\' in base_url or not (port is None or 1 <= port <= 65535)):
            raise ValueError()
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        loopback = host.lower() == 'localhost' or (literal is not None and literal.is_loopback)
        if parts.scheme == 'http' and not loopback:
            raise ValueError()
        if literal is not None and not literal.is_global and not literal.is_loopback:
            raise ValueError()
        if resolve_dns and literal is None:
            addresses = socket.getaddrinfo(host, port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            if not addresses:
                raise ValueError()
            for item in addresses:
                address = ipaddress.ip_address(item[4][0])
                if loopback:
                    if not address.is_loopback:
                        raise ValueError()
                elif not address.is_global:
                    raise ValueError()
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
    except socket.gaierror as exc:
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Không phân giải được địa chỉ model provider.', True) from exc
    except (ValueError, TypeError) as exc:
        raise ApiError(422, 'INVALID_MODEL_ENDPOINT', 'Dùng HTTPS công khai hoặc HTTP localhost; không dùng thông tin đăng nhập, query hay địa chỉ mạng nội bộ trong URL.') from exc


def resolve_generation_settings(settings, config):
    if config is None:
        return settings
    if config.backend == 'extractive':
        return replace(settings, generation_backend='extractive', llm_base_url='', llm_model='', llm_api_key='')
    return replace(settings, generation_backend='api', llm_base_url=validate_endpoint(config.base_url),
                   llm_model=config.model, llm_api_key=config.api_key.get_secret_value())


def fetch_models(config) -> list[str]:
    base_url = validate_endpoint(config.base_url)
    headers = {}
    key = config.api_key.get_secret_value()
    if key:
        headers['Authorization'] = f'Bearer {key}'
    try:
        response = httpx.get(base_url + '/models', headers=headers, timeout=20, follow_redirects=False, trust_env=False)
        if response.status_code in {401, 403}:
            raise ApiError(502, 'MODEL_AUTH_FAILED', 'Provider từ chối API key. Kiểm tra key và quyền truy cập model.')
        if response.is_redirect:
            raise ApiError(422, 'INVALID_MODEL_ENDPOINT', 'Provider chuyển hướng URL; hãy nhập trực tiếp base URL chính thức.')
        response.raise_for_status()
        data = response.json()
        items = data.get('data') if isinstance(data, dict) else None
        if not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in items):
            raise ValueError()
        return sorted({item['id'] for item in items if item['id'] and len(item['id']) <= 200})
    except ApiError:
        raise
    except httpx.TimeoutException as exc:
        raise ApiError(504, 'UPSTREAM_TIMEOUT', 'Provider phản hồi quá thời gian.', True) from exc
    except httpx.HTTPStatusError as exc:
        raise ApiError(502, 'UPSTREAM_ERROR', 'Provider không tải được danh sách model.', exc.response.status_code >= 500 or exc.response.status_code == 429) from exc
    except httpx.RequestError as exc:
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Không kết nối được model provider.', True) from exc
    except (ValueError, TypeError) as exc:
        raise ApiError(502, 'MODEL_LIST_BAD_RESPONSE', 'Provider không trả danh sách model theo định dạng tương thích.') from exc

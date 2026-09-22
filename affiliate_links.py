"""Shared affiliate conversion for queued and dashboard posts."""
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config
from userbot.extrape_agent import get_sync_link, _trusted_affiliate_url

logger = logging.getLogger('dealbuddy')


def get_affiliate_link(original_url):
    try:
        parts = urlsplit(original_url)
        host = (parts.hostname or '').lower()
        if (parts.scheme not in ('http', 'https') or parts.username or parts.password
                or parts.port not in (None, 80, 443)
                or not (host == 'flipkart.com' or host.endswith('.flipkart.com')
                        or host in ('fkrt.it', 'fkrt.co'))):
            return None
    except (ValueError, TypeError):
        return None
    try:
        converted = get_sync_link(original_url)
        trusted = _trusted_affiliate_url(converted, original_url)
        if trusted:
            return trusted
    except Exception as exc:
        logger.warning('Affiliate conversion failed (%s)', type(exc).__name__)

    # Adding query parameters to a short URL does not establish attribution.
    affid = config._load_secret('EXTRAPE_AFFID')
    if not affid or host in ('fkrt.it', 'fkrt.co'):
        logger.warning('No usable affiliate link; post held back.')
        return None
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['affid'] = affid
    query['affExtParam1'] = config._load_secret('EXTRAPE_PARAM1')
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

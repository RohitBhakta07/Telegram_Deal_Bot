"""Serialize publication and retain successful delivery per channel."""
import logging
import threading

from database import db_manager
from telegram.bot import send_telegram_deal_post
from telegram.deal_media import post_deal_message

_publish_lock = threading.Lock()
logger = logging.getLogger('dealbuddy')


def publish_deal(deal, message, affiliate_link, category, post_type, can_send=None):
    if not affiliate_link:
        return 0
    link = deal['link']
    sent = 0
    with _publish_lock:
        delivered = db_manager.delivered_channels(link)
        for channel in db_manager.get_all_channels():
            if can_send is not None and not can_send():
                break
            if channel[0] in delivered:
                continue
            try:
                result = post_deal_message(send_telegram_deal_post, channel[0], message, deal)
            except Exception as exc:
                logger.error('Channel delivery failed (%s)', type(exc).__name__)
                continue
            if result:
                # Persist immediately, so a failure on the next channel is retryable.
                db_manager.record_channel_delivery(link, channel[0])
                db_manager.save_deal(deal.get('title', ''), link, affiliate_link,
                                     category, deal.get('image', ''), post_type)
                sent += 1
                logger.info('Deal album delivered; channel receipt saved.')
            else:
                logger.warning('Deal album failed; channel remains eligible for retry.')
    return sent

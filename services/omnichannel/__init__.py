"""
Omnichannel Messaging Services Package
پکیج ارسال چندکاناله املاک سقف (تلگرام، بله، ایتا، واتساپ، روبیکا)
"""
from .base import BaseChannelAdapter
from .dispatcher import omnichannel_dispatcher

__all__ = ['BaseChannelAdapter', 'omnichannel_dispatcher']

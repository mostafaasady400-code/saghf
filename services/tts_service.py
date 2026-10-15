"""
=============================================================================
سامانه تبدیل متن به گفتار طبیعی فارسی (Persian Neural TTS Service)
پشتیبانی از صدای استودیویی فوق‌العاده انسانی مایکروسافت (fa-IR-FaridNeural / DilaraNeural)
قابلیت پاک‌سازی متن، حافظه نهان (In-Memory Cache) و خروجی استریم صوتی MP3
=============================================================================
"""

import asyncio
import re
import os
import logging
from io import BytesIO
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# حافظه نهان در سطح حافظه موقت رم برای کاهش زمان پاسخ‌دهی جملات پرتکرار
_TTS_CACHE: Dict[str, bytes] = {}
MAX_CACHE_ITEMS = 150

# صدای پیش‌فرض مشاور ارشد فایلینگ سقف
DEFAULT_VOICE = "fa-IR-FaridNeural"

def clean_text_for_speech(text: str) -> str:
    """
    پاک‌سازی و بهینه‌سازی متن فارسی جهت خوانش کاملاً طبیعی و انسانی:
    - حذف اموجی‌ها، تگ‌های مارک‌داون، لینک‌ها و کاراکترهای نامتعارف
    - اصلاح فاصله‌ها و علائم نگارشی برای ایجاد مکث‌های طبیعی
    """
    if not text:
        return ""

    # حذف تگ‌های HTML
    cleaned = re.sub(r'<[^>]+>', ' ', text)
    
    # حذف لینک‌های اینترنتی
    cleaned = re.sub(r'https?://\S+|www\.\S+', ' ', cleaned)
    
    # حذف نشانه‌گذاری‌های مارک‌داون (*, _, #, `, ~, >, |, -)
    cleaned = re.sub(r'[*_#`~>|]', '', cleaned)
    
    # تبدیل خط فاصله‌های متوالی و کاراکترهای تزئینی
    cleaned = re.sub(r'[-=]{2,}', ' ', cleaned)
    
    # حذف اموجی‌ها و سمبل‌های غیرمتنی
    emoji_pattern = re.compile(
        "["
        "\U00010000-\U0010FFFF"
        "\u2600-\u27BF"
        "\u2300-\u23FF"
        "\u2B50\u2B55\u200D\uFE0F"
        "]+",
        flags=re.UNICODE
    )
    cleaned = emoji_pattern.sub(' ', cleaned)
    
    # حذف پرانتزها و براکت‌های اضافی اما نگه داشتن محتوا
    cleaned = cleaned.replace('(', '، ').replace(')', ' ').replace('[', ' ').replace(']', ' ')
    cleaned = cleaned.replace('«', ' ').replace('»', ' ').replace('"', ' ')
    
    # جایگزینی کلمات انگلیسی شناخته‌شده به تلفظ روان فارسی در صورت لزوم
    cleaned = cleaned.replace('NER', 'سیستم تحلیل').replace('AI', 'هوش مصنوعی')
    
    # اصلاح فاصله‌های اضافی و تنظیم مکث با ویرگول و نقطه
    cleaned = re.sub(r'[ \t]+', ' ', cleaned).strip()
    
    return cleaned

async def _synthesize_edge_tts(text: str, voice: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    buf = BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    return buf.getvalue()

def synthesize_speech(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """
    تولید بایت‌های فایل صوتی MP3 با صدای طبیعی فارسی فرید
    با رعایت کَش هوشمند و اجرای ایمن ناهمگام
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        cleaned = "سلام، در خدمت شما هستم."
        
    cache_key = f"{voice}::{cleaned}"
    if cache_key in _TTS_CACHE:
        return _TTS_CACHE[cache_key]

    try:
        # مدیریت Event Loop برای سازگاری کامل با ترد‌های Flask و گیت‌وی‌ها
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                audio_bytes = pool.submit(lambda: asyncio.run(_synthesize_edge_tts(cleaned, voice))).result(timeout=12)
        else:
            audio_bytes = loop.run_until_complete(_synthesize_edge_tts(cleaned, voice))

        if audio_bytes and len(audio_bytes) > 200:
            # نگهداری در کش موقت
            if len(_TTS_CACHE) >= MAX_CACHE_ITEMS:
                _TTS_CACHE.pop(next(iter(_TTS_CACHE)))
            _TTS_CACHE[cache_key] = audio_bytes
            return audio_bytes
        else:
            logger.warning("[TTS] خروجی صوت دریافت نشد یا حجم آن کم است.")
            return b""

    except Exception as e:
        logger.error(f"[TTS] خطا در سنتز گفتار فارسی: {e}", exc_info=True)
        return b""

def pregenerate_welcome_audio(output_filepath: str) -> bool:
    """
    پیش‌تولید فایل صوتی خوش‌آمدگویی اولیه دستیار صوتی و ذخیره روی دیسک
    """
    welcome_text = "سلام، خوش آمدید به سقف. من مشاور ارشد فایلینگ هستم. برای خرید یا اجاره چه متراژ و در چه منطقه‌ای مد نظرتونه؟"
    try:
        os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
        audio = synthesize_speech(welcome_text)
        if audio:
            with open(output_filepath, "wb") as f:
                f.write(audio)
            logger.info(f"[TTS] فایل خوش‌آمدگویی با موفقیت ذخیره شد: {output_filepath}")
            return True
    except Exception as e:
        logger.error(f"[TTS] خطا در ذخیره فایل صوتی خوش‌آمدگویی: {e}")
    return False

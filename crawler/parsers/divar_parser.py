"""
Divar Structured Data Parser for Saghf Platform.
Extracts normalized real estate listings from Divar Web/API payloads,
including Widget Tree parsing, Preloaded State extraction, and Anti-Agency verification.
Zero-Mock Implementation.
"""

import re
import json
from typing import Dict, Any, List, Optional, Tuple
from crawler.schemas import parse_price, persian_to_english_numbers

class DivarStructuredParser:
    """
    موتور استخراج ساختاریافته داده‌های آگهی دیوار
    پارس هوشمند درخت ویجت‌ها، مشخصات فنی، قیمت‌ها، تصاویر CDN و وضعیت مالکیت شخصی
    """

    @staticmethod
    def parse_widget_tree(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        پارس عمیق ساختار بخش‌ها و ویجت‌های آگهی دیوار (Post Details Widgets)
        """
        parsed: Dict[str, Any] = {
            'title': '',
            'description': '',
            'total_price': 0,
            'meter_price': 0,
            'deposit': 0,
            'monthly_rent': 0,
            'area': 85,
            'rooms': 1,
            'floor': 1,
            'total_floors': None,
            'build_year': 1400,
            'has_elevator': False,
            'has_parking': False,
            'has_warehouse': False,
            'has_balcony': False,
            'features': [],
            'images': [],
            'is_agency': False,
            'agency_reasons': []
        }

        if not data or not isinstance(data, dict):
            return parsed

        sections = data.get('sections', [])
        if isinstance(sections, dict):
            sections = sections.get('sections', [])

        images: List[str] = []
        features: List[str] = []

        for sec in sections:
            for w in sec.get('widgets', []):
                wt = w.get('widget_type', '')
                wd = w.get('data', {})

                # ۰. بررسی و شناسایی حساب‌های مشاورین املاک و پنل‌های تجاری دیوار
                if wt == 'LAZY_SECTION':
                    req_data = wd.get('request_data', {})
                    biz_type = str(req_data.get('post_business_type', '')).lower()
                    if biz_type in ['premium-panel', 'business', 'agency', 'consultant', 'real_estate_agency']:
                        parsed['is_agency'] = True
                        parsed['agency_reasons'].append(f"Business Panel: {biz_type}")
                elif any(k in wt.lower() for k in ['agency_info', 'business_section', 'seller_profile']):
                    parsed['is_agency'] = True
                    parsed['agency_reasons'].append(f"Agency Widget: {wt}")

                # ۱. عنوان و تیتر اصلی
                elif wt in ['TITLE_ROW', 'HEADER_ROW', 'LEGEND_TITLE_ROW']:
                    t = wd.get('title') or wd.get('text') or ''
                    if t and not parsed['title']:
                        parsed['title'] = t.strip()

                # ۲. متن توضیحات کامل آگهی
                elif wt == 'DESCRIPTION_ROW':
                    desc = wd.get('text', '')
                    if desc:
                        parsed['description'] = desc.strip()

                # ۳. استخراج تصاویر واقعی CDN دیوار
                elif wt in ['IMAGE_CAROUSEL', 'IMAGE_SLIDER', 'IMAGES_ROW']:
                    for it in wd.get('items', []):
                        img_url = it.get('image', {}).get('url') or it.get('url')
                        if img_url and 'divarcdn.com' in img_url and img_url not in images:
                            images.append(img_url)

                # ۴. مشخصات پایه ابعادی (متراژ، سال ساخت، تعداد اتاق)
                elif wt == 'GROUP_INFO_ROW':
                    for item in wd.get('items', []):
                        title = item.get('title', '')
                        val = item.get('value', '')
                        val_en = persian_to_english_numbers(val)
                        if 'متراژ' in title:
                            m = re.search(r'\d+', val_en)
                            if m:
                                parsed['area'] = int(m.group(0))
                        elif 'ساخت' in title:
                            m = re.search(r'\d+', val_en)
                            if m:
                                parsed['build_year'] = int(m.group(0))
                        elif 'اتاق' in title:
                            if 'بدون' in val:
                                parsed['rooms'] = 0
                            else:
                                m = re.search(r'\d+', val_en)
                                if m:
                                    parsed['rooms'] = int(m.group(0))

                # ۵. قیمت‌ها و طبقات (UNEXPANDABLE_ROW)
                elif wt == 'UNEXPANDABLE_ROW':
                    title = wd.get('title', '')
                    val = wd.get('value', '')
                    val_en = persian_to_english_numbers(val)

                    if 'قیمت کل' in title:
                        p = parse_price(val)
                        if p > 0:
                            parsed['total_price'] = p
                    elif 'قیمت هر متر' in title:
                        mp = parse_price(val)
                        if mp > 0:
                            parsed['meter_price'] = mp
                    elif 'ودیعه' in title or 'رهن' in title:
                        dep = parse_price(val)
                        if dep > 0:
                            parsed['deposit'] = dep
                    elif 'اجاره' in title:
                        rnt = parse_price(val)
                        if rnt > 0:
                            parsed['monthly_rent'] = rnt
                    elif 'طبقه' in title:
                        m_floors = re.search(r'(\d+)\s*از\s*(\d+)', val_en)
                        if m_floors:
                            parsed['floor'] = int(m_floors.group(1))
                            parsed['total_floors'] = int(m_floors.group(2))
                        elif 'همکف' in val:
                            parsed['floor'] = 0
                        elif 'زیر' in val:
                            parsed['floor'] = -1
                        else:
                            m_fl = re.search(r'\d+', val_en)
                            if m_fl:
                                parsed['floor'] = int(m_fl.group(0))

                # ۶. امکانات رفاهی و تگ‌ها (FEATURE_ROW, TAG_ROW, GROUP_FEATURE_ROW)
                elif wt in ['GROUP_FEATURE_ROW', 'FEATURE_ROW', 'TAG_ROW']:
                    items = wd.get('items', [])
                    for it in items:
                        t = it.get('title') or it.get('name') or ''
                        available = it.get('available', True)
                        if t and available:
                            features.append(t)
                            if 'آسانسور' in t:
                                parsed['has_elevator'] = True
                            elif 'پارکینگ' in t:
                                parsed['has_parking'] = True
                            elif 'انباری' in t:
                                parsed['has_warehouse'] = True
                            elif 'بالکن' in t or 'تراس' in t:
                                parsed['has_balcony'] = True

        parsed['images'] = images
        parsed['features'] = list(dict.fromkeys(features))
        parsed['is_agency_post'] = parsed['is_agency']
        return parsed

    @staticmethod
    def _extract_balanced_state(html_text: str) -> dict:
        marker = '__PRELOADED_STATE__'
        s_idx = html_text.find(marker)
        if s_idx < 0:
            return {}
        eq_idx = html_text.find('=', s_idx)
        if eq_idx < 0:
            return {}
        json_start = eq_idx + 1
        while json_start < len(html_text) and html_text[json_start].isspace():
            json_start += 1
        if json_start >= len(html_text) or html_text[json_start] != '{':
            return {}

        depth = 0
        in_str = False
        esc = False
        end_pos = -1
        for i in range(json_start, len(html_text)):
            ch = html_text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end_pos = i
                        break

        if end_pos > 0:
            try:
                return json.loads(html_text[json_start:end_pos + 1])
            except Exception:
                pass
        return {}

    @classmethod
    def parse_preloaded_state(cls, html_text: str) -> List[Dict[str, Any]]:
        """
        استخراج آگهی‌های خام از آبجکت __PRELOADED_STATE__ صفحه جستجوی دیوار
        پشتیبانی دوگانه از ساختارهای browse.postList و ساختار مدرن nb.listWidgets با الگوریتم Balanced Brackets
        """
        items: List[Dict[str, Any]] = []
        state = cls._extract_balanced_state(html_text)
        if not state:
            m = re.search(r'(?:window\.)?__PRELOADED_STATE__\s*=\s*(\{.+?\});?(?:\s*</script>|\s*$)', html_text, re.DOTALL)
            if m:
                try:
                    state = json.loads(m.group(1))
                except Exception:
                    state = {}

        if not state:
            return items

        try:
            browse = state.get('browse', {}) or {}
            post_list = browse.get('postList') or browse.get('items') or []
            if isinstance(post_list, dict):
                post_list = post_list.get('postList') or post_list.get('items') or []

            for p in post_list:
                data = p.get('data', {}) or p
                token = data.get('token') or data.get('action', {}).get('payload', {}).get('token')
                title = data.get('title') or ''
                if not token or not title:
                    continue

                district = data.get('district') or data.get('action', {}).get('payload', {}).get('district') or 'تهران'
                middle_str = data.get('middle_description_string') or data.get('middle_description_text') or ''
                bottom_str = data.get('bottom_description_sub_title') or data.get('bottom_description_text') or ''
                img = data.get('image') or data.get('image_url')
                if isinstance(img, dict):
                    img = img.get('url')

                items.append({
                    'token': str(token),
                    'title': str(title),
                    'district': str(district),
                    'middle_description': str(middle_str),
                    'bottom_description': str(bottom_str),
                    'image': img
                })

            # بررسی ساختار مدرن nb.listWidgets
            if not items:
                nb = state.get('nb', {}) or {}
                widgets = nb.get('listWidgets') or nb.get('list_widgets') or state.get('listWidgets') or []
                for w in widgets:
                    wdata = w.get('data', {}) if isinstance(w, dict) else {}
                    if not isinstance(wdata, dict):
                        continue
                    dto = wdata.get('dto', {}) if isinstance(wdata.get('dto'), dict) else {}
                    d = dto.get('data', {}) if isinstance(dto.get('data'), dict) else (wdata.get('data', {}) if isinstance(wdata.get('data'), dict) else wdata)
                    action = d.get('action', {}) if isinstance(d, dict) else {}
                    payload = action.get('payload', {}) if isinstance(action, dict) else {}
                    token = payload.get('token') or d.get('token')
                    title = d.get('title') or payload.get('web_info', {}).get('title')
                    if not token or not title:
                        continue

                    district = payload.get('web_info', {}).get('district_persian') or d.get('district') or 'تهران'
                    middle_str = d.get('middle_description_text') or d.get('middle_description_string') or ''
                    bottom_str = d.get('bottom_description_text') or d.get('bottom_description_sub_title') or ''
                    img = d.get('image_url') or d.get('image')
                    if isinstance(img, dict):
                        img = img.get('url')

                    items.append({
                        'token': str(token),
                        'title': str(title),
                        'district': str(district),
                        'middle_description': str(middle_str),
                        'bottom_description': str(bottom_str),
                        'image': img
                    })

        except Exception:
            pass

        return items

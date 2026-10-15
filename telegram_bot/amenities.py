"""Require explicit amenities evidence; unknown is not a positive match."""
ALIASES = {
    'بالکن': ('بالکن', 'تراس'), 'لابی': ('لابی',), 'لابی‌من': ('لابی‌من', 'لابی من', 'لابیمن'),
    'سرایدار': ('سرایدار',), 'دوربین مداربسته': ('دوربین مداربسته', 'دوربین مدار بسته'),
    'استخر': ('استخر',), 'سونا': ('سونا',), 'جکوزی': ('جکوزی',),
    'روف‌گاردن': ('روف‌گاردن', 'روف گاردن', 'روفگاردن'), 'سالن ورزش': ('سالن ورزش', 'باشگاه بدنسازی'),
    'سالن اجتماعات': ('سالن اجتماعات',),
}


def normalize(value):
    return ''.join(str(value).replace('ي','ی').replace('ك','ک').replace('‌',' ').split())


def extra_features_match(item, required):
    recorded = item.get('features') or []
    if not isinstance(recorded, (list,tuple,set)):
        recorded = []
    explicit = {normalize(name) for name in recorded if isinstance(name,str)}
    for name in required or []:
        if name not in ALIASES:
            continue
        if name=='بالکن' and item.get('has_balcony') is True:
            continue
        if not any(normalize(alias) in explicit for alias in ALIASES[name]):
            return False
    return True


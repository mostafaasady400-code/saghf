from crawler.parsers.divar_listing_dom import parse_listing_metadata


def test_missing_values_are_unknown():
    data = parse_listing_metadata("<h1>آگهی</h1>")
    assert "area" not in data
    assert "rooms" not in data
    assert "deposit" not in data
    assert data["images"] == []


def test_rendered_metadata_and_strict_cdn_host():
    html = '''<div class="description-abc"><p class="kt-description-row__text">شرح کامل مالک</p></div>
    <div class="kt-group-row"><span class="kt-group-row-item__title">متراژ</span><span class="kt-group-row-item__title">اتاق</span><span class="kt-group-row-item__value">۸۰</span><span class="kt-group-row-item__value">۲</span></div>
    <div class="kt-unexpandable-row"><span class="kt-unexpandable-row__title">ودیعه</span><span class="kt-unexpandable-row__value">۵۰۰٬۰۰۰٬۰۰۰ تومان</span></div>
    <img src="https://s100.divarcdn.com/static/photo.jpg"><img src="https://divarcdn.com.attacker.example/fake.jpg"><img src="https://s100.divarcdn.com/static/photo.jpg">'''
    data = parse_listing_metadata(html)
    assert data["description"] == "شرح کامل مالک"
    assert data["area"] == 80
    assert data["rooms"] == 2
    assert data["deposit"] == 500_000_000
    assert data["images"] == ["https://s100.divarcdn.com/static/photo.jpg"]

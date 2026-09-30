from crawler.hybrid_divar import HybridDivarCrawler
from crawler.parsers.divar_dom_contact import DivarDOMContactParser


def test_extracts_owner_mobile_from_tel_link():
    html = """
    <html><head><meta property="og:title" content="فروش شخصی آپارتمان در پونک"></head>
    <body>
      <h1>فروش شخصی آپارتمان در پونک</h1>
      <div itemprop="description">مالک هستم؛ بدون واسطه تماس بگیرید.</div>
      <a href="tel:+989128765432">تماس با مالک</a>
    </body></html>
    """

    result = DivarDOMContactParser.parse(html)

    assert result["is_personal_owner"] is True
    assert result["is_agency_post"] is False
    assert result["phone"] == "09128765432"
    assert result["phone_source"] == "dom_tel_href"
    assert result["phone_confidence"] >= 98


def test_extracts_persian_spaced_number_only_in_contact_context():
    html = """
    <html><body>
      <h1>اجاره مستقیم واحد مسکونی</h1>
      <p data-testid="description">واگذاری توسط مالک و بدون واسطه</p>
      <button aria-label="شماره تماس مالک">شماره مالک: ۰۹۱۲ ۸۷۶ ۵۴۳۲</button>
    </body></html>
    """

    result = DivarDOMContactParser.parse(html)

    assert result["phone"] == "09128765432"
    assert result["phone_source"] == "dom_contact_context"


def test_extracts_contact_from_embedded_json_without_javascript_execution():
    html = """
    <html><body>
      <h1>فروش آپارتمان شخصی</h1>
      <div class="kt-description-row__text">من مالک واحد هستم.</div>
      <script type="application/ld+json">
        {"@type":"RealEstateListing","telephone":"09128675432"}
      </script>
    </body></html>
    """

    result = DivarDOMContactParser.parse(html)

    assert result["phone"] == "09128675432"
    assert result["phone_source"] == "dom_json_telephone"


def test_suppresses_phone_when_structured_dom_marks_business_account():
    html = """
    <html><body>
      <h1>فروش آپارتمان در پونک</h1>
      <div itemprop="description">فایل مناسب بازدید</div>
      <a href="tel:09128765432">تماس</a>
      <script type="application/json">
        {"action_log":{"server_side_info":{"info":{"is_business":true,
        "business_type":"agency","agency_id":"ag-12"}}}}
      </script>
    </body></html>
    """

    result = DivarDOMContactParser.parse(html)

    assert result["is_agency_post"] is True
    assert result["is_personal_owner"] is False
    assert result["phone"] is None
    assert result["agency_evidence"]


def test_ignores_unlabelled_prices_and_tracking_numbers():
    html = """
    <html><body>
      <h1>فروش شخصی واحد مسکونی</h1>
      <p itemprop="description">مالک هستم. قیمت 09128765432 تومان نیست؛ کد رهگیری است.</p>
      <div>شناسه رهگیری: 09128675432</div>
    </body></html>
    """

    result = DivarDOMContactParser.parse(html)

    assert result["is_personal_owner"] is True
    assert result["phone"] is None


def test_normalizes_database_and_url_token_forms():
    assert HybridDivarCrawler.normalize_post_token("divar_AbC-12_x") == "AbC-12_x"
    assert HybridDivarCrawler.normalize_post_token("https://divar.ir/v/AbC-12_x?ref=test") == "AbC-12_x"
    assert HybridDivarCrawler.normalize_post_token("../not-valid") == "not-valid"
    assert HybridDivarCrawler.normalize_post_token("bad token") == ""


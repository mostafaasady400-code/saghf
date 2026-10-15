import pytest
from crawler.strict_owner_guard import strict_decision, install_strict_owner_guard
from crawler.owner_filter import OwnerFilter


@pytest.mark.parametrize("description", [
    "دوخوابه بسیار تمیز املاک ارغوان لطفا همکاران تماس نگیرن",
    "مالک هستم؛ املاک ارغوان لطفا همکاران تماس نگیرن",
    "مالک هستم؛ همکاران املاک تماس نگیرند",
    "مالک هستم؛ فایل شخصی، کلید در اختیار",
    "مالک هستم؛ عکس مشابه",
    "مالک هستم؛ اـمـلاك ارغوان",
    "مالک هستم؛ فایل‌شخصی",
    "مالک مستقیم هستم؛ واحد خودم را می‌فروشم",
    "مالک‌مستقیم هستم",
    "مالک هستم؛ ارتباط با مالک مستقیم",
])
def test_agency_terms_precede_every_disclaimer(description):
    result = strict_decision("۹۵ متر دوخوابه پونک", description, {"business_type": "personal"})
    assert not result.allowed and result.status == "rejected_forbidden_words"


@pytest.mark.parametrize("description", ["مالک هستم؛ مشاوران تماس نگیرند", "صاحبخانه هستم؛ آشپزخانه بزرگ", "مالک هستم؛ لطفا املاک تماس نگیرند"])
def test_owner_claim_with_neutral_disclaimer_is_not_false_positive(description):
    assert strict_decision("آپارتمان", description).allowed


@pytest.mark.parametrize("description", ["مشاوران تماس نگیرند", "املاک تماس نگیرند", "واحد تمیز آماده تحویل", "من مالک نیستم"])
def test_personal_account_and_disclaimer_are_not_owner_proof(description):
    assert strict_decision("آپارتمان", description, {"business_type": "personal"}).status == "rejected_unverified_owner"


def test_business_metadata_overrides_owner_claim():
    assert not strict_decision("آپارتمان", "مالک هستم", {"publisher": {"is_business": True}}).allowed
    assert not strict_decision("آپارتمان", "مالک هستم", {"business_type": "real_estate_agency"}).allowed


@pytest.mark.parametrize('phrase', [
    'مناسب سکونت خانواده و (مشتریان) سخت‌پسند.',
    'مناسب سکونت خانواده و مشتریان سخت پسند',
    'مناسب سکونت خانواده، مشتریان سخت-پسند',
    'مناسب سکونت خانواده و «مشتریان» سختپسند',
])
def test_family_and_clients_marketing_phrase_is_rejected(phrase):
    decision = strict_decision('آپارتمان', 'مالک هستم؛ ' + phrase, {'business_type': 'personal'})
    assert not decision.allowed
    assert 'سکونت خانواده و مشتریان سخت‌پسند' in decision.terms
    install_strict_owner_guard()
    result = OwnerFilter.evaluate(platform='divar', title='آپارتمان', description='مالک هستم؛ ' + phrase, widget_data={'business_type': 'personal'})
    assert not result.is_personal


@pytest.mark.parametrize('phrase', ['مناسب سکونت خانواده', 'مناسب سکونت خانواده سخت‌پسند', 'برای سکونت خانواده خودم خریده‌ام'])
def test_family_residence_alone_is_not_intermediary_evidence(phrase):
    assert strict_decision('آپارتمان', 'مالک هستم؛ ' + phrase, {'business_type': 'personal'}).allowed


def test_adapter_is_idempotent_and_preserves_original_result_contract():
    install_strict_owner_guard()
    first = OwnerFilter.evaluate.__func__
    install_strict_owner_guard()
    assert OwnerFilter.evaluate.__func__ is first
    result = OwnerFilter.evaluate(platform="divar", title="۹۵ متر", description="املاک ارغوان لطفا همکاران تماس نگیرن", widget_data={"business_type": "personal"})
    assert result.is_personal is False
    assert result.status == "rejected_forbidden_words"
    assert result.metadata["version"] == "strict-owner-v1"

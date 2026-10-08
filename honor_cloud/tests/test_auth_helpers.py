from load_module import load

auth_helpers = load("auth_helpers.py")


def test_flag_true():
    assert auth_helpers.flag_true(True)
    assert auth_helpers.flag_true("true")
    assert auth_helpers.flag_true("1")
    assert not auth_helpers.flag_true(False)
    assert not auth_helpers.flag_true("no")


def test_should_offer_reauth_transient():
    assert not auth_helpers.should_offer_reauth("LOGIN_IN_PROGRESS", False)
    assert not auth_helpers.should_offer_reauth("NO_SESSION", True)


def test_should_offer_reauth_expired():
    assert auth_helpers.should_offer_reauth("AUTH_EXPIRED", False)
    assert auth_helpers.should_offer_reauth("", True, auth_required=True)

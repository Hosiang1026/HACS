from load_module import load

const = load("const.py")


def test_parse_windows_valid():
    assert const.parse_windows("07:00-09:00,17:00-20:00") == [(420, 540), (1020, 1200)]


def test_parse_windows_empty():
    assert const.parse_windows("") == []


def test_parse_windows_invalid():
    assert const.parse_windows("bad") is None


def test_in_windows():
    assert const.in_windows(480, [(420, 540)]) is True
    assert const.in_windows(600, [(420, 540)]) is False


def test_pairs_roundtrip():
    text = const.pairs_to_windows_text([("07:00", "09:00"), ("none", "none"), ("none", "none")])
    assert text == "07:00-09:00"
    pairs = const.windows_text_to_pairs(text or "", 3)
    assert pairs[0] == ("07:00", "09:00")


def test_resolve_max_interval_legacy_seconds():
    assert const.resolve_max_interval_minutes({const.CONF_INTERVAL: 600}, {}) == 10


def test_resolve_max_interval_minutes():
    assert const.resolve_max_interval_minutes({const.CONF_MAX_INTERVAL: 15}, {}) == 15


def test_opt_windows_text_list():
    assert const.opt_windows_text(["a", "b"], "") == "a,b"


def test_default_locate_options_keys():
    opts = const.default_locate_options()
    assert const.CONF_MAX_INTERVAL in opts

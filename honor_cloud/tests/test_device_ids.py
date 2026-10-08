from load_module import load

device_ids = load("device_ids.py")


def test_generate_slug():
    assert device_ids.generate_slug("Honor Magic", "abc123456789") == "honor_magic"


def test_get_stable_device_id():
    assert device_ids.get_stable_device_id({"deviceId": "X"}) == "X"


def test_wgs84_outside_china():
    lng, lat = device_ids.wgs84_to_gcj02(0.0, 0.0)
    assert lng == 0.0 and lat == 0.0

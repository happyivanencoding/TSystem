from src.services.region_bucket import (
    NORTH_AMERICA,
    OTHERS,
    WEST_EUROPE,
    region_bucket_value,
)


def test_region_bucket_west_europe():
    assert region_bucket_value("West Europe") == WEST_EUROPE


def test_region_bucket_na():
    assert region_bucket_value("North America") == NORTH_AMERICA


def test_region_bucket_others():
    assert region_bucket_value("Asia") == OTHERS
    assert region_bucket_value(None) == OTHERS

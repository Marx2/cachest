import stats


def setup_function():
    stats._registry.clear()


def test_record_hit():
    stats.record("/dy/{ticker}", "HIT")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 1
    assert s.misses == 0
    assert s.stale == 0


def test_record_miss():
    stats.record("/dy/{ticker}", "MISS")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 0
    assert s.misses == 1
    assert s.stale == 0


def test_record_stale():
    stats.record("/dy/{ticker}", "STALE")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 0
    assert s.misses == 0
    assert s.stale == 1


def test_record_accumulates():
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/dy/{ticker}", "MISS")
    stats.record("/dy/{ticker}", "STALE")
    s = stats.get("/dy/{ticker}")
    assert s.total == 4
    assert s.hits == 2
    assert s.misses == 1
    assert s.stale == 1


def test_record_multiple_routes():
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/fi/{isin}", "MISS")
    assert stats.get("/dy/{ticker}").hits == 1
    assert stats.get("/fi/{isin}").misses == 1
    assert stats.get("/dy/{ticker}").misses == 0


def test_all_routes_snapshot():
    stats.record("/a", "HIT")
    stats.record("/b", "MISS")
    snapshot = stats.all_routes()
    assert set(snapshot.keys()) == {"/a", "/b"}
    assert snapshot["/a"].hits == 1
    assert snapshot["/b"].misses == 1


def test_all_routes_is_copy():
    stats.record("/a", "HIT")
    snapshot = stats.all_routes()
    stats.record("/a", "HIT")
    assert snapshot["/a"].hits == 1  # snapshot not mutated


def test_unknown_x_cache_increments_total_only():
    stats.record("/dy/{ticker}", "UNKNOWN")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 0
    assert s.misses == 0
    assert s.stale == 0


def test_get_creates_empty():
    s = stats.get("/new/path")
    assert s.total == 0
    assert s.hits == 0

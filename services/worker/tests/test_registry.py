from messer_worker.registry import discover_jobs


def test_jobs_are_discovered_with_unique_names() -> None:
    names = [fn.__name__ for fn in discover_jobs()]
    assert "send_email" in names
    assert len(names) == len(set(names))

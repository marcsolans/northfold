from messer_scheduler.core import PeriodicTask, run_due


async def test_run_due_respects_intervals() -> None:
    calls: list[str] = []

    async def a() -> None:
        calls.append("a")

    async def boom() -> None:
        raise RuntimeError("isolated")

    tasks = [PeriodicTask("a", 10, a), PeriodicTask("boom", 10, boom)]
    await run_due(tasks, now=100)
    await run_due(tasks, now=105)
    await run_due(tasks, now=111)
    assert calls == ["a", "a"]

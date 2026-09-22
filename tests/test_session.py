"""Tests for adapter-wide BLE session arbitration."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.candy_house_ble.session import SesameBLESessionGate


@pytest.mark.asyncio
async def test_command_preempts_active_poll_and_runs_before_queued_poll() -> None:
    gate = SesameBLESessionGate()
    first_poll_started = asyncio.Event()
    first_poll_preempted = asyncio.Event()
    release_command = asyncio.Event()
    order: list[str] = []

    async def first_poll() -> None:
        async with gate.poll(first_poll_preempted.set):
            order.append("first_poll")
            first_poll_started.set()
            await first_poll_preempted.wait()

    async def second_poll() -> None:
        async with gate.poll(lambda: None):
            order.append("second_poll")

    async def command() -> None:
        async with gate.command():
            order.append("command")
            release_command.set()

    first = asyncio.create_task(first_poll())
    await first_poll_started.wait()
    second = asyncio.create_task(second_poll())
    await asyncio.sleep(0)
    operation = asyncio.create_task(command())

    await release_command.wait()
    await asyncio.gather(first, second, operation)
    assert order == ["first_poll", "command", "second_poll"]


@pytest.mark.asyncio
async def test_cancelled_settle_delay_does_not_leave_gate_locked() -> None:
    gate = SesameBLESessionGate(settle_delay=60)
    entered = asyncio.Event()

    async def first_command() -> None:
        async with gate.command():
            entered.set()

    first = asyncio.create_task(first_command())
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    gate._settle_delay = 0
    async with gate.command():
        pass

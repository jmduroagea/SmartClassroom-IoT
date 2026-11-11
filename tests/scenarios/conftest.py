"""Fixtures for scenario tests. `pytest tests/scenarios` is the only command:
the simulation is built, started and stopped from here."""

import pytest

from tests.scenarios import simulation


@pytest.fixture(scope="session")
def docker_images():
    """Build the images once, and stop everything when all tests are done."""
    simulation.build_images()
    yield
    simulation.stop()


@pytest.fixture
def sim(docker_images):
    """A clean running system for each test: empty database, brain just started.

    After every test it also checks that the speaker was never told to say
    the wake word. If the test fails, pytest shows the last lines the brain and
    the web logged.
    """
    simulation.restart_clean()
    system = simulation.Simulation()
    try:
        system.connect()
        yield system
        system.assert_wake_word_never_said()
    finally:
        system.close()
        print(simulation.logs())

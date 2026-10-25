import pytest
from fastmcp.exceptions import ToolError

from kitsu_mcp.kitsu.lookups import Lookups
from tests.fake_data import ST_WFA, TT_MODEL
from tests.fakes import FakeClient


def test_resolves_by_id_name_and_short_name_case_insensitively():
    lookups = Lookups(FakeClient(), ttl=300)  # type: ignore[arg-type]
    assert lookups.task_type(TT_MODEL)["name"] == "Modeling"
    assert lookups.task_type("modeling")["id"] == TT_MODEL
    assert lookups.task_type("MOD")["id"] == TT_MODEL
    assert lookups.task_status("WFA")["id"] == ST_WFA
    assert lookups.person("bob@example.com")["full_name"] == "Bob Leroy"
    assert lookups.project("demo short")["id"] == "p-1"


def test_unknown_name_lists_valid_values():
    lookups = Lookups(FakeClient(), ttl=300)  # type: ignore[arg-type]
    with pytest.raises(ToolError, match=r"Unknown task status 'apv'.*done.*wfa"):
        lookups.task_status("apv")


def test_ambiguous_name_is_an_error():
    fake = FakeClient()
    fake.data["people"].append({**fake.data["people"][0], "id": "person-alice-2"})
    with pytest.raises(ToolError, match="Ambiguous"):
        Lookups(fake, ttl=300).person("Alice Martin")  # type: ignore[arg-type]


def test_reference_data_is_cached_until_cleared():
    fake = FakeClient()
    lookups = Lookups(fake, ttl=300)  # type: ignore[arg-type]
    lookups.index("people")
    lookups.index("people")
    assert sum(path == "data/persons" for _, path, _ in fake.calls) == 1
    lookups.clear()
    lookups.index("people")
    assert sum(path == "data/persons" for _, path, _ in fake.calls) == 2


def test_cache_expires_after_ttl():
    fake = FakeClient()
    lookups = Lookups(fake, ttl=0)  # type: ignore[arg-type]
    lookups.index("people")
    lookups.index("people")
    assert sum(path == "data/persons" for _, path, _ in fake.calls) == 2

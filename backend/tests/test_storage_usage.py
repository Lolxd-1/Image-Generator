"""Pure-function tests for app.routers.storage: summarise, purge_plan, delete_plan.

No DB fixture in this suite - these three helpers take plain StoredObject lists, so they
are tested directly with no app.db / app.models involved.
"""
from app.routers.storage import StoredObject, delete_plan, purge_plan, summarise


def test_usage_sums_by_kind():
    objects = [
        StoredObject(key="shops/1/dish/a.jpg", kind="dish", bytes_len=100),
        StoredObject(key="shops/1/dish/b.jpg", kind="dish", bytes_len=200),
        StoredObject(key="shops/1/menu/c.jpg", kind="menu", bytes_len=0),
        StoredObject(key="shops/1/reference/d.jpg", kind="reference", bytes_len=50),
    ]
    assert summarise(objects) == {
        "dish": (2, 300),
        "menu": (1, 0),
        "reference": (1, 50),
    }


def test_purge_plan_lists_only_dish_keys():
    objects = [
        StoredObject(key="shops/1/dish/a.jpg", kind="dish", bytes_len=100),
        StoredObject(key="shops/1/menu/b.jpg", kind="menu", bytes_len=0),
        StoredObject(key="shops/1/reference/c.jpg", kind="reference", bytes_len=50),
        StoredObject(key="shops/1/dish/d.jpg", kind="dish", bytes_len=150),
        StoredObject(key="exports/1/e.csv", kind="export", bytes_len=0),
    ]
    assert purge_plan(objects) == ["shops/1/dish/a.jpg", "shops/1/dish/d.jpg"]


def test_delete_plan_covers_every_object():
    objects = [
        StoredObject(key="shops/1/dish/a.jpg", kind="dish", bytes_len=100),
        StoredObject(key="shops/1/menu/b.jpg", kind="menu", bytes_len=0),
        StoredObject(key="shops/1/dish/a.jpg", kind="dish", bytes_len=100),  # duplicate key
        StoredObject(key="shops/1/reference/c.jpg", kind="reference", bytes_len=50),
    ]
    assert delete_plan(objects) == [
        "shops/1/dish/a.jpg",
        "shops/1/menu/b.jpg",
        "shops/1/reference/c.jpg",
    ]


def test_plans_on_empty_input():
    assert purge_plan([]) == []
    assert delete_plan([]) == []
    assert summarise([]) == {}


def test_summarise_ignores_none_bytes():
    objects = [StoredObject(key="shops/1/dish/a.jpg", kind="dish", bytes_len=0)]
    assert summarise(objects) == {"dish": (1, 0)}

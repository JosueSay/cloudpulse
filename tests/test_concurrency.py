"""Behaviour under the concurrent traffic the simulator will produce.

Each thread builds its own test client: the shared state under test lives in
the loaded module, not in the client.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

WORKERS = 16


def test_concurrent_cancels_of_the_same_order_yield_exactly_one_success(
    app, valid_order
):
    order_id = app.test_client().post("/orders", json=valid_order).get_json()["id"]

    def cancel(index):
        client = app.test_client()
        return client.post(
            f"/orders/{order_id}/cancel",
            headers={"X-Request-ID": f"sim-cancel-{index}"},
        ).status_code

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        statuses = list(pool.map(cancel, range(WORKERS)))

    assert statuses.count(200) == 1
    assert statuses.count(409) == WORKERS - 1


def test_concurrent_creates_produce_unique_retrievable_orders(app, valid_order):
    def create(index):
        client = app.test_client()
        response = client.post(
            "/orders",
            json=valid_order,
            headers={"X-Request-ID": f"sim-create-{index}"},
        )
        assert response.status_code == 201
        return response.get_json()["id"]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        order_ids = list(pool.map(create, range(WORKERS)))

    assert len(set(order_ids)) == WORKERS

    reader = app.test_client()
    assert all(reader.get(f"/orders/{oid}").status_code == 200 for oid in order_ids)


def test_every_concurrent_request_emits_its_own_log_event(
    app, valid_order, read_events
):
    def create(index):
        return app.test_client().post(
            "/orders",
            json=valid_order,
            headers={"X-Request-ID": f"sim-log-{index}"},
        )

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(create, range(WORKERS)))

    events = read_events()
    assert len(events) == WORKERS
    assert {event["request_id"] for event in events} == {
        f"sim-log-{index}" for index in range(WORKERS)
    }

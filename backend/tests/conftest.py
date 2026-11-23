import os
import socket
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

import psycopg
import pytest
import uvicorn
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from wallet_lab.api import create_app
from wallet_lab.migrate import migrate


@pytest.fixture
def database():
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        pytest.fail("Set TEST_DATABASE_URL to a PostgreSQL test database")
    schema = f"test_{uuid4().hex}"
    options = conninfo_to_dict(base_url).get("options", "")
    database_url = make_conninfo(
        base_url, options=f"{options} -c search_path={schema}", application_name=schema
    )
    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            migrate(database_url)
            yield database_url
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def server(database):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        app = create_app(database, demo_delay=2)
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 5
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.01)
            assert server.started, "Uvicorn failed to start"
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive(), "Uvicorn failed to stop"

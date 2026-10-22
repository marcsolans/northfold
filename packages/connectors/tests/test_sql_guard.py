from __future__ import annotations

import pytest

from messer_connectors.sql import StatementRejected, check_read_only, parse_dsn, to_format_params
from messer_connectors.sql import values as V


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM invoices",
        "select id, total from public.invoices where total > 10;",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
        "EXPLAIN SELECT 1",
        "SELECT 'drop table x; delete' AS harmless",
        "SELECT replace(name, 'a', 'b'), comment FROM t",
        "SHOW search_path",
        "TABLE invoices",
    ],
)
def test_guard_accepts_read_queries(sql: str) -> None:
    assert check_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM invoices",
        "UPDATE invoices SET total = 0",
        "SELECT 1; DROP TABLE invoices",
        "WITH d AS (DELETE FROM invoices RETURNING *) SELECT * FROM d",
        "SELECT * INTO copy FROM invoices",
        "SELECT pg_sleep(10)",
        "SELECT nextval('seq')",
        "EXPLAIN ANALYZE SELECT 1",
        "EXPLAIN (ANALYZE, BUFFERS) SELECT 1",
        "CALL refresh()",
        "",
        "SELECT * FROM t FOR UPDATE",
        "SELECT 'a\\' ; DELETE FROM t; --'",
    ],
)
def test_guard_rejects_writes_and_side_effects(sql: str) -> None:
    with pytest.raises(StatementRejected):
        check_read_only(sql)


def test_guard_dialect_comments_and_identifiers() -> None:
    # In MySQL "#" starts a comment, so the DELETE after it is not part of the statement.
    assert check_read_only("SELECT 1 # DELETE everything", "mysql")
    # In PostgreSQL "#" is an operator: the hidden second statement must be caught.
    with pytest.raises(StatementRejected):
        check_read_only("SELECT 1 # 2; DELETE FROM t", "postgresql")
    assert check_read_only("SELECT [delete] FROM [order]", "sqlserver")
    assert check_read_only("SELECT `update` FROM t", "mysql")


def test_dollar_params_are_converted_in_order() -> None:
    sql, params = to_format_params("SELECT * FROM t WHERE a = $2 AND b = $1 AND c LIKE '50%'", ["x", 7])
    assert sql == "SELECT * FROM t WHERE a = %s AND b = %s AND c LIKE '50%%'"
    assert params == [7, "x"]
    with pytest.raises(StatementRejected):
        to_format_params("SELECT $1", None)
    with pytest.raises(StatementRejected):
        to_format_params("SELECT $3", [1])


def test_dsn_parsing() -> None:
    pg = parse_dsn("postgresql://reader:p%40ss@db.example:6543/erp?sslmode=require", "postgresql")
    assert (pg.host, pg.port, pg.database, pg.user, pg.password) == ("db.example", 6543, "erp", "reader", "p@ss")
    assert "p@ss" not in pg.redacted()
    libpq = parse_dsn("host=10.0.0.5 port=5433 dbname=erp user=reader password='a b'", "postgresql")
    assert (libpq.host, libpq.port, libpq.password) == ("10.0.0.5", 5433, "a b")
    my = parse_dsn("mysql://u:p@mysql.example/shop?ssl=true", "mysql")
    assert (my.port, my.options["ssl"]) == (3306, "true")
    ado = parse_dsn("Server=tcp:sql.example,1444;Database=crm;User ID=r;Password=x;Encrypt=True", "sqlserver")
    assert (ado.host, ado.port, ado.database, ado.user, ado.options["encrypt"]) == (
        "sql.example",
        1444,
        "crm",
        "r",
        "True",
    )
    with pytest.raises(ValueError):
        parse_dsn("mysql://u:p@h/db", "postgresql")


def test_value_round_trip_and_type_inference() -> None:
    import datetime as dt
    from decimal import Decimal

    stamp = dt.datetime(2026, 10, 21, 9, 30, tzinfo=dt.UTC)
    assert V.revive("timestamp", V.to_json_value(stamp)) == stamp
    assert V.revive("numeric", V.to_json_value(Decimal("12.50"))) == Decimal("12.50")
    assert V.revive("boolean", 1) is True
    assert V.infer_kb_type(["2026-10-21T09:30:00Z", None]) == "timestamp"
    assert V.infer_kb_type(["01234", "48001"]) == "text"  # leading zeros stay text
    assert V.kb_type_postgres("timestamp with time zone", "timestamptz") == "timestamp"
    assert V.kb_type_mysql("tinyint", "tinyint(1)") == "boolean"
    assert V.kb_type_sqlserver("datetime2") == "timestamp"

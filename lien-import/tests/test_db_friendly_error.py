from lien_import.db import friendly_connect_error


def _err(code, detail):
    return Exception(code, detail)


def test_unknown_database():
    msg = friendly_connect_error(_err(1049, "Unknown database 'root'"))
    assert "no database with that name" in msg
    assert "config.json" in msg  # default `where`


def test_unknown_database_custom_where():
    msg = friendly_connect_error(_err(1049, "Unknown database 'x'"), where="the form above")
    assert "the form above" in msg
    assert "config.json" not in msg


def test_access_denied():
    msg = friendly_connect_error(_err(1045, "Access denied for user 'root'"))
    assert "Login was rejected" in msg
    assert "username and password" in msg


def test_unknown_table_also_access_denied_code():
    msg = friendly_connect_error(_err(1044, "Access denied for user to database"))
    assert "Login was rejected" in msg


def test_cannot_reach_server():
    for code in (2003, 2002, 2005):
        msg = friendly_connect_error(_err(code, "Can't connect to MySQL server"))
        assert "Could not reach the database server" in msg


def test_unrecognised_code_falls_back():
    msg = friendly_connect_error(_err(9999, "something else"))
    assert "9999" in msg
    assert "something else" in msg


def test_exception_with_no_args_does_not_raise():
    msg = friendly_connect_error(Exception())
    assert isinstance(msg, str) and msg

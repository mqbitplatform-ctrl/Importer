from lien_import.connstr import parse_connection_string


def test_full_uri():
    p = parse_connection_string("mysql://root:secret@127.0.0.1:3306/lineitem")
    assert p.host == "127.0.0.1"
    assert p.port == 3306
    assert p.user == "root"
    assert p.password == "secret"
    assert p.database == "lineitem"


def test_without_scheme_prefix():
    p = parse_connection_string("root:secret@127.0.0.1:3306/lineitem")
    assert (p.host, p.port, p.user, p.password, p.database) == (
        "127.0.0.1", 3306, "root", "secret", "lineitem",
    )


def test_host_and_db_only_no_credentials():
    p = parse_connection_string("db.example.com:3307/mydb")
    assert p.host == "db.example.com"
    assert p.port == 3307
    assert p.database == "mydb"
    assert p.user is None
    assert p.password is None


def test_bare_host():
    p = parse_connection_string("db.example.com")
    assert p.host == "db.example.com"
    assert p.port is None
    assert p.database is None


def test_url_encoded_password():
    p = parse_connection_string("mysql://user:p%40ss@host/db")
    assert p.password == "p@ss"


def test_empty_string_is_empty():
    p = parse_connection_string("")
    assert p.is_empty()
    p2 = parse_connection_string(None)
    assert p2.is_empty()


def test_whitespace_only_is_empty():
    assert parse_connection_string("   ").is_empty()


def test_garbage_does_not_raise():
    # must never raise - the GUI calls this on arbitrary pasted text
    p = parse_connection_string("not a connection string @@@ :::")
    assert isinstance(p.is_empty(), bool)

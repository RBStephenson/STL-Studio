from app.utils import like_escape


class TestLikeEscape:
    def test_escapes_percent(self):
        assert like_escape("50%off") == "50\\%off"

    def test_escapes_underscore(self):
        assert like_escape("My_Guy") == "My\\_Guy"

    def test_escapes_backslash_first(self):
        # Backslash must be escaped before % and _ or a literal "\_" in the
        # input would be misread as an already-escaped wildcard.
        assert like_escape("a\\_b") == "a\\\\\\_b"

    def test_plain_string_unchanged(self):
        assert like_escape("Ordinary Name") == "Ordinary Name"

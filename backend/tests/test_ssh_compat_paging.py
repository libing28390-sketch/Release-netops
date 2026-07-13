from drivers.ssh_compat import contains_paging_prompt, drain_paged_output


class FakePagedConnection:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.writes = []

    def write_channel(self, data):
        self.writes.append(data)

    def read_channel_timing(self, read_timeout=10):
        if self.chunks:
            return self.chunks.pop(0)
        return ""


def test_contains_paging_prompt_matches_h3c_more_prompt():
    assert contains_paging_prompt("line 1\n---- More ----")
    assert contains_paging_prompt("line 1\n--More--")
    assert not contains_paging_prompt("line 1\n<agg-sw1>")


def test_drain_paged_output_sends_space_until_more_prompt_clears():
    conn = FakePagedConnection([
        "\nline 2\n---- More ----",
        "\nline 3\n<agg-sw1>",
    ])

    output = drain_paged_output(conn, "line 1\n---- More ----", read_timeout=30)

    assert conn.writes == [" ", " "]
    assert "line 1" in output
    assert "line 2" in output
    assert "line 3" in output

import pytest

from agent.config.settings import PAPER_BASE_URL, ConfigError, load_settings

GOOD = {
    "TRADING_MODE": "paper",
    "ALPACA_PAPER_KEY_ID": "PKTESTKEY123",
    "ALPACA_PAPER_SECRET_KEY": "secret",
    "ALPACA_PAPER_BASE_URL": PAPER_BASE_URL,
    "ALPACA_DATA_FEED": "sip",
}


def test_valid_paper_settings():
    s = load_settings(env=GOOD)
    assert s.paper and s.data_feed == "sip"
    assert "secret" not in s.masked_key()


@pytest.mark.parametrize(
    "override, message",
    [
        ({"TRADING_MODE": "live"}, "paper trading"),
        ({"ALPACA_PAPER_BASE_URL": "https://api.alpaca.markets"}, "endereço de paper"),
        ({"ALPACA_PAPER_KEY_ID": ""}, "ausentes"),
        ({"ALPACA_PAPER_KEY_ID": "AKREALKEY"}, "REAL"),
        ({"ALPACA_DATA_FEED": "otc"}, "inválido"),
    ],
)
def test_unsafe_settings_are_refused(override, message):
    with pytest.raises(ConfigError, match=message):
        load_settings(env={**GOOD, **override})

"""Tests del pago de cláusula: una sola petición, cuerpo exacto y sin reintentos."""

import json

import pytest
import responses

from fantasy.api import FantasyApiClient, FantasyApiError
from fantasy.api import endpoints
from fantasy.auth.store import BaseTokenStore, set_token_store
from fantasy.auth.tokens import TokenSet


class DummyTokenStore(BaseTokenStore):
    def load(self):
        return TokenSet(access_token="test_bearer_token", expires_at=9999999999)

    def save(self, tokens):
        pass


@pytest.fixture(autouse=True)
def token():
    set_token_store(DummyTokenStore())


URL = endpoints.pay_buyout_url("111", "pt-9")


def test_url_de_pago():
    assert URL == "https://fantasy-api.llt-services.com/api/v1/competition/1/league/111/buyout/pt-9/pay"


@responses.activate
def test_pago_envia_la_clausula_completa_y_acepta_200_vacio():
    responses.add(responses.POST, URL, body="", status=200)

    result = FantasyApiClient(throttle_seconds=0).pay_buyout_clause("111", "pt-9", 12_500_000)

    assert result is None
    assert len(responses.calls) == 1
    assert json.loads(responses.calls[0].request.body) == {"buyoutClauseToPay": 12_500_000}
    assert responses.calls[0].request.headers["Authorization"] == "Bearer test_bearer_token"


@responses.activate
def test_pago_acepta_204():
    responses.add(responses.POST, URL, status=204)
    assert FantasyApiClient(throttle_seconds=0).pay_buyout_clause("111", "pt-9", 1) is None


@pytest.mark.parametrize("status", [409, 400, 500, 503, 429])
@responses.activate
def test_pago_no_se_reintenta_nunca(status):
    """Un pago reenviado tras un error podría repetir algo que ya se hizo: una sola petición."""
    responses.add(responses.POST, URL, json={"message": "no"}, status=status)

    with pytest.raises(FantasyApiError) as exc_info:
        FantasyApiClient(throttle_seconds=0, max_retries=3).pay_buyout_clause("111", "pt-9", 1)

    assert exc_info.value.status_code == status
    assert len(responses.calls) == 1


@responses.activate
def test_las_lecturas_siguen_reintentando():
    """El modo sin reintentos es solo para el pago: los GET conservan su backoff."""
    url = "https://fantasy-api.llt-services.com/api/x"
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, json={"ok": True}, status=200)

    assert FantasyApiClient(throttle_seconds=0, max_retries=2).get(url) == {"ok": True}
    assert len(responses.calls) == 2


@responses.activate
def test_error_tras_renovar_token_no_se_disfraza_de_auth(monkeypatch):
    """Tras un 401 se renueva el token y se reenvía; si el reenvío da 409, es un 409."""
    import fantasy.api.client as client_mod

    monkeypatch.setattr(client_mod, "get_access_token", lambda force_refresh=False: "tok")
    responses.add(responses.POST, URL, status=401)
    responses.add(responses.POST, URL, json={"message": "Clausula no disponible"}, status=409)

    with pytest.raises(FantasyApiError) as exc_info:
        FantasyApiClient(throttle_seconds=0).pay_buyout_clause("111", "pt-9", 1)

    assert exc_info.value.status_code == 409
    assert len(responses.calls) == 2

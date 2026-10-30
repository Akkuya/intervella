import httpx
import pytest

from deployment_smoke import SmokeError, run_smoke


def test_smoke_refuses_cleartext_before_network():
    with httpx.Client(base_url="http://localhost") as client:
        with pytest.raises(SmokeError, match="https_required"):
            run_smoke(client, "synthetic")


def test_smoke_detects_anonymous_leak_without_sending_passcode():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/":
            return httpx.Response(
                200,
                text="Intervella",
                headers={"content-security-policy": "frame-ancestors 'none'"},
            )
        return httpx.Response(200, json={"private": "leak"})

    with httpx.Client(
        base_url="https://stage.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(SmokeError, match="anonymous_boundary"):
            run_smoke(client, "synthetic")
    assert "/auth/beta" not in paths

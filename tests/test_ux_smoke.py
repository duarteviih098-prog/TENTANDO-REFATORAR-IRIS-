"""Smoke UX — telas principais carregam e empty_state existe no HTML base."""
import pytest


@pytest.mark.parametrize('path,needle', [
    ('/os/lista', 'iris-empty-state'),
    ('/pagamentos/lancamentos', 'iris-empty-state'),
    ('/inventario/hub', 'iris-empty-state'),
    ('/controle/hub', 'iris-empty-state'),
    ('/combustivel', 'iris-empty-state'),
    ('/custos', 'iris-empty-state'),
])
def test_main_module_pages_load(admin_session, client, path, needle):
    response = client.get(path)
    assert response.status_code == 200
    body = response.get_data(as_text=True).lower()
    assert needle.lower() in body


def test_base_has_global_toast_and_loading(admin_session, client):
    response = client.get('/os/lista')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="iris-toast"' in body
    assert 'window.irisToast' in body
    assert 'data-iris-busy-form' in body or 'Importando planilha' in body

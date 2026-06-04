from pathlib import Path

routes = Path(__file__).resolve().parent.parent / 'app' / 'pagamentos' / 'routes.py'
text = routes.read_text(encoding='utf-8')

# Remove duplicate unprefixed pagamentos_import
dup = '''



def pagamentos_import():
    file = request.files.get('arquivo_excel')
    if not file or not file.filename:
        flash('Selecione um arquivo Excel para importar pagamentos.', 'warning')
        return redirect(url_for('pagamentos'))
    mes_override = request.form.get('mes_importacao', '').strip() or None
    try:
        qtd = import_pagamentos_excel(file, mes_override=mes_override)
        clear_view_cache()
        flash(f'Importação de pagamentos concluída: {qtd} linha(s).', 'success')
    except Exception as exc:
        flash(f'Erro ao importar pagamentos: {exc}', 'danger')
    return redirect(url_for('pagamentos'))





'''
if dup in text:
    text = text.replace(dup, '\n\n', 1)

redirect_fn = '''@require_permission('view_pagamentos')
def pagamentos_redirect():
    """Redireciona /pagamentos para o hub."""
    return redirect(url_for('pagamentos_hub'))


'''
if 'def pagamentos_redirect' not in text:
    text = text.replace(
        "@require_permission('view_pagamentos')\ndef pagamentos():",
        redirect_fn + "@require_permission('view_pagamentos')\ndef pagamentos():",
        1,
    )

routes.write_text(text, encoding='utf-8')
print('fixed routes.py')

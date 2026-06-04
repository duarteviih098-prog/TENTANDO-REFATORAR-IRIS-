"""Storage local e Supabase (uploads, anexos, identidade)."""
from app.storage.attachments import (
    ATTACHMENT_GROUPS,
    missing_attachment_response,
    normalize_os_attachment_list,
    normalize_payment_attachment_list,
    payment_storage_kind,
    persist_os_attachment,
    persist_payment_attachment,
    read_attachment_bytes,
    read_attachment_bytes_fast,
    save_os_files,
    storage_or_local_response,
    sync_os_attachments,
    sync_payment_attachments,
    _os_attachment_relpath,
    _payment_attachment_relpath,
)
from app.storage.company import (
    active_whatsapp_template,
    backup_company_data,
    company_identity_file,
    ensure_company_storage,
    load_company_identity_config,
    load_whatsapp_templates,
    save_company_identity_config,
    save_company_identity_file,
    save_whatsapp_templates,
    whatsapp_templates_path,
)
from app.storage.paths import (
    BASE_DIR,
    OS_STORAGE_FOLDER,
    PAYMENT_STORAGE_FOLDER,
    TENANT_UPLOAD_ROOT,
    UPLOAD_OS,
    UPLOAD_PAG,
    company_folder_name,
    company_identity_config_path,
    company_identity_dir,
    get_file_url,
    normalize_storage_path,
    resolve_local_path,
    resolve_os_upload_path,
    slugify_company_name,
    storage_kind_folder,
    tenant_upload_dir,
)
from app.storage.pdf import _save_pdf_bytes_locally, _upload_pdf_bytes_to_supabase
from app.storage.routes import register_routes
from app.storage.settings import (
    OS_STORAGE_FOLDER as SETTINGS_OS_FOLDER,
    PAYMENT_STORAGE_FOLDER as SETTINGS_PAYMENT_FOLDER,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_STORAGE_KEY,
    SUPABASE_URL,
)
from app.storage.supabase import upload_file_to_supabase


def register_storage(app):
    register_routes(app)


__all__ = [
    'register_storage',
    'SUPABASE_URL', 'SUPABASE_STORAGE_BUCKET', 'SUPABASE_STORAGE_KEY',
    'PAYMENT_STORAGE_FOLDER', 'OS_STORAGE_FOLDER',
    'BASE_DIR', 'UPLOAD_OS', 'UPLOAD_PAG', 'TENANT_UPLOAD_ROOT',
    'storage_kind_folder', 'normalize_storage_path', 'get_file_url',
    'upload_file_to_supabase', 'read_attachment_bytes', 'read_attachment_bytes_fast',
    'storage_or_local_response', 'resolve_local_path', 'resolve_os_upload_path',
    'slugify_company_name', 'company_folder_name', 'tenant_upload_dir',
    'ensure_company_storage', 'company_identity_dir', 'company_identity_config_path',
    'load_company_identity_config', 'save_company_identity_config',
    'company_identity_file', 'save_company_identity_file',
    'whatsapp_templates_path', 'load_whatsapp_templates', 'save_whatsapp_templates',
    'active_whatsapp_template', 'backup_company_data',
    'ATTACHMENT_GROUPS', 'payment_storage_kind', 'persist_payment_attachment',
    'normalize_payment_attachment_list', 'sync_payment_attachments', 'missing_attachment_response',
    '_payment_attachment_relpath', 'save_os_files', '_os_attachment_relpath',
    'persist_os_attachment', 'normalize_os_attachment_list', 'sync_os_attachments',
    '_save_pdf_bytes_locally', '_upload_pdf_bytes_to_supabase',
]

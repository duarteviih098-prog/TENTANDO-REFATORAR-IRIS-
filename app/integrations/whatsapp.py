"""WhatsApp — re-exporta helpers de templates (storage)."""
from app.storage import (
    active_whatsapp_template,
    load_whatsapp_templates,
    save_whatsapp_templates,
    whatsapp_templates_path,
)

__all__ = [
    'active_whatsapp_template',
    'load_whatsapp_templates',
    'save_whatsapp_templates',
    'whatsapp_templates_path',
]

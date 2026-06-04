"""Configuração Supabase Storage e pastas oficiais."""
import os

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://njbzfjbponspalirndqj.supabase.co").rstrip("/")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "uploads").strip() or "uploads"
SUPABASE_STORAGE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_STORAGE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or ""
).strip()

# Rotas oficiais dentro do bucket `uploads`:
# - Fotos/anexos da O.S.: empresas/<empresa>/os/<arquivo>
# - NF e boleto da aba Pagamentos: empresas/<empresa>/BOLETO E NF/<arquivo>
PAYMENT_STORAGE_FOLDER = os.getenv("PAYMENT_STORAGE_FOLDER", "BOLETO E NF").strip() or "BOLETO E NF"
OS_STORAGE_FOLDER = os.getenv("OS_STORAGE_FOLDER", "os").strip() or "os"

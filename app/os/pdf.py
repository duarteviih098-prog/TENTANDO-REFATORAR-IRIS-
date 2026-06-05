"""PDF de O.S. — facade de compatibilidade (imports legados)."""
from app.os.pdf_builder import _build_os_pdf, _build_os_pdf_mes_buffer, excel_file, table_pdf
from app.os.pdf_jobs import _create_pdf_job, _gerar_pdf_mensal_job_worker, _pdf_job_now, _start_pdf_job_thread
from app.os.pdf_routes import register_pdf_routes
from app.os.pdf_support import _draw_pdf_header

__all__ = [
    '_build_os_pdf',
    '_build_os_pdf_mes_buffer',
    '_create_pdf_job',
    '_draw_pdf_header',
    '_gerar_pdf_mensal_job_worker',
    '_pdf_job_now',
    '_start_pdf_job_thread',
    'excel_file',
    'register_pdf_routes',
    'table_pdf',
]

# core_engine.py
# KUMPULAN FUNGSI MURNI (Domain Independent)

def calculate_age_from_entry_year(entry_year: int, current_year: int = 2026) -> int:
    """
    Logika murni: Menghitung estimasi usia berdasarkan tahun masuk kuliah.
    Asumsi standar di Indonesia: Masuk kuliah pada usia 18 tahun.
    """
    standard_entry_age = 18
    return (current_year - entry_year) + standard_entry_age
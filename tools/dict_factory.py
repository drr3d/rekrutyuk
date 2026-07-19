def dict_factory(cursor, row):
    """Helper untuk mengubah hasil query SQLite menjadi dictionary (mirip struktur JSON)."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
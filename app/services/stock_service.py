from app.database import db


def list_low_stock():
    with db() as conn:
        flavor_rows = conn.execute("SELECT name, stock_kg, min_stock_kg FROM flavors WHERE active=1 AND stock_kg<=min_stock_kg ORDER BY stock_kg").fetchall()
        item_rows = conn.execute("SELECT name, quantity, minimum FROM stock_items WHERE active=1 AND quantity<=minimum ORDER BY quantity").fetchall()
    return flavor_rows, item_rows

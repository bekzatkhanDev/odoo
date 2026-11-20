"""Deterministic, explicitly simulated demand for the academic demo."""

import csv
import math
import random
from datetime import timedelta


def write_demo_csv(path, codes, end_date, days=120):
    """Create a reproducible CSV; no Odoo sales records are created."""
    rng = random.Random(20261120)
    with open(path, 'w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['date', 'product_code', 'quantity', 'source'])
        for number, code in enumerate(codes):
            for offset in range(days):
                day = end_date - timedelta(days=days - 1 - offset)
                weekday = 1.5 if day.weekday() in (0, 4) else 0
                season = 1.8 * math.sin(2 * math.pi * offset / 30 + number / 3)
                trend = offset * (0.01 if number % 3 else 0.025)
                quantity = max(0, round(4 + number % 7 + weekday + season + trend + rng.uniform(-2, 2)))
                writer.writerow([day.isoformat(), code, quantity, 'SIMULATED'])


def read_demo_csv(path):
    by_code = {}
    with open(path, newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if row['source'] != 'SIMULATED':
                raise ValueError('Demo CSV contains an unexpected data source')
            by_code.setdefault(row['product_code'], []).append(
                (row['date'], float(row['quantity'])))
    return by_code

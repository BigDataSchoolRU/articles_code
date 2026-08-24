# Pillow 12.3.0, Python 3.12.13, прогнано на стенде 2026-08-24
"""Готовит тестовую картинку: таблица продаж по кварталам.

Картинка нужна двум демо сразу, поэтому генерация вынесена в отдельный модуль.
Синтетическая таблица удобнее фотографии: мы точно знаем правильный ответ
и можем проверить, что модель прочитала именно его.
"""
from PIL import Image, ImageDraw

ROWS = [
    ("Квартал", "Выручка, млн", "Заказы"),
    ("Q1", "12.4", "1840"),
    ("Q2", "15.9", "2110"),
    ("Q3", "11.2", "1605"),
    ("Q4", "18.7", "2480"),
]

# Тот же контент, но текстом. Нужен второму демо для честного сравнения.
AS_TEXT = "\n".join(" | ".join(row) for row in ROWS)


def build(path="sales_table.png", width=1200, height=800):
    """Рисует таблицу и сохраняет её в PNG заданного размера."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    cell_w, cell_h = width // 3, height // (len(ROWS) + 2)
    top = cell_h  # отступ сверху, чтобы таблица не липла к краю
    for r, row in enumerate(ROWS):
        for c, text in enumerate(row):
            x0, y0 = c * cell_w, top + r * cell_h
            draw.rectangle([x0, y0, x0 + cell_w, y0 + cell_h], outline="black", width=3)
            # шрифт по умолчанию мелкий, поэтому увеличиваем его масштабом
            draw.text((x0 + 20, y0 + cell_h // 2 - 10), text, fill="black", font_size=36)
    img.save(path)
    return path


if __name__ == "__main__":
    print("сохранено:", build())

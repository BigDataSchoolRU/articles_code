# pageindex 0.2.10, прогон на macOS 26.5.2, Python 3.12.13, вывод снят 2026-08-24
"""Строит дерево документа из PDF режимом flash: без LLM, без эмбеддингов."""
import json
import time
from pageindex import page_index_flash

PDF = "annual_report.pdf"


def print_tree(nodes, depth=0):
    """Печатает дерево с отступами: заголовок узла и диапазон страниц."""
    for node in nodes:
        pages = f'{node["start_index"]}-{node["end_index"]}'
        print(f'{"  " * depth}[{pages:>6}] {node["title"][:70]}')
        print_tree(node.get("nodes", []), depth + 1)


if __name__ == "__main__":
    start = time.time()
    # summary=False и optimize=False отключают все обращения к модели:
    # структура извлекается по типографике страницы и закладкам PDF
    result = page_index_flash(PDF, summary=False, optimize=False)
    elapsed = time.time() - start

    structure = result["structure"]
    print(f'Документ: {result["doc_title"]}')
    print(f"Дерево построено за {elapsed:.2f} с, без единого вызова LLM")
    print(f"Узлов верхнего уровня: {len(structure)}")
    print("-" * 60)
    print_tree(structure)

    # дерево сохраняется в JSON, дальше по нему идёт reasoning-поиск
    with open("tree.json", "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)
    print("-" * 60)
    print("Дерево сохранено в tree.json")

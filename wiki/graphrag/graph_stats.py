# Проверено на graphrag 3.1.1, Python 3.12.13, networkx 3.6.1
"""Разбор графа, который построил graphrag.

Печатает состав графа, стоимость индексации из stats.json и ищет путь между
двумя сущностями. Путь это и есть та связь, которую векторный поиск не видит:
она нигде не записана целиком, а собирается из рёбер разных документов.
"""

import json
import os
import sys

import networkx as nx
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(ROOT, "output")


def load_graph() -> nx.Graph:
    """Собирает граф networkx из parquet-файлов с сущностями и связями."""
    entities = pd.read_parquet(os.path.join(OUTPUT, "entities.parquet"))
    relationships = pd.read_parquet(os.path.join(OUTPUT, "relationships.parquet"))

    graph = nx.Graph()
    for _, row in entities.iterrows():
        graph.add_node(row["title"], type=row["type"])
    for _, row in relationships.iterrows():
        graph.add_edge(row["source"], row["target"], weight=float(row["weight"]))
    return graph


def print_cost() -> None:
    """Показывает, сколько времени съел каждый этап индексации."""
    with open(os.path.join(OUTPUT, "stats.json"), encoding="utf-8") as fh:
        stats = json.load(fh)

    total = stats.get("total_runtime", 0)
    print(f"Индексация целиком: {total:.0f} с ({total / 60:.1f} мин)")
    for name, data in stats.get("workflows", {}).items():
        seconds = data.get("overall", 0)
        # Печатаем только этапы дороже секунды: остальное шум
        if seconds >= 1:
            share = seconds / total * 100 if total else 0
            print(f"  {name:<26} {seconds:>7.0f} с  {share:>5.1f}%")


def print_graph(graph: nx.Graph) -> None:
    """Показывает состав графа и сообщества, найденные при индексации."""
    print(f"\nУзлов: {graph.number_of_nodes()}, рёбер: {graph.number_of_edges()}")
    communities = pd.read_parquet(os.path.join(OUTPUT, "communities.parquet"))
    print(f"Сообществ: {len(communities)}")

    print("\nСущности по типам:")
    by_type: dict[str, list[str]] = {}
    for node, data in graph.nodes(data=True):
        by_type.setdefault(data.get("type", "UNKNOWN"), []).append(node)
    for node_type, titles in sorted(by_type.items()):
        print(f"  {node_type}: {', '.join(sorted(titles))}")


def print_path(graph: nx.Graph, source: str, target: str) -> None:
    """Ищет кратчайший путь между сущностями и печатает его по шагам."""
    if source not in graph or target not in graph:
        print(f"\nНет узла: {source if source not in graph else target}")
        return
    try:
        path = nx.shortest_path(graph, source, target)
    except nx.NetworkXNoPath:
        print(f"\nПути между {source} и {target} нет")
        return

    print(f"\nПуть из «{source}» в «{target}», переходов: {len(path) - 1}")
    for step, node in enumerate(path):
        print(f"  {step}. {node}")


def main() -> None:
    graph = load_graph()
    print_cost()
    print_graph(graph)

    source = sys.argv[1] if len(sys.argv) > 2 else 'ООО "СЕВЕРНЫЙ ВЕТЕР"'
    target = sys.argv[2] if len(sys.argv) > 2 else "СЕВЕРО-ЗАПАДНАЯ ДИРЕКЦИЯ БАНКА"
    print_path(graph, source, target)


if __name__ == "__main__":
    main()

# Синтетический корпус для демо Contextual Retrieval, Python 3.12, прогнано на стенде 2026-11-14
"""Шесть квартальных отчётов трёх выдуманных компаний за два квартала.

Каждый отчёт режется на четыре чанка по абзацам. Название компании и квартал есть только
в первом абзаце (шапке). Абзацы про выручку, маржу и планы их не повторяют, как в настоящих
отчётах: «Revenue grew by 3% over the previous quarter». После нарезки такой чанк не знает,
о какой компании и каком квартале он говорит, и именно это чинит Contextual Retrieval.

Корпус на английском, как пример в первоисточнике Anthropic: модель эмбеддингов
nomic-embed-text обучена в основном на английском тексте.
"""

DOCUMENTS = {
    "northwind_q1_2025": [
        "Northwind Logistics. Quarterly report for Q1 2025 (January to March 2025). "
        "Northwind Logistics runs road freight and cold-chain warehousing in Central Europe.",
        "Revenue grew by 3% over the previous quarter and reached $41.2 million. "
        "Most of the growth came from cold-chain contracts with grocery retailers.",
        "Operating margin narrowed to 11.4% from 12.1%, mainly because diesel prices rose "
        "and two new warehouses were still ramping up.",
        "The company plans to hire 120 drivers next quarter and expects revenue to stay "
        "flat while the new warehouses reach full utilization.",
    ],
    "northwind_q2_2025": [
        "Northwind Logistics. Quarterly report for Q2 2025 (April to June 2025). "
        "Northwind Logistics runs road freight and cold-chain warehousing in Central Europe.",
        "Revenue grew by 7% over the previous quarter and reached $44.1 million. "
        "Most of the growth came from long-haul contracts signed in spring.",
        "Operating margin widened to 13.0% from 11.4% as diesel prices fell and the new "
        "warehouses reached full utilization.",
        "The company plans to open a third warehouse next quarter and expects revenue "
        "growth to slow to about 2%.",
    ],
    "brightleaf_q1_2025": [
        "Brightleaf Foods. Quarterly report for Q1 2025 (January to March 2025). "
        "Brightleaf Foods makes packaged salads and plant-based snacks sold in supermarkets.",
        "Revenue grew by 5% over the previous quarter and reached $18.6 million. "
        "Growth came mainly from the new line of protein snacks.",
        "Operating margin narrowed to 8.2% from 9.0% because of higher packaging costs "
        "and a one-off product recall.",
        "The company plans to hire 40 production workers next quarter and expects revenue "
        "to grow by 4%.",
    ],
    "brightleaf_q2_2025": [
        "Brightleaf Foods. Quarterly report for Q2 2025 (April to June 2025). "
        "Brightleaf Foods makes packaged salads and plant-based snacks sold in supermarkets.",
        "Revenue fell by 2% over the previous quarter to $18.2 million. "
        "Salad sales dropped after a supermarket chain changed its supplier.",
        "Operating margin widened to 9.5% from 8.2% after the company renegotiated "
        "packaging contracts.",
        "The company plans to launch snacks in two new countries next quarter and expects "
        "revenue to return to growth.",
    ],
    "helix_q1_2025": [
        "Helix Cloud. Quarterly report for Q1 2025 (January to March 2025). "
        "Helix Cloud sells a subscription platform for data backup to mid-size companies.",
        "Revenue grew by 9% over the previous quarter and reached $27.5 million. "
        "Growth came mainly from upgrades to the enterprise subscription tier.",
        "Operating margin narrowed to 15.3% from 17.8% because the company doubled "
        "spending on data center capacity.",
        "The company plans to hire 60 engineers next quarter and expects revenue to grow "
        "by 8%.",
    ],
    "helix_q2_2025": [
        "Helix Cloud. Quarterly report for Q2 2025 (April to June 2025). "
        "Helix Cloud sells a subscription platform for data backup to mid-size companies.",
        "Revenue grew by 6% over the previous quarter and reached $29.2 million. "
        "Growth came mainly from new customers in the healthcare sector.",
        "Operating margin widened to 18.4% from 15.3% as new data center capacity "
        "lowered the cost per stored terabyte.",
        "The company plans to cut its hiring plan to 25 engineers next quarter and expects "
        "revenue to grow by 5%.",
    ],
}

# Запрос и эталонный чанк (документ, номер абзаца). Ни один запрос не повторяет слова
# из текста чанка, кроме общих: компанию и квартал знает только шапка документа.
QUERIES = [
    ("How much did Northwind Logistics revenue grow in Q1 2025?", ("northwind_q1_2025", 1)),
    ("What was the operating margin of Northwind Logistics in Q2 2025?", ("northwind_q2_2025", 2)),
    ("What are Northwind Logistics plans for the quarter after Q2 2025?", ("northwind_q2_2025", 3)),
    ("Why did Northwind Logistics margin fall in Q1 2025?", ("northwind_q1_2025", 2)),
    ("How did Brightleaf Foods revenue change in Q2 2025?", ("brightleaf_q2_2025", 1)),
    ("What was the operating margin of Brightleaf Foods in Q1 2025?", ("brightleaf_q1_2025", 2)),
    ("How many workers will Brightleaf Foods hire after Q1 2025?", ("brightleaf_q1_2025", 3)),
    ("Why did Brightleaf Foods margin improve in Q2 2025?", ("brightleaf_q2_2025", 2)),
    ("How much did Helix Cloud revenue grow in Q2 2025?", ("helix_q2_2025", 1)),
    ("What was the operating margin of Helix Cloud in Q1 2025?", ("helix_q1_2025", 2)),
    ("How many engineers will Helix Cloud hire after Q2 2025?", ("helix_q2_2025", 3)),
    ("What drove Helix Cloud revenue growth in Q1 2025?", ("helix_q1_2025", 1)),
]


def chunks():
    """Плоский список чанков: (id, документ, номер, текст)."""
    out = []
    for doc_id, paragraphs in DOCUMENTS.items():
        for i, text in enumerate(paragraphs):
            out.append((f"{doc_id}#{i}", doc_id, i, text))
    return out


def whole_document(doc_id):
    return "\n\n".join(DOCUMENTS[doc_id])


if __name__ == "__main__":
    ch = chunks()
    print(f"документов: {len(DOCUMENTS)}, чанков: {len(ch)}, запросов: {len(QUERIES)}")
    print("пример чанка без контекста:", ch[1][3])

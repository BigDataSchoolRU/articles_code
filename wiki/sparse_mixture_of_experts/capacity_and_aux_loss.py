# PyTorch 2.13.0, прогнано на стенде 2026-08-31
"""
Capacity factor, token dropping и auxiliary loss в Sparse MoE. Capacity задаёт
жёсткий лимит токенов на эксперта: ceil(capacity_factor * tokens_in_batch /
num_experts). Токены сверх лимита эксперт не обслуживает (token dropping,
GShard, arXiv:2006.16668) — в демо у них просто нет вклада эксперта, как если
бы MoE-подслой для них вернул ноль и residual-связь пронесла их дальше без
изменений. Auxiliary loss (Switch Transformer, arXiv:2101.03961:
loss = alpha * N * sum(f_i * P_i)) штрафует роутер за неравномерность:
f_i — доля токенов, реально отправленных на эксперта i, P_i — средняя
вероятность роутера по эксперту i. Демо сравнивает сбалансированный роутер со
смещённым (искусственная имитация коллапса на один эксперт) и показывает, как
растут дропы и auxiliary loss.
"""
import math
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(42)

D_MODEL = 64
NUM_EXPERTS = 8
NUM_TOKENS = 32
ALPHA = 1e-2  # коэффициент auxiliary loss из Switch Transformer


def route_top1(x: torch.Tensor, gate: nn.Linear, capacity_factor: float):
    logits = gate(x)
    probs = F.softmax(logits, dim=-1)
    top_prob, top_idx = probs.max(dim=-1)

    num_tokens = x.shape[0]
    capacity = math.ceil(capacity_factor * num_tokens / NUM_EXPERTS)

    # диспетчеризация по порядку токенов в батче: кто пришёл первым, тот и занял слот
    dispatched = torch.zeros(num_tokens, dtype=torch.bool)
    slot_in_expert = torch.zeros(NUM_EXPERTS, dtype=torch.long)
    for t in range(num_tokens):
        e = top_idx[t].item()
        if slot_in_expert[e] < capacity:
            dispatched[t] = True
            slot_in_expert[e] += 1
        # иначе токен дропается: слот эксперта уже заполнен

    return top_idx, top_prob, probs, dispatched, capacity


def auxiliary_loss(top_idx: torch.Tensor, probs: torch.Tensor) -> torch.Tensor:
    num_tokens = probs.shape[0]
    f = torch.bincount(top_idx, minlength=NUM_EXPERTS).float() / num_tokens  # доля диспетчеризации
    p = probs.mean(dim=0)  # средняя вероятность роутера по эксперту
    return ALPHA * NUM_EXPERTS * (f * p).sum()


if __name__ == "__main__":
    x = torch.randn(NUM_TOKENS, D_MODEL)

    print("=== Сбалансированный роутер (случайная инициализация) ===")
    gate_balanced = nn.Linear(D_MODEL, NUM_EXPERTS, bias=False)
    for capacity_factor in (1.0, 1.25):
        top_idx, top_prob, probs, dispatched, capacity = route_top1(x, gate_balanced, capacity_factor)
        dropped = (~dispatched).sum().item()
        print(f"capacity_factor={capacity_factor}: лимит на эксперта={capacity}, "
              f"дропнуто токенов={dropped} из {NUM_TOKENS}")
    aux = auxiliary_loss(top_idx, probs)
    print(f"auxiliary loss (alpha={ALPHA}): {aux.item():.6f}")

    print("\n=== Смещённый роутер (collapse: один эксперт доминирует) ===")
    gate_collapsed = nn.Linear(D_MODEL, NUM_EXPERTS, bias=False)
    with torch.no_grad():
        # искусственно поднимаем логит одного эксперта — имитация коллапса роутинга,
        # к которому в реальности приводит самоусиливающийся эффект: эксперт, получивший
        # чуть больше градиента на старте, чаще выбирается и обучается быстрее остальных
        gate_collapsed.weight[0] += 5.0
    for capacity_factor in (1.0, 1.25):
        top_idx, top_prob, probs, dispatched, capacity = route_top1(x, gate_collapsed, capacity_factor)
        dropped = (~dispatched).sum().item()
        counts = torch.bincount(top_idx, minlength=NUM_EXPERTS).tolist()
        print(f"capacity_factor={capacity_factor}: лимит на эксперта={capacity}, "
              f"дропнуто токенов={dropped} из {NUM_TOKENS}, токенов на эксперта={counts}")
    aux_collapsed = auxiliary_loss(top_idx, probs)
    print(f"auxiliary loss (alpha={ALPHA}): {aux_collapsed.item():.6f}")

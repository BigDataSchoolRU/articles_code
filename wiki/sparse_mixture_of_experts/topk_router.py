# PyTorch 2.13.0, прогнано на стенде 2026-08-31
"""
Top-k роутер Sparse Mixture-of-Experts: линейный слой считает logits по числу
экспертов, softmax даёт вероятности, top-k выбирает k экспертов на токен и
ренормализует их веса. Демо сравнивает top-1 (Switch Transformer,
arXiv:2101.03961) и top-2 (GShard, arXiv:2006.16668) на одном и том же батче
токенов и считает долю активных параметров относительно общих — ключевую
метрику sparse-активации: слой большой, но на каждый токен считается только
малая его часть.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(42)

D_MODEL = 64
HIDDEN = 128
NUM_EXPERTS = 8
NUM_TOKENS = 16


class Expert(nn.Module):
    """Один эксперт — обычный двухслойный FFN, как в плотном трансформере."""

    def __init__(self, d_model: int, hidden: int):
        super().__init__()
        self.fc1 = nn.Linear(d_model, hidden)
        self.fc2 = nn.Linear(hidden, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(F.relu(self.fc1(x)))


class TopKRouter(nn.Module):
    """Роутер: считает logits по экспертам, выбирает top-k и ренормализует веса
    выбранных экспертов так, чтобы они снова суммировались в единицу."""

    def __init__(self, d_model: int, num_experts: int, top_k: int):
        super().__init__()
        self.gate = nn.Linear(d_model, num_experts, bias=False)
        self.top_k = top_k

    def forward(self, x: torch.Tensor):
        logits = self.gate(x)  # [tokens, num_experts]
        probs = F.softmax(logits, dim=-1)
        top_probs, top_idx = torch.topk(probs, self.top_k, dim=-1)
        top_probs = top_probs / top_probs.sum(dim=-1, keepdim=True)
        return top_probs, top_idx, probs


def count_params(module: nn.Module) -> int:
    return sum(p.numel() for p in module.parameters())


def run_moe(top_k: int, x: torch.Tensor, experts: nn.ModuleList, router: TopKRouter):
    """Диспетчеризация: для каждого из top_k слотов группируем токены по
    выбранному эксперту и прогоняем каждую группу через свой FFN одним вызовом."""
    top_probs, top_idx, _ = router(x)
    output = torch.zeros_like(x)
    for k in range(top_k):
        expert_idx = top_idx[:, k]
        weight = top_probs[:, k].unsqueeze(-1)
        for e in range(len(experts)):
            mask = expert_idx == e
            if mask.any():
                output[mask] += weight[mask] * experts[e](x[mask])
    return output, top_idx


if __name__ == "__main__":
    x = torch.randn(NUM_TOKENS, D_MODEL)
    experts = nn.ModuleList([Expert(D_MODEL, HIDDEN) for _ in range(NUM_EXPERTS)])

    total_expert_params = count_params(experts)
    single_expert_params = count_params(experts[0])

    for top_k, name in [(1, "top-1 (Switch Transformer)"), (2, "top-2 (GShard)")]:
        router = TopKRouter(D_MODEL, NUM_EXPERTS, top_k)
        router_params = count_params(router)
        output, top_idx = run_moe(top_k, x, experts, router)

        # распределение токенов по экспертам (учитываются все top_k назначения)
        counts = torch.zeros(NUM_EXPERTS, dtype=torch.long)
        for k in range(top_k):
            counts += torch.bincount(top_idx[:, k], minlength=NUM_EXPERTS)

        # активные параметры = то, что реально считается на один токен:
        # роутер плюс top_k экспертов. Общие параметры = роутер плюс все эксперты.
        active_params = router_params + top_k * single_expert_params
        total_params = router_params + total_expert_params

        print(f"\n--- {name} ---")
        print("токенов на эксперта:", counts.tolist())
        print(f"выход батча: shape={tuple(output.shape)}")
        print(f"активные параметры на токен: {active_params:,} из {total_params:,} "
              f"({100 * active_params / total_params:.1f}%)")

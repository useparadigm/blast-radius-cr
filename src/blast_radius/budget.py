"""Token budget estimation and context truncation."""

from __future__ import annotations

from dataclasses import dataclass

from .resolver import FunctionContext


# Rough estimate: 1 token ≈ 4 chars for code
CHARS_PER_TOKEN = 4

# Anthropic pricing per 1M tokens (input) as of 2026
PRICING = {
    "claude-sonnet-4-20250514": 3.00,
    "claude-haiku-4-5-20251001": 0.80,
    "gpt-4o": 2.50,
}


@dataclass
class BudgetReport:
    total_tokens: int
    total_functions: int
    total_callers: int
    total_callees: int
    estimated_cost: float
    truncated: bool
    model: str

    def summary(self) -> str:
        lines = [
            f"Context: ~{self.total_tokens:,} tokens "
            f"({self.total_functions} functions, "
            f"{self.total_callers} callers, "
            f"{self.total_callees} callees)",
        ]
        if self.estimated_cost > 0:
            lines.append(f"Estimated cost: ${self.estimated_cost:.3f} ({self.model})")
        if self.truncated:
            lines.append("Context was truncated to fit budget")
        return " | ".join(lines)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def estimate_context_tokens(contexts: list[FunctionContext]) -> int:
    total = 0
    for ctx in contexts:
        total += estimate_tokens(ctx.function.body)
        total += estimate_tokens(ctx.old_body)
        total += estimate_tokens(ctx.diff_text)
        for c in ctx.callers:
            total += estimate_tokens(c.body)
        for c in ctx.callees:
            total += estimate_tokens(c.body)
    # Add overhead for prompt template (~2K tokens)
    return total + 2000


def estimate_cost(tokens: int, model: str) -> float:
    rate = PRICING.get(model, 3.00)  # default to sonnet pricing
    return (tokens / 1_000_000) * rate


def truncate_body(body: str, max_lines: int) -> str:
    """Truncate function body to max_lines, keeping first and last parts."""
    lines = body.splitlines()
    if len(lines) <= max_lines:
        return body
    keep_top = max_lines * 2 // 3
    keep_bottom = max_lines - keep_top
    truncated_count = len(lines) - keep_top - keep_bottom
    return "\n".join(
        lines[:keep_top]
        + [f"    # ... ({truncated_count} lines truncated)"]
        + lines[-keep_bottom:]
    )


def apply_budget(
    contexts: list[FunctionContext],
    max_tokens: int = 100_000,
    max_functions: int = 20,
    max_callers: int = 15,
    max_body_lines: int = 50,
    model: str = "claude-sonnet-4-20250514",
) -> tuple[list[FunctionContext], BudgetReport]:
    """Apply budget constraints to contexts. Returns (truncated_contexts, report)."""
    truncated = False

    # 1. Limit number of changed functions
    if len(contexts) > max_functions:
        contexts = contexts[:max_functions]
        truncated = True

    # 2. Limit callers/callees per function and truncate bodies
    for ctx in contexts:
        if len(ctx.callers) > max_callers:
            ctx.callers = ctx.callers[:max_callers]
            truncated = True
        if len(ctx.callees) > max_callers:
            ctx.callees = ctx.callees[:max_callers]
            truncated = True

        ctx.function.body = truncate_body(ctx.function.body, max_body_lines)
        if ctx.old_body:
            ctx.old_body = truncate_body(ctx.old_body, max_body_lines)
        for c in ctx.callers:
            c.body = truncate_body(c.body, max_body_lines)
        for c in ctx.callees:
            c.body = truncate_body(c.body, max_body_lines)

    # 3. If still over budget, progressively remove callers from the end
    tokens = estimate_context_tokens(contexts)
    if tokens > max_tokens:
        truncated = True
        # Remove callers starting from functions with the most
        while tokens > max_tokens and any(ctx.callers for ctx in contexts):
            # Find context with most callers and remove last one
            most = max(contexts, key=lambda c: len(c.callers))
            if most.callers:
                most.callers.pop()
            tokens = estimate_context_tokens(contexts)

    total_callers = sum(len(ctx.callers) for ctx in contexts)
    total_callees = sum(len(ctx.callees) for ctx in contexts)

    report = BudgetReport(
        total_tokens=tokens,
        total_functions=len(contexts),
        total_callers=total_callers,
        total_callees=total_callees,
        estimated_cost=estimate_cost(tokens, model),
        truncated=truncated,
        model=model,
    )

    return contexts, report

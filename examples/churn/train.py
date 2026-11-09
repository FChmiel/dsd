"""Toy churn model trainer (pure Python, no dependencies) used by the dsd demo.

    dsd exec -b churn-v1 --task T-3 -- python train.py --model logreg --lr 0.1 --seed 0
"""

import argparse
import math
import random

import dsd


def make_data(n: int, seed: int, noise: float):
    rng = random.Random(1000 + seed)
    rows = []
    for _ in range(n):
        tenure = rng.uniform(0, 72)
        charges = rng.uniform(20, 120)
        tickets = rng.randint(0, 8)
        contract = rng.choice([0, 1, 2])  # monthly, 1y, 2y
        z = -0.04 * tenure + 0.02 * charges + 0.35 * tickets - 0.9 * contract - 0.6 + rng.gauss(0, noise)
        y = 1 if rng.random() < 1 / (1 + math.exp(-z)) else 0
        rows.append(([tenure / 72, charges / 120, tickets / 8, contract / 2], y))
    return rows


def auc(scores, labels):
    pairs = sorted(zip(scores, labels))
    pos = sum(labels)
    neg = len(labels) - pos
    rank_sum = sum(i + 1 for i, (_, y) in enumerate(pairs) if y == 1)
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg) if pos and neg else 0.5


def logloss(p, y):
    p = min(max(p, 1e-7), 1 - 1e-7)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def sigmoid(z):
    return 1 / (1 + math.exp(-max(min(z, 30), -30)))


def train_logreg(train, test, lr, l2, epochs, run, interactions=False):
    feats = (lambda x: x + [x[0] * x[3], x[2] * x[1]]) if interactions else (lambda x: x)
    d = len(feats(train[0][0]))
    w, b = [0.0] * d, 0.0
    for epoch in range(epochs):
        random.shuffle(train)
        total = 0.0
        for x, y in train:
            f = feats(x)
            p = sigmoid(sum(wi * xi for wi, xi in zip(w, f)) + b)
            g = p - y
            w = [wi - lr * (g * xi + l2 * wi) for wi, xi in zip(w, f)]
            b -= lr * g
            total += logloss(p, y)
        scores = [sigmoid(sum(wi * xi for wi, xi in zip(w, feats(x))) + b) for x, _ in test]
        run.log({"train_loss": total / len(train), "val_auc": auc(scores, [y for _, y in test])}, step=epoch)
    return lambda x: sigmoid(sum(wi * xi for wi, xi in zip(w, feats(x))) + b)


def train_nb(train):
    stats = {}
    for c in (0, 1):
        xs = [x for x, y in train if y == c]
        prior = len(xs) / len(train)
        means = [sum(col) / len(xs) for col in zip(*xs)]
        vars_ = [max(sum((v - m) ** 2 for v in col) / len(xs), 1e-4) for col, m in zip(zip(*xs), means)]
        stats[c] = (prior, means, vars_)

    def predict(x):
        logp = {}
        for c, (prior, means, vars_) in stats.items():
            logp[c] = math.log(prior) + sum(-0.5 * math.log(2 * math.pi * v) - (xi - m) ** 2 / (2 * v)
                                            for xi, m, v in zip(x, means, vars_))
        return sigmoid(logp[1] - logp[0])

    return predict


def report_html(name, scores, labels, metrics):
    # Simple ROC curve as inline SVG
    pts = sorted(zip(scores, labels), reverse=True)
    pos = sum(labels) or 1
    neg = (len(labels) - sum(labels)) or 1
    tp = fp = 0
    roc = [(0.0, 0.0)]
    for _, y in pts:
        if y:
            tp += 1
        else:
            fp += 1
        roc.append((fp / neg, tp / pos))
    path = " ".join(f"{'M' if i == 0 else 'L'}{20 + x * 260:.1f},{280 - y * 260:.1f}" for i, (x, y) in enumerate(roc[:: max(1, len(roc) // 300)] + [roc[-1]]))
    rows = "".join(f"<tr><td>{k}</td><td style='text-align:right'>{v:.4f}</td></tr>" for k, v in metrics.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{name} eval</title>
<style>body{{font:14px -apple-system,system-ui,sans-serif;margin:24px;color:#191917}}h1{{font-size:20px}}
table{{border-collapse:collapse}}td{{padding:4px 12px;border-bottom:1px solid #eee;font-variant-numeric:tabular-nums}}
.wrap{{display:flex;gap:32px;flex-wrap:wrap;align-items:flex-start}}</style></head><body>
<h1>Evaluation · {name}</h1>
<div class="wrap"><svg width="300" height="300" role="img" aria-label="ROC curve">
<rect x="20" y="20" width="260" height="260" fill="none" stroke="#ddd"/>
<line x1="20" y1="280" x2="280" y2="20" stroke="#bbb" stroke-dasharray="4 4"/>
<path d="{path}" fill="none" stroke="#2a78d6" stroke-width="2"/>
<text x="150" y="298" text-anchor="middle" font-size="11" fill="#777">false positive rate</text>
<text x="8" y="150" font-size="11" fill="#777" transform="rotate(-90 8 150)" text-anchor="middle">true positive rate</text></svg>
<table>{rows}</table></div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="logreg", choices=["logreg", "logreg_x", "nb"])
    ap.add_argument("--lr", type=float, default=0.1)
    ap.add_argument("--l2", type=float, default=0.0)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n", type=int, default=1500)
    args = ap.parse_args()
    random.seed(args.seed)

    params = vars(args)
    data = make_data(args.n, args.seed, noise=0.8)
    split = int(0.8 * len(data))
    train, test = data[:split], data[split:]

    name = f"{args.model}-lr{args.lr:g}-s{args.seed}" if args.model != "nb" else f"nb-s{args.seed}"
    with dsd.run(name, params=params,
                 datasets=[dsd.dataset(name="churn", id="synthetic-churn-v1", config="configs/data.yml")]) as run:
        print(f"training {args.model} on {len(train)} rows (seed {args.seed})")
        if args.model == "nb":
            predict = train_nb(train)
        else:
            predict = train_logreg(train, test, args.lr, args.l2, args.epochs, run, interactions=args.model == "logreg_x")
        scores = [predict(x) for x, _ in test]
        labels = [y for _, y in test]
        metrics = {
            "auc": auc(scores, labels),
            "accuracy": sum((s > 0.5) == bool(y) for s, y in zip(scores, labels)) / len(labels),
            "logloss": sum(logloss(s, y) for s, y in zip(scores, labels)) / len(labels),
        }
        run.log(metrics)
        run.info(train_rows=len(train), test_rows=len(test), positive_rate=round(sum(labels) / len(labels), 3))
        run.html("eval.html", report_html(name, scores, labels, metrics), description="ROC + metrics")
        print("  ".join(f"{k}={v:.4f}" for k, v in metrics.items()))


if __name__ == "__main__":
    main()

import torch
import numpy as np
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForSequenceClassification


device = "cuda" if torch.cuda.is_available() else "cpu"

CANON = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
IDX = {l: i for i, l in enumerate(CANON)}

distilbert_name = "bhadresh-savani/distilbert-base-uncased-emotion"
distilbert_tokenizer = AutoTokenizer.from_pretrained(distilbert_name)
distilbert_model = AutoModelForSequenceClassification.from_pretrained(distilbert_name).to(device)
distilbert_labels = [
    distilbert_model.config.id2label[i].lower()
    for i in range(distilbert_model.config.num_labels)
]
print("Loaded DistilBERT")

deberta_name = "mrm8488/deberta-v3-base-goemotions"
deberta_tokenizer = AutoTokenizer.from_pretrained(deberta_name)
deberta_model = AutoModelForSequenceClassification.from_pretrained(deberta_name).to(device)

goemotions_labels = [
    "admiration","amusement","anger","annoyance","approval","caring","confusion",
    "curiosity","desire","disappointment","disapproval","disgust","embarrassment",
    "excitement","fear","gratitude","grief","joy","love","nervousness","optimism",
    "pride","realization","relief","remorse","sadness","surprise","neutral"
]
deberta_labels = [label.lower() for label in goemotions_labels]
print("Loaded DeBERTa-v3 GoEmotions")

roberta_name = "j-hartmann/emotion-english-distilroberta-base"
roberta_tokenizer = AutoTokenizer.from_pretrained(roberta_name)
roberta_model = AutoModelForSequenceClassification.from_pretrained(roberta_name).to(device)
roberta_labels = [
    roberta_model.config.id2label[i].lower()
    for i in range(roberta_model.config.num_labels)
]
print("Loaded RoBERTa\n")

map_m1_to_canon = {
    "anger": "anger",
    "fear": "fear",
    "joy": "joy",
    "love": "joy",
    "sadness": "sadness",
    "surprise": "surprise",
}


fold_goe = {
    "anger": "anger", "annoyance": "anger", "disapproval": "anger",
    "disgust": "disgust",
    "fear": "fear", "nervousness": "fear", "embarrassment": "fear",
    "joy": "joy", "amusement": "joy", "excitement": "joy", "gratitude": "joy",
    "love": "joy", "optimism": "joy", "pride": "joy", "relief": "joy",
    "admiration": "joy", "approval": "joy",
    "neutral": "neutral",
    "sadness": "sadness", "disappointment": "sadness", "grief": "sadness", "remorse": "sadness",
    "surprise": "surprise", "realization": "surprise", "curiosity": "surprise", "confusion": "surprise",
}


map_m3_to_canon = {
    "anger": "anger",
    "disgust": "disgust",
    "fear": "fear",
    "joy": "joy",
    "neutral": "neutral",
    "sadness": "sadness",
    "surprise": "surprise",
}

def get_probs(model, tokenizer, text, label_map, model_labels):
    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=128,
    ).to(device)

    with torch.no_grad():
        logits = model(**inputs).logits
        probs = F.softmax(logits, dim=-1)[0].cpu().numpy()

    result = np.zeros(len(CANON), dtype=np.float32)

    for i, label in enumerate(model_labels):
        if label in label_map:
            canon = label_map[label]
            result[IDX[canon]] += probs[i]

    total = result.sum()
    if total > 0:
        result /= total

    return result


def run_distilbert(text: str):
    return get_probs(distilbert_model, distilbert_tokenizer, text, map_m1_to_canon, distilbert_labels)

def run_deberta(text: str):
    return get_probs(deberta_model, deberta_tokenizer, text, fold_goe, deberta_labels)

def run_roberta(text: str):
    return get_probs(roberta_model, roberta_tokenizer, text, map_m3_to_canon, roberta_labels)

def ensemble(
    text: str,
    weights=(0.4, 0.35, 0.25),
    return_all: bool = False,
    runners=(
        ("distilbert", run_distilbert),
        ("deberta_v3", run_deberta),
        ("roberta", run_roberta),
    ),
):
    probs = []
    names = []

    for name, fn in runners:
        p = fn(text)
        p = np.asarray(p, dtype=np.float32)
        probs.append(p)
        names.append(name)

    w = np.asarray(weights, dtype=np.float32)
    if len(w) != len(probs):
        raise ValueError("weights length must match number of runners")

    fused = np.tensordot(w, np.stack(probs), axes=1)
    idx = int(np.argmax(fused))

    result = {
        "text": text,
        "labels": CANON,
        "final_emotion": CANON[idx],
        "confidence": float(fused[idx]),
        "ensemble_probs": {lbl: float(fused[i]) for i, lbl in enumerate(CANON)},
    }

    if return_all:
        per_model = {}
        for name, p in zip(names, probs):
            per_model[name] = {lbl: float(p[i]) for i, lbl in enumerate(CANON)}
        per_model["weights"] = {name: float(w[i]) for i, name in enumerate(names)}
        result["per_model"] = per_model

    return result

print("Emotion model loaded successfully.\n")

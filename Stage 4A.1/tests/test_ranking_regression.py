"""Bucket parity, multiplicity, paired sampling, and metric identity regressions."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

STAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE))
from stage4a1 import bootstrap
from stage4a1 import metrics as shared_metrics
from sklearn.metrics import log_loss
from stage4a1.metrics import classification_metrics, ranking_metrics
from stage4a1.ranking import bucket_membership, bucket_metrics


def fixture(probabilities=(.5, .5, .5, .5)):
    return pd.DataFrame({
        "Signal ID": ["a", "b", "c", "d"],
        "Signal Date": pd.date_range("2020-01-01", periods=4),
        "Actual Label": [0, 0, 0, 1], "Predicted Probability": probabilities,
        "Training Prior": [.5] * 4, "Mode": ["TRANSFER"] * 4,
        "Target": ["TEST"] * 4, "Model Variant": ["DUMMY_PRIOR"] * 4,
        "Feature Set": ["NONE"] * 4, "Evaluation Year": [2020] * 4,
    })


def identity_parity(frame):
    point = ranking_metrics(frame).iloc[0]
    dates = pd.Index(sorted(frame["Signal Date"].unique()))
    actual = bootstrap.vector_metrics(frame, np.ones((1, len(dates)), dtype=int), dates).iloc[0]
    assert point["Overall Success Rate"] == actual["Prevalence"]
    for bucket in ["Top 10%", "Top 20%", "Bottom 20%"]:
        for metric in ["Success Rate", "Lift"]:
            key = bucket + " " + metric
            assert point[key] == actual[key], (key, point[key], actual[key])


def tied_membership():
    for seed in range(10):
        frame = fixture().sample(frac=1, random_state=seed)
        for fraction, bottom, expected in [(.1, False, ["a"]), (.2, False, ["a"]), (.2, True, ["d"])]:
            selected = bucket_membership(frame["Predicted Probability"], frame["Signal ID"], np.ones(4, dtype=int), fraction, bottom)[0]
            assert frame.loc[selected > 0, "Signal ID"].tolist() == expected


def duplicated_observations():
    frame = fixture()
    frame["Signal Date"] = pd.to_datetime(["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-03"])
    counts = np.array([[2, 0, 1], [0, 1, 3]])
    dates = pd.Index(sorted(frame["Signal Date"].unique()))
    actual = bootstrap.vector_metrics(frame, counts, dates)
    for i, sample in enumerate(counts):
        weights = sample[dates.get_indexer(frame["Signal Date"])]
        expanded = frame.iloc[np.repeat(np.arange(len(frame)), weights)]
        point = bucket_metrics(expanded).iloc[0]
        assert actual.iloc[i]["Rows"] == len(expanded)
        assert actual.iloc[i]["Prevalence"] == point["Overall Success Rate"]
        for bucket in ["Top 10%", "Top 20%", "Bottom 20%"]:
            for metric in ["Success Rate", "Lift"]:
                key = bucket + " " + metric
                assert point[key] == actual.iloc[i][key]
    assert actual.iloc[0]["Rows"] == 5
    assert actual.iloc[1]["Positive Count"] == 3


def paired_observations():
    left = fixture()
    right = left.assign(Mode="PRIMARY_ONLY", **{"Predicted Probability": [.8, .6, .4, .2]})
    calls = []
    original = bootstrap.vector_metrics
    def capture(group, counts, dates):
        calls.append((group["Mode"].iloc[0], group["Signal ID"].tolist(), counts.copy(), dates.copy()))
        return original(group, counts, dates)
    with patch.object(bootstrap, "vector_metrics", side_effect=capture):
        bootstrap.run_bootstrap(pd.concat([left, right], ignore_index=True), 2, 20, 42)
    assert len(calls) == 4  # pooled and 2016-2020, two modes each
    for i in range(0, len(calls), 2):
        a, b = calls[i:i+2]
        assert a[0] != b[0] and a[1] == b[1]
        np.testing.assert_array_equal(a[2], b[2])
        assert a[3].equals(b[3])


def log_loss_identity():
    frame = fixture((1., .5, .5, 0.))
    actual = bootstrap.vector_metrics(frame, np.ones((1, 4), dtype=int), pd.Index(frame["Signal Date"])).iloc[0]["Log Loss"]
    expected = classification_metrics(frame["Actual Label"], frame["Predicted Probability"], frame["Training Prior"])["Log Loss"]
    assert actual == expected, f"point={expected!r}, identical bootstrap={actual!r}"


def extreme_contract():
    frame = pd.concat([fixture(), fixture()], ignore_index=True).iloc[:6].copy()
    frame["Signal ID"] = list("abcdef")
    frame["Signal Date"] = pd.date_range("2020-01-01", periods=6)
    frame["Actual Label"] = [1, 0, 1, 0, 0, 1]
    frame["Predicted Probability"] = [0., 1., 1e-20, 1 - 1e-20, .25, .75]
    expected = float(log_loss(frame["Actual Label"], np.clip(frame["Predicted Probability"], 1e-15, 1 - 1e-15), labels=[0, 1]))
    assert classification_metrics(frame["Actual Label"], frame["Predicted Probability"], .5)["Log Loss"] == expected
    assert bootstrap.vector_metrics(frame, np.ones((1, 6), dtype=int), pd.Index(frame["Signal Date"])).iloc[0]["Log Loss"] == expected


def nonmutation():
    frame = fixture((0., 1., 1e-20, 1 - 1e-20))
    before = frame.copy(deep=True)
    classification_metrics(frame["Actual Label"], frame["Predicted Probability"], frame["Training Prior"])
    bootstrap.vector_metrics(frame, np.ones((1, 4), dtype=int), pd.Index(frame["Signal Date"]))
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    for invalid in [-.01, 1.01, np.nan, np.inf]:
        try:
            shared_metrics.fixed_log_loss([0], [invalid])
        except ValueError:
            continue
        raise AssertionError("Invalid probability accepted")


def shared_loss_routes():
    frame = pd.concat([fixture(), fixture().assign(Mode="PRIMARY_ONLY")], ignore_index=True)
    for block in [63, 21, 126]:
        with patch.object(shared_metrics, "fixed_log_loss", wraps=shared_metrics.fixed_log_loss) as spy:
            raw = bootstrap.run_bootstrap(frame, block, 3, 42)
            assert spy.call_count == len(raw), (block, spy.call_count, len(raw))
            assert raw["Log Loss"].eq(shared_metrics.fixed_log_loss([0, 0, 0, 1], [.5]*4)).all()


def full_identity():
    # Other vectorized metrics allow only 1e-14 absolute rounding error;
    # shared Log Loss and bucket helper paths require exact equality.
    for probabilities in [(1., .5, .5, 0.), (.1, .8, .4, .7), (.5,)*4]:
        frame = fixture(probabilities)
        point = classification_metrics(frame["Actual Label"], frame["Predicted Probability"], frame["Training Prior"])
        actual = bootstrap.vector_metrics(frame, np.ones((1, 4), dtype=int), pd.Index(frame["Signal Date"])).iloc[0]
        for metric, value in point.items():
            np.testing.assert_allclose(actual[metric], value, rtol=0, atol=0 if metric == "Log Loss" else 1e-14, equal_nan=True, err_msg=metric)
        identity_parity(frame)


def run():
    checks = [
        ("Identity sample all bucket rates and lifts", lambda: identity_parity(fixture((.1, .8, .4, .7)))),
        ("All probabilities tied deterministic memberships", tied_membership),
        ("Bottom-bucket original failing case", lambda: identity_parity(fixture())),
        ("Duplicated observations counted repeatedly", duplicated_observations),
        ("Paired modes identical observation multiplicities every replicate", paired_observations),
        ("Additional classification identity: log loss at boundaries", log_loss_identity),
        ("Extreme probabilities frozen Stage 4A clipping", extreme_contract),
        ("Metric-local clipping nonmutation and input validation", nonmutation),
        ("Every bootstrap Log Loss route uses shared helper", shared_loss_routes),
        ("Full shared metric identity", full_identity),
    ]
    rows = []
    for name, function in checks:
        try:
            function()
            rows.append({"Test": name, "Status": "PASS", "Details": ""})
        except Exception as error:
            rows.append({"Test": name, "Status": "FAIL", "Details": str(error)})
    frame = pd.DataFrame(rows)
    frame.to_csv(STAGE / "tests" / "ranking_regression_results.csv", index=False)
    print(frame.to_string(index=False))
    if frame["Status"].eq("FAIL").any():
        raise SystemExit(1)


if __name__ == "__main__":
    run()

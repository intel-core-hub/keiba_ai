import json

from scripts.analyze_pre_contract_filters import analyze_pre_contract_filters


def test_analyze_pre_contract_filters_reports_loss_reduction(tmp_path):
    evaluation = tmp_path / "eval.json"
    evaluation.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "selection": "1",
                        "odds_regime": "DEEP_LONGSHOT",
                        "favorite_rank": 9,
                        "stake": 100,
                        "profit": -100,
                        "hit": 0,
                    },
                    {
                        "selection": "2",
                        "odds_regime": "LONGSHOT",
                        "favorite_rank": 5,
                        "stake": 100,
                        "profit": 200,
                        "hit": 1,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = analyze_pre_contract_filters(
        evaluation_json=evaluation,
        output_json=tmp_path / "filters.json",
        output_md=tmp_path / "filters.md",
    )

    by_name = {row["name"]: row for row in report["policies"]}
    assert by_name["baseline_all"]["candidate_count"] == 2
    assert by_name["baseline_all"]["profit_sum"] == 100
    assert by_name["exclude_deep_longshot"]["candidate_count"] == 1
    assert by_name["exclude_deep_longshot"]["profit_sum"] == 200
    assert by_name["exclude_deep_longshot"]["loss_reduction_vs_baseline"] == 100
    assert (tmp_path / "filters.md").exists()
